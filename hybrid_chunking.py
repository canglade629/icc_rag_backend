#!/usr/bin/env python3
"""
Hybrid PyMuPDF + OCR Chunking System for ICC Judgment PDF

Combines:
- PyMuPDF for footnote extraction (from corrected_icc_chunking.py)
- OCR for main text and paragraph number detection
- Content-based footnote validation
"""

import fitz
import pytesseract
import cv2
import numpy as np
from PIL import Image
import io
import re
import json
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration combining both approaches
HYBRID_CHUNKING_CONFIG = {
    # Document processing
    "skip_first_pages": 6,  # Skip intro and table of contents
    
    # OCR settings
    "ocr_psm": 6,  # Uniform block of text
    "image_scale": 2.0,  # Higher resolution for better OCR
    
    # PyMuPDF footnote detection (from corrected_icc_chunking.py)
    "footnote_pattern": r'^(\d{1,3})\s+',  # Matches 1, 2, 3, etc. at start of line
    "footnote_min_confidence": 0.7,
    
    # OCR paragraph detection
    "paragraph_number_patterns": [
        r'^(\d{1,4})\.\s+',  # "1. ", "2. ", etc.
        r'^(\d{1,4})\.',  # "4289." without space (OCR pattern)
    ],
    
    # High-numbered paragraph patterns
    "high_number_patterns": [
        r'^(\d{4})\.\s+',  # 4-digit numbers like 4848.
        r'^(\d{3,4})\.\s+',  # 3-4 digit numbers
    ],
    
    # Date patterns to exclude from footnotes
    "date_patterns": [
        r'\b(19|20)\d{2}\b',  # Years like 1975, 2014, 2012
        r'\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
        r'\b\d{1,2}\s+\w+\s+\d{4}\b',  # "23 February 1975"
    ],
    
    # Header/Footer patterns
    "header_patterns": [
        r'ICC-01/14-01/18-2784-Red\s+\d{2}-\d{2}-\d{4}\s+\d+/\d+\s+T',
        r'No\.\s+ICC-01/14-01/18\s+\d+/\d+\s+\d{2}\s+\w+\s+\d{4}',
        r'^\d+/\d+$',  # Page numbers
        r'^No\.\s+ICC-',  # Document headers
    ],
    
    # Content-based footnote detection
    "footnote_keywords": [
        'judgment', 'appeals', 'trial', 'chamber', 'para', 'icc-',
        'prosecutor', 'statute', 'article', 'red', 'conf', 'bemba',
        'ongwen', 'al hassan', 'court', 'decision'
    ],
}

@dataclass
class Footnote:
    """Individual footnote with metadata."""
    number: str
    content: str
    page: int
    confidence: float
    detection_method: str
    referenced_paragraphs: List[str] = None
    
    def __post_init__(self):
        if self.referenced_paragraphs is None:
            self.referenced_paragraphs = []

@dataclass
class LegalParagraph:
    """Legal paragraph with metadata."""
    number: str
    content: str
    page: int
    section_type: str
    token_count: int
    footnote_references: List[str] = None
    start_line: int = 0
    end_line: int = 0
    extraction_method: str = "hybrid_ocr"
    confidence: float = 0.0
    
    def __post_init__(self):
        if self.footnote_references is None:
            self.footnote_references = []

@dataclass
class SemanticChunk:
    """Semantic chunk for RAG."""
    chunk_id: str
    content: str
    chunk_type: str
    page_range: Tuple[int, int]
    paragraph_numbers: List[str]
    footnote_numbers: List[str]
    token_count: int
    metadata: Dict

