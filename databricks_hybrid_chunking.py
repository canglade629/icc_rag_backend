"""
Databricks-compatible hybrid chunking system for ICC judgment processing.

This module provides distributed processing capabilities for the hybrid chunking
system on Databricks clusters, handling large PDF documents efficiently.
"""

import os
import time
import json
from typing import Dict, List, Any, Optional
from dataclasses import asdict
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import cv2
import numpy as np
import re
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, lit, when, regexp_extract, split, explode, count, sum as spark_sum
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, FloatType, ArrayType

# Import the base chunking system
from hybrid_chunking import HybridPyMuPDFOCRChunker, TextBlock, Footnote, SemanticChunk


class DatabricksHybridChunker:
    """
    Databricks-compatible wrapper for the hybrid chunking system.
    
    This class provides distributed processing capabilities for large PDF documents
    on Databricks clusters, leveraging Spark for parallel processing.
    """
    
    def __init__(self, pdf_path: str, config: Dict[str, Any], use_databricks: bool = True):
        """
        Initialize the Databricks chunker.
        
        Args:
            pdf_path: Path to the PDF file (DBFS or volume path)
            config: Configuration dictionary for chunking parameters
            use_databricks: Whether to use Databricks-specific optimizations
        """
        self.pdf_path = pdf_path
        self.config = config
        self.use_databricks = use_databricks
        self.spark = SparkSession.getActiveSession()
        
        if not self.spark:
            raise RuntimeError("No active Spark session found. Please run this in a Databricks notebook.")
        
        # Initialize the base chunker for metadata extraction
        self.base_chunker = None
        self.total_pages = 0
        
    def _get_pdf_metadata(self) -> int:
        """Get the total number of pages in the PDF."""
        try:
            # Open PDF to get page count
            doc = fitz.open(self.pdf_path)
            total_pages = len(doc)
            doc.close()
            return total_pages
        except Exception as e:
            print(f"Error getting PDF metadata: {e}")
            return 0
    
    def _process_page_partition(self, page_range: List[int]) -> List[Dict[str, Any]]:
        """
        Process a range of pages in a single partition.
        
        Args:
            page_range: List of page numbers to process
            
        Returns:
            List of dictionaries containing extracted data
        """
        results = []
        
        try:
            # Initialize chunker for this partition
            chunker = HybridPyMuPDFOCRChunker(self.pdf_path, self.config)
            
            for page_num in page_range:
                try:
                    # Process the page
                    page_result = chunker.process_page(page_num)
                    
                    if page_result:
                        # Convert dataclasses to dictionaries for Spark serialization
                        page_data = {
                            'page': page_num,
                            'paragraphs': [asdict(p) for p in page_result.get('paragraphs', [])],
                            'footnotes': [asdict(f) for f in page_result.get('footnotes', [])],
                            'processing_time': page_result.get('processing_time', 0),
                            'success': True
                        }
                        results.append(page_data)
                    else:
                        results.append({
                            'page': page_num,
                            'paragraphs': [],
                            'footnotes': [],
                            'processing_time': 0,
                            'success': False
                        })
                        
                except Exception as e:
                    print(f"Error processing page {page_num}: {e}")
                    results.append({
                        'page': page_num,
                        'paragraphs': [],
                        'footnotes': [],
                        'processing_time': 0,
                        'success': False,
                        'error': str(e)
                    })
            
            chunker.close()
            
        except Exception as e:
            print(f"Error in partition processing: {e}")
            # Return empty results for all pages in this partition
            for page_num in page_range:
                results.append({
                    'page': page_num,
                    'paragraphs': [],
                    'footnotes': [],
                    'processing_time': 0,
                    'success': False,
                    'error': str(e)
                })
        
        return results
    
    def process_document_distributed(self) -> Dict[str, Any]:
        """
        Process the entire document using distributed processing.
        
        Returns:
            Dictionary containing all extracted data and statistics
        """
        print("Starting distributed processing...")
        start_time = time.time()
        
        # Get total pages
        self.total_pages = self._get_pdf_metadata()
        if self.total_pages == 0:
            raise RuntimeError("Could not determine PDF page count")
        
        print(f"Total pages to process: {self.total_pages}")
        
        # Skip first pages as configured
        skip_pages = self.config.get('skip_first_pages', 6)
        start_page = skip_pages + 1  # Convert to 1-based indexing
        pages_to_process = list(range(start_page, self.total_pages + 1))
        
        print(f"Processing pages {start_page} to {self.total_pages} (skipping first {skip_pages} pages)")
        
        # Create page partitions
        pages_per_partition = self.config.get('pages_per_partition', 50)
        page_partitions = [pages_to_process[i:i + pages_per_partition] 
                          for i in range(0, len(pages_to_process), pages_per_partition)]
        
        print(f"Created {len(page_partitions)} partitions of up to {pages_per_partition} pages each")
        
        # Process partitions in parallel using Spark
        partition_rdd = self.spark.sparkContext.parallelize(page_partitions, len(page_partitions))
        results_rdd = partition_rdd.flatMap(self._process_page_partition)
        
        # Collect results
        all_results = results_rdd.collect()
        
        # Process and aggregate results
        all_paragraphs = []
        all_footnotes = []
        successful_pages = 0
        failed_pages = 0
        total_processing_time = 0
        
        for page_result in all_results:
            if page_result.get('success', False):
                successful_pages += 1
                total_processing_time += page_result.get('processing_time', 0)
                
                # Add page number to each paragraph and footnote
                for para in page_result.get('paragraphs', []):
                    para['page'] = page_result['page']
                    all_paragraphs.append(para)
                
                for footnote in page_result.get('footnotes', []):
                    footnote['page'] = page_result['page']
                    all_footnotes.append(footnote)
            else:
                failed_pages += 1
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Create statistics
        stats = {
            'total_pages_processed': len(all_results),
            'successful_pages': successful_pages,
            'failed_pages': failed_pages,
            'total_paragraphs': len(all_paragraphs),
            'total_footnotes': len(all_footnotes),
            'total_processing_time': total_time,
            'avg_time_per_page': total_time / len(all_results) if all_results else 0
        }
        
        return {
            'paragraphs': all_paragraphs,
            'footnotes': all_footnotes,
            'statistics': stats
        }
    
    def save_results_to_databricks(self, results: Dict[str, Any], table_prefix: str) -> None:
        """
        Save results to Delta tables in Databricks.
        
        Args:
            results: Results dictionary from process_document_distributed
            table_prefix: Prefix for table names (e.g., "icc.jugement")
        """
        print("Saving results to Delta tables...")
        
        # Create DataFrames
        paragraphs_df = self.spark.createDataFrame(results['paragraphs'])
        footnotes_df = self.spark.createDataFrame(results['footnotes'])
        
        # Write to Delta tables
        paragraphs_table = f"{table_prefix}_paragraphs"
        footnotes_table = f"{table_prefix}_footnotes"
        
        paragraphs_df.write.mode("overwrite").saveAsTable(paragraphs_table)
        footnotes_df.write.mode("overwrite").saveAsTable(footnotes_table)
        
        print(f"✅ Results saved to tables: {paragraphs_table} and {footnotes_table}")
    
    def close(self):
        """Close any open resources."""
        if self.base_chunker:
            self.base_chunker.close()


def process_page_for_databricks(page_num: int, pdf_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single page for Databricks UDF usage.
    
    Args:
        page_num: Page number to process (1-based)
        pdf_path: Path to the PDF file
        config: Configuration dictionary
        
    Returns:
        Dictionary containing extracted data
    """
    try:
        chunker = HybridPyMuPDFOCRChunker(pdf_path, config)
        result = chunker.process_page(page_num)
        chunker.close()
        
        if result:
            return {
                'page': page_num,
                'paragraphs': [asdict(p) for p in result.get('paragraphs', [])],
                'footnotes': [asdict(f) for f in result.get('footnotes', [])],
                'processing_time': result.get('processing_time', 0),
                'success': True
            }
        else:
            return {
                'page': page_num,
                'paragraphs': [],
                'footnotes': [],
                'processing_time': 0,
                'success': False
            }
            
    except Exception as e:
        return {
            'page': page_num,
            'paragraphs': [],
            'footnotes': [],
            'processing_time': 0,
            'success': False,
            'error': str(e)
        }