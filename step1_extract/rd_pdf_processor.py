#!/usr/bin/env python3
"""
RD PDF Processor - Grid Mode Extraction
Processes Restaurant Depot PDF receipts using grid-based table extraction.

Processing Flow:
1. Vendor detection (handled by main.py via VendorDetector)
2. PDF grid extraction using pdfplumber (layout-preserving)
3. Convert table to DataFrame
4. Apply layout rules using LayoutApplier (same as Excel)
5. UoM extraction (always applied: 30_uom_extraction.yaml)

See step1_rules/21_rd_pdf_layout.yaml for layout rules.
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


class RDPDFProcessor:
    """Process Restaurant Depot PDF receipts using grid-based table extraction"""
    
    def __init__(self, rule_loader, input_dir=None):
        """
        Initialize RD PDF processor
        
        Args:
            rule_loader: RuleLoader instance
            input_dir: Input directory path (for knowledge base location)
        """
        self.rule_loader = rule_loader
        self.input_dir = Path(input_dir) if input_dir else None
        
        # Prepare config with knowledge base file path (from input folder)
        config = {}
        if self.input_dir:
            kb_file = self.input_dir / 'knowledge_base.json'
            if kb_file.exists():
                config['knowledge_base_file'] = str(kb_file)
        
        # Import existing ReceiptProcessor for knowledge base enrichment
        from .receipt_processor import ReceiptProcessor
        self._legacy_processor = ReceiptProcessor(config=config)
        
        # Import LayoutApplier to apply layout rules (same as Excel)
        from .layout_applier import LayoutApplier
        self.layout_applier = LayoutApplier(rule_loader)
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Process an RD PDF file using grid-based table extraction
        
        Args:
            file_path: Path to PDF file
            detected_vendor_code: Vendor code from detection (optional)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        if not PDFPLUMBER_AVAILABLE:
            logger.error("pdfplumber not available. Cannot process RD PDF files.")
            return None
        
        try:
            # Extract text from PDF for detection and totals (may be empty for image-based PDFs)
            pdf_text = self._extract_pdf_text(file_path)
            
            # Extract table using pdfplumber (grid mode)
            # Note: Layout matching will be done by LayoutApplier using rules from 21_rd_layout.yaml
            # Try table extraction even if text extraction failed (for image-based PDFs)
            df = self._extract_table_from_pdf(file_path)
            
            if df is None or df.empty:
                if not pdf_text:
                    logger.warning(f"Could not extract text or tables from {file_path.name} - PDF may be image-based (requires OCR)")
                else:
                    logger.warning(f"Could not extract table from {file_path.name} (text extraction succeeded but no tables found)")
                return None
            
            # If text extraction failed but table extraction succeeded, use empty string for text
            if not pdf_text:
                logger.info(f"Table extraction succeeded but text extraction failed for {file_path.name} - PDF may be image-based")
                pdf_text = ""  # Use empty string to avoid None errors
            
            # Prepare receipt context
            receipt_data = {
                'filename': file_path.name,
                'vendor': 'RD',
                'detected_vendor_code': vendor_code,
                'detected_source_type': 'localgrocery_based',
                'source_file': str(file_path.name),
                'items': [],
                'subtotal': 0.0,
                'tax': 0.0,
                'total': 0.0,
                'currency': 'USD'
            }
            
            # Apply layout rules using LayoutApplier (same as Excel)
            # Note: Excel layout rules work for PDF tables too since they have the same column mappings
            items = self.layout_applier.apply_layout_to_excel(
                df, vendor_code, receipt_data, file_path=file_path, receipt_text=pdf_text
            )
            
            if not items:
                logger.warning(f"No items extracted from {file_path.name}")
                return None
            
            receipt_data['items'] = items
            
            # Extract totals from PDF text (using regex patterns)
            self._extract_totals_from_text(pdf_text, receipt_data)
            
            # Set parsed_by (will be set by LayoutApplier if layout matched)
            if not receipt_data.get('parsed_by'):
                receipt_data['parsed_by'] = 'rd_pdf_v1'
            
            # Enrich with knowledge base (same as Excel)
            if self._legacy_processor:
                receipt_data = self._legacy_processor.enrich_with_vendor_kb(receipt_data, vendor_code)
            
            logger.info(f"Extracted {len(items)} items from RD PDF {file_path.name}")
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing RD PDF {file_path.name}: {e}", exc_info=True)
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
    
    def _extract_table_from_pdf(self, file_path: Path) -> Optional[pd.DataFrame]:
        """
        Extract table from PDF using pdfplumber (grid mode)
        
        Args:
            file_path: Path to PDF file
            layout: Layout configuration
            
        Returns:
            DataFrame with extracted table data
        """
        try:
            tables = []
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # Try multiple table extraction strategies
                    # Strategy 1: Standard table extraction
                    page_tables = page.extract_tables()
                    if page_tables:
                        tables.extend(page_tables)
                        logger.debug(f"Found {len(page_tables)} tables on page {page_num + 1} using standard extraction")
                        continue
                    
                    # Strategy 2: Try with different settings for better detection
                    page_tables = page.extract_tables(table_settings={
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "explicit_vertical_lines": [],
                        "explicit_horizontal_lines": [],
                        "snap_tolerance": 3,
                        "join_tolerance": 3,
                        "edge_tolerance": 3,
                        "intersection_tolerance": 3,
                    })
                    if page_tables:
                        tables.extend(page_tables)
                        logger.debug(f"Found {len(page_tables)} tables on page {page_num + 1} using line-based extraction")
                        continue
                    
                    # Strategy 3: Try text-based extraction (if PDF has text but no table structure)
                    text = page.extract_text()
                    if text and "Item Description" in text:
                        logger.debug(f"Found text with 'Item Description' on page {page_num + 1}, but no table structure")
                        # Could try to parse text as table manually, but for now just log
            
            if not tables:
                logger.debug(f"No tables found in PDF {file_path.name} - may be image-based or unstructured")
                return None
            
            # Find the table with the header row matching RD layout
            # Look for headers: "Item Description" and "Extended Amount"
            header_patterns = [
                r'Item\s+Description',
                r'Extended\s+Amount',
            ]
            
            for table in tables:
                if not table or len(table) < 2:
                    continue
                
                # Check if first row matches header patterns
                header_row = table[0]
                header_text = ' '.join(str(cell) if cell else '' for cell in header_row)
                
                matches = False
                for pattern in header_patterns:
                    if re.search(pattern, header_text, re.IGNORECASE):
                        matches = True
                        break
                
                if matches:
                    # Convert table to DataFrame
                    df = pd.DataFrame(table[1:], columns=table[0])
                    
                    # Clean column names
                    df.columns = [str(col).strip() if col else '' for col in df.columns]
                    
                    logger.info(f"Extracted table with {len(df)} rows from PDF")
                    return df
            
            # If no table matches header, try first table
            if tables:
                table = tables[0]
                if table and len(table) >= 2:
                    df = pd.DataFrame(table[1:], columns=table[0])
                    df.columns = [str(col).strip() if col else '' for col in df.columns]
                    logger.info(f"Using first table with {len(df)} rows (header may not match)")
                    return df
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting table from PDF: {e}", exc_info=True)
            return None
    
    def _extract_totals_from_text(self, text: str, receipt_data: Dict[str, Any]):
        """Extract subtotal, tax, and total from PDF text using regex patterns"""
        # Extract subtotal
        subtotal_patterns = [
            r'Subtotal[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Sub\s+Total[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
        ]
        for pattern in subtotal_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    receipt_data['subtotal'] = value
                    break
                except (ValueError, IndexError):
                    continue
        
        # Extract tax
        tax_patterns = [
            r'Taxes?[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Tax[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Sales\s+Tax[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
        ]
        for pattern in tax_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    receipt_data['tax'] = value
                    break
                except (ValueError, IndexError):
                    continue
        
        # Extract total
        total_patterns = [
            r'Total[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Grand\s+Total[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Transaction\s+Total[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
        ]
        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    receipt_data['total'] = value
                    break
                except (ValueError, IndexError):
                    continue
    