class HybridPyMuPDFOCRChunker:
    """Hybrid chunking system using PyMuPDF for footnotes and OCR for main text."""
    
    def __init__(self, pdf_path: str, config: Dict = None):
        self.pdf_path = pdf_path
        self.config = config or HYBRID_CHUNKING_CONFIG
        self.doc = None
        
        # Storage for extracted data
        self.paragraphs = []
        self.footnotes = []
        self.page_sections = {}
        
    def open_document(self):
        """Open the PDF document."""
        self.doc = fitz.open(self.pdf_path)
        logger.info(f"Opened PDF with {len(self.doc)} pages")
    
    def extract_text_with_ocr(self, page_num: int) -> List[str]:
        """Extract text using OCR for main content."""
        try:
            page = self.doc[page_num]
            # Convert page to image with higher resolution
            mat = fitz.Matrix(self.config["image_scale"], self.config["image_scale"])
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            # Use PIL to open the image
            image = Image.open(io.BytesIO(img_data))
            
            # Extract text with OCR
            text = pytesseract.image_to_string(
                image, 
                config=f'--psm {self.config["ocr_psm"]}'
            )
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            
            return lines
        except Exception as e:
            logger.error(f"OCR failed for page {page_num + 1}: {e}")
            return []
    
    def clean_headers_footers(self, lines: List[str]) -> List[str]:
        """Remove headers and footers from page content."""
        cleaned_lines = []
        
        for line in lines:
            # Skip header/footer patterns
            if any(re.search(pattern, line) for pattern in self.config["header_patterns"]):
                continue
            
            cleaned_lines.append(line)
        
        return cleaned_lines
    
    def extract_footnotes_pymupdf(self, page_num: int) -> List[Footnote]:
        """Extract footnotes using PyMuPDF (from corrected_icc_chunking.py logic)."""
        page = self.doc[page_num]
        text = page.get_text("text")
        lines = text.split('\n')
        
        footnotes = []
        current_footnote = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip header/footer patterns
            if any(re.search(pattern, line) for pattern in self.config["header_patterns"]):
                continue
            
            # Check if line starts with incremental footnote number
            footnote_match = re.match(self.config["footnote_pattern"], line)
            if footnote_match:
                # Save previous footnote if exists
                if current_footnote:
                    footnotes.append(current_footnote)
                
                # Start new footnote
                footnote_num = footnote_match.group(1)
                content = line[footnote_match.end():].strip()
                
                # Validate footnote content (not a date)
                if self._is_valid_footnote_pymupdf(content, footnote_num):
                    current_footnote = Footnote(
                        number=footnote_num,
                        content=content,
                        page=page_num + 1,
                        confidence=self._calculate_footnote_confidence(content),
                        detection_method="pymupdf"
                    )
                else:
                    current_footnote = None
            else:
                # Continue current footnote
                if current_footnote and len(line) > 10:
                    current_footnote.content += " " + line
        
        # Save last footnote
        if current_footnote:
            footnotes.append(current_footnote)
        
        return footnotes
    
    def _is_valid_footnote_pymupdf(self, content: str, footnote_num: str) -> bool:
        """Validate if content is a legitimate footnote (from corrected_icc_chunking.py)."""
        if len(content) < 10:
            return False
        
        # Check if it's a date pattern
        for date_pattern in self.config["date_patterns"]:
            if re.search(date_pattern, content, re.IGNORECASE):
                return False
        
        # Look for legal citation patterns
        legal_patterns = [
            r'P-\d+:',  # Witness references
            r'T-\d+',   # Transcript references
            r'CAR-',    # Document references
            r'ICC-',    # Case references
            r'para\.?\s+\d+',  # Paragraph references
            r'p\.\s+\d+',  # Page references
            r'lines?\s+\d+',  # Line references
            r'Article\s+\d+',  # Article references
            r'Rule\s+\d+',  # Rule references
        ]
        
        return any(re.search(pattern, content) for pattern in legal_patterns)
    
    def _calculate_footnote_confidence(self, content: str) -> float:
        """Calculate confidence score for footnote content (from corrected_icc_chunking.py)."""
        score = 0.0
        
        # Legal citation patterns (high value)
        if re.search(r'P-\d+:', content):
            score += 0.4
        if re.search(r'T-\d+', content):
            score += 0.3
        if re.search(r'CAR-', content):
            score += 0.2
        if re.search(r'ICC-', content):
            score += 0.2
        if re.search(r'para\.?\s+\d+', content):
            score += 0.1
        if re.search(r'p\.\s+\d+', content):
            score += 0.1
        if re.search(r'Article\s+\d+', content):
            score += 0.1
        if re.search(r'Rule\s+\d+', content):
            score += 0.1
        
        # Length bonus
        if len(content) > 50:
            score += 0.1
        
        return min(score, 1.0)
    
    def extract_paragraphs_ocr(self, lines: List[str], page_num: int) -> List[LegalParagraph]:
        """Extract paragraphs using OCR with enhanced detection."""
        paragraphs = []
        current_para = []
        current_num = None
        seen_numbers = set()
        
        for line_num, line in enumerate(lines):
            # Check for paragraph number patterns
            para_match = None
            for pattern in self.config["paragraph_number_patterns"]:
                match = re.match(pattern, line)
                if match:
                    para_match = match
                    break
            
            # Check high-numbered patterns
            if not para_match:
                for pattern in self.config["high_number_patterns"]:
                    match = re.match(pattern, line)
                    if match:
                        para_match = match
                        break
            
            if para_match:
                # Save previous paragraph
                if current_para and current_num and current_num not in seen_numbers:
                    content = ' '.join(current_para).strip()
                    if self._is_valid_paragraph(content):
                        paragraph = LegalParagraph(
                            number=current_num,
                            content=content,
                            page=page_num + 1,
                            section_type="main_text",
                            token_count=int(len(content.split()) * 1.3),
                            footnote_references=self._extract_footnote_references(content),
                            start_line=line_num - len(current_para),
                            end_line=line_num,
                            extraction_method="hybrid_ocr",
                            confidence=0.8
                        )
                        paragraphs.append(paragraph)
                        seen_numbers.add(current_num)
                
                # Start new paragraph
                new_num = para_match.group(1)
                if new_num not in seen_numbers:
                    current_num = new_num
                    current_para = [line[para_match.end():].strip()]
                else:
                    current_para = []
                    current_num = None
            else:
                # Continue current paragraph
                if current_para:
                    current_para.append(line)
        
        # Handle last paragraph
        if current_para and current_num and current_num not in seen_numbers:
            content = ' '.join(current_para).strip()
            if self._is_valid_paragraph(content):
                paragraph = LegalParagraph(
                    number=current_num,
                    content=content,
                    page=page_num + 1,
                    section_type="main_text",
                    token_count=int(len(content.split()) * 1.3),
                    footnote_references=self._extract_footnote_references(content),
                    start_line=len(lines) - len(current_para),
                    end_line=len(lines),
                    extraction_method="hybrid_ocr",
                    confidence=0.8
                )
                paragraphs.append(paragraph)
                seen_numbers.add(current_num)
        
        return paragraphs
    
    def _is_valid_paragraph(self, content: str) -> bool:
        """Validate if content is a legitimate paragraph."""
        if len(content) < 50:
            return False
        
        # Check for common paragraph indicators
        if any(indicator in content.lower() for indicator in 
               ['chamber', 'court', 'evidence', 'statute', 'article']):
            return True
        
        return len(content.split()) >= 10
    
    def _extract_footnote_references(self, content: str) -> List[str]:
        """Extract footnote references from paragraph content."""
        # Look for superscript numbers or footnote references
        references = re.findall(r'(\d{1,3})', content)
        return references
    
    def process_page(self, page_num: int) -> Tuple[List[LegalParagraph], List[Footnote]]:
        """Process a single page with hybrid approach."""
        logger.info(f"Processing page {page_num + 1}...")
        
        # Extract footnotes using PyMuPDF
        footnotes = self.extract_footnotes_pymupdf(page_num)
        
        # Extract main text using OCR
        lines = self.extract_text_with_ocr(page_num)
        if not lines:
            return [], footnotes
        
        # Clean headers and footers
        cleaned_lines = self.clean_headers_footers(lines)
        
        # Extract paragraphs using OCR
        paragraphs = self.extract_paragraphs_ocr(cleaned_lines, page_num)
        
        logger.info(f"Page {page_num + 1}: {len(paragraphs)} paragraphs, {len(footnotes)} footnotes")
        
        return paragraphs, footnotes
    
    def process_document(self) -> Tuple[List[LegalParagraph], List[Footnote]]:
        """Process the entire document."""
        if not self.doc:
            self.open_document()
        
        all_paragraphs = []
        all_footnotes = []
        
        # Process all pages (skip first 6 pages)
        for page_num in range(self.config["skip_first_pages"], len(self.doc)):
            paragraphs, footnotes = self.process_page(page_num)
            all_paragraphs.extend(paragraphs)
            all_footnotes.extend(footnotes)
        
        self.paragraphs = all_paragraphs
        self.footnotes = all_footnotes
        
        logger.info(f"Document processing complete:")
        logger.info(f"  Total paragraphs: {len(all_paragraphs)}")
        logger.info(f"  Total footnotes: {len(all_footnotes)}")
        
        return all_paragraphs, all_footnotes
    
    def create_semantic_chunks(self) -> List[SemanticChunk]:
        """Create semantic chunks for RAG."""
        chunks = []
        chunk_id = 1
        
        # Group paragraphs by page
        paragraphs_by_page = {}
        for para in self.paragraphs:
            if para.page not in paragraphs_by_page:
                paragraphs_by_page[para.page] = []
            paragraphs_by_page[para.page].append(para)
        
        # Create chunks
        for page_num in sorted(paragraphs_by_page.keys()):
            page_paragraphs = paragraphs_by_page[page_num]
            page_footnotes = [f for f in self.footnotes if f.page == page_num]
            
            # Create paragraph chunks
            for para in page_paragraphs:
                chunk = SemanticChunk(
                    chunk_id=f"para_{chunk_id}",
                    content=para.content,
                    chunk_type="paragraph",
                    page_range=(para.page, para.page),
                    paragraph_numbers=[para.number],
                    footnote_numbers=para.footnote_references,
                    token_count=para.token_count,
                    metadata={
                        "extraction_method": para.extraction_method,
                        "confidence": para.confidence,
                        "section_type": para.section_type
                    }
                )
                chunks.append(chunk)
                chunk_id += 1
            
            # Create footnote chunks
            for footnote in page_footnotes:
                chunk = SemanticChunk(
                    chunk_id=f"footnote_{chunk_id}",
                    content=footnote.content,
                    chunk_type="footnote",
                    page_range=(footnote.page, footnote.page),
                    paragraph_numbers=[],
                    footnote_numbers=[footnote.number],
                    token_count=int(len(footnote.content.split()) * 1.3),
                    metadata={
                        "detection_method": footnote.detection_method,
                        "confidence": footnote.confidence
                    }
                )
                chunks.append(chunk)
                chunk_id += 1
        
        return chunks
    
    def save_results(self, output_dir: str = "output_hybrid"):
        """Save extraction results to files."""
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        # Save paragraphs
        paragraphs_data = [asdict(p) for p in self.paragraphs]
        with open(f"{output_dir}/hybrid_paragraphs.json", "w", encoding="utf-8") as f:
            json.dump(paragraphs_data, f, indent=2, ensure_ascii=False)
        
        # Save footnotes
        footnotes_data = [asdict(f) for f in self.footnotes]
        with open(f"{output_dir}/hybrid_footnotes.json", "w", encoding="utf-8") as f:
            json.dump(footnotes_data, f, indent=2, ensure_ascii=False)
        
        # Save chunks
        chunks = self.create_semantic_chunks()
        chunks_data = [asdict(c) for c in chunks]
        with open(f"{output_dir}/hybrid_chunks.json", "w", encoding="utf-8") as f:
            json.dump(chunks_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Results saved to {output_dir}/")
    
    def close(self):
        """Close the document."""
        if self.doc:
            self.doc.close()

def main():
    """Main function to run the hybrid chunking."""
    chunker = HybridPyMuPDFOCRChunker("data/jugement.pdf")
    
    try:
        # Process the document
        paragraphs, footnotes = chunker.process_document()
        
        # Create and save results
        chunker.save_results()
        
        # Print summary
        print(f"\n=== HYBRID PYMUPDF + OCR CHUNKING RESULTS ===")
        print(f"Total paragraphs: {len(paragraphs)}")
        print(f"Total footnotes: {len(footnotes)}")
        
        # Show paragraph number range
        if paragraphs:
            para_numbers = [int(p.number) for p in paragraphs if p.number.isdigit()]
            if para_numbers:
                print(f"Paragraph number range: {min(para_numbers)} - {max(para_numbers)}")
        
        # Show footnote number range
        if footnotes:
            footnote_numbers = [int(f.number) for f in footnotes if f.number.isdigit()]
            if footnote_numbers:
                print(f"Footnote number range: {min(footnote_numbers)} - {max(footnote_numbers)}")
        
    finally:
        chunker.close()

if __name__ == "__main__":
    main()
