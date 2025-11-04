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

# Try to import OCR libraries
try:
    import pytesseract
    from PIL import Image
    import fitz  # PyMuPDF for PDF to image conversion
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.debug("OCR libraries not available. Install with: pip install pytesseract Pillow pymupdf")


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
        
        # Load OCR patterns from YAML rules
        self._load_ocr_patterns()
        
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
    
    def _load_ocr_patterns(self):
        """Load OCR extraction patterns from YAML rules"""
        try:
            # Load RD layout rules from YAML
            rd_layouts = self.rule_loader.load_rule_file_by_name('21_rd_layout.yaml')
            if rd_layouts and 'rd_layouts' in rd_layouts:
                # Find the PDF layout with OCR patterns
                for layout in rd_layouts['rd_layouts']:
                    if layout.get('parsed_by') == 'rd_pdf_v1' and 'ocr_extraction' in layout:
                        self.ocr_config = layout['ocr_extraction']
                        logger.debug("Loaded OCR patterns from YAML rules")
                        return
            
            # Fallback: use default patterns if not found in YAML
            logger.warning("OCR patterns not found in YAML rules, using defaults")
            self.ocr_config = None
        except Exception as e:
            logger.warning(f"Error loading OCR patterns from YAML: {e}, using defaults")
            self.ocr_config = None
    
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
            # Get vendor code
            vendor_code = detected_vendor_code or 'RD'
            
            # Extract text from PDF for detection and totals (may be empty for image-based PDFs)
            pdf_text = self._extract_pdf_text(file_path)
            
            # Extract table using pdfplumber (grid mode)
            # Note: Layout matching will be done by LayoutApplier using rules from 21_rd_layout.yaml
            # Try table extraction even if text extraction failed (for image-based PDFs)
            df = self._extract_table_from_pdf(file_path)
            
            # If table extraction failed, try OCR for image-based PDFs
            if df is None or df.empty:
                if not pdf_text:
                    logger.info(f"Could not extract text or tables from {file_path.name} - trying OCR for image-based PDF")
                    if OCR_AVAILABLE:
                        df = self._extract_table_from_pdf_ocr(file_path)
                        if df is not None and not df.empty:
                            logger.info(f"Successfully extracted table using OCR from {file_path.name}")
                            pdf_text = ""  # OCR text is used for table extraction, not for totals
                        else:
                            logger.warning(f"OCR extraction also failed for {file_path.name}")
                            return None
                    else:
                        logger.warning(f"Could not extract text or tables from {file_path.name} - OCR not available (install pytesseract, Pillow, pymupdf)")
                        return None
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
            # If text extraction failed, try OCR for totals extraction
            if not pdf_text and OCR_AVAILABLE:
                ocr_text = self._extract_pdf_text_ocr(file_path)
                if ocr_text:
                    pdf_text = ocr_text
                    logger.info(f"Extracted totals using OCR from {file_path.name}")
            
            if pdf_text:
                self._extract_totals_from_text(pdf_text, receipt_data)
            
            # Set parsed_by (will be set by LayoutApplier if layout matched)
            if not receipt_data.get('parsed_by'):
                receipt_data['parsed_by'] = 'rd_pdf_v1'
            
            # Enrich with knowledge base (same as Excel processor)
            # Use the same enrichment logic as Excel processor for RD
            receipt_data['items'] = self._enrich_rd_items(receipt_data.get('items', []))
            
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
    
    def _extract_table_from_pdf_ocr(self, file_path: Path) -> Optional[pd.DataFrame]:
        """
        Extract table from image-based PDF using OCR
        
        Args:
            file_path: Path to PDF file
        
        Returns:
            DataFrame with extracted table data
        """
        if not OCR_AVAILABLE:
            logger.warning("OCR libraries not available for {file_path.name}")
            return None
        
        try:
            import pytesseract
            from PIL import Image
            import fitz  # PyMuPDF
            
            # Convert PDF pages to images
            doc = fitz.open(file_path)
            all_text_lines = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                # Render page to image (300 DPI for good quality)
                mat = fitz.Matrix(300/72, 300/72)  # 300 DPI
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Run OCR with structured output (TSV format for better parsing)
                # Use tesseract config for better table detection
                tesseract_config = r'--oem 3 --psm 6'  # Uniform block of text
                ocr_text = pytesseract.image_to_string(img, config=tesseract_config)
                
                if ocr_text:
                    lines = ocr_text.split('\n')
                    all_text_lines.extend(lines)
                    logger.debug(f"OCR extracted {len(lines)} lines from page {page_num + 1}")
            
            doc.close()
            
            if not all_text_lines:
                logger.warning(f"No text extracted via OCR from {file_path.name}")
                return None
            
            # Parse OCR text into table structure
            # Look for header row with "Item Description" and "Ext. Amount" or "Extended Amount"
            header_idx = -1
            for i, line in enumerate(all_text_lines):
                if 'Item Description' in line and ('Ext. Amount' in line or 'Extended Amount' in line or 'Amount' in line):
                    header_idx = i
                    break
            
            if header_idx == -1:
                logger.warning(f"Could not find header row in OCR text from {file_path.name}")
                return None
            
            # Parse data rows using patterns from YAML
            # RD OCR format: UPC ItemNumber ItemDescription UnitPrice Qty U(T) ExtAmount Tax
            # Example: "2370002749 980356 CHX NUGGET BTRD TY 10LB 28.91 1 U (T) 28.91 T"
            data_rows = []
            seen_lines = set()  # Deduplicate OCR artifacts
            
            # Get OCR config from YAML (RD-specific patterns)
            ocr_config = self.ocr_config or {}
            item_pattern = ocr_config.get('item_pattern', {}).get('regex')
            error_corrections = ocr_config.get('error_corrections', [])
            skip_lines = ocr_config.get('skip_lines', [])
            stop_patterns = ocr_config.get('stop_patterns', [])
            
            # Process item pattern: YAML loads single-quoted strings with escaped backslashes
            # YAML '\\d' becomes Python '\d' (invalid), so we need to decode it
            if item_pattern:
                # Convert YAML-escaped pattern to Python re-compatible pattern
                # YAML loads '\\d' as literal '\d', which needs to be '\\d' for Python re
                try:
                    # Decode the escaped string to get the actual pattern
                    item_pattern = item_pattern.encode('utf-8').decode('unicode_escape')
                except Exception:
                    # If decoding fails, use as-is (might already be correct)
                    pass
            else:
                # Default item pattern if not in YAML
                item_pattern = r'^(\d{10,13})\s+(\d{5,10})\s+(.+?)\s+(\d+[.,]\d{2})\s+(\d+(?:\.\d+)?)\s+[Uu]\s*\(?[Tt]\)?\s+(\d+[.,]\d{2})\s*[Tt]?.*$'
            
            for i in range(header_idx + 1, len(all_text_lines)):
                line = all_text_lines[i].strip()
                if not line:
                    continue
                
                # Stop at totals section (using YAML patterns)
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in stop_patterns):
                    break
                
                # Skip non-item lines (using YAML patterns)
                skip_this_line = False
                for skip_pattern in skip_lines:
                    if re.match(skip_pattern, line, re.IGNORECASE):
                        skip_this_line = True
                        break
                    elif skip_pattern.upper() in line.upper():
                        skip_this_line = True
                        break
                if skip_this_line:
                    continue
                
                # Apply OCR error corrections from YAML
                for correction in error_corrections:
                    find_pattern = correction.get('find', '')
                    replace_pattern = correction.get('replace', '')
                    if find_pattern and replace_pattern:
                        # Handle regex replacements
                        if '(' in find_pattern or '[' in find_pattern:
                            # It's a regex pattern
                            line = re.sub(find_pattern, replace_pattern, line)
                        else:
                            # Simple string replacement
                            line = line.replace(find_pattern, replace_pattern)
                
                # Try to match RD item pattern (from YAML)
                item_match = re.match(item_pattern, line)
                
                if item_match:
                    upc = item_match.group(1)
                    item_number = item_match.group(2)
                    description = item_match.group(3).strip()
                    unit_price = item_match.group(4).replace(',', '.')
                    qty = item_match.group(5)
                    ext_amount = item_match.group(6).replace(',', '.')
                    
                    # Create a normalized line for deduplication
                    normalized = f"{upc}_{item_number}_{description[:50]}_{ext_amount}"
                    if normalized in seen_lines:
                        continue  # Skip duplicate OCR artifacts
                    seen_lines.add(normalized)
                    
                    # Create row: Item Description, QTY, Unit Price, Extended Amount, UPC, Item Number
                    # Include UPC and item_number for knowledge base lookup
                    row = [description, qty, unit_price, ext_amount, upc, item_number]
                    data_rows.append(row)
                    continue
                
                # Fallback: Try to find price patterns and split by price positions
                # Look for price patterns: "28.91", "32.15", etc.
                price_pattern = r'\d+[.,]\d{2}'
                prices = list(re.finditer(price_pattern, line))
                
                if len(prices) >= 2:  # At least unit price and extended amount
                    # First price is likely unit price, last is extended amount
                    unit_price_match = prices[0]
                    ext_amount_match = prices[-1]
                    
                    # Extract description (before first price)
                    description = line[:unit_price_match.start()].strip()
                    
                    # Extract qty (between prices, or assume 1)
                    qty = '1'
                    if len(prices) >= 2:
                        # Try to extract qty between unit price and ext amount
                        between_prices = line[unit_price_match.end():ext_amount_match.start()].strip()
                        qty_match = re.search(r'^(\d+(?:\.\d+)?)', between_prices)
                        if qty_match:
                            qty = qty_match.group(1)
                    
                    unit_price = unit_price_match.group(0).replace(',', '.')
                    ext_amount = ext_amount_match.group(0).replace(',', '.')
                    
                    # Create normalized line for deduplication
                    normalized = f"{description[:50]}_{ext_amount}"
                    if normalized in seen_lines:
                        continue
                    seen_lines.add(normalized)
                    
                    row = [description, qty, unit_price, ext_amount]
                    data_rows.append(row)
                    continue
            
            if not data_rows:
                logger.warning(f"No data rows found in OCR text from {file_path.name}")
                return None
            
            # Create DataFrame
            # Try to match header columns with data columns
            # For now, use a simple approach: assume first column is description, last is amount
            max_cols = max(len(row) for row in data_rows) if data_rows else 0
            
            # Create column names based on header if possible, otherwise use generic names
            # Include UPC and Item Number columns if available
            if max_cols >= 6:
                column_names = ['Item Description', 'QTY', 'Unit Price', 'Extended Amount', 'UPC', 'Item Number']
            elif max_cols >= 4:
                column_names = ['Item Description', 'QTY', 'Unit Price', 'Extended Amount']
            elif max_cols >= 3:
                column_names = ['Item Description', 'QTY', 'Extended Amount']
            elif max_cols >= 2:
                column_names = ['Item Description', 'Extended Amount']
            else:
                column_names = [f'Column_{i+1}' for i in range(max_cols)]
            
            # Pad rows to same length
            padded_rows = []
            for row in data_rows:
                padded_row = row + [''] * (max_cols - len(row))
                padded_rows.append(padded_row[:max_cols])
            
            # Create DataFrame
            df = pd.DataFrame(padded_rows, columns=column_names[:max_cols])
            
            # Clean column names
            df.columns = [str(col).strip() if col else '' for col in df.columns]
            
            logger.info(f"Extracted table with {len(df)} rows using OCR from {file_path.name}")
            return df
            
        except Exception as e:
            logger.error(f"Error extracting table via OCR from PDF: {e}", exc_info=True)
            return None
    
    def _extract_totals_from_text(self, text: str, receipt_data: Dict[str, Any]):
        """Extract subtotal, tax, and total from PDF text using regex patterns from YAML (RD-specific)"""
        # Get totals patterns from YAML (RD-specific)
        ocr_config = self.ocr_config or {}
        totals_patterns = ocr_config.get('totals_patterns', {})
        
        # Extract subtotal (using YAML patterns)
        subtotal_patterns = totals_patterns.get('subtotal', [
            r'Subtotal[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Sub\s+Total[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'SUBTOTAL[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
        ])
        for pattern_config in subtotal_patterns:
            pattern = pattern_config if isinstance(pattern_config, str) else pattern_config.get('regex', pattern_config)
            # Decode YAML-escaped pattern (same as item pattern)
            try:
                pattern = pattern.encode('utf-8').decode('unicode_escape')
            except Exception:
                pass
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value_str = match.group(1).replace(',', '').replace(':', '.').replace('|', '')  # Fix OCR errors
                    value = float(value_str)
                    receipt_data['subtotal'] = value
                    break
                except (ValueError, IndexError):
                    continue
        
        # Extract tax (using YAML patterns)
        tax_patterns = totals_patterns.get('tax', [
            r'Taxes?[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Tax[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Sales\s+Tax[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'IL\s+FOOD\s+Tax[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'TOTAL\s+TAX[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
        ])
        for pattern_config in tax_patterns:
            pattern = pattern_config if isinstance(pattern_config, str) else pattern_config.get('regex', pattern_config)
            # Decode YAML-escaped pattern (same as item pattern)
            try:
                pattern = pattern.encode('utf-8').decode('unicode_escape')
            except Exception:
                pass
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value_str = match.group(1).replace(',', '').replace(':', '.').replace('|', '')  # Fix OCR errors
                    value = float(value_str)
                    receipt_data['tax'] = value
                    break
                except (ValueError, IndexError):
                    continue
        
        # Extract total (using YAML patterns)
        total_patterns = totals_patterns.get('total', [
            r'TRANSACTION\s+TOTAL[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Total[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Grand\s+Total[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
        ])
        for pattern_config in total_patterns:
            pattern = pattern_config if isinstance(pattern_config, str) else pattern_config.get('regex', pattern_config)
            # Decode YAML-escaped pattern (same as item pattern)
            try:
                pattern = pattern.encode('utf-8').decode('unicode_escape')
            except Exception:
                pass
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value_str = match.group(1).replace(',', '').replace(':', '.').replace('|', '')  # Fix OCR errors
                    value = float(value_str)
                    receipt_data['total'] = value
                    break
                except (ValueError, IndexError):
                    continue
    
    def _enrich_rd_items(self, items: list) -> list:
        """
        Enrich RD items with size/spec information from knowledge base.
        Same logic as ExcelProcessor._enrich_rd_items()
        
        Args:
            items: List of item dictionaries
        
        Returns:
            List of enriched items
        """
        from . import vendor_profiles
        
        # Load knowledge base (uses singleton cache)
        kb = vendor_profiles._ensure_kb_loaded()
        
        if not kb:
            logger.warning("Knowledge base not loaded, skipping RD enrichment")
            return items
        
        enriched_items = []
        
        for item in items:
            item_number = str(item.get('item_number', '')).strip()
            
            # Look up in knowledge base
            kb_entry = kb.get(item_number)
            if kb_entry:
                kb_spec = kb_entry.get('spec', '')  # Size/spec info
                kb_name = kb_entry.get('name', '')
                
                # Add size/spec info if available
                if kb_spec:
                    item['kb_size'] = kb_spec
                    item['kb_source'] = 'knowledge_base'
                    logger.debug(f"RD KB: {item.get('product_name', 'Unknown')} ({item_number}): size={kb_spec}")
                
                # Optionally verify the name matches (for QA purposes)
                if kb_name and kb_name.upper() != item.get('product_name', '').upper():
                    item['kb_name_mismatch'] = True
                    logger.debug(f"RD KB: Name mismatch for {item_number}: receipt='{item.get('product_name')}' vs kb='{kb_name}'")
            else:
                logger.debug(f"RD KB: Item {item_number} not found in knowledge base")
            
            enriched_items.append(item)
        
        return enriched_items

