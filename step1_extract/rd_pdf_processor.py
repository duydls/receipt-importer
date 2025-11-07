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
            rd_layouts = self.rule_loader.load_rule_file_by_name('21_rd_pdf_layout.yaml')
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
                # Also extract transaction date from text
                self._extract_transaction_date_from_text(pdf_text, receipt_data)
            
            # Set parsed_by (will be set by LayoutApplier if layout matched)
            if not receipt_data.get('parsed_by'):
                receipt_data['parsed_by'] = 'rd_pdf_v1'
            
            # Enrich with knowledge base (same as Excel processor)
            # Use the same enrichment logic as Excel processor for RD
            receipt_data['items'] = self._enrich_rd_items(receipt_data.get('items', []))
            
            # Validate totals and flag mismatches
            self._validate_rd_totals(receipt_data)
            
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
            all_pages_processed = []
            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"Processing {total_pages} page(s) from {file_path.name}")
                
                for page_num, page in enumerate(pdf.pages):
                    page_tables = []
                    
                    # Try multiple table extraction strategies
                    # Strategy 1: Standard table extraction
                    page_tables = page.extract_tables()
                    if page_tables:
                        tables.extend(page_tables)
                        all_pages_processed.append(page_num + 1)
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
                        "intersection_tolerance": 3,
                    })
                    if page_tables:
                        tables.extend(page_tables)
                        all_pages_processed.append(page_num + 1)
                        logger.debug(f"Found {len(page_tables)} tables on page {page_num + 1} using line-based extraction")
                        continue
                    
                    # Strategy 3: Try text-based extraction (if PDF has text but no table structure)
                    text = page.extract_text()
                    if text and "Item Description" in text:
                        logger.warning(f"Found text with 'Item Description' on page {page_num + 1}, but no table structure - may need OCR")
                        # Could try to parse text as table manually, but for now just log
                    elif not text:
                        logger.warning(f"No text found on page {page_num + 1} - may be image-based and need OCR")
            
            if not tables:
                logger.warning(f"No tables found in PDF {file_path.name} (processed {len(all_pages_processed)}/{total_pages} pages) - may be image-based or unstructured")
                return None
            
            if len(all_pages_processed) < total_pages:
                logger.warning(f"Only processed {len(all_pages_processed)}/{total_pages} pages from {file_path.name} - some pages may have been skipped")
            
            # Find tables with header row matching RD layout
            # Look for headers: "Item Description" and "Extended Amount"
            header_patterns = [
                r'Item\s+Description',
                r'Extended\s+Amount',
            ]
            
            matching_tables = []
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
                    matching_tables.append(table)
            
            # Merge all matching tables (in case items are split across pages)
            if matching_tables:
                if len(matching_tables) > 1:
                    logger.info(f"Found {len(matching_tables)} matching tables - merging rows from all tables")
                    # Use header from first table
                    header = matching_tables[0][0]
                    # Combine all data rows (skip header from subsequent tables)
                    all_rows = [header]
                    for table in matching_tables:
                        all_rows.extend(table[1:])
                    
                    df = pd.DataFrame(all_rows[1:], columns=header)
                    df.columns = [str(col).strip() if col else '' for col in df.columns]
                    logger.info(f"Merged {len(matching_tables)} tables into one DataFrame with {len(df)} rows")
                    return df
                else:
                    # Single matching table
                    table = matching_tables[0]
                    df = pd.DataFrame(table[1:], columns=table[0])
                    df.columns = [str(col).strip() if col else '' for col in df.columns]
                    logger.info(f"Extracted table with {len(df)} rows from PDF")
                    return df
            
            # If no table matches header, try first table
            if tables:
                table = tables[0]
                if table and len(table) >= 2:
                    df = pd.DataFrame(table[1:], columns=table[0])
                    df.columns = [str(col).strip() if col else '' for col in df.columns]
                    logger.warning(f"Using first table with {len(df)} rows (header may not match RD layout)")
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
            
            # Load knowledge base for UPC/product name lookups
            from . import vendor_profiles
            kb = vendor_profiles._ensure_kb_loaded()
            
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
                
                # Also skip summary lines (single character lines like "$", "} $", etc.)
                line_clean = line.strip()
                if len(line_clean) <= 3 and (line_clean in ['$', '} $', '| $'] or re.match(r'^[}\|]?\s*\$?\s*$', line_clean)):
                    skip_this_line = True
                
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
                
                # Step 1: Extract UPC from the beginning of the line (if present)
                # NOTE: UPC extraction is RD-specific - RD receipts have UPC at the start of each line
                # UPC is typically 10-13 digits at the start
                # Format: UPC ItemNumber Description UnitPrice Qty U(T) ExtAmount Tax
                upc_match = re.match(r'^(\d{10,13})\s+', line)
                upc = upc_match.group(1) if upc_match else ''
                
                # Step 2: Try to extract item_number early (before pattern match) for KB lookup
                # RD format: UPC ItemNumber Description...
                # Try to extract item_number after UPC (5-10 digits)
                # This is RD-specific - other vendors may not have this format
                item_number_for_kb = None
                if upc:
                    # After UPC, look for item_number (5-10 digits)
                    after_upc = line[len(upc):].strip()
                    item_no_match = re.match(r'^(\d{5,10})\s+', after_upc)
                    if item_no_match:
                        item_number_for_kb = item_no_match.group(1)
                
                # Step 3: Look up product name in knowledge base using item_number
                # NOTE: This KB lookup is RD-specific - uses UPC and item_number from RD format
                # KB is keyed by item_number (not UPC), so we look up by item_number
                kb_product_name = None
                kb_item_number = None
                if kb and item_number_for_kb:
                    # KB is keyed by item_number, so look up by item_number
                    kb_entry = kb.get(item_number_for_kb)
                    if kb_entry:
                        if isinstance(kb_entry, dict):
                            kb_product_name = kb_entry.get('name', '')
                            kb_item_number = item_number_for_kb
                        elif isinstance(kb_entry, list) and len(kb_entry) > 0:
                            # Old format: [name, store, spec, price]
                            kb_product_name = kb_entry[0] if len(kb_entry) > 0 else ''
                            kb_item_number = item_number_for_kb
                
                # Step 4: Apply common OCR error corrections before pattern matching
                # Fix common OCR errors in prices: f/F -> 7, O/o -> 0, I/l -> 1
                # But only fix in price-like patterns to avoid breaking descriptions
                line_original = line
                # Fix price OCR errors: "21.f2" -> "21.72", "2O.91" -> "20.91"
                # Only fix f/F in price context (after digit, before 1-2 digits): "21.f2" -> "21.72"
                # Match pattern: digit(s) + [.,] + f/F + 1-2 digits (common OCR error)
                line = re.sub(r'(\d+)[.,]f(\d{1,2})', r'\1.7\2', line)  # f -> 7 (e.g., "21.f2" -> "21.72")
                line = re.sub(r'(\d+)[.,]F(\d{1,2})', r'\1.7\2', line)  # F -> 7
                # Fix O/o -> 0 only in price context (between digits)
                line = re.sub(r'(\d+)O(\d)', r'\g<1>0\2', line)  # O -> 0 (but preserve in words)
                line = re.sub(r'(\d+)o(\d)', r'\g<1>0\2', line)  # o -> 0
                # Fix I/l -> 1 only in price context (between digits)
                line = re.sub(r'(\d+)I(\d)', r'\g<1>1\2', line)  # I -> 1
                line = re.sub(r'(\d+)l(\d)', r'\g<1>1\2', line)  # l -> 1
                
                # Step 5: Try to match RD item pattern (from YAML)
                # If we have KB product name, we can use it to validate/correct the description
                item_match = re.match(item_pattern, line)
                
                if item_match:
                    extracted_upc = item_match.group(1)
                    item_number = item_match.group(2)
                    description = item_match.group(3).strip()
                    # Clean description (remove leading | and other OCR artifacts)
                    description = re.sub(r'^\|\s*', '', description).strip()
                    unit_price = item_match.group(4).replace(',', '.')
                    qty = item_match.group(5)
                    ext_amount = item_match.group(6).replace(',', '.')
                    
                    # Use KB product name if available and description seems wrong
                    if kb_product_name and kb_product_name:
                        # Check if description is significantly different from KB name
                        # If KB name is more reliable, use it (but keep OCR description for reference)
                        desc_upper = description.upper()
                        kb_name_upper = kb_product_name.upper()
                        
                        # Check for poor OCR indicators
                        has_ocr_errors = (
                            len(description) < 10 or 
                            description.count('|') > 2 or
                            # Check for common OCR errors in product names
                            any(err in desc_upper for err in ['TI ISE', 'A32Z', 'SJLOE', 'BREAST', 'PAS 1 U (T)']) or
                            # Check if description starts with UPC (OCR artifact)
                            description.startswith(extracted_upc) if extracted_upc else False
                        )
                        
                        # If description has OCR errors, prefer KB name
                        if has_ocr_errors:
                            description = kb_product_name
                            logger.debug(f"Using KB product name for UPC {extracted_upc} (OCR errors detected): {kb_product_name}")
                        # If KB name is found in description, use KB name (cleaner)
                        elif kb_name_upper in desc_upper:
                            description = kb_product_name
                            logger.debug(f"Using KB product name for UPC {extracted_upc} (found in OCR): {kb_product_name}")
                        # Otherwise, keep OCR description but note KB name for validation
                        elif kb_name_upper not in desc_upper and desc_upper not in kb_name_upper:
                            # Names don't match - keep OCR but add KB name as reference
                            logger.debug(f"Description mismatch for UPC {extracted_upc}: OCR='{description}' vs KB='{kb_product_name}'")
                    
                    # Normalize ext_amount for deduplication (handle OCR errors)
                    try:
                        ext_amount_float = float(ext_amount)
                    except ValueError:
                        # Skip if can't parse
                        continue
                    
                    # Create a normalized line for deduplication (use original line before OCR correction)
                    # Use UPC + item_number + ext_amount for deduplication (most reliable)
                    if extracted_upc and item_number:
                        normalized = f"{extracted_upc}_{item_number}_{ext_amount_float:.2f}"
                    elif item_number:
                        normalized = f"{item_number}_{ext_amount_float:.2f}"
                    else:
                        # Fallback: use description + ext_amount
                        normalized = f"{description[:50]}_{ext_amount_float:.2f}"
                    
                    if normalized in seen_lines:
                        continue  # Skip duplicate OCR artifacts
                    seen_lines.add(normalized)
                    
                    # Create row: Item Description, QTY, Unit Price, Extended Amount, UPC, Item Number
                    # Include UPC and item_number for knowledge base lookup
                    row = [description, qty, unit_price, ext_amount, extracted_upc, item_number]
                    data_rows.append(row)
                    continue
                
                # Fallback: Try to find price patterns and split by price positions
                # Look for price patterns: "28.91", "32.15", etc. (handle OCR errors like "21.f2" -> "21.72")
                # First try strict pattern, then try OCR-error-tolerant pattern
                price_pattern_strict = r'\d+[.,]\d{2}'
                price_pattern_ocr = r'\d+[.,fF]\d{2}'  # Handle OCR errors: f/F instead of digit
                
                prices_strict = list(re.finditer(price_pattern_strict, line))
                prices_ocr = list(re.finditer(price_pattern_ocr, line))
                
                # Use OCR-tolerant pattern if strict pattern finds fewer prices
                prices = prices_strict if len(prices_strict) >= 2 else prices_ocr
                
                # Skip summary lines (very short lines with only prices, no product description)
                line_clean = line.strip()
                if len(line_clean) <= 5 and len(prices) > 0:
                    # Very short line with prices - likely a summary line
                    continue
                
                if len(prices) >= 2:  # At least unit price and extended amount
                    # First price is likely unit price, last is extended amount
                    unit_price_match = prices[0]
                    ext_amount_match = prices[-1]
                    
                    # Extract description (before first price)
                    description = line[:unit_price_match.start()].strip()
                    
                    # Clean description (remove leading | and other OCR artifacts)
                    description = re.sub(r'^\|\s*', '', description).strip()
                    
                    # If we have KB product name, try to find it in the description and use it
                    if kb_product_name and kb_product_name:
                        # Try to find KB product name in the OCR line (fuzzy match)
                        kb_name_upper = kb_product_name.upper()
                        desc_upper = description.upper()
                        # If KB name is found in description, use KB name (cleaner)
                        if kb_name_upper in desc_upper:
                            description = kb_product_name
                            logger.debug(f"Using KB product name from fallback for UPC {upc}: {kb_product_name}")
                        # If description is very short or mostly OCR artifacts, prefer KB name
                        elif len(description) < 10 or description.count('|') > 2:
                            description = kb_product_name
                            logger.debug(f"Replacing short/artifacts description with KB name for UPC {upc}: {kb_product_name}")
                    
                    # Extract qty (between prices, or assume 1)
                    qty = '1'
                    if len(prices) >= 2:
                        # Try to extract qty between unit price and ext amount
                        between_prices = line[unit_price_match.end():ext_amount_match.start()].strip()
                        qty_match = re.search(r'^(\d+(?:\.\d+)?)', between_prices)
                        if qty_match:
                            qty = qty_match.group(1)
                    
                    # Clean prices (handle OCR errors: f/F -> digit, | -> nothing)
                    unit_price_raw = unit_price_match.group(0).replace(',', '.').replace('f', '7').replace('F', '7').replace('|', '')
                    ext_amount_raw = ext_amount_match.group(0).replace(',', '.').replace('f', '7').replace('F', '7').replace('|', '')
                    
                    # Try to parse as float, if fails, try OCR correction
                    try:
                        unit_price = float(unit_price_raw)
                        ext_amount = float(ext_amount_raw)
                    except ValueError:
                        # Try OCR correction: common errors
                        unit_price_raw = unit_price_raw.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1')
                        ext_amount_raw = ext_amount_raw.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1')
                        try:
                            unit_price = float(unit_price_raw)
                            ext_amount = float(ext_amount_raw)
                        except ValueError:
                            # Skip if still can't parse
                            continue
                    
                    # Extract UPC and item number from description if present
                    upc = ''
                    item_number = ''
                    # Try to extract from beginning of description (UPC ItemNumber Description)
                    desc_match = re.match(r'^(\d{10,13})\s+(\d{5,10})\s+(.+)$', description)
                    if desc_match:
                        upc = desc_match.group(1)
                        item_number = desc_match.group(2)
                        description = desc_match.group(3).strip()
                    
                    # Create normalized line for deduplication
                    normalized = f"{upc}_{item_number}_{description[:50]}_{ext_amount:.2f}"
                    if normalized in seen_lines:
                        continue
                    seen_lines.add(normalized)
                    
                    # Create row: Item Description, QTY, Unit Price, Extended Amount, UPC, Item Number
                    row = [description, qty, f"{unit_price:.2f}", f"{ext_amount:.2f}", upc, item_number]
                    data_rows.append(row)
                    continue
                
                # Second fallback: If only one price found, might be extended amount only
                if len(prices) == 1:
                    # Skip if line is too short (likely summary line)
                    line_clean = line.strip()
                    if len(line_clean) <= 5:
                        continue
                    
                    price_match = prices[0]
                    description = line[:price_match.start()].strip()
                    description = re.sub(r'^\|\s*', '', description).strip()
                    
                    # Skip if description is empty or just a symbol
                    if not description or description in ['$', '} $', '| $']:
                        continue
                    
                    # Try to extract UPC/item number from description
                    upc = ''
                    item_number = ''
                    desc_match = re.match(r'^(\d{10,13})\s+(\d{5,10})\s+(.+)$', description)
                    if desc_match:
                        upc = desc_match.group(1)
                        item_number = desc_match.group(2)
                        description = desc_match.group(3).strip()
                    
                    # Clean price
                    ext_amount_raw = price_match.group(0).replace(',', '.').replace('f', '7').replace('F', '7').replace('|', '')
                    try:
                        ext_amount = float(ext_amount_raw)
                    except ValueError:
                        ext_amount_raw = ext_amount_raw.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1')
                        try:
                            ext_amount = float(ext_amount_raw)
                        except ValueError:
                            continue
                    
                    # Create normalized line for deduplication
                    normalized = f"{upc}_{item_number}_{description[:50]}_{ext_amount:.2f}"
                    if normalized in seen_lines:
                        continue
                    seen_lines.add(normalized)
                    
                    # Create row with qty=1 (default)
                    row = [description, '1', f"{ext_amount:.2f}", f"{ext_amount:.2f}", upc, item_number]
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
        
        # Extract tax (using YAML patterns) - RD specific: IL TAX + IL FOOD TAX => TOTAL TAX
        tax_patterns = totals_patterns.get('tax', [
            r'TOTAL\s+TAX[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)', # Prioritize TOTAL TAX
            r'IL\s+FOOD\s+Tax[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'IL\s+TAX[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Taxes?[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Tax[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
            r'Sales\s+Tax[:\s]+(?:\\$?\\s*)?([0-9,]+(?:\.[0-9]{2})?)',
        ])

        # RD tax logic: prefer IL TAX lines over TOTAL TAX (IL TAX is more reliable)
        try:
            il_food_match = re.search(r'IL\s*FOOD\s*TAX[:\s]+\$?\s*([0-9,]+(?:\.[0-9]{2})?)', text, re.IGNORECASE)
            il_tax_match = re.search(r'IL\s*TAX[:\s]+\$?\s*([0-9,]+(?:\.[0-9]{2})?)', text, re.IGNORECASE)
            if il_food_match or il_tax_match:
                il_food_val = float(il_food_match.group(1).replace(',', '').replace(':', '.')) if il_food_match else 0.0
                il_val = float(il_tax_match.group(1).replace(',', '').replace(':', '.')) if il_tax_match else 0.0
                combined = round(il_food_val + il_val, 2)
                # Only set if positive; otherwise continue to other patterns
                if combined >= 0.0:
                    receipt_data['tax'] = combined
                    logger.debug(f"RD tax extracted as sum: IL FOOD TAX ${il_food_val:.2f} + IL TAX ${il_val:.2f} = ${combined:.2f}")
        except Exception:
            pass

        if not receipt_data.get('tax'):
            # If no IL TAX lines found, try TOTAL TAX
            total_tax_match = re.search(r'TOTAL\s*TAX[:\s]+\$?\s*([0-9,]+(?:\.[0-9]{2})?)', text, re.IGNORECASE)
            if total_tax_match:
                try:
                    value = float(total_tax_match.group(1).replace(',', '').replace(':', '.'))
                    receipt_data['tax'] = value
                    logger.debug(f"RD tax extracted from TOTAL TAX: ${value:.2f}")
                except (ValueError, IndexError):
                    pass

        if not receipt_data.get('tax'):
            # Fallback to generic patterns
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
        
        logger.debug(f"RD totals extracted: subtotal=${receipt_data.get('subtotal', 0):.2f}, tax=${receipt_data.get('tax', 0):.2f}, total=${receipt_data.get('total', 0):.2f}")
    
    def _extract_transaction_date_from_text(self, text: str, receipt_data: Dict[str, Any]):
        """Extract transaction date from PDF text using common date patterns"""
        from datetime import datetime
        
        # First, try extracting from filename (RD_MMDD.pdf format) as primary source
        filename = receipt_data.get('filename', '')
        filename_date_match = re.search(r'RD_(\d{2})(\d{2})\.pdf', filename, re.IGNORECASE)
        if filename_date_match:
            month = filename_date_match.group(1)
            day = filename_date_match.group(2)
            year = datetime.now().year
            # Try to construct date (e.g., RD_0902.pdf -> 09/02/2025)
            try:
                date_str = f"{month}/{day}/{year}"
                parsed_date = datetime.strptime(date_str, '%m/%d/%Y')
                receipt_data['transaction_date'] = date_str
                logger.debug(f"RD transaction date extracted from filename: {date_str}")
                return
            except ValueError:
                pass
        
        # If filename extraction failed, try extracting from PDF text
        if not text:
            return
        
        # Common date patterns for RD receipts
        date_patterns = [
            # Pattern: "Date: MM/DD/YYYY" or "Transaction Date: MM/DD/YYYY"
            r'(?:Date|Transaction\s+Date|Trans\s+Date)[:\s]+(\d{1,2}/\d{1,2}/\d{4})',
            # Pattern: "MM/DD/YYYY" near "Date" keyword
            r'Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})',
            # Pattern: Standalone date in MM/DD/YYYY format (prefer dates near top of receipt)
            r'(\d{1,2}/\d{1,2}/\d{4})',
        ]
        
        # Try patterns in order of specificity
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                # Validate the date format (MM/DD/YYYY)
                try:
                    # Parse to ensure it's a valid date
                    parsed_date = datetime.strptime(date_str, '%m/%d/%Y')
                    receipt_data['transaction_date'] = date_str
                    logger.debug(f"RD transaction date extracted from text: {date_str}")
                    return
                except ValueError:
                    # Invalid date format, try next pattern
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
            # KB format: [name, store, spec, price] or {name, store, spec, price}
            kb_entry = kb.get(item_number)
            if kb_entry:
                # Handle both array and dict formats
                if isinstance(kb_entry, list):
                    kb_name = kb_entry[0] if len(kb_entry) > 0 else ''
                    kb_spec = kb_entry[2] if len(kb_entry) > 2 else ''  # Size/spec info (UoM)
                elif isinstance(kb_entry, dict):
                    kb_name = kb_entry.get('name', '')
                    kb_spec = kb_entry.get('spec', '')
                else:
                    kb_name = ''
                    kb_spec = ''
                
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
    
    def _validate_rd_totals(self, receipt_data: Dict[str, Any]):
        """
        Validate RD receipt totals and flag mismatches.
        
        Checks if calculated total from items matches receipt total.
        Flags receipts with significant mismatches for review.
        """
        items = receipt_data.get('items', [])
        if not items:
            return
        
        # Calculate totals from items (excluding fees)
        calculated_subtotal = sum(
            float(item.get('total_price', 0)) 
            for item in items 
            if not item.get('is_fee', False)
        )
        
        # Get receipt totals
        receipt_subtotal = float(receipt_data.get('subtotal', 0) or 0)
        receipt_tax = float(receipt_data.get('tax', 0) or 0)
        receipt_total = float(receipt_data.get('total', 0) or 0)
        
        # Calculate expected total
        expected_total = calculated_subtotal + receipt_tax
        
        # Check for mismatches
        subtotal_diff = abs(calculated_subtotal - receipt_subtotal) if receipt_subtotal > 0 else 0
        total_diff = abs(expected_total - receipt_total) if receipt_total > 0 else 0
        
        # Flag if mismatch is significant (> $1.00 or > 5% of receipt total)
        threshold_absolute = 1.00
        threshold_percent = 0.05
        
        is_mismatch = False
        mismatch_reasons = []
        
        if receipt_subtotal > 0 and subtotal_diff > threshold_absolute:
            pct_diff = (subtotal_diff / receipt_subtotal) * 100 if receipt_subtotal > 0 else 0
            if pct_diff > (threshold_percent * 100):
                is_mismatch = True
                mismatch_reasons.append(
                    f"Subtotal mismatch: calculated ${calculated_subtotal:.2f} vs receipt ${receipt_subtotal:.2f} "
                    f"(diff: ${subtotal_diff:.2f}, {pct_diff:.1f}%)"
                )
        
        if receipt_total > 0 and total_diff > threshold_absolute:
            pct_diff = (total_diff / receipt_total) * 100 if receipt_total > 0 else 0
            if pct_diff > (threshold_percent * 100):
                is_mismatch = True
                mismatch_reasons.append(
                    f"Total mismatch: calculated ${expected_total:.2f} vs receipt ${receipt_total:.2f} "
                    f"(diff: ${total_diff:.2f}, {pct_diff:.1f}%)"
                )
        
        if is_mismatch:
            # Flag receipt for review
            receipt_data['needs_review'] = True
            if 'review_reasons' not in receipt_data:
                receipt_data['review_reasons'] = []
            
            for reason in mismatch_reasons:
                if reason not in receipt_data['review_reasons']:
                    receipt_data['review_reasons'].append(reason)
            
            # Add detailed mismatch info
            receipt_data['total_mismatch'] = {
                'calculated_subtotal': calculated_subtotal,
                'receipt_subtotal': receipt_subtotal,
                'subtotal_diff': subtotal_diff,
                'calculated_total': expected_total,
                'receipt_total': receipt_total,
                'total_diff': total_diff,
                'item_count': len([i for i in items if not i.get('is_fee', False)]),
            }
            
            logger.warning(
                f"RD total mismatch detected for {receipt_data.get('filename', 'unknown')}: "
                f"calculated ${expected_total:.2f} vs receipt ${receipt_total:.2f} "
                f"(diff: ${total_diff:.2f}). {len(items)} items extracted."
            )

