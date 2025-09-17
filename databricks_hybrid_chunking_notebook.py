# Databricks notebook source
"""
Databricks Serverless Notebook for ICC Judgment Hybrid Chunking

This notebook runs the hybrid chunking system on a Databricks serverless cluster
for processing the 1600+ page ICC judgment document.

Note: Serverless clusters automatically handle scaling and resource management.
No external configuration files needed.
"""

# COMMAND ----------

# Install all required packages using pip
%pip install PyMuPDF==1.23.8 pytesseract==0.3.10 opencv-python==4.8.1.78 Pillow==10.0.1 numpy==1.24.3 pyspark==3.5.0

# COMMAND ----------

# Check if Tesseract is available and install if needed
import subprocess
import sys

try:
    result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True)
    print(f"Tesseract version: {result.stdout}")
except FileNotFoundError:
    print("Tesseract not found. Installing...")
    try:
        subprocess.run(['apt-get', 'update'], check=True)
        subprocess.run(['apt-get', 'install', '-y', 'tesseract-ocr', 'tesseract-ocr-eng'], check=True)
        print("Tesseract installed successfully")
    except Exception as e:
        print(f"Failed to install Tesseract: {e}")
        print("Please ensure Tesseract is available on your serverless cluster")

# COMMAND ----------

# Import the hybrid chunking system
%run ./databricks_hybrid_chunking

# COMMAND ----------

# Configure the chunking system
config = {
    "skip_first_pages": 6,  # Skip intro and table of contents
    "pages_per_partition": 50,  # Process 50 pages per partition
    "max_workers": 8,  # Max parallel workers
    "ocr_psm": 6,
    "image_scale": 2.0,
    "footnote_pattern": r'^(\d{1,3})\s+',
    "footnote_min_confidence": 0.7,
    "paragraph_number_patterns": [
        r'^(\d{1,4})\.\s+',
        r'^(\d{1,4})\.',
    ],
    "high_number_patterns": [
        r'^(\d{4})\.\s+',
        r'^(\d{3,4})\.\s+',
    ],
    "date_patterns": [
        r'\b(19|20)\d{2}\b',
        r'\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
        r'\b\d{1,2}\s+\w+\s+\d{4}\b',
    ],
    "header_patterns": [
        r'ICC-01/14-01/18-2784-Red\s+\d{2}-\d{2}-\d{4}\s+\d+/\d+\s+T',
        r'No\.\s+ICC-01/14-01/18\s+\d+/\d+\s+\d{2}\s+\w+\s+\d{4}',
        r'^\d+/\d+$',
        r'^No\.\s+ICC-',
    ],
    "footnote_keywords": [
        'judgment', 'appeals', 'trial', 'chamber', 'para', 'icc-',
        'prosecutor', 'statute', 'article', 'red', 'conf', 'bemba',
        'ongwen', 'al hassan', 'court', 'decision'
    ],
}

# COMMAND ----------

# Initialize the chunker with the correct volume path
pdf_path = "/Volumes/icc/jugement/files/jugement.pdf"
chunker = DatabricksHybridChunker(pdf_path, config, use_databricks=True)

# COMMAND ----------

# Process the document
print("Starting distributed processing of ICC judgment...")
results = chunker.process_document_distributed()

# COMMAND ----------

# Display results summary
stats = results["statistics"]
print(f"\n=== PROCESSING COMPLETE ===")
print(f"Total pages processed: {stats['total_pages_processed']}")
print(f"Successful pages: {stats['successful_pages']}")
print(f"Failed pages: {stats['failed_pages']}")
print(f"Total paragraphs: {stats['total_paragraphs']}")
print(f"Total footnotes: {stats['total_footnotes']}")
print(f"Total processing time: {stats['total_processing_time']:.2f}s")
print(f"Average time per page: {stats['avg_time_per_page']:.2f}s")

# COMMAND ----------

# Save results to Delta tables
table_name = "icc.jugement.chunks"
chunker.save_results_to_databricks(results, table_name)

# COMMAND ----------

# Verify the results in Delta tables
paragraphs_df = spark.table(f"{table_name}_paragraphs")
footnotes_df = spark.table(f"{table_name}_footnotes")

print(f"Paragraphs table: {paragraphs_df.count()} records")
print(f"Footnotes table: {footnotes_df.count()} records")

# COMMAND ----------

# Display sample results
print("\n=== SAMPLE PARAGRAPHS ===")
paragraphs_df.select("paragraph_number", "page", "content").show(5, truncate=False)

print("\n=== SAMPLE FOOTNOTES ===")
footnotes_df.select("footnote_number", "page", "content").show(5, truncate=False)

# COMMAND ----------

# Analyze paragraph number distribution
print("\n=== PARAGRAPH NUMBER ANALYSIS ===")
paragraphs_df.select("paragraph_number").distinct().orderBy("paragraph_number").show(20)

# COMMAND ----------

# Analyze footnote number distribution
print("\n=== FOOTNOTE NUMBER ANALYSIS ===")
footnotes_df.select("footnote_number").distinct().orderBy("footnote_number").show(20)

# COMMAND ----------

# Page-by-page analysis
print("\n=== PAGE-BY-PAGE ANALYSIS ===")
page_stats = paragraphs_df.groupBy("page").agg(
    count("paragraph_id").alias("paragraph_count")
).orderBy("page").show(20)

# COMMAND ----------

# Close the chunker
chunker.close()

# COMMAND ----------

# Final summary
print("\n=== FINAL SUMMARY ===")
print(f"✅ Processing completed successfully")
print(f"📊 Total paragraphs extracted: {stats['total_paragraphs']}")
print(f"📊 Total footnotes extracted: {stats['total_footnotes']}")
print(f"⏱️  Total processing time: {stats['total_processing_time']:.2f} seconds")
print(f"📈 Average time per page: {stats['avg_time_per_page']:.2f} seconds")
print(f"💾 Results saved to Delta tables: {table_name}_paragraphs and {table_name}_footnotes")
