#!/usr/bin/env python3
"""
Jewel-Osco PDF Processor
Processes Jewel-Osco PDF receipts using text-based extraction.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Try to import pdfplumber
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available. Install with: pip install pdfplumber")


class JewelPDFProcessor:
    """Process Jewel-Osco PDF receipts using text-based extraction"""
    
    def __init__(self, rule_loader, input_dir=None):
        """
        Initialize Jewel-Osco PDF processor
        
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
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Process a Jewel-Osco PDF file using text-based extraction
        
        Args:
            file_path: Path to PDF file
            detected_vendor_code: Vendor code from detection (optional)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        if not PDFPLUMBER_AVAILABLE:
            logger.error("pdfplumber not available. Cannot process Jewel-Osco PDF files.")
            return None
        
        try:
            # Extract text from PDF
            pdf_text = self._extract_pdf_text(file_path)
            if not pdf_text:
                logger.warning(f"Could not extract text from {file_path.name}")
                return None
            
            # Parse receipt text
            items = self._parse_receipt_text(pdf_text)
            
            if not items:
                logger.warning(f"No items extracted from {file_path.name}")
                return None
            
            # Extract totals from text
            totals = self._extract_totals_from_text(pdf_text)
            
            # Build receipt data
            receipt_data = {
                'filename': file_path.name,
                'source_file': str(file_path),
                'vendor_code': 'JEWEL',
                'detected_vendor_code': detected_vendor_code or 'JEWEL',
                'source_type': 'localgrocery_based',
                'items': items,
                'parsed_by': 'jewel_pdf_v1',
                'subtotal': totals.get('subtotal', 0.0),
                'tax': totals.get('tax', 0.0),
                'total': totals.get('total', 0.0),
                'currency': 'USD'
            }
            
            # Extract transaction date
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})', pdf_text)
            if date_match:
                receipt_data['transaction_date'] = date_match.group(1)
            
            # Enrich with knowledge base
            if receipt_data.get('items'):
                receipt_data['items'] = self._enrich_jewel_items(receipt_data['items'])
            
            logger.info(f"Extracted {len(items)} items from Jewel-Osco PDF {file_path.name}")
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing Jewel-Osco PDF {file_path.name}: {e}", exc_info=True)
            return None
    
    def _extract_pdf_text(self, file_path: Path) -> str:
        """Extract text from PDF using pdfplumber"""
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
    
    def _parse_receipt_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse Jewel-Osco receipt text into items
        
        Format example:
        "Signature Select Sugar Granulated 10 Lb $8.99
        Quantity: 1"
        
        or
        
        "Cauliflower Florets - 0.67lb @4.96/lb $3.32
        Quantity: 1"
        """
        items = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Find the receipt section (after "Here is your receipt from")
        receipt_start = -1
        for i, line in enumerate(lines):
            if 'Here is your receipt from' in line or 'Order Details' in line:
                receipt_start = i
                break
        
        if receipt_start == -1:
            # Try to find product lines anyway
            receipt_start = 0
        
        # Find summary section (Subtotal, Tax, Total)
        summary_start = len(lines)
        for i in range(receipt_start, len(lines)):
            line = lines[i]
            if any(keyword in line.upper() for keyword in ['SUBTOTAL', 'TOTAL', 'TAX']) and 'Order Details' not in line:
                summary_start = i
                break
        
        # Parse product lines
        i = receipt_start
        while i < summary_start:
            line = lines[i]
            
            # Look for product + price pattern: "Product Name $XX.XX"
            # Pattern: product name (can have multi-word) followed by $XX.XX
            price_match = re.search(r'\$(\d+\.\d{2})\s*$', line)
            if price_match:
                price_value = float(price_match.group(1))
                # Extract product name (everything before the $)
                product_text = line[:price_match.start()].strip()
                
                # Skip if it's a summary line
                if any(keyword in product_text.upper() for keyword in ['SUBTOTAL', 'TOTAL', 'TAX', 'QUANTITY', 'TOTAL ITEMS']):
                    i += 1
                    continue
                
                # Look for quantity on next line
                quantity = 1.0
                if i + 1 < summary_start:
                    next_line = lines[i + 1]
                    qty_match = re.search(r'Quantity:\s*(\d+(?:\.\d+)?)', next_line, re.IGNORECASE)
                    if qty_match:
                        quantity = float(qty_match.group(1))
                        i += 1  # Skip the quantity line
                
                # Calculate unit price
                unit_price = price_value / quantity if quantity > 0 else price_value
                
                # Parse product name to extract size/UoM
                product_name_clean, size, uom = self._parse_product_line(product_text)
                
                item = {
                    'vendor': 'Jewel-Osco',
                    'product_name': product_name_clean,
                    'description': product_text,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': price_value,
                    'purchase_uom': uom,
                    'is_summary': False,
                }
                items.append(item)
            
            i += 1
        
        return items
    
    def _parse_product_line(self, product_text: str) -> tuple:
        """
        Parse product line to extract name, size, and unit
        
        Examples:
        "Signature Select Sugar Granulated 10 Lb" -> ("Sugar Granulated", "10", "LB")
        "Cauliflower Florets - 0.67lb @4.96/lb" -> ("Cauliflower Florets", "0.67", "LB")
        """
        # Try to extract size/unit patterns
        size_patterns = [
            (r'(.+?)\s+(\d+(?:\.\d+)?)\s*(LB|LBS|OZ|OZS|CT|PACK|PK|QT|QTS|GAL|GALS|EA|EACH|L|ML|FL\s*OZ)\s*\.?$', re.IGNORECASE),
            (r'(.+?)\s+(\d+(?:\.\d+)?)(LB|LBS|OZ|OZS|CT|PACK|PK|QT|QTS|GAL|GALS|EA|EACH|L|ML|FL\s*OZ)\s*\.?$', re.IGNORECASE),
            (r'(.+?)\s+-\s+(\d+(?:\.\d+)?)\s*(LB|LBS|OZ|OZS|CT|PACK|PK|QT|QTS|GAL|GALS|EA|EACH|L|ML|FL\s*OZ)\s*', re.IGNORECASE),
        ]
        
        for pattern, flags in size_patterns:
            match = re.search(pattern, product_text, flags)
            if match:
                product_name = match.group(1).strip()
                size = match.group(2)
                uom = match.group(3).upper().strip()
                return product_name, size, uom
        
        # No size/unit found, return whole line as product name
        return product_text, None, 'EACH'
    
    def _extract_totals_from_text(self, text: str) -> Dict[str, float]:
        """Extract subtotal, tax, and total from PDF text"""
        totals = {
            'subtotal': 0.0,
            'tax': 0.0,
            'total': 0.0
        }
        
        # Extract subtotal
        subtotal_match = re.search(r'Subtotal\s+\$?(\d+\.\d{2})', text, re.IGNORECASE)
        if subtotal_match:
            totals['subtotal'] = float(subtotal_match.group(1))
        
        # Extract tax (Sales Tax or Taxes and Fees)
        tax_match = re.search(r'(?:Sales\s+Tax|Taxes?\s+and\s+Fees?)\s+\$?(\d+\.\d{2})', text, re.IGNORECASE)
        if tax_match:
            totals['tax'] = float(tax_match.group(1))
        
        # Extract total (look for "Total $XX.XX" but not "Total Items")
        # Try multiple patterns to find the total
        # Match "Total $XX.XX" on its own line (not "Total Items")
        total_patterns = [
            r'^Total\s+\$(\d+\.\d{2})(?:\s|$)',  # "Total $9.19" at start of line
            r'^Total\s+(\d+\.\d{2})(?:\s|$)',     # "Total 9.19" at start of line
            r'\nTotal\s+\$(\d+\.\d{2})(?:\s|$)',  # "Total $9.19" after newline
            r'\nTotal\s+(\d+\.\d{2})(?:\s|$)',    # "Total 9.19" after newline
        ]
        
        for pattern in total_patterns:
            total_match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if total_match:
                # Check that it's not "Total Items" - look at context before the match
                match_start = total_match.start()
                context_before = text[max(0, match_start-30):match_start]
                if 'Total Items' not in context_before and 'Items' not in context_before:
                    totals['total'] = float(total_match.group(1))
                    break
        
        return totals
    
    def _enrich_jewel_items(self, items: List[Dict]) -> List[Dict]:
        """Enrich Jewel-Osco items with knowledge base data"""
        if not self._legacy_processor:
            return items
        
        # Use ReceiptProcessor to enrich with KB
        try:
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                enriched_items = self._legacy_processor.enrich_with_vendor_kb(
                    items,
                    vendor_code='JEWEL'
                )
                return enriched_items
        except Exception as e:
            logger.warning(f"Error enriching Jewel items: {e}")
        
        return items

