#!/usr/bin/env python3
"""
Aldi PDF Processor
Processes Aldi PDF receipts using OCR-based extraction (image-based PDFs).
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
import pandas as pd

logger = logging.getLogger(__name__)

# Try to import pdfplumber
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available. Install with: pip install pdfplumber")

# Try to import OCR libraries
try:
    import pytesseract
    from PIL import Image
    import fitz  # PyMuPDF
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.debug("OCR libraries not available. Install with: pip install pytesseract Pillow pymupdf")


class AldiPDFProcessor:
    """Process Aldi PDF receipts using OCR-based extraction"""
    
    def __init__(self, rule_loader, input_dir=None):
        """
        Initialize Aldi PDF processor
        
        Args:
            rule_loader: RuleLoader instance
            input_dir: Input directory path (for knowledge base location)
        """
        self.rule_loader = rule_loader
        self.input_dir = Path(input_dir) if input_dir else None
        
        # Prepare config with knowledge base file path
        config = {}
        if self.input_dir:
            kb_file = self.input_dir / 'knowledge_base.json'
            if kb_file.exists():
                config['knowledge_base_file'] = str(kb_file)
        
        # Import ReceiptProcessor for knowledge base enrichment
        from .receipt_processor import ReceiptProcessor
        self._legacy_processor = ReceiptProcessor(config=config)
        
        # Import LayoutApplier to apply layout rules
        from .layout_applier import LayoutApplier
        self.layout_applier = LayoutApplier(rule_loader)
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Process an Aldi PDF file using OCR-based text extraction
        
        Args:
            file_path: Path to PDF file
            detected_vendor_code: Vendor code from detection (optional)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        if not PDFPLUMBER_AVAILABLE:
            logger.error("pdfplumber not available. Cannot process Aldi PDF files.")
            return None
        
        try:
            vendor_code = detected_vendor_code or 'ALDI'
            
            # Try to extract text first (for text-based PDFs)
            pdf_text = self._extract_pdf_text(file_path)
            
            # If text extraction failed, try OCR for image-based PDFs
            if not pdf_text:
                logger.info(f"Could not extract text from {file_path.name} - trying OCR for image-based PDF")
                if OCR_AVAILABLE:
                    pdf_text = self._extract_pdf_text_ocr(file_path)
                    if not pdf_text:
                        logger.warning(f"OCR extraction also failed for {file_path.name}")
                        return None
                    logger.info(f"Successfully extracted text using OCR from {file_path.name}")
                else:
                    logger.warning(f"Could not extract text from {file_path.name} - OCR not available")
                    return None
            
            # Parse receipt text (Aldi format: _ ITEM_NUMBER PRODUCT_NAME SIZE UOM PRICE)
            items = self._parse_receipt_text(pdf_text)
            
            if not items:
                logger.warning(f"No items extracted from {file_path.name}")
                return None
            
            # Extract totals from PDF text
            totals = self._extract_totals_from_text(pdf_text)
            
            # Build receipt data
            receipt_data = {
                'filename': file_path.name,
                'vendor': 'ALDI',
                'detected_vendor_code': vendor_code,
                'detected_source_type': 'localgrocery_based',
                'source_file': str(file_path.name),
                'items': items,
                'parsed_by': 'aldi_pdf_v1',
                'subtotal': totals.get('subtotal', 0.0),
                'tax': totals.get('tax', 0.0),
                'total': totals.get('total', 0.0),
                'currency': 'USD'
            }
            
            # Enrich with knowledge base
            receipt_data['items'] = self._enrich_aldi_items(receipt_data.get('items', []))
            
            logger.info(f"Extracted {len(items)} items from Aldi PDF {file_path.name}")
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing Aldi PDF {file_path.name}: {e}", exc_info=True)
            return None
    
    def _extract_pdf_text(self, file_path: Path) -> str:
        """Extract text from PDF for detection and totals"""
        text = ""
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            logger.debug(f"Text extraction failed: {e}")
        return text
    
    def _extract_pdf_text_ocr(self, file_path: Path) -> str:
        """Extract text from image-based PDF using OCR"""
        if not OCR_AVAILABLE:
            return ""
        
        try:
            import pytesseract
            from PIL import Image
            import fitz  # PyMuPDF
            
            text = ""
            doc = fitz.open(file_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                # Render page to image (300 DPI for good quality)
                mat = fitz.Matrix(300/72, 300/72)  # 300 DPI
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Run OCR
                tesseract_config = r'--oem 3 --psm 6'  # Uniform block of text
                ocr_text = pytesseract.image_to_string(img, config=tesseract_config)
                
                if ocr_text:
                    text += ocr_text + "\n"
            
            doc.close()
            return text
            
        except Exception as e:
            logger.debug(f"OCR text extraction failed: {e}")
            return ""
    
    def _parse_receipt_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse Aldi receipt text into items
        
        Format example:
        "_ 418510 Heavy Whip 32 02 10,78 FB"
        - "_" prefix indicates product line
        - "418510" is item number
        - "Heavy Whip" is product name
        - "32 02" might be size (32 oz)
        - "10,78" is price
        - "FB" might be UOM or other info
        """
        items = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Find summary section (SUBTOTAL, TAX, AMOUNT DUE, etc.)
        summary_start = len(lines)
        for i, line in enumerate(lines):
            line_upper = line.upper()
            if any(keyword in line_upper for keyword in ['SUBTOTAL', 'TAX', 'AMOUNT DUE', 'TOTAL']):
                summary_start = i
                break
        
        # Parse product lines (lines starting with "_")
        for i in range(summary_start):
            line = lines[i]
            
            # Aldi format: _ ITEM_NUMBER PRODUCT_NAME ... PRICE
            # Pattern: _ digits product_name ... price (with comma or dot)
            if line.startswith('_'):
                # Extract item number and price
                # Pattern: _ NUMBER PRODUCT ... PRICE
                item_match = re.match(r'_\s+(\d+)\s+(.+?)\s+(\d+[.,]\d{2})\s*', line)
                if item_match:
                    item_number = item_match.group(1)
                    product_text = item_match.group(2).strip()
                    price_text = item_match.group(3).replace(',', '.')
                    price_value = float(price_text)
                    
                    # Parse product name (remove size/UOM info if present)
                    # Try to extract size/UOM from product_text
                    product_name = product_text
                    size = None
                    uom = None
                    
                    # Look for size patterns: "32 02", "10 LB", etc.
                    size_match = re.search(r'(\d+)\s*(LB|LBS|OZ|OZS|CT|GAL|GALS|EA|EACH)', product_text, re.IGNORECASE)
                    if size_match:
                        size = size_match.group(1)
                        uom = size_match.group(2).upper()
                        # Remove size from product name
                        product_name = product_text[:size_match.start()].strip()
                    
                    item = {
                        'vendor': 'ALDI',
                        'item_number': item_number,
                        'product_name': product_name,
                        'description': product_text,
                        'quantity': 1.0,
                        'unit_price': price_value,
                        'total_price': price_value,
                        'purchase_uom': uom or 'EACH',
                        'is_summary': False,
                    }
                    items.append(item)
        
        return items
    
    def _extract_totals_from_text(self, text: str) -> Dict[str, float]:
        """Extract subtotal, tax, and total from PDF text"""
        totals = {
            'subtotal': 0.0,
            'tax': 0.0,
            'total': 0.0
        }
        
        # Extract subtotal (handle comma decimal separator)
        subtotal_match = re.search(r'SUBTOTAL\s+(\d+[.,]\d{2})', text, re.IGNORECASE)
        if subtotal_match:
            totals['subtotal'] = float(subtotal_match.group(1).replace(',', '.'))
        
        # Extract tax (handle comma decimal separator)
        tax_match = re.search(r'(?:TAX|TAXABLE)\s+.*?(\d+[.,]\d{2})', text, re.IGNORECASE)
        if tax_match:
            totals['tax'] = float(tax_match.group(1).replace(',', '.'))
        
        # Extract total/amount due (handle comma decimal separator)
        total_match = re.search(r'(?:AMOUNT\s+DUE|TOTAL)\s+(\d+[.,]\d{2})', text, re.IGNORECASE)
        if total_match:
            totals['total'] = float(total_match.group(1).replace(',', '.'))
        
        return totals
    
    def _enrich_aldi_items(self, items: List[Dict]) -> List[Dict]:
        """Enrich Aldi items with knowledge base data"""
        if not self._legacy_processor:
            return items
        
        try:
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                enriched_items = self._legacy_processor.enrich_with_vendor_kb(
                    items,
                    vendor_code='ALDI'
                )
                return enriched_items
        except Exception as e:
            logger.warning(f"Error enriching Aldi items: {e}")
        
        return items

