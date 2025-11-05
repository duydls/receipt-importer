#!/usr/bin/env python3
"""
Costco PDF Processor
Processes Costco PDF receipts using text-based line pattern extraction.
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


class CostcoPDFProcessor:
    """Process Costco PDF receipts using text-based line pattern extraction"""
    
    def __init__(self, rule_loader, input_dir=None):
        """
        Initialize Costco PDF processor
        
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
        
        # Import CostcoParser for line pattern parsing
        from .legacy.costco_parser import CostcoParser
        self.costco_parser = CostcoParser()
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Process a Costco PDF file using text-based line pattern extraction
        
        Args:
            file_path: Path to PDF file
            detected_vendor_code: Vendor code from detection (optional)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        if not PDFPLUMBER_AVAILABLE:
            logger.error("pdfplumber not available. Cannot process Costco PDF files.")
            return None
        
        try:
            # Extract text from PDF
            pdf_text = self._extract_pdf_text(file_path)
            if not pdf_text:
                logger.warning(f"Could not extract text from {file_path.name}")
                return None
            
            # Load Costco PDF layout rules
            costco_layouts = self.rule_loader.load_rule_file_by_name('20_costco_layout.yaml')
            if not costco_layouts or 'costco_layouts' not in costco_layouts:
                logger.warning("Costco layout rules not found")
                return None
            
            # Find PDF multiline layout
            pdf_layout = None
            for layout in costco_layouts['costco_layouts']:
                if layout.get('parsed_by') == 'costco_pdf_multiline_v1':
                    pdf_layout = layout
                    break
            
            if not pdf_layout:
                logger.warning("Costco PDF multiline layout not found in rules")
                return None
            
            # Parse receipt using CostcoParser with layout rules
            all_items = self.costco_parser.parse_costco_receipt(pdf_text, layout=pdf_layout)
            
            if not all_items:
                logger.warning(f"No items extracted from {file_path.name}")
                return None
            
            # Filter out summary items (SUBTOTAL, TAX, TOTAL, etc.)
            items = [item for item in all_items if not item.get('is_summary', False)]
            
            if not items:
                logger.warning(f"No product items extracted from {file_path.name} (only summary items found)")
                return None
            
            # Extract totals from text
            totals = self._extract_totals_from_text(pdf_text)
            
            # Build receipt data
            receipt_data = {
                'filename': file_path.name,
                'source_file': str(file_path),
                'vendor_code': 'COSTCO',
                'detected_vendor_code': detected_vendor_code or 'COSTCO',
                'source_type': 'localgrocery_based',
                'items': items,
                'parsed_by': 'costco_pdf_multiline_v1',
                'subtotal': totals.get('subtotal', 0.0),
                'tax': totals.get('tax', 0.0),
                'total': totals.get('total', 0.0),
                'currency': 'USD'
            }
            
            # Extract transaction date
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})', pdf_text)
            if date_match:
                receipt_data['transaction_date'] = date_match.group(1)
            
            # Extract items sold count
            items_sold_match = re.search(r'TOTAL NUMBER OF ITEMS SOLD\s*=\s*(\d+)', pdf_text, re.IGNORECASE)
            if items_sold_match:
                receipt_data['items_sold'] = int(items_sold_match.group(1))
            
            # Enrich with knowledge base
            if receipt_data.get('items'):
                receipt_data['items'] = self._enrich_costco_items(receipt_data['items'])
            
            logger.info(f"Extracted {len(items)} items from Costco PDF {file_path.name}")
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing Costco PDF {file_path.name}: {e}", exc_info=True)
            return None
    
    def _extract_pdf_text(self, file_path: Path) -> str:
        """Extract text from PDF using pdfplumber"""
        text = ""
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text(layout=True)  # layout=True preserves structure
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            logger.debug(f"Text extraction failed: {e}")
        return text
    
    def _extract_totals_from_text(self, text: str) -> Dict[str, float]:
        """Extract subtotal, tax, and total from PDF text"""
        totals = {
            'subtotal': 0.0,
            'tax': 0.0,
            'total': 0.0
        }
        
        # Extract subtotal
        subtotal_match = re.search(r'SUBTOTAL\s+(\d+\.\d{2})', text, re.IGNORECASE)
        if subtotal_match:
            totals['subtotal'] = float(subtotal_match.group(1))
        
        # Extract tax
        tax_match = re.search(r'TAX\s+(\d+\.\d{2})', text, re.IGNORECASE)
        if tax_match:
            totals['tax'] = float(tax_match.group(1))
        
        # Extract total (look for "TOTAL" or "**** TOTAL")
        total_match = re.search(r'(?:\*\*\*\*)?\s*TOTAL\s+(\d+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            totals['total'] = float(total_match.group(1))
        
        return totals
    
    def _enrich_costco_items(self, items: List[Dict]) -> List[Dict]:
        """Enrich Costco items with knowledge base data"""
        if not self._legacy_processor:
            return items
        
        # Use ReceiptProcessor to enrich with KB (same as Excel processor)
        # The enrich_with_vendor_kb method is in receipt_processor.py
        try:
            # Check if method exists
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                enriched_items = self._legacy_processor.enrich_with_vendor_kb(
                    items,
                    vendor_code='COSTCO'
                )
                return enriched_items
            else:
                # Fallback: use vendor_profiles if available
                from .vendor_profiles import VendorProfileHandler
                from .rule_loader import RuleLoader
                rules_dir = Path(__file__).parent.parent / 'step1_rules'
                kb_file = str(self.input_dir / 'knowledge_base.json') if self.input_dir and (self.input_dir / 'knowledge_base.json').exists() else None
                rule_loader = RuleLoader(rules_dir)
                vendor_profiles_config = rule_loader.load_rule_file_by_name('vendor_profiles.yaml')
                vendor_handler = VendorProfileHandler(vendor_profiles_config.get('vendor_profiles', {}), rules_dir, kb_file)
                enriched_items = []
                for item in items:
                    enriched_item = vendor_handler.lookup_cached(item, vendor_code='COSTCO')
                    enriched_items.append(enriched_item)
                return enriched_items
        except Exception as e:
            logger.warning(f"Error enriching Costco items: {e}")
            return items

