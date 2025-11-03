#!/usr/bin/env python3
"""
Text Extractor - Extract text directly from PDF files
Primary method before OCR fallback
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Try PyMuPDF (fitz) - best for structured PDFs
try:
    import fitz  # PyMuPDF
    MUPDF_AVAILABLE = True
except ImportError:
    MUPDF_AVAILABLE = False
    logger.warning("PyMuPDF not available. Install with: pip install pymupdf")

# Try PyPDF2 - fallback for text extraction
try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("PyPDF2 not available. Install with: pip install PyPDF2")


class TextExtractor:
    """Extract text directly from PDF files without OCR"""
    
    def __init__(self, threshold: int = 200):
        """
        Initialize text extractor
        
        Args:
            threshold: Minimum character count to consider text valid (default: 200)
        """
        self.threshold = threshold
    
    def extract_text(self, pdf_path: Path) -> Optional[str]:
        """
        Extract text from PDF using direct methods (no OCR)
        
        Tries:
        1. PyMuPDF (fitz) - best for structured PDFs
        2. PyPDF2 - fallback method
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text or None if extraction fails
        """
        text = None
        
        # Method 1: Try PyMuPDF (best for structured PDFs)
        if MUPDF_AVAILABLE:
            try:
                text = self._extract_with_mupdf(pdf_path)
                if text and self._is_valid_text(text):
                    logger.debug(f"Extracted text using PyMuPDF ({len(text)} chars)")
                    return text
            except Exception as e:
                logger.debug(f"PyMuPDF extraction failed: {e}")
        
        # Method 2: Try PyPDF2
        if PDF_AVAILABLE:
            try:
                pdf_text = self._extract_with_pypdf2(pdf_path)
                if pdf_text and self._is_valid_text(pdf_text):
                    logger.debug(f"Extracted text using PyPDF2 ({len(pdf_text)} chars)")
                    return pdf_text
                elif pdf_text and not text:
                    text = pdf_text
            except Exception as e:
                logger.debug(f"PyPDF2 extraction failed: {e}")
        
        # Return whatever we got, even if below threshold (caller decides if OCR needed)
        return text
    
    def _extract_with_mupdf(self, pdf_path: Path) -> str:
        """Extract text using PyMuPDF (fitz)"""
        doc = fitz.open(pdf_path)
        text = ""
        try:
            for page_num, page in enumerate(doc):
                page_text = page.get_text()
                text += page_text
                if page_num > 0:
                    text += "\n"  # Add page break
        finally:
            doc.close()
        return text
    
    def _extract_with_pypdf2(self, pdf_path: Path) -> str:
        """Extract text using PyPDF2"""
        text = ""
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    
    def _is_valid_text(self, text: Optional[str]) -> bool:
        """
        Check if extracted text is valid (not empty, not mostly whitespace, not unreadable symbols)
        
        Args:
            text: Text to validate
            
        Returns:
            True if text is valid, False otherwise
        """
        if not text:
            return False
        
        # Remove whitespace for length check
        cleaned = text.strip()
        
        # Must have minimum character count
        if len(cleaned) < self.threshold:
            return False
        
        # Check for unreadable patterns (mostly symbols, no letters/numbers)
        # At least 20% should be alphanumeric
        alphanumeric_count = sum(1 for c in cleaned if c.isalnum())
        if len(cleaned) > 0:
            alphanumeric_ratio = alphanumeric_count / len(cleaned)
            if alphanumeric_ratio < 0.2:
                logger.debug(f"Text appears to be mostly symbols (ratio: {alphanumeric_ratio:.2f})")
                return False
        
        # Check for PDF stream artifacts (common in scanned PDFs)
        if any(pattern in text for pattern in ['<< /Type', '/Filter /FlateDecode', 'stream']):
            # If we see stream markers but have reasonable text, it's OK
            # But if >50% of lines contain stream artifacts, it's invalid
            lines = text.split('\n')
            stream_lines = sum(1 for line in lines if any(p in line for p in ['<< /', '/Filter', 'stream', 'endstream']))
            if len(lines) > 0 and stream_lines / len(lines) > 0.5:
                logger.debug(f"Text contains too many PDF stream artifacts ({stream_lines}/{len(lines)} lines)")
                return False
        
        return True

