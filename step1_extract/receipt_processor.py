#!/usr/bin/env python3
"""
Receipt Processor - Extract data from PDF receipts
"""

import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal, ROUND_HALF_UP

try:
    from .csv_processor import CSVProcessor
    CSV_AVAILABLE = True
except ImportError:
    CSV_AVAILABLE = False
    CSVProcessor = None

try:
    from .fee_extractor import FeeExtractor
    FEE_EXTRACTOR_AVAILABLE = True
except ImportError:
    FEE_EXTRACTOR_AVAILABLE = False
    FeeExtractor = None

try:
    from .vendor_matcher import VendorMatcher
    VENDOR_MATCHER_AVAILABLE = True
except ImportError:
    VENDOR_MATCHER_AVAILABLE = False
    VendorMatcher = None

try:
    from .rule_loader import RuleLoader
    from .receipt_parsers import VendorIdentifier, ItemLineParser, UnitDetector, TotalValidator
    from .utils.text_extractor import TextExtractor
    from .instacart_csv_matcher import InstacartCSVMatcher
    from .vendor_profiles import VendorProfileHandler
    RULE_LOADER_AVAILABLE = True
except ImportError:
    RULE_LOADER_AVAILABLE = False
    RuleLoader = None
    VendorIdentifier = None
    ItemLineParser = None
    UnitDetector = None
    TotalValidator = None
    TextExtractor = None
    InstacartCSVMatcher = None
    VendorProfileHandler = None

try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logging.warning("PyPDF2 not available. Install with: pip install PyPDF2")

try:
    import fitz  # PyMuPDF
    MUPDF_AVAILABLE = True
except ImportError:
    MUPDF_AVAILABLE = False

logger = logging.getLogger(__name__)

# Receipt processing supports PDF, Excel, and CSV files


class ReceiptProcessor:
    """Process PDF receipts and extract structured data"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.receipt_data = {}
        self.csv_processor = CSVProcessor(config) if CSV_AVAILABLE else None
        self.fee_extractor = FeeExtractor(config) if FEE_EXTRACTOR_AVAILABLE else None
        
        # Load rules from step1_rules folder first (needed for VendorMatcher)
        if RULE_LOADER_AVAILABLE:
            rules_dir = Path(__file__).parent.parent / 'step1_rules'
            self.rule_loader = RuleLoader(rules_dir, enable_hot_reload=True)
            self.rules = self.rule_loader.load_all_rules()
        else:
            self.rule_loader = None
            self.rules = {}
        
        # In step 1, skip database checks
        # Pass rule_loader to VendorMatcher so it can load vendor alias rules
        step1_config = config.copy() if config else {}
        step1_config['skip_database_check'] = True
        self.vendor_matcher = VendorMatcher(step1_config, rule_loader=self.rule_loader) if VENDOR_MATCHER_AVAILABLE else None
        
        # Continue with rule-based initialization
        if RULE_LOADER_AVAILABLE:
            
            # Initialize rule-based parsers
            self.vendor_identifier = VendorIdentifier(self.rules.get('vendor_identification', {}))
            self.item_parser = ItemLineParser(self.rules.get('item_line_parsing', {}))
            self.unit_detector = UnitDetector(self.rules.get('unit_detection', {}))
            self.total_validator = TotalValidator(self.rules.get('validation', {}))
            
            # Initialize new modules
            # Initialize text extractor for direct PDF text extraction
            self.text_extractor = TextExtractor() if TextExtractor else None
            
            # Load knowledge base file path from config or use default
            kb_file = config.get('knowledge_base_file', None) if config else None
            self.vendor_profiles = VendorProfileHandler(
                self.rules.get('vendor_profiles', {}), 
                rules_dir,
                knowledge_base_file=kb_file
            ) if VendorProfileHandler else None
            
            # Initialize AI line interpreter (optional fallback for parsing)
            # Load AI interpreter rules from rule_loader (now uses shared.yaml)
            try:
                from step1_extract.ai_line_interpreter import AILineInterpreter, AI_AVAILABLE
                if AI_AVAILABLE:
                    # Pass rule_loader to AILineInterpreter so it can load rules from YAML
                    self.ai_interpreter = AILineInterpreter(rule_loader=self.rule_loader)
                    logger.info("AI line interpreter initialized with rules")
                else:
                    self.ai_interpreter = None
                    logger.debug("AI line interpreter not available (no LLM backend found)")
            except ImportError:
                logger.debug("AI line interpreter module not available")
                self.ai_interpreter = None
            
            # Fallback rules
            self.fallback_rules = self.rules.get('fallback_rules', {})
        else:
            self.rule_loader = None
            self.rules = {}
            self.vendor_identifier = None
            self.item_parser = None
            self.unit_detector = None
            self.total_validator = None
            self.text_extractor = None
            self.vendor_profiles = None
            self.fallback_rules = {}
    
    def process_excel(self, excel_path: str) -> Dict:
        """
        Extract data from Excel receipt (for Costco receipts converted to Excel)
        
        Args:
            excel_path: Path to Excel file (.xlsx)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        excel_path = Path(excel_path)
        if not excel_path.exists():
            raise FileNotFoundError(f"Excel file not found: {excel_path}")
        
        logger.info(f"Processing Excel receipt: {excel_path.name}")
        
        try:
            import pandas as pd
        except ImportError:
            logger.error("pandas not installed. Install with: pip install pandas openpyxl")
            return {
                'filename': excel_path.name,
                'vendor': 'Costco',
                'items': [],
                'total': 0.0,
                'needs_review': True,
                'review_reasons': ['pandas not installed - cannot process Excel file']
            }
        
        # Read Excel file (use openpyxl engine - block xlrd to avoid Python 2 syntax errors)
        try:
            # Temporarily block xlrd import (it has Python 2 syntax and breaks pandas)
            import sys
            xlrd_backup = sys.modules.get('xlrd')
            sys.modules['xlrd'] = None  # Block xlrd import
            
            try:
                if excel_path.suffix.lower() in ['.xlsx', '.xls']:
                    df = pd.read_excel(excel_path, engine='openpyxl')
                else:
                    df = pd.read_excel(excel_path)
            finally:
                # Restore xlrd if it was there
                if xlrd_backup is not None:
                    sys.modules['xlrd'] = xlrd_backup
                elif 'xlrd' in sys.modules:
                    del sys.modules['xlrd']
        except Exception as e:
            logger.error(f"Failed to read Excel file: {e}")
            return {
                'filename': excel_path.name,
                'vendor': 'Costco',
                'items': [],
                'total': 0.0,
                'needs_review': True,
                'review_reasons': [f'Failed to read Excel file: {str(e)}']
            }
        
        # Initialize receipt data
        # Try to detect vendor from filename or folder
        vendor = 'Unknown'
        filename_lower = excel_path.name.lower()
        path_lower = str(excel_path).lower()
        
        # Localgrocery vendors no longer use Excel files (PDF only)
        localgrocery_vendors = ['costco', 'rd', 'restaurant depot', 'jewel', 'mariano', 'aldi', 'parktoshop']
        
        if 'costco' in filename_lower or 'costco' in path_lower:
            vendor = 'Costco'
        elif 'mariano' in filename_lower or 'mariano' in path_lower:
            vendor = 'Mariano'  # or 'Mariano\'s'
        elif 'aldi' in filename_lower or 'aldi' in path_lower:
            vendor = 'Aldi'
        elif 'parktoshop' in filename_lower or 'parktoshop' in path_lower or 'park to shop' in path_lower:
            vendor = 'ParkToShop'
        elif 'rd' in filename_lower or 'restaurant depot' in path_lower:
            vendor = 'Restaurant Depot'
        elif 'jewel' in filename_lower or 'jewel' in path_lower:
            vendor = 'Jewel Osco'
        
        # Reject localgrocery vendors (Excel no longer supported)
        if vendor != 'Unknown' and any(lgv in vendor.lower() or lgv in filename_lower or lgv in path_lower for lgv in localgrocery_vendors):
            logger.warning(f"Excel files no longer supported for {vendor}. Use PDF files instead. Skipping: {excel_path.name}")
            return {
                'filename': excel_path.name,
                'vendor': vendor,
                'items': [],
                'needs_review': True,
                'review_reasons': [f'Excel files no longer supported for {vendor}. Please use PDF files.'],
                'parsed_by': 'rejected_excel_format',
                'source_type': 'excel'
            }
        
        receipt_data = {
            'filename': excel_path.name,
            'vendor': vendor,
            'order_date': None,
            'store_name': None,
            'receipt_number': None,
            'member_number': None,
            'payment_method': None,
            'items': [],
            'total': 0.0,
            'subtotal': 0.0,
            'tax': 0.0,  # Always initialize tax - will be extracted from file, NOT calculated
            'other_charges': 0.0,  # Always initialize other charges (will be extracted or remain 0)
            'items_sold': None,  # Total Items Sold - read from file, NOT calculated
            'notes': [],
            'needs_review': False,
            'review_reasons': [],
            'source_type': 'excel',  # Mark as Excel source
        }
        
        # Parse Excel data - handle three formats:
        # Format 1: Key-value format with ['Field', 'Detail'] columns
        # Format 2: Table format with ['Item Name', 'Item Code', 'Total Paid', 'Unit Price', 'Quantity'] columns
        # Format 3: Tabular format with ['Store Name', 'Transaction Date', 'Item Description', 'Extended Amount (USD)'] columns (new format)
        # May also have 'Item Number' column (Costco-specific)
        if 'Item Description' in df.columns and 'Extended Amount (USD)' in df.columns:
            # Format 3: New tabular format (Store Name, Transaction Date, Item Description, Extended Amount (USD))
            # May have optional 'Item Number' and 'UPC' columns
            has_item_number_col = 'Item Number' in df.columns
            has_upc_col = 'UPC' in df.columns
            
            for idx, row in df.iterrows():
                # Get item number and UPC if available (optional columns)
                item_number = None
                upc = None
                
                # Extract Item Number from Item Number column if available
                if has_item_number_col:
                    item_num_raw = row.get('Item Number', '')
                    if pd.notna(item_num_raw):
                        item_num_str = str(item_num_raw).strip()
                        # Skip if it's "TAX (Fee)" or "TOTAL (Grand Total)" - these are summary rows, not items
                        if item_num_str and item_num_str.lower() not in ['nan', 'none', '', 'tax (fee)', 'total (grand total)', 'total items sold']:
                            # Clean citation markers
                            item_num_str = re.sub(r'\[cite[^\]]*\]', '', item_num_str).strip()
                            # Item number can be numeric or alphanumeric
                            if item_num_str and (item_num_str.isdigit() or len(item_num_str) > 0):
                                item_number = item_num_str
                
                # Extract UPC from UPC column if available
                if has_upc_col:
                    upc_raw = row.get('UPC', '')
                    if pd.notna(upc_raw):
                        upc_str = str(upc_raw).strip()
                        # Clean citation markers
                        upc_str = re.sub(r'\[cite[^\]]*\]', '', upc_str).strip()
                        if upc_str and upc_str.lower() not in ['nan', 'none', '']:
                            upc = upc_str
                
                # Extract Size from Size column if available (BBI-specific)
                size = None
                if has_size_col:
                    size_raw = row.get('Size', '')
                    if pd.notna(size_raw):
                        size_str = str(size_raw).strip()
                        # Clean citation markers
                        size_str = re.sub(r'\[cite[^\]]*\]', '', size_str).strip()
                        if size_str and size_str.lower() not in ['nan', 'none', '']:
                            size = size_str
                
                item_desc = str(row.get('Item Description', '')).strip() if pd.notna(row.get('Item Description')) else ''
                amount = row.get('Extended Amount (USD)', 0)
                
                # Clean citation markers from item description and amount
                item_desc = re.sub(r'\[cite[^\]]*\]', '', item_desc).strip()
                
                # Handle amount - may have citation markers or be in a different format
                amount_str = str(amount) if pd.notna(amount) else '0'
                # Clean citation markers from amount
                amount_str = re.sub(r'\[cite[^\]]*\]', '', amount_str).strip()
                
                # Convert amount to float
                try:
                    # Try to extract number from string (handles cases like "6.49 [cite: 8]")
                    amount_match = re.search(r'(\d+\.\d{2})', amount_str)
                    if amount_match:
                        amount_float = float(amount_match.group(1))
                    else:
                        amount_float = float(amount_str) if amount_str and amount_str != 'nan' else 0.0
                except (ValueError, TypeError):
                    amount_float = 0.0
                
                # Handle rows with empty Item Description - these might be trailing summary rows (tax, total, items_sold)
                # For RD and Aldi, tax/total/items_sold often appear at the end with empty Item Description
                if not item_desc or item_desc.lower() in ['nan', 'none', '']:
                    # Check if this is a trailing summary row with an amount
                    # These typically appear after all items (RD format: tax, total, items_sold in separate rows)
                    if amount_float > 0 or pd.notna(amount):
                        # This could be tax, total, or items_sold
                        # Check vendor code to determine what it might be
                        vendor_code = receipt_data.get('detected_vendor_code', '').upper()
                        is_rd = vendor_code in ['RD', 'RESTAURANT_DEPOT']
                        is_aldi = vendor_code in ['ALDI']
                        
                        # For RD and Aldi: trailing rows are typically: subtotal/tax, total, items_sold
                        # We'll identify them by position and amount pattern
                        # If we haven't extracted tax yet and this looks like a tax amount (< total, < items count), it's probably tax
                        # If it's a large amount and we don't have a total yet, it's probably the total
                        # If it's a small integer and we don't have items_sold yet, it's probably items_sold
                        
                        # Check if this is likely tax (small amount, no tax extracted yet)
                        if not receipt_data.get('tax', 0) and amount_float > 0 and amount_float < 100:
                            # Could be tax - but we can't be 100% sure without context
                            # Only set if we're reasonably sure (e.g., for RD/Aldi when tax should be present)
                            if (is_rd or is_aldi) and amount_float > 0:
                                receipt_data['tax'] = amount_float
                                logger.debug(f"Extracted tax from trailing row (empty Item Description): ${amount_float:.2f}")
                        
                        # Check if this is likely total (larger amount, matches pattern)
                        if not receipt_data.get('total', 0) and amount_float > 100:
                            receipt_data['total'] = amount_float
                            logger.debug(f"Extracted total from trailing row (empty Item Description): ${amount_float:.2f}")
                        
                        # Check if this is likely items_sold (small integer, no decimal or .0)
                        if receipt_data.get('items_sold') is None:
                            amount_int = int(amount_float) if amount_float == int(amount_float) else None
                            if amount_int and amount_int > 0 and amount_int < 1000:
                                receipt_data['items_sold'] = int(amount_int)
                                logger.debug(f"Extracted Total Items Sold from trailing row (empty Item Description): {receipt_data['items_sold']}")
                    continue
                
                # Extract vendor and store name from first row if available
                if idx == 0 and 'Store Name' in df.columns:
                    store_name = str(row.get('Store Name', '')).strip() if pd.notna(row.get('Store Name')) else ''
                    if store_name and store_name.lower() not in ['nan', 'none', '']:
                        # Save store name
                        receipt_data['store_name'] = store_name
                        # Try to match vendor from store name
                        store_lower = store_name.lower()
                        if 'mariano' in store_lower:
                            receipt_data['vendor'] = 'Mariano'
                        elif 'costco' in store_lower:
                            receipt_data['vendor'] = 'Costco'
                        elif 'aldi' in store_lower:
                            receipt_data['vendor'] = 'Aldi'
                        elif 'jewel' in store_lower:
                            receipt_data['vendor'] = 'Jewel Osco'
                        elif 'park' in store_lower or 'shop' in store_lower:
                            receipt_data['vendor'] = 'ParkToShop'
                        elif 'restaurant depot' in store_lower or 'rd' in store_lower:
                            receipt_data['vendor'] = 'Restaurant Depot'
                
                # Extract transaction date from first row if available
                if idx == 0 and 'Transaction Date' in df.columns:
                    tx_date = row.get('Transaction Date')
                    if pd.notna(tx_date):
                        try:
                            # Try to parse date
                            if isinstance(tx_date, str):
                                receipt_data['order_date'] = tx_date
                            else:
                                receipt_data['order_date'] = str(tx_date)
                        except:
                            pass
                
                # Extract receipt number, member number, and payment method from Format 3 if available
                # These might appear as separate columns or in Item Description for summary rows
                if idx == 0:
                    # Check for additional columns that might contain receipt metadata
                    for col in df.columns:
                        col_lower = str(col).lower()
                        if 'receipt' in col_lower and 'number' in col_lower:
                            receipt_num = row.get(col)
                            if pd.notna(receipt_num):
                                receipt_data['receipt_number'] = str(receipt_num).strip()
                        elif 'member' in col_lower and ('number' in col_lower or 'id' in col_lower):
                            member_num = row.get(col)
                            if pd.notna(member_num):
                                receipt_data['member_number'] = str(member_num).strip()
                        elif 'payment' in col_lower:
                            payment = row.get(col)
                            if pd.notna(payment):
                                receipt_data['payment_method'] = str(payment).strip()
                
                item_desc_lower = item_desc.lower()
                
                # Check if Item Number column indicates TAX/FEE (Costco-specific)
                if has_item_number_col:
                    item_num_str = str(row.get('Item Number', '')).strip() if pd.notna(row.get('Item Number')) else ''
                    item_num_str = re.sub(r'\[cite[^\]]*\]', '', item_num_str).strip()
                    item_num_lower = item_num_str.lower()
                    
                    # Check if Item Number is "TAX (Fee)"
                    if item_num_lower == 'tax (fee)' or item_num_lower == 'tax':
                        # Tax amount might be in Item Description (NaN) or Extended Amount column
                        # Check next row for tax amount if current row has NaN in Item Description
                        if pd.isna(row.get('Item Description')) or str(row.get('Item Description', '')).strip().lower() in ['nan', 'none', '']:
                            # Tax amount is likely in next row's Extended Amount column
                            if idx + 1 < len(df):
                                next_row = df.iloc[idx + 1]
                                next_amount = next_row.get('Extended Amount (USD)', 0)
                                next_amount_str = str(next_amount) if pd.notna(next_amount) else '0'
                                next_amount_str = re.sub(r'\[cite[^\]]*\]', '', next_amount_str).strip()
                                try:
                                    tax_match = re.search(r'(\d+\.\d{2})', next_amount_str)
                                    if tax_match:
                                        receipt_data['tax'] = float(tax_match.group(1))
                                        logger.debug(f"Extracted tax from next row: ${receipt_data['tax']:.2f}")
                                except:
                                    pass
                        else:
                            # Tax amount might be in Extended Amount column
                            if amount_float > 0:
                                receipt_data['tax'] = amount_float
                                logger.debug(f"Extracted tax: ${amount_float:.2f}")
                        continue
                    
                    # Check if Item Number is "TOTAL (Grand Total)"
                    if 'total' in item_num_lower and ('grand' in item_num_lower or 'final' in item_num_lower):
                        # Total amount is likely in next row's Extended Amount column
                        if pd.isna(row.get('Item Description')) or str(row.get('Item Description', '')).strip().lower() in ['nan', 'none', '']:
                            if idx + 1 < len(df):
                                next_row = df.iloc[idx + 1]
                                next_amount = next_row.get('Extended Amount (USD)', 0)
                                next_amount_str = str(next_amount) if pd.notna(next_amount) else '0'
                                next_amount_str = re.sub(r'\[cite[^\]]*\]', '', next_amount_str).strip()
                                try:
                                    total_match = re.search(r'(\d+\.\d{2})', next_amount_str)
                                    if total_match:
                                        receipt_data['total'] = float(total_match.group(1))
                                        logger.debug(f"Extracted total from next row: ${receipt_data['total']:.2f}")
                                except:
                                    pass
                        continue
                    
                    # Check if Item Number is "Total Items Sold" - extract value from next row
                    if 'total items' in item_num_lower or 'items sold' in item_num_lower:
                        # Total Items Sold value is in the next row's Extended Amount column
                        if pd.isna(row.get('Item Description')) or str(row.get('Item Description', '')).strip().lower() in ['nan', 'none', '']:
                            if idx + 1 < len(df):
                                next_row = df.iloc[idx + 1]
                                next_amount = next_row.get('Extended Amount (USD)', 0)
                                next_amount_str = str(next_amount) if pd.notna(next_amount) else '0'
                                next_amount_str = re.sub(r'\[cite[^\]]*\]', '', next_amount_str).strip()
                                try:
                                    # Extract number (could be decimal or integer)
                                    items_sold_match = re.search(r'(\d+(?:\.\d+)?)', next_amount_str)
                                    if items_sold_match:
                                        receipt_data['items_sold'] = float(items_sold_match.group(1))
                                        logger.debug(f"Extracted Total Items Sold from next row: {receipt_data['items_sold']}")
                                except:
                                    pass
                        continue
                
                # Check if Item Description indicates TAX (for non-Costco or fallback)
                # Handle variations: "tax", "food tax", "sales tax", "state tax", "B:Taxable @2.250%", etc.
                # For RD and Aldi, tax is always present, so extract it carefully
                # Also handle patterns like "B:Taxable @2.250%" which should be treated as tax, not a product
                is_tax_line = (
                    item_desc_lower == 'tax' or 
                    item_desc_lower.startswith('tax ') or 
                    item_desc_lower == 'taxable' or
                    'b:taxable' in item_desc_lower or  # Handle "B:Taxable @2.250%" pattern (Aldi receipts)
                    re.search(r'b:\s*taxable\s*@', item_desc_lower, re.IGNORECASE) is not None or  # Pattern: "B:Taxable @X.XXX%"
                    'food tax' in item_desc_lower or
                    'sales tax' in item_desc_lower or
                    'state tax' in item_desc_lower or
                    item_desc_lower.endswith(' tax') or
                    item_desc_lower.endswith(' tax.')
                )
                if is_tax_line:
                    # Tax amount is in Extended Amount column
                    # If amount is 0 or empty, check if it's in next row (like Costco format)
                    if amount_float > 0:
                        receipt_data['tax'] = amount_float
                        logger.debug(f"Extracted tax from Item Description: ${amount_float:.2f}")
                    elif pd.isna(row.get('Extended Amount (USD)')) or str(row.get('Extended Amount (USD)', '')).strip().lower() in ['nan', 'none', '']:
                        # Tax amount might be in next row (Costco-style format)
                        if idx + 1 < len(df):
                            next_row = df.iloc[idx + 1]
                            next_amount = next_row.get('Extended Amount (USD)', 0)
                            next_amount_str = str(next_amount) if pd.notna(next_amount) else '0'
                            next_amount_str = re.sub(r'\[cite[^\]]*\]', '', next_amount_str).strip()
                            try:
                                tax_match = re.search(r'(\d+\.\d{2})', next_amount_str)
                                if tax_match:
                                    receipt_data['tax'] = float(tax_match.group(1))
                                    logger.debug(f"Extracted tax from next row: ${receipt_data['tax']:.2f}")
                            except:
                                pass
                    continue
                
                # Check if this is OTHER CHARGES or FEES
                if 'other charge' in item_desc_lower or ('fee' in item_desc_lower and 'tax' not in item_desc_lower) or 'charge' in item_desc_lower:
                    receipt_data['other_charges'] = receipt_data.get('other_charges', 0.0) + amount_float
                    logger.debug(f"Extracted other charges/fees: ${amount_float:.2f}")
                    continue
                
                # Check if this is TOTAL or TRANSACTION TOTAL
                is_total = (
                    ('total' in item_desc_lower and ('grand' in item_desc_lower or 'final' in item_desc_lower)) or
                    'transaction total' in item_desc_lower
                )
                if is_total:
                    receipt_data['total'] = amount_float
                    logger.debug(f"Extracted total: ${amount_float:.2f} from '{item_desc[:50]}...'")
                    continue
                
                # Check if this is SUBTOTAL
                if 'subtotal' in item_desc_lower:
                    receipt_data['subtotal'] = amount_float
                    logger.debug(f"Extracted subtotal: ${amount_float:.2f}")
                    continue
                
                # Extract Total Items Sold from Item Description (for non-Costco formats)
                if 'total items' in item_desc_lower or 'items sold' in item_desc_lower:
                    # Total Items Sold value is in Extended Amount column
                    # If amount is empty, check next row
                    if amount_float > 0:
                        receipt_data['items_sold'] = float(amount_float)
                        logger.debug(f"Extracted Total Items Sold: {receipt_data['items_sold']}")
                    elif pd.isna(row.get('Extended Amount (USD)')) or str(row.get('Extended Amount (USD)', '')).strip().lower() in ['nan', 'none', '']:
                        # Value might be in next row (Costco-style format)
                        if idx + 1 < len(df):
                            next_row = df.iloc[idx + 1]
                            next_amount = next_row.get('Extended Amount (USD)', 0)
                            next_amount_str = str(next_amount) if pd.notna(next_amount) else '0'
                            next_amount_str = re.sub(r'\[cite[^\]]*\]', '', next_amount_str).strip()
                            try:
                                items_sold_match = re.search(r'(\d+(?:\.\d+)?)', next_amount_str)
                                if items_sold_match:
                                    receipt_data['items_sold'] = float(items_sold_match.group(1))
                                    logger.debug(f"Extracted Total Items Sold from next row: {receipt_data['items_sold']}")
                            except:
                                pass
                    continue
                
                # This is a product item
                if amount_float > 0:
                    # First, try to get quantity from Quantity or QTY column if it exists
                    quantity = 1.0  # Default to 1.0
                    qty_col_name = None
                    if 'Quantity' in df.columns:
                        qty_col_name = 'Quantity'
                    elif 'QTY' in df.columns:
                        qty_col_name = 'QTY'
                    
                    if qty_col_name:
                        qty_col = row.get(qty_col_name)
                        if pd.notna(qty_col):
                            try:
                                quantity = float(qty_col)
                            except (ValueError, TypeError):
                                quantity = 1.0
                    
                    # Extract size/UoM from Size column if available (BBI-specific), otherwise from product name
                    uom = 'each'
                    size_info = None
                    
                    # First, try Size column if available (BBI-specific)
                    if size:
                        size_info = size
                        # Try to extract UoM from Size column
                        qty_uom_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:FL\s+)?(LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH|EA|BAG|CAN|BUCKET|PACK)\.?', size, re.IGNORECASE)
                        if qty_uom_match:
                            uom_raw = qty_uom_match.group(2).upper()
                            uom_map = {
                                'LB': 'lb', 'POUND': 'lb', 'LBS': 'lb',
                                'OZ': 'oz', 'OUNCE': 'oz',
                                'GAL': 'gal', 'GALLON': 'gal',
                                'QT': 'qt', 'QUART': 'qt',
                                'PT': 'pt', 'PINT': 'pt',
                                'CT': 'ct', 'COUNT': 'ct',
                                'EA': 'each', 'EACH': 'each',
                                'L': 'l', 'LITER': 'l',
                                'ML': 'ml', 'MILLILITER': 'ml',
                                'KG': 'kg', 'KILOGRAM': 'kg',
                                'G': 'g', 'GRAM': 'g',
                                'BAG': 'bag', 'CAN': 'can', 'BUCKET': 'bucket', 'PACK': 'pack',
                            }
                            uom = uom_map.get(uom_raw, uom_raw.lower())
                            if 'FL' in size.upper() and uom == 'oz':
                                uom = 'fl_oz'
                    
                    # If Size column not available, try to extract size and UoM from description (this is size/weight, not quantity)
                    # Pattern: "10 LB", "10LB", "32 OZ", etc. in product name
                    if not size_info:
                        qty_uom_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:FL\s+)?(LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH|EA)\.?', item_desc, re.IGNORECASE)
                        if qty_uom_match:
                            # This is size/weight, NOT quantity - extract as size_info
                            size_qty = float(qty_uom_match.group(1))
                            uom_raw = qty_uom_match.group(2).upper()
                            uom_map = {
                                'LB': 'lb', 'POUND': 'lb', 'LBS': 'lb',
                                'OZ': 'oz', 'OUNCE': 'oz',
                                'GAL': 'gal', 'GALLON': 'gal',
                                'QT': 'qt', 'QUART': 'qt',
                                'PT': 'pt', 'PINT': 'pt',
                                'CT': 'ct', 'COUNT': 'ct',
                                'EA': 'each',
                                'L': 'l', 'LITER': 'l',
                                'ML': 'ml', 'MILLILITER': 'ml',
                                'KG': 'kg', 'KILOGRAM': 'kg',
                                'G': 'g', 'GRAM': 'g',
                            }
                            uom_for_size = uom_map.get(uom_raw, uom_raw.lower())
                            if 'FL' in item_desc.upper() and uom_for_size == 'oz':
                                uom_for_size = 'fl_oz'
                            
                            # Store as size (not quantity)
                            size_info = f"{size_qty} {uom_for_size}"
                            uom = uom_for_size  # Also set UoM for the item
                            
                            # Clean product name - remove size/weight pattern
                            item_desc = re.sub(r'\d+(?:\.\d+)?\s*(?:FL\s+)?(?:LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH|EA)\.?', '', item_desc, flags=re.IGNORECASE).strip()
                    
                    # Extract item number from product name if not already extracted from Item Number column
                    # (Item number and UPC were already extracted at the start of the loop)
                    if not item_number:
                        # Try to extract from item description (e.g., "Code: 3923" or "— Code: 3923")
                        code_match = re.search(r'(?:Code|Item\s*#?|Item\s*Code)[:\s]+(\d{1,10})', item_desc, re.IGNORECASE)
                        if code_match:
                            item_number = code_match.group(1)
                            item_desc = re.sub(r'(?:Code|Item\s*#?|Item\s*Code)[:\s]+\d{1,10}', '', item_desc, flags=re.IGNORECASE).strip()
                    
                    # Clean product name
                    product_name = re.sub(r'\s+', ' ', item_desc).strip()
                    
                    # Calculate unit price
                    unit_price = amount_float / quantity if quantity > 0 else amount_float
                    
                    item = {
                        'product_name': product_name,
                        'quantity': quantity,
                        'purchase_uom': uom,
                        'unit_price': unit_price,
                        'total_price': amount_float,
                        'line_text': f"{product_name} {quantity} {uom} ${amount_float:.2f}",
                    }
                    
                    # Add size if extracted (from Size column or description)
                    if size_info:
                        item['size'] = size_info
                    elif size:  # If Size column exists but wasn't parsed as size_info, store it directly
                        item['size'] = size
                    
                    # Add item_number and UPC if available (already extracted at start of loop)
                    # Convert to INT type for Group 1 receipts
                    if item_number:
                        try:
                            # Convert to int (strip any non-numeric characters first)
                            item_num_int = int(float(re.sub(r'[^\d.]', '', str(item_number))))
                            item['item_number'] = item_num_int
                            item['item_code'] = item_num_int
                        except (ValueError, TypeError):
                            # If conversion fails, keep as string
                            item['item_number'] = item_number
                            item['item_code'] = item_number
                    
                    if upc:
                        try:
                            # Convert to int (strip any non-numeric characters first)
                            upc_int = int(float(re.sub(r'[^\d.]', '', str(upc))))
                            item['upc'] = upc_int
                        except (ValueError, TypeError):
                            # If conversion fails, keep as string
                            item['upc'] = upc
                    
                    receipt_data['items'].append(item)
            
            # Calculate subtotal from items if not already set (excluding fees)
            if not receipt_data.get('subtotal') and receipt_data['items']:
                item_only_items = [item for item in receipt_data['items'] if not item.get('is_fee', False)]
                receipt_data['subtotal'] = sum(item.get('total_price', 0) for item in item_only_items)
            
            # Calculate other_charges by summing all fees (items with is_fee=True), excluding tax
            # Other charges should include: bag fee, tips, service fees, but NOT tax
            fee_items = [item for item in receipt_data['items'] if item.get('is_fee', False)]
            if fee_items:
                calculated_other_charges = sum(item.get('total_price', 0) for item in fee_items)
                # Update other_charges if it wasn't already set, or add to existing other_charges
                receipt_data['other_charges'] = receipt_data.get('other_charges', 0.0) + calculated_other_charges
                logger.debug(f"Calculated other_charges from fees: ${calculated_other_charges:.2f} (total other_charges: ${receipt_data['other_charges']:.2f})")
            
            # For Mariano's orders: Total already includes tax, so don't add tax again
            vendor = receipt_data.get('vendor', '').lower()
            is_mariano = 'mariano' in vendor or 'mariano' in excel_path.name.lower()
            
            # If total was extracted, use it as-is (it already includes tax for Mariano's)
            # Otherwise calculate from subtotal + tax + other_charges
            if not receipt_data.get('total'):
                calculated_total = receipt_data.get('subtotal', 0)
                if not is_mariano:
                    calculated_total += receipt_data.get('tax', 0) + receipt_data.get('other_charges', 0)
                receipt_data['total'] = calculated_total
                logger.debug(f"Calculated total: subtotal ${receipt_data.get('subtotal', 0):.2f} + tax ${receipt_data.get('tax', 0):.2f} + other_charges ${receipt_data.get('other_charges', 0):.2f} = ${receipt_data['total']:.2f}")
            elif is_mariano:
                logger.debug(f"Using extracted total ${receipt_data['total']:.2f} for Mariano's order (already includes tax)")
        
        elif 'Item Name' in df.columns and 'Item Code' in df.columns:
            # Format 2: Table format (new Costco Excel format)
            for _, row in df.iterrows():
                # Skip header row if present
                if pd.isna(row.get('Item Name')) or str(row.get('Item Name', '')).strip().lower() in ['item name', 'product name', 'nan']:
                    continue
                
                product_name = str(row['Item Name']).strip() if pd.notna(row.get('Item Name')) else ''
                item_code = str(row['Item Code']).strip() if pd.notna(row.get('Item Code')) else ''
                total_paid = row.get('Total Paid', 0)
                unit_price_col = row.get('Unit Price', 0)
                quantity_col = row.get('Quantity', 1)
                
                # Convert to numeric if needed
                try:
                    total_price = float(total_paid) if pd.notna(total_paid) else 0.0
                    unit_price = float(unit_price_col) if pd.notna(unit_price_col) else 0.0
                    quantity = float(quantity_col) if pd.notna(quantity_col) else 1.0
                except (ValueError, TypeError):
                    total_price = 0.0
                    unit_price = 0.0
                    quantity = 1.0
                
                # Skip if no product name or price
                if not product_name or total_price <= 0:
                    continue
                
                # Skip summary lines like "Transaction Total" - these should not be treated as products
                product_name_lower = product_name.lower().strip()
                if product_name_lower in ['transaction total', 'total', 'grand total', 'final total']:
                    # Extract total from this row
                    if total_price > 0:
                        receipt_data['total'] = total_price
                        logger.debug(f"Extracted total from Format 2 (Item Name): ${total_price:.2f}")
                    continue
                
                # Extract quantity and UoM from product name (e.g., "LIMES 3 LB.")
                uom = 'each'
                quantity_from_name = quantity  # Use quantity from column by default
                size_info = None  # Store size information
                
                # Try to extract quantity and UoM from product name
                # Look for patterns like "3 LB.", "128 FL OZ", etc.
                qty_uom_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:FL\s+)?(LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH)\.?', product_name, re.IGNORECASE)
                if qty_uom_match:
                    quantity_from_name = float(qty_uom_match.group(1))
                    uom_raw = qty_uom_match.group(2).upper()
                    uom_map = {
                        'LB': 'lb', 'POUND': 'lb', 'LBS': 'lb',
                        'OZ': 'oz', 'OUNCE': 'oz',
                        'GAL': 'gal', 'GALLON': 'gal',
                        'QT': 'qt', 'QUART': 'qt',
                        'PT': 'pt', 'PINT': 'pt',
                        'CT': 'ct', 'COUNT': 'ct',
                        'L': 'l', 'LITER': 'l',
                        'ML': 'ml', 'MILLILITER': 'ml',
                        'KG': 'kg', 'KILOGRAM': 'kg',
                        'G': 'g', 'GRAM': 'g',
                    }
                    uom = uom_map.get(uom_raw, uom_raw.lower())
                    if 'FL' in product_name.upper() and uom == 'oz':
                        uom = 'fl_oz'
                    
                    # Store size information
                    size_info = f"{quantity_from_name} {uom}"
                    
                    # Clean product name - remove quantity and UoM
                    product_name = re.sub(r'\d+(?:\.\d+)?\s*(?:FL\s+)?(?:LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH)\.?', '', product_name, flags=re.IGNORECASE).strip()
                
                # Use quantity from column, but if it's 1.0 and we found quantity in name, use name quantity
                if quantity == 1.0 and quantity_from_name != 1.0:
                    quantity = quantity_from_name
                
                # Calculate unit_price if not provided or if it seems incorrect
                if unit_price <= 0 or (unit_price == total_price and quantity > 1.0):
                    unit_price = total_price / quantity if quantity > 0 else total_price
                
                item = {
                    'product_name': product_name,
                    'quantity': quantity,
                    'purchase_uom': uom,
                    'unit_price': unit_price,
                    'total_price': total_price,
                    'line_text': f"{product_name} {quantity} {uom} ${total_price:.2f}",
                }
                
                # Add size if extracted
                if size_info:
                    item['size'] = size_info
                
                # Add item_number from Item Code column (convert to INT for Group 1 receipts)
                if item_code and item_code.lower() not in ['item code', 'nan']:
                    try:
                        # Convert to int (strip any non-numeric characters first)
                        item_code_int = int(float(re.sub(r'[^\d.]', '', str(item_code))))
                        item['item_number'] = item_code_int
                        item['item_code'] = item_code_int
                    except (ValueError, TypeError):
                        # If conversion fails, keep as string
                        item_code_str = str(item_code).rstrip('0').rstrip('.') if '.' in str(item_code) else str(item_code)
                        item['item_number'] = item_code_str
                        item['item_code'] = item_code_str
                
                receipt_data['items'].append(item)
            
            # Extract total from last row if available
            if len(df) > 0:
                last_row = df.iloc[-1]
                if 'Item Name' in last_row and 'Transaction Total' in str(last_row.get('Item Name', '')).lower():
                    total_col = last_row.get('Total Paid', 0) or last_row.get('Total', 0)
                    if pd.notna(total_col):
                        try:
                            receipt_data['total'] = float(total_col)
                        except (ValueError, TypeError):
                            pass
        
        elif 'Field' in df.columns and 'Detail' in df.columns:
            # Key-value format (Field: Detail)
            in_items_section = False
            for _, row in df.iterrows():
                field = str(row['Field']).strip() if pd.notna(row['Field']) else ''
                detail = str(row['Detail']).strip() if pd.notna(row['Detail']) else ''
                
                # Remove citation markers like [cite_start]... [cite: ...]
                detail = re.sub(r'\[cite[^\]]*\]', '', detail).strip()
                # Remove trailing numbers that might be citation coordinates
                detail = re.sub(r'\s+\d+,\s*\d+\s*$', '', detail).strip()
                
                # Check if we're entering the items section
                if 'Itemized Purchases' in field:
                    in_items_section = True
                    # The first item might be in the same row as "Itemized Purchases"
                    if detail and len(detail) > 3:
                        # Parse the detail as the first item
                        # Extract price first
                        price_match = re.search(r'\(?\$(\d+\.\d{2})\)?', detail)
                        if not price_match:
                            price_match = re.search(r'\$(\d+\.\d{2})', detail)
                        price = float(price_match.group(1)) if price_match else 0.0
                        
                        if price > 0:
                            # Remove price from detail to get product info
                            product_detail = re.sub(r'\(?\$?\d+\.\d{2}\)?', '', detail).strip()
                            product_detail = re.sub(r'\([^)]*\)', '', product_detail).strip()
                            
                            # Try to extract quantity and UoM
                            qty_uom_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:FL\s+)?(LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH)\.?', product_detail, re.IGNORECASE)
                            quantity = 1.0
                            uom = 'each'
                            
                            size_info = None  # Store size information
                            if qty_uom_match:
                                quantity = float(qty_uom_match.group(1))
                                uom_raw = qty_uom_match.group(2).upper()
                                uom_map = {
                                    'LB': 'lb', 'POUND': 'lb', 'LBS': 'lb',
                                    'OZ': 'oz', 'OUNCE': 'oz',
                                    'GAL': 'gal', 'GALLON': 'gal',
                                    'QT': 'qt', 'QUART': 'qt',
                                    'PT': 'pt', 'PINT': 'pt',
                                    'CT': 'ct', 'COUNT': 'ct',
                                    'L': 'l', 'LITER': 'l',
                                    'ML': 'ml', 'MILLILITER': 'ml',
                                    'KG': 'kg', 'KILOGRAM': 'kg',
                                    'G': 'g', 'GRAM': 'g',
                                }
                                uom = uom_map.get(uom_raw, uom_raw.lower())
                                if 'FL' in product_detail.upper() and uom == 'oz':
                                    uom = 'fl_oz'
                                
                                # Store size information
                                size_info = f"{quantity} {uom}"
                                
                                product_detail = re.sub(r'\d+(?:\.\d+)?\s*(?:FL\s+)?(?:LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH)\.?', '', product_detail, flags=re.IGNORECASE).strip()
                            
                            product_name = product_detail.strip()
                            
                            # Extract item number/code from product name or line text (for Costco format: "Code: 3923")
                            item_number = None
                            code_match = re.search(r'(?:Code|Item\s*#?|Item\s*Code)[:\s]+(\d{1,10})', detail, re.IGNORECASE)
                            if code_match:
                                item_number = code_match.group(1)
                            # Also check if product name ends with item number pattern (e.g., " — Code: 3923")
                            if not item_number:
                                item_num_match = re.search(r'[—\-]\s*Code[:\s]+(\d{1,10})', product_name, re.IGNORECASE)
                                if item_num_match:
                                    item_number = item_num_match.group(1)
                                    # Remove item number from product name
                                    product_name = re.sub(r'[—\-]\s*Code[:\s]+\d{1,10}', '', product_name, flags=re.IGNORECASE).strip()
                            
                            if product_name:
                                item = {
                                    'product_name': product_name,
                                    'quantity': quantity,
                                    'purchase_uom': uom,
                                    'unit_price': price / quantity if quantity > 0 else price,
                                    'total_price': price,
                                    'line_text': detail,
                                }
                                
                                # Add size if extracted
                                if size_info:
                                    item['size'] = size_info
                                
                                # Add item_number if extracted
                                if item_number:
                                    item['item_number'] = item_number
                                    item['item_code'] = item_number
                                
                                receipt_data['items'].append(item)
                    continue
                
                # If in items section, parse items
                if in_items_section:
                    # Items have 'nan' in Field column or empty Field
                    if field.lower() in ['nan', 'none', ''] or not field:
                        # This is an item row
                        if detail and len(detail) > 3:
                            # Parse item format: "PRODUCT NAME (QUANTITY UOM) ($PRICE)" or "PRODUCT NAME ($PRICE)"
                            # Examples: "LIMES 3 LB. ($6.49)" or "WATERMELON ($6.99)"
                            # Also handle: "OIL SHRT CRM LQ SR B (4 units @ $32.15 ea.)"
                            
                            # First, try to extract quantity from parentheses format
                            # Pattern 1: "(4 units @ $32.15 ea.)" - quantity and unit price together
                            # Pattern 2: "(4 units, 40 qty) ($83.20 ea.)" - quantity and unit price in separate parentheses
                            quantity = 1.0
                            uom = 'each'
                            extracted_qty_from_paren = None
                            unit_price_from_paren = None
                            
                            # Try pattern 1: "(N units @ $X.XX ea.)"
                            paren_qty_match = re.search(r'\((\d+(?:\.\d+)?)\s+units?\s*@\s*\$?(\d+\.\d{2})\s*(?:ea\.?)?\)', detail, re.IGNORECASE)
                            if paren_qty_match:
                                # Found quantity and unit price in same parentheses
                                extracted_qty_from_paren = float(paren_qty_match.group(1))
                                unit_price_from_paren = float(paren_qty_match.group(2))
                                quantity = extracted_qty_from_paren
                                uom = 'each'
                                logger.debug(f"Extracted quantity {quantity} and unit price ${unit_price_from_paren} from pattern 1: {detail[:50]}...")
                            else:
                                # Try pattern 2: "(N units, M qty) ($X.XX ea.)" - separate parentheses
                                qty_only_match = re.search(r'\((\d+(?:\.\d+)?)\s+units?,?\s*\d+\s*qty\)', detail, re.IGNORECASE)
                                if qty_only_match:
                                    extracted_qty_from_paren = float(qty_only_match.group(1))
                                    quantity = extracted_qty_from_paren
                                    uom = 'each'
                                    
                                    # Look for unit price in separate parentheses: "($X.XX ea.)"
                                    unit_price_match = re.search(r'\(\$(\d+\.\d{2})\s+ea\.?\)', detail, re.IGNORECASE)
                                    if unit_price_match:
                                        unit_price_from_paren = float(unit_price_match.group(1))
                                        logger.debug(f"Extracted quantity {quantity} from pattern 2a and unit price ${unit_price_from_paren} from pattern 2b: {detail[:50]}...")
                                    else:
                                        logger.debug(f"Extracted quantity {quantity} from pattern 2a but no unit price found: {detail[:50]}...")
                            
                            # Extract price (total price) - in parentheses, e.g., "($6.49)" or "$6.49"
                            # If we found unit price in parentheses, calculate total from it
                            if unit_price_from_paren:
                                price = unit_price_from_paren * quantity
                            else:
                                price_match = re.search(r'\(?\$(\d+\.\d{2})\)?', detail)
                                if not price_match:
                                    # Try alternative pattern without parentheses
                                    price_match = re.search(r'\$(\d+\.\d{2})', detail)
                                price = float(price_match.group(1)) if price_match else 0.0
                            
                            # Remove parentheses with quantity and price BEFORE removing prices
                            # This prevents leftover artifacts in product name
                            if extracted_qty_from_paren:
                                # Remove pattern 1: "(N units @ $X.XX ea.)"
                                detail = re.sub(r'\(\d+(?:\.\d+)?\s+units?\s*@\s*\$?\d+\.\d{2}\s*(?:ea\.?)?\)', '', detail, flags=re.IGNORECASE).strip()
                                # Remove pattern 2a: "(N units, M qty)"
                                detail = re.sub(r'\(\d+(?:\.\d+)?\s+units?,?\s*\d+\s*qty\)', '', detail, flags=re.IGNORECASE).strip()
                                # Remove pattern 2b: "($X.XX ea.)" if it's a unit price (not total)
                                if unit_price_from_paren:
                                    detail = re.sub(r'\(\$?\d+\.\d{2}\s+ea\.?\)', '', detail, flags=re.IGNORECASE).strip()
                            
                            # Now remove remaining price patterns from cleaned detail
                            product_detail = re.sub(r'\(?\$?\d+\.\d{2}\)?', '', detail).strip()
                            
                            # Remove any other remaining parentheses content
                            product_detail = re.sub(r'\([^)]*\)', '', product_detail).strip()
                            
                            # Try to extract quantity and UoM (e.g., "3 LB.", "128 FL OZ")
                            # Look for patterns like "3 LB", "3 LB.", "128 FL OZ", etc.
                            # Only do this if we haven't already extracted quantity from parentheses
                            size_info = None  # Store size information
                            if not extracted_qty_from_paren:
                                qty_uom_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:FL\s+)?(LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH)\.?', product_detail, re.IGNORECASE)
                                if qty_uom_match:
                                    quantity = float(qty_uom_match.group(1))
                                    uom_raw = qty_uom_match.group(2).upper()
                                    # Normalize UoM
                                    uom_map = {
                                        'LB': 'lb', 'POUND': 'lb', 'LBS': 'lb',
                                        'OZ': 'oz', 'OUNCE': 'oz',
                                        'GAL': 'gal', 'GALLON': 'gal',
                                        'QT': 'qt', 'QUART': 'qt',
                                        'PT': 'pt', 'PINT': 'pt',
                                        'CT': 'ct', 'COUNT': 'ct',
                                        'L': 'l', 'LITER': 'l',
                                        'ML': 'ml', 'MILLILITER': 'ml',
                                        'KG': 'kg', 'KILOGRAM': 'kg',
                                        'G': 'g', 'GRAM': 'g',
                                    }
                                    uom = uom_map.get(uom_raw, uom_raw.lower())
                                    # Check if it's FL OZ (fluid ounce)
                                    if 'FL' in product_detail.upper() and uom == 'oz':
                                        uom = 'fl_oz'
                                    
                                    # Store size information
                                    size_info = f"{quantity} {uom}"
                                    
                                    # Remove quantity and UoM from product name
                                    product_detail = re.sub(r'\d+(?:\.\d+)?\s*(?:FL\s+)?(?:LB|OZ|GAL|QT|PT|CT|L|ML|KG|G|COUNT|EACH)\.?', '', product_detail, flags=re.IGNORECASE).strip()
                            
                            # Clean product name - remove extra spaces and trailing artifacts
                            product_name = re.sub(r'\s+', ' ', product_detail).strip()
                            # Remove trailing "ea.)" or similar artifacts if any
                            product_name = re.sub(r'\s+ea\.?\)?\s*$', '', product_name, flags=re.IGNORECASE).strip()
                            
                            # Skip summary lines like "Transaction Total" - these should not be treated as products
                            product_name_lower = product_name.lower().strip()
                            if product_name_lower in ['transaction total', 'total', 'grand total', 'final total']:
                                # Extract total from this row
                                receipt_data['total'] = price
                                logger.debug(f"Extracted total from Format 1 (Itemized Purchases): ${price:.2f}")
                                continue
                            
                            # Extract item number/code from product name or line text (for Costco format: "Code: 3923")
                            item_number = None
                            code_match = re.search(r'(?:Code|Item\s*#?|Item\s*Code)[:\s]+(\d{1,10})', detail, re.IGNORECASE)
                            if code_match:
                                item_number = code_match.group(1)
                            # Also check if product name ends with item number pattern (e.g., " — Code: 3923")
                            if not item_number:
                                item_num_match = re.search(r'[—\-]\s*Code[:\s]+(\d{1,10})', product_name, re.IGNORECASE)
                                if item_num_match:
                                    item_number = item_num_match.group(1)
                                    # Remove item number from product name
                                    product_name = re.sub(r'[—\-]\s*Code[:\s]+\d{1,10}', '', product_name, flags=re.IGNORECASE).strip()
                            
                            if product_name and price > 0:
                                # Use unit price from parentheses if extracted, otherwise calculate from total
                                final_unit_price = unit_price_from_paren if unit_price_from_paren else (price / quantity if quantity > 0 else price)
                                
                                item = {
                                    'product_name': product_name,
                                    'quantity': quantity,
                                    'purchase_uom': uom,
                                    'unit_price': final_unit_price,
                                    'total_price': price,
                                    'line_text': detail,
                                }
                                
                                # Add size if extracted
                                if size_info:
                                    item['size'] = size_info
                                
                                # Add item_number if extracted
                                if item_number:
                                    item['item_number'] = item_number
                                    item['item_code'] = item_number
                                
                                receipt_data['items'].append(item)
                    else:
                        # Field is not empty and not "Itemized Purchases" - we're past items section
                        in_items_section = False
                
                # Parse header/metadata fields (only if not in items section)
                if not in_items_section:
                    if 'Transaction Date' in field or 'Date' in field or 'Date/Time' in field:
                        receipt_data['order_date'] = detail
                    elif 'Total Amount' in field or 'TOTAL' in field or ('Total' in field and 'Sub' not in field):
                        # Extract amount from detail
                        amount_match = re.search(r'\$?(\d+\.\d{2})', detail)
                        if amount_match:
                            receipt_data['total'] = float(amount_match.group(1))
                        # If detail is empty (like "[cite_start]"), try to get total from next row
                        # This handles cases where total is on a separate row like "$5.10 (**** BALANCE)"
                        elif (not detail.strip() or detail.strip() == '[cite_start]') and idx + 1 < len(df):
                            next_row = df.iloc[idx + 1]
                            next_field = str(next_row.get('Field', '')).strip() if 'Field' in df.columns else ''
                            next_detail = str(next_row.get('Detail', '')).strip() if 'Detail' in df.columns else ''
                            # Check if next row has a price (it's likely the total amount)
                            if 'nan' in next_field.lower() or not next_field or next_field.lower() in ['nan', 'none', '']:
                                next_amount_match = re.search(r'\$?(\d+\.\d{2})', next_detail)
                                if next_amount_match:
                                    receipt_data['total'] = float(next_amount_match.group(1))
                                    logger.debug(f"Extracted total from next row: ${receipt_data['total']:.2f}")
                    elif 'Subtotal' in field or 'Sub Total' in field:
                        # Extract subtotal
                        subtotal_match = re.search(r'\$?(\d+\.\d{2})', detail)
                        if subtotal_match:
                            receipt_data['subtotal'] = float(subtotal_match.group(1))
                    elif ('Tax' in field and 'Total' not in field) or ('Taxes' in field and 'Charges' in field):
                        # Extract tax from "Tax: $0.11" or "TAX: $0.11" or "Taxes, Fees, & Other Charges: TAX: $0.11"
                        # Handle formats like "TAX: $0.11", "Tax: $0.11", "Taxes, Fees, & Other Charges: TAX: $0.11"
                        tax_match = re.search(r'(?:TAX|Tax|tax)[:\s]*\$?(\d+\.\d{2})', detail, re.IGNORECASE)
                        if tax_match:
                            receipt_data['tax'] = float(tax_match.group(1))
                            logger.debug(f"Extracted tax: ${receipt_data['tax']:.2f} from '{detail[:50]}...'")
                        else:
                            # Fallback: try to extract any price in the detail if it contains tax
                            if 'tax' in detail.lower():
                                fallback_tax_match = re.search(r'\$?(\d+\.\d{2})', detail)
                                if fallback_tax_match:
                                    receipt_data['tax'] = float(fallback_tax_match.group(1))
                                    logger.debug(f"Extracted tax (fallback): ${receipt_data['tax']:.2f} from '{detail[:50]}...'")
                    elif 'Store Location' in field or 'Location' in field or 'Store' in field:
                        receipt_data['store_name'] = detail
                        # Extract store number if present (e.g., "LINCOLN PARK #380")
                        store_match = re.search(r'#(\d+)', detail)
                        if store_match:
                            receipt_data['store_number'] = store_match.group(1)
                    elif 'Items Sold' in field or ('Items' in field and 'Sold' in detail):
                        # Try to extract numeric value from detail
                        items_sold_match = re.search(r'(\d+(?:\.\d+)?)', detail)
                        if items_sold_match:
                            try:
                                receipt_data['items_sold'] = float(items_sold_match.group(1))
                                logger.debug(f"Extracted Total Items Sold from Format 1: {receipt_data['items_sold']}")
                            except (ValueError, TypeError):
                                # If conversion fails, store as string (shouldn't happen but be safe)
                                receipt_data['items_sold'] = detail
                        else:
                            # If no number found, store as string
                            receipt_data['items_sold'] = detail
                    elif 'Payment Method' in field or 'Payment' in field:
                        receipt_data['payment_method'] = detail
                    elif 'Receipt Number' in field or 'Receipt #' in field or ('Receipt' in field and 'Number' in detail):
                        receipt_data['receipt_number'] = detail
                    elif 'Member Number' in field or 'Member #' in field or ('Member' in field and 'Number' in detail):
                        receipt_data['member_number'] = detail
        
        # Calculate subtotal from items
        if receipt_data['items']:
            receipt_data['subtotal'] = sum(item.get('total_price', 0) for item in receipt_data['items'])
            
            # For Mariano's orders: Total already includes tax, so don't add tax again
            # Check if vendor is Mariano
            vendor = receipt_data.get('vendor', '').lower()
            is_mariano = 'mariano' in vendor or 'mariano' in excel_path.name.lower()
            
            # If total was extracted from Excel, use it as-is (it already includes tax if present)
            # Only calculate total if it wasn't extracted
            if not receipt_data.get('total'):
                # No total extracted - calculate from subtotal + tax (for non-Mariano orders)
                calculated_total = receipt_data['subtotal']
                if not is_mariano and receipt_data.get('tax', 0) > 0:
                    # For non-Mariano orders, add tax if present
                    calculated_total = receipt_data['subtotal'] + receipt_data['tax']
                receipt_data['total'] = calculated_total
                logger.debug(f"Calculated total: subtotal ${receipt_data['subtotal']:.2f} + tax ${receipt_data.get('tax', 0) if not is_mariano else 0:.2f} = ${receipt_data['total']:.2f}")
            else:
                # Total was extracted from Excel - use it as-is (it already includes tax for Mariano's)
                if is_mariano:
                    logger.debug(f"Using extracted total ${receipt_data['total']:.2f} for Mariano's order (already includes tax, don't add tax to subtotal)")
                else:
                    # For other vendors, verify total matches subtotal + tax
                    expected_total = receipt_data['subtotal'] + receipt_data.get('tax', 0)
                    if abs(receipt_data['total'] - expected_total) > 0.01:
                        # Mismatch - use calculated total
                        receipt_data['total'] = expected_total
                        logger.debug(f"Total mismatch: extracted ${receipt_data.get('total', 0):.2f} vs calculated ${expected_total:.2f}, using calculated")
        
        logger.info(f"Extracted {len(receipt_data['items'])} items from Excel file")
        
        # Apply vendor profiles and other enhancements (same as PDF processing)
        excel_path = Path(excel_path)
        receipt_data = self._apply_new_features(receipt_data, excel_path)
        
        return receipt_data
    
    def process_pdf(self, pdf_path: str) -> Dict:
        """
        Extract text from PDF receipt
        First tries to use CSV file if available (more accurate), then falls back to PDF
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Dictionary containing extracted receipt data
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        logger.info(f"Processing receipt: {pdf_path.name}")
        
        # Try to use CSV file first (more accurate for product items)
        if self.csv_processor:
            receipt_folder = pdf_path.parent
            order_id = self._extract_order_id_from_filename(pdf_path.name)
            
            csv_data = self.csv_processor.process_receipt_with_csv(receipt_folder, order_id)
            if csv_data and csv_data.get('items'):
                logger.info(f"Extracted product items from CSV: {len(csv_data.get('items', []))} items")
                
                # Run unit detection on CSV items (only to improve, not to override valid CSV units)
                # CSV units are authoritative for Instacart orders, so we preserve them
                # First check Size field for UoM if purchase_uom is missing or 'each'
                from step1_extract.csv_processor import derive_uom_from_size
                
                for item in csv_data.get('items', []):
                    current_uom = item.get('purchase_uom', '').lower() if item.get('purchase_uom') else ''
                    size_field = item.get('size', '')
                    
                    # If UoM is missing or 'each', try to derive from Size field
                    if (not current_uom or current_uom == '' or current_uom == 'each') and size_field:
                        derived_uom, extra_fields = derive_uom_from_size(size_field)
                        if derived_uom and derived_uom != 'each':
                            # Found a unit in Size field - use it instead of 'each'
                            item['purchase_uom'] = derived_uom
                            item['unit_confidence'] = 0.9  # High confidence from Size field
                            item.update(extra_fields)  # Merge extra fields like count_per_package
                            logger.debug(f"Derived UoM from Size field for CSV item '{item.get('product_name', '')}': {derived_uom} (size: {size_field})")
                            continue  # Skip to next item, don't run unit detector
                
                # Now run unit detector only if still needed
                if self.unit_detector:
                    for item in csv_data.get('items', []):
                        current_uom = item.get('purchase_uom', '').lower() if item.get('purchase_uom') else ''
                        
                        # Only try to improve if:
                        # 1. Unit is missing/empty (shouldn't happen from CSV, but check anyway)
                        # 2. Unit is 'each' (might be default, could be wrong for weight-based items)
                        # Don't override valid CSV units like 'ct', 'lb', 'gal', etc.
                        if not current_uom or current_uom == '':
                            # Missing unit - try to detect from product name
                            product_name = item.get('product_name', '')
                            line_text = product_name
                            price = item.get('total_price')
                            
                            detected_unit, confidence = self.unit_detector.detect_unit(
                                product_name,
                                line_text,
                                price
                            )
                            
                            if detected_unit and detected_unit != 'unknown':
                                item['purchase_uom'] = detected_unit
                                item['unit_confidence'] = confidence
                                logger.debug(f"Detected missing unit for CSV item '{product_name}': {detected_unit}")
                            else:
                                # If detection failed, check product name for unit words
                                # (CSV might have empty Cost Unit column but name has unit info)
                                product_lower = product_name.lower()
                                unit_from_name = None
                                if 'pint' in product_lower:
                                    unit_from_name = 'pt'
                                elif 'pound' in product_lower or ' lb' in product_lower or product_lower.endswith(' lb'):
                                    unit_from_name = 'lb'
                                elif 'gallon' in product_lower or ' gal' in product_lower or product_lower.endswith(' gal'):
                                    unit_from_name = 'gal'
                                elif 'quart' in product_lower or ' qt' in product_lower or product_lower.endswith(' qt'):
                                    unit_from_name = 'qt'
                                elif 'ounce' in product_lower or ' oz' in product_lower or product_lower.endswith(' oz'):
                                    unit_from_name = 'oz'
                                
                                if unit_from_name:
                                    item['purchase_uom'] = unit_from_name
                                    item['unit_confidence'] = 0.7
                                    logger.debug(f"Extracted unit from product name '{product_name}': {unit_from_name}")
                                else:
                                    # Truly unknown - but this shouldn't happen often with CSV
                                    item['purchase_uom'] = 'unknown'
                                    item['unit_confidence'] = 0.0
                                    logger.warning(f"Could not determine unit for CSV item: '{product_name}'")
                        elif current_uom == 'each':
                            # CSV says 'each' - check if it should be weight-based (milk, fruits, etc.)
                            product_name = item.get('product_name', '')
                            line_text = product_name
                            price = item.get('total_price')
                            
                            detected_unit, confidence = self.unit_detector.detect_unit(
                                product_name,
                                line_text,
                                price
                            )
                            
                            # Only override 'each' if we detect a clearly different unit with high confidence
                            # (like 'gal' for milk, 'lb' for fruits)
                            if detected_unit and detected_unit not in ['each', 'unknown'] and confidence >= 0.7:
                                item['purchase_uom'] = detected_unit
                                item['unit_confidence'] = confidence
                                logger.debug(f"Improved unit for CSV item '{product_name}': {detected_unit} (was: each)")
                            else:
                                # Keep 'each' from CSV (it's probably correct for items like napkins)
                                item['unit_confidence'] = 0.8  # High confidence in CSV data
                        else:
                            # CSV has a valid unit (not 'each') - trust it completely
                            # Just add confidence score
                            item['unit_confidence'] = 0.9  # Very high confidence in CSV data
                
                # Extract fees from PDF (fees are only in PDF, not CSV)
                pdf_text = None
                pdf_total = None
                if self.fee_extractor:
                    pdf_text = self._get_pdf_text(pdf_path)
                    if pdf_text:
                        fees = self.fee_extractor.extract_fees_from_receipt_text(pdf_text)
                        if fees:
                            csv_data = self.fee_extractor.add_fees_to_receipt_items(csv_data, fees)
                            logger.info(f"Extracted {len(fees)} fee items from PDF")
                
                # Calculate total from items + fees
                item_only_items = [item for item in csv_data.get('items', []) if not item.get('is_fee', False)]
                calculated_subtotal = sum(item['total_price'] for item in item_only_items)
                fee_items = [item for item in csv_data.get('items', []) if item.get('is_fee', False)]
                calculated_fees = sum(item['total_price'] for item in fee_items)
                calculated_total = calculated_subtotal + calculated_fees
                
                # Calculate other_charges from fees (bag fee, tips, service fees, but NOT tax)
                if fee_items:
                    calculated_other_charges = sum(item.get('total_price', 0) for item in fee_items)
                    csv_data['other_charges'] = csv_data.get('other_charges', 0.0) + calculated_other_charges
                    logger.debug(f"Calculated other_charges from fees: ${calculated_other_charges:.2f} (total other_charges: ${csv_data['other_charges']:.2f})")
                
                # Remove "Fees Total" summary line if it exists (prevent double counting)
                items = csv_data.get('items', [])
                items_without_fees_total = [
                    item for item in items 
                    if item.get('product_name', '').lower() != 'fees total'
                ]
                
                # Only update if we found and removed a "Fees Total" line
                if len(items_without_fees_total) < len(items):
                    csv_data['items'] = items_without_fees_total
                    logger.debug(f"Removed 'Fees Total' summary line to prevent double counting")
                    # Recalculate after removal
                    item_only_items = [item for item in csv_data['items'] if not item.get('is_fee', False)]
                    fee_items = [item for item in csv_data['items'] if item.get('is_fee', False)]
                    calculated_subtotal = sum(item['total_price'] for item in item_only_items)
                    calculated_fees = sum(item['total_price'] for item in fee_items)
                    calculated_total = calculated_subtotal + calculated_fees
                
                csv_data['subtotal'] = calculated_subtotal
                
                # Validate total amount using order summary CSV and set from CSV baseline
                validation = self.csv_processor.validate_receipt_total(receipt_folder, csv_data, order_id)
                csv_baseline_total = None
                if validation:
                    csv_baseline_total = validation.get('expected_total')
                    if csv_baseline_total is not None:
                        # Set total from CSV baseline (authoritative source)
                        csv_data['total'] = csv_baseline_total
                    else:
                        logger.warning("Could not find expected total in order summary CSV")
                
                # Log validation result
                if validation and csv_baseline_total is not None:
                    if validation.get('matches'):
                        logger.info(f"✓ Total matches CSV baseline: ${csv_data['total']:.2f}")
                    else:
                        logger.info(f"✓ Total set from CSV baseline: ${csv_data['total']:.2f} (calculated was ${calculated_total:.2f})")
                
                # Light validation + fallback flags even for CSV-success path
                csv_data = self._apply_validation_and_review_flagging(csv_data)
                csv_data = self._apply_fallback_rules(csv_data, pdf_path.name)
                return csv_data
        
        # Fallback to PDF processing (if CSV not available)
        logger.info("Extracting from PDF (CSV not available or empty)")
        
        text = self._get_pdf_text(pdf_path)
        if not text:
            # If text extraction completely failed, mark for review
            return {
                'filename': pdf_path.name,
                'vendor': None,
                'items': [],
                'total': 0.0,
                'needs_review': True,
                'review_reasons': ['Failed to extract text from PDF']
            }
        
        # Parse receipt data
        receipt_data = self._parse_receipt_text(text, pdf_path.name, pdf_path)
        
        # Extract vendor name using priority: Option 1 = Receipt text, Option 2 = Filename
        extracted_vendor = None
        source = None
        
        # Option 1: Try to extract from receipt text first (highest priority)
        if receipt_data.get('vendor'):
            extracted_vendor = receipt_data['vendor']
            source = "receipt text"
            logger.debug(f"Found vendor '{extracted_vendor}' in receipt text")
        
        # Also check vendor_info from receipt text extraction
        if not extracted_vendor:
            vendor_info = receipt_data.get('vendor_info', {})
            if vendor_info.get('name'):
                extracted_vendor = vendor_info['name']
                source = "receipt text (vendor_info)"
                logger.debug(f"Found vendor '{extracted_vendor}' from vendor_info in receipt text")
        
        # Option 2: Fallback to filename if not found in receipt text
        if not extracted_vendor and self.vendor_matcher:
            filename_vendor = self.vendor_matcher.extract_vendor_from_filename(pdf_path.name)
            if filename_vendor:
                extracted_vendor = filename_vendor
                source = "filename"
                logger.info(f"Extracted vendor '{extracted_vendor}' from filename (fallback)")
        
        # Match extracted vendor to database
        if extracted_vendor:
            matched_vendor = None
            if self.vendor_matcher:
                # Get normalization info from vendor matcher
                norm_info = self.vendor_matcher.match_vendor(extracted_vendor, return_normalization_info=True)
                if norm_info and isinstance(norm_info, dict):
                    matched_vendor = norm_info.get('normalized_vendor_name')
                    receipt_data['normalized_vendor_name'] = norm_info.get('normalized_vendor_name', extracted_vendor)
                    receipt_data['normalized_by'] = norm_info.get('normalized_by', 'none')
                else:
                    matched_vendor = norm_info if norm_info else extracted_vendor
                    receipt_data['normalized_vendor_name'] = matched_vendor
                    receipt_data['normalized_by'] = 'none'
            
            # In step 1, just use the extracted vendor name (no database matching)
            # Matching to database will happen in step 2 if needed
            receipt_data['vendor'] = extracted_vendor
            logger.debug(f"Using vendor from {source}: '{extracted_vendor}'")
        else:
            logger.warning(f"Could not extract vendor name from receipt text or filename: {pdf_path.name}")
        
        # Extract fees from PDF
        if self.fee_extractor:
            fees = self.fee_extractor.extract_fees_from_receipt_text(text)
            if fees:
                receipt_data = self.fee_extractor.add_fees_to_receipt_items(receipt_data, fees)
                logger.info(f"Extracted {len(fees)} fee items from PDF")
                # Calculate other_charges from fees (bag fee, tips, service fees, but NOT tax)
                fee_items = [item for item in receipt_data['items'] if item.get('is_fee', False)]
                if fee_items:
                    calculated_other_charges = sum(item.get('total_price', 0) for item in fee_items)
                    receipt_data['other_charges'] = receipt_data.get('other_charges', 0.0) + calculated_other_charges
                    logger.debug(f"Calculated other_charges from fees: ${calculated_other_charges:.2f} (total other_charges: ${receipt_data['other_charges']:.2f})")
        
        # Tax-exempt vendor validation: Check against configured list
        # If tax > $1.00, flag for review (may indicate parsing error)
        vendor_name = receipt_data.get('vendor', '').upper()
        tax_exempt_vendors = self.rule_loader.get_tax_exempt_vendors()
        is_tax_exempt = any(keyword in vendor_name for keyword in tax_exempt_vendors)
        
        if is_tax_exempt:
            tax_amount = receipt_data.get('tax', 0.0) or 0.0
            if tax_amount > 1.0:
                if not receipt_data.get('needs_review'):
                    receipt_data['needs_review'] = True
                    receipt_data['review_reasons'] = []
                receipt_data['review_reasons'].append(
                    f"Tax-exempt vendor ({vendor_name}) has tax=${tax_amount:.2f} (expected ~$0.00)"
                )
                logger.warning(f"Tax-exempt vendor {vendor_name} has tax=${tax_amount:.2f}")
        
        return receipt_data
    
    def _get_pdf_text(self, pdf_path: Path) -> Optional[str]:
        """
        Extract text from PDF using direct text extraction (vendor-agnostic).
        
        Returns:
            Extracted text or None if extraction fails
        """
        # Try direct text extraction (vendor-agnostic - all vendors use same extraction)
        if self.text_extractor:
            try:
                text = self.text_extractor.extract_text(pdf_path)
                if text and self._is_good_quality_text(text):
                    logger.info(f"Extracted text using direct extraction ({len(text)} chars)")
                    return text
                elif text:
                    logger.debug(f"Extracted text ({len(text)} chars)")
            except Exception as e:
                logger.debug(f"Direct text extraction failed: {e}")
                text = None
        else:
            # Fallback to old methods if text_extractor not available
            text = None
            if MUPDF_AVAILABLE:
                try:
                    text = self._extract_with_mupdf(pdf_path)
                    if text and self._is_good_quality_text(text):
                        logger.info("Extracted text using PyMuPDF")
                        return text
                except Exception as e:
                    logger.debug(f"PyMuPDF extraction failed: {e}")
            
            if not text and PDF_AVAILABLE:
                try:
                    pdf_text = self._extract_with_pypdf2(pdf_path)
                    if pdf_text and self._is_good_quality_text(pdf_text):
                        logger.info("Extracted text using PyPDF2")
                        return pdf_text
                    text = pdf_text
                except Exception as e:
                    logger.debug(f"PyPDF2 extraction failed: {e}")
        # Return whatever we got (may be None or insufficient)
        return text
    
    def _extract_with_mupdf(self, pdf_path: Path) -> str:
        """Extract text using PyMuPDF"""
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    
    def _extract_with_pypdf2(self, pdf_path: Path) -> str:
        """Extract text using PyPDF2"""
        text = ""
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text()
        return text
    
    def _extract_with_strings(self, pdf_path: Path) -> str:
        """Extract readable text using strings command"""
        import subprocess
        result = subprocess.run(
            ['strings', str(pdf_path)],
            capture_output=True,
            text=True
        )
        return result.stdout
    
    def _is_good_quality_text(self, text: str) -> bool:
        """
        Check if extracted text is of good quality (not binary/scanned)
        
        Args:
            text: Extracted text to check
            
        Returns:
            True if text appears to be good quality, False otherwise
        """
        if not text or len(text.strip()) < 50:
            return False
        
        # Check for binary PDF structure markers (indicates binary extraction, not real text)
        binary_markers = ['%PDF', '/Filter', 'stream', 'endstream', 'obj <<', '/Type /Page']
        binary_count = sum(1 for marker in binary_markers if marker in text[:1000])
        if binary_count >= 3:
            return False
        
        # Check for meaningful content (dates, prices, numbers)
        import re
        has_dates = bool(re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', text) or 
                        re.search(r'[A-Z][a-z]+\s+\d{1,2},\s+\d{4}', text))
        has_prices = bool(re.search(r'\$\d+\.\d{2}|\d+\.\d{2}', text))
        has_meaningful_numbers = len(re.findall(r'\d+', text)) > 10
        
        # Good quality if it has dates/prices OR many numbers
        return has_dates or has_prices or (has_meaningful_numbers and len(text) > 200)
    
    def _parse_receipt_text(self, text: str, filename: str, pdf_path: Path) -> Dict:
        """
        Parse receipt text and extract structured data using advanced parser
        
        Args:
            text: Extracted text from PDF
            filename: Original filename
            
        Returns:
            Dictionary with parsed receipt data
        """
        receipt = {
            'filename': filename,
            'raw_text': text,
            'order_id': None,
            'order_date': None,
            'delivery_date': None,
            'vendor': None,
            'vendor_ref': None,
            'delivery_address': None,
            'currency': 'USD',
            'items': [],
            'subtotal': 0.0,
            'tax': 0.0,
            'total': 0.0,
            'notes': [],
            # Vendor information fields
            'vendor_info': {
                'name': None,
                'store_name': None,
                'store_id': None,
                'store_number': None,
                'address': None,
                'city': None,
                'state': None,
                'zip_code': None,
                'phone': None,
                'website': None,
                'member_number': None,
                'receipt_number': None,
                'other_info': {}
            },
        }
        
        # Extract order ID (Instacart format: 17892079670490780)
        order_id_match = re.search(r'\b\d{17}\b', text)
        if order_id_match:
            receipt['order_id'] = order_id_match.group(0)
            receipt['vendor_ref'] = order_id_match.group(0)
        
        # Extract dates (various formats)
        date_patterns = [
            r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})',
            r'(\w+)\s+(\d{1,2}),\s+(\d{4})',
            r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})',
        ]
        for pattern in date_patterns:
            dates = re.findall(pattern, text)
            if dates:
                # Try to parse first date as order date
                try:
                    date_str = '/'.join(dates[0])
                    receipt['order_date'] = self._parse_date(date_str)
                except:
                    pass
        
        # Identify vendor using rule-based parser (with filename fallback)
        vendor_source = None
        if self.vendor_identifier:
            vendor_name, confidence, source = self.vendor_identifier.identify_vendor(text, filename)
            vendor_source = source
            if vendor_name:
                # Normalize vendor name using vendor_matcher if available
                if self.vendor_matcher:
                    normalized_vendor = self.vendor_matcher._normalize_vendor_name(vendor_name)
                    # Try to match to database vendor
                    # Get normalization info from vendor matcher
                    norm_info = self.vendor_matcher.match_vendor(normalized_vendor, return_normalization_info=True)
                    if norm_info and isinstance(norm_info, dict):
                        matched_vendor = norm_info.get('normalized_vendor_name')
                        receipt['normalized_vendor_name'] = norm_info.get('normalized_vendor_name', normalized_vendor)
                        receipt['normalized_by'] = norm_info.get('normalized_by', 'none')
                    else:
                        matched_vendor = norm_info if norm_info else normalized_vendor
                        receipt['normalized_vendor_name'] = matched_vendor
                        receipt['normalized_by'] = 'none'
                    if matched_vendor:
                        receipt['vendor'] = matched_vendor
                        receipt['vendor_source'] = source
                        logger.debug(f"Identified vendor: {vendor_name} (confidence: {confidence:.2f}, source: {source})")
                    else:
                        receipt['vendor'] = normalized_vendor
                        receipt['vendor_source'] = source
                        logger.debug(f"Identified vendor: {vendor_name} (confidence: {confidence:.2f}, source: {source})")
                else:
                    receipt['vendor'] = vendor_name
                    receipt['vendor_source'] = source
                    logger.debug(f"Identified vendor: {vendor_name} (confidence: {confidence:.2f}, source: {source})")
        
        # Fallback to old vendor extraction if rule-based fails
        if not receipt.get('vendor'):
            vendor_patterns = [
                r'^(ALDI|Costco|Jewel[\s-]?Osco|Jewel Osco|Mariano\'?s?|Park\s+to\s+Shop|RD|R\s*D)',
                r'(ALDI\s+store|Costco\s+(Business|Warehouse)|Jewel[\s-]?Osco|Mariano\'?s?|Park\s+to\s+Shop|RD)',
                r'Order\s+from\s+([A-Za-z\s\-\']+)',
                r'(Store\s*[#:]?\s*\d+.*?([A-Z][A-Za-z\s\-\']+?))',
                r'\b(ALDI|Costco|Jewel[\s-]?Osco|Mariano\'?s?|Park\s+to\s+Shop)\b',
            ]
            for pattern in vendor_patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
                if match:
                    vendor_name = match.group(1) if match.lastindex >= 1 else match.group(0)
                    if match.lastindex >= 2:
                        vendor_name = match.group(2)
                    vendor_name = vendor_name.strip()
                    if self.vendor_matcher:
                        vendor_name = self.vendor_matcher._normalize_vendor_name(vendor_name)
                    receipt['vendor'] = vendor_name
                    receipt['vendor_source'] = 'text'
                    logger.debug(f"Extracted vendor from receipt text (fallback): '{vendor_name}'")
                    break
        
        # Extract delivery address (customer delivery address for Instacart)
        address_pattern = r'(\d+\s+[A-Za-z\s]+(?:Street|Avenue|Road|Lane|Drive|Boulevard)[,\s]*[A-Za-z\s]+\d{5})'
        address_match = re.search(address_pattern, text)
        if address_match:
            receipt['delivery_address'] = address_match.group(1).strip()
        
        # Extract comprehensive vendor information from receipt text
        vendor_info = self._extract_vendor_info(text)
        receipt['vendor_info'] = vendor_info
        if vendor_info.get('name') and not receipt.get('vendor'):
            receipt['vendor'] = vendor_info['name']
        
        # Filter out address lines from all receipts
        try:
            from step1_extract.utils.address_filter import AddressFilter
            address_filter = AddressFilter()
            text = address_filter.filter_text(text)
            logger.debug("Filtered address lines from receipt text")
        except ImportError:
            logger.debug("Address filter not available, skipping address filtering")
        except Exception as e:
            logger.debug(f"Address filter error: {e}, continuing without filtering")
        
        # Get vendor code from receipt (from vendor detection)
        vendor_code = receipt.get('detected_vendor_code')
        items = []
        
        # Try to get matching layout and parse with generic engine
        if vendor_code and self.rule_loader:
            try:
                from step1_extract.layout_applier import LayoutApplier
                from step1_extract.receipt_line_engine import ReceiptLineEngine
                
                # Get matching layout for PDF parsing
                layout_applier = LayoutApplier(self.rule_loader)
                layout = layout_applier.get_matching_layout(vendor_code, pdf_path, text)
                
                if layout:
                    # Use generic receipt line engine to parse with layout
                    engine = ReceiptLineEngine()
                    shared_rules = self.rules if hasattr(self, 'rules') else {}
                    items = engine.parse_receipt_text(text, layout, shared_rules)
                    
                    if items:
                        logger.info(f"Parsed {len(items)} items using layout '{layout.get('name', 'unnamed')}' for vendor {vendor_code}")
                
                # Separate regular items from summary items
                regular_items = [item for item in items if not item.get('is_summary', False)]
                summary_items = [item for item in items if item.get('is_summary', False)]
                if summary_items:
                    logger.info(f"Found {len(summary_items)} summary lines (SUBTOTAL, TAX, TOTAL, etc.)")
                # Store summary items separately for later use (totals extraction)
                receipt['summary_lines'] = summary_items
                # Continue with regular items only
                items = regular_items
                if not items:
                    logger.debug(f"No items extracted using layout for {vendor_code}, falling back to generic parser")
            except Exception as e:
                logger.warning(f"Error parsing with layout for {vendor_code}: {e}, falling back to generic parser")
                # Check if legacy should be used
                if self.rule_loader:
                    legacy_enabled = self.rule_loader.get_legacy_enabled()
                    if legacy_enabled:
                        logger.info(f"[LEGACY] Using legacy parser for: {pdf_path.name} (vendor={vendor_code}, reason=layout error)")
        
        # Extract line items using generic parser (if no layout matched or vendor parser failed)
        if not items:
            lines = text.split('\n')
            items = []
            
            # Merge multiline items if enabled (using rule-based config)
            if self.item_parser:
                # Get multiline config from rules based on vendor_code and layout_name
                multiline_config = None
                if self.rule_loader:
                    # Try to get vendor_code from receipt (may not be set yet for regular parsing)
                    vendor_code = receipt.get('detected_vendor_code') or receipt.get('vendor', '')
                    # Extract layout name from parsed_by field (if set)
                    parsed_by = receipt.get('parsed_by', '')
                    layout_name = None
                    if parsed_by.startswith('layout_'):
                        # Convert "layout_costco_pdf_multiline" to "Costco PDF Multiline"
                        layout_name = parsed_by.replace('layout_', '').replace('_', ' ').title()
                    multiline_config = self.rule_loader.get_multiline_config(vendor_code if vendor_code else None, layout_name)
                lines = self.item_parser.merge_multiline_items(lines, multiline_config=multiline_config)
            
            # Parse each line
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Parse item line using rule-based parser
                item = None
                if self.item_parser:
                    item = self.item_parser.parse_item_line(line)
                
                # If regex parsing failed, try AI interpreter
                if not item and self.ai_interpreter:
                    vendor_name = receipt.get('vendor', '') or receipt.get('vendor_name', '')
                    # Get context from previously parsed items for better AI understanding
                    context = None
                    if items:
                        # Provide sample of successfully parsed items as context
                        sample_items = items[-3:] if len(items) >= 3 else items
                        context = "\n".join([
                            f"- {it.get('product_name', '')}: ${it.get('total_price', 0):.2f}"
                            for it in sample_items
                        ])
                    
                    ai_item = self.ai_interpreter.interpret_line(line, vendor=vendor_name, context=context)
                    if ai_item:
                        item = ai_item
                        logger.debug(f"AI interpreter parsed line: {line[:50]}...")
                
                if item:
                    # Always run unit detection (will use existing if high confidence, otherwise improve)
                    if self.unit_detector:
                        detected_unit, confidence = self.unit_detector.detect_unit(
                            item['product_name'],
                            item['line_text'],
                            item.get('total_price')
                        )
                        # Only override if we got a better detection (not None/unknown, or higher confidence)
                        if detected_unit and detected_unit != 'unknown':
                            # Override even if unit was already set, if we got a detection
                            item['purchase_uom'] = detected_unit
                            item['unit_confidence'] = confidence
                        elif not item.get('purchase_uom') or item.get('purchase_uom') == 'unknown':
                            # Only set if we don't have a unit or it's unknown
                            item['purchase_uom'] = detected_unit or 'unknown'
                            item['unit_confidence'] = confidence
                        else:
                            # Keep existing unit but add confidence if not present
                            if 'unit_confidence' not in item:
                                item['unit_confidence'] = confidence
                    else:
                        # Fallback if no unit detector
                        if not item.get('purchase_uom'):
                            item['purchase_uom'] = 'unknown'
                            item['unit_confidence'] = 0.0
                    
                    items.append(item)
                else:
                    # Fallback to old parsing logic
                    # Check if this is a summary line (subtotal/tax/total) - keep it even if parsing fails
                    line_lower = line.lower()
                    is_summary_line = any(keyword in line_lower for keyword in ['subtotal', 'tax', 'total'])
                    
                    if is_summary_line:
                        # Keep summary lines even if parsing fails - extract price if present
                        price_matches = list(re.finditer(r'\$?(\d+\.\d{2})', line))
                        if price_matches:
                            # Prefer rightmost price
                            rightmost_match = price_matches[-1]
                            price = float(rightmost_match.group(1))
                            
                            # Create summary item
                            summary_item = {
                                'product_name': line.strip(),
                                'quantity': 1.0,
                                'purchase_uom': 'each',
                                'unit_price': price,
                                'total_price': price,
                                'line_text': line,
                                'is_summary': True,
                            }
                            
                            # Determine summary type
                            if 'subtotal' in line_lower:
                                summary_item['summary_type'] = 'subtotal'
                                receipt['subtotal'] = price
                            elif 'tax' in line_lower:
                                summary_item['summary_type'] = 'tax'
                                receipt['tax'] = price
                            elif 'total' in line_lower:
                                summary_item['summary_type'] = 'total'
                                receipt['total'] = price
                            
                            items.append(summary_item)
                        continue  # Skip regular parsing for summary lines
                    
                    # Find price in line (prefer rightmost if multiple)
                    price_matches = list(re.finditer(r'\$?(\d+\.\d{2})', line))
                    if not price_matches:
                        # Skip lines without prices
                        continue
                    
                    # Prefer rightmost price when multiple prices found
                    price_match = price_matches[-1]  # Last match is rightmost
                    price = float(price_match.group(1))
                    
                    # Extract quantity and unit
                    qty_match = re.search(r'(\d+\.?\d*)\s*(lb|each|unit|oz|kg)', line, re.IGNORECASE)
                    if qty_match:
                        quantity = float(qty_match.group(1))
                        uom = qty_match.group(2).lower()
                        product_name = line[:line.find(qty_match.group(0))].strip()
                        product_name = re.sub(r'\$\d+\.\d{2}', '', product_name).strip()
                    else:
                        qty_match = re.search(r'^\s*(\d+\.?\d*)', line)
                        if qty_match:
                            quantity = float(qty_match.group(1))
                            uom = None  # Will be detected by unit detector
                            product_name = line[len(qty_match.group(0)):].strip()
                            product_name = re.sub(r'\$\d+\.\d{2}', '', product_name).strip()
                        else:
                            quantity = 1.0
                            uom = None  # Will be detected by unit detector
                            # Remove price from product name
                            product_name = line[:price_match.start()].strip()
                            if not product_name:
                                # If no product name found, skip this line
                                continue
                    
                    # Calculate unit price
                    unit_price = price / quantity if quantity > 0 else price
                    
                    item = {
                        'product_name': product_name,
                        'quantity': quantity,
                        'purchase_uom': uom,  # May be None, will be detected
                        'unit_price': unit_price,
                        'total_price': price,
                        'line_text': line,
                    }
                # Run unit detection on fallback items too
                if self.unit_detector and not item.get('purchase_uom'):
                    detected_unit, confidence = self.unit_detector.detect_unit(
                        item['product_name'],
                        item['line_text'],
                        item.get('total_price')
                    )
                    item['purchase_uom'] = detected_unit or 'unknown'
                    item['unit_confidence'] = confidence
                elif not item.get('purchase_uom'):
                    item['purchase_uom'] = 'unknown'
                    item['unit_confidence'] = 0.0
                
                items.append(item)
        
        receipt['items'] = items
        
        # Note: Fees will be extracted from PDF separately (not in this method)
        # This method only parses product items from PDF text
        
        # Extract totals using rule-based validator
        if self.total_validator:
            extracted_totals = self.total_validator.extract_totals(text)
            if extracted_totals.get('subtotal'):
                receipt['subtotal'] = extracted_totals['subtotal']
            if extracted_totals.get('tax'):
                receipt['tax'] = extracted_totals['tax']
            if extracted_totals.get('total'):
                receipt['total'] = extracted_totals['total']
        
        # Calculate subtotal (items only, excluding fees)
        item_only_items = [item for item in receipt['items'] if not item.get('is_fee', False)]
        if not receipt['subtotal'] and item_only_items:
            receipt['subtotal'] = sum(item['total_price'] for item in item_only_items)
        
        # Set total if not found (will include fees later)
        if not receipt['total']:
            receipt['total'] = sum(item['total_price'] for item in receipt['items'])
        
        # Validate totals using rule-based validator
        if self.total_validator:
            is_valid, error_msg = self.total_validator.validate_totals(receipt)
            if not is_valid and error_msg:
                receipt['notes'].append(error_msg)
        
        # Apply all new features: Instacart CSV matching, vendor profiles, validation, review flagging
        receipt = self._apply_new_features(receipt, pdf_path)
        
        return receipt
    
    def _apply_new_features(self, receipt: Dict, pdf_path: Path) -> Dict:
        """
        Apply all new features to receipt:
        - Instacart CSV matching
        - Vendor profiles (Costco/Restaurant Depot)
        - Validation and review flagging
        - Fallback rules
        """
        filename = pdf_path.name
        receipt_folder = pdf_path.parent
        
        # 1. Apply Instacart CSV matching if applicable (only for Group 2 / Instacart)
        # Skip CSV matching for Group 1 vendors (from rules)
        vendor = receipt.get('vendor', '')
        vendor_lower = vendor.lower() if vendor else ''
        
        # Skip CSV matching for localgrocery vendors (group1 deprecated - now use vendor-specific PDF rules)
        # Localgrocery vendors: Costco, RD, Jewel, Aldi, Parktoshop (no longer use group1)
        is_group1_vendor = False
        localgrocery_keywords = ['costco', 'restaurant depot', 'restaurantdepot', 'rd', 'jewel', 'aldi', 'parktoshop']
        is_group1_vendor = any(name in vendor_lower for name in localgrocery_keywords)
        
        # Load Instacart CSV matching rules from rule_loader
        instacart_rules = {}
        if self.rule_loader:
            instacart_rules = {'instacart_csv_match': self.rule_loader.get_instacart_csv_match_rules()}
        else:
            instacart_rules = self.rules.get('instacart_csv_match', {})
        
        # Only instantiate and search CSV for Instacart-like vendors to avoid noisy warnings
        if InstacartCSVMatcher and instacart_rules.get('instacart_csv_match', {}).get('enabled', True) and not is_group1_vendor:
            vendor_is_instacart = (vendor_lower.find('instacart') != -1)
            if vendor_is_instacart:
                instacart_matcher = InstacartCSVMatcher(rules=instacart_rules, receipt_folder=receipt_folder, rule_loader=self.rule_loader)
                if instacart_matcher.should_match(filename, vendor=vendor):
                    order_id = receipt.get('order_id') or instacart_matcher.extract_order_id(filename)
                    receipt['items'] = instacart_matcher.match_items(receipt.get('items', []), order_id, vendor=vendor)
            else:
                logger.debug("Skip Instacart CSV matching for vendor '%s'", vendor)
        
        # 2. Apply vendor profiles (Costco/Restaurant Depot)
        vendor = receipt.get('vendor', '')
        vendor_key = None  # Initialize vendor_key for quantity verification
        if self.vendor_profiles:
            if vendor and self.vendor_profiles.should_process(vendor, filename):
                # First, process items with item number lookup (existing logic)
                receipt['items'] = self.vendor_profiles.process_items(vendor, receipt.get('items', []))
                
                # Enrich items by product name search (unified enrichment using cloudscraper)
                vendor_key = self.vendor_profiles._normalize_vendor_key(vendor)
                enriched_items = []
                total_items = len(receipt.get('items', []))
                logger.info(f"Enriching {total_items} items for vendor '{vendor}' (vendor_key: {vendor_key})")
                
                for idx, item in enumerate(receipt['items'], 1):
                    # Enrich by product name if item lacks complete data
                    product_name = item.get('product_name', '')
                    if product_name and vendor_key in ['costco', 'restaurant_depot']:
                        # Check if enrichment is needed (missing size, URL, or price)
                        needs_enrichment = (
                            not item.get('size') or 
                            not item.get('url') or 
                            (vendor_key == 'costco' and not item.get('unit_price'))
                        )
                        
                        if needs_enrichment:
                            # Priority: Use item_number or UPC if available (more accurate than product name search)
                            item_number = item.get('item_number')
                            upc = item.get('upc')
                            
                            logger.debug(f"  [{idx}/{total_items}] Enriching item '{product_name[:50]}...' (item_number: {item_number}, UPC: {upc})")
                            
                            enriched_info = self.vendor_profiles.get_vendor_product_info(
                                vendor, 
                                product_name,
                                force_update=(vendor_key == 'costco'),  # Always fresh for Costco
                                item_number=item_number,  # Use item_number if available
                                upc=upc  # Use UPC if available
                            )
                            
                            if enriched_info:
                                logger.debug(f"  [{idx}/{total_items}] Successfully enriched item '{product_name[:50]}...'")
                                
                                # Store vendor_size and vendor_price (for Costco and RD only)
                                if vendor_key in ['costco', 'restaurant_depot']:
                                    # Store vendor size from enrichment
                                    if enriched_info.get('unit_size'):
                                        item['vendor_size'] = enriched_info.get('unit_size')
                                    
                                    # Store vendor price from enrichment
                                    if vendor_key == 'costco' and enriched_info.get('price'):
                                        price_str = enriched_info.get('price', '').replace('$', '').strip()
                                        if price_str and price_str != 'N/A':
                                            try:
                                                item['vendor_price'] = float(price_str)
                                            except (ValueError, TypeError):
                                                pass
                                    elif vendor_key == 'restaurant_depot' and enriched_info.get('price_total'):
                                        price_str = enriched_info.get('price_total', '').replace('$', '').strip()
                                        if price_str and price_str != 'N/A':
                                            try:
                                                item['vendor_price'] = float(price_str)
                                            except (ValueError, TypeError):
                                                pass
                                
                                # Merge enriched data into item (fallback if not already set)
                                if not item.get('size') and enriched_info.get('unit_size'):
                                    item['size'] = enriched_info.get('unit_size')
                                if not item.get('url') and enriched_info.get('url'):
                                    item['url'] = enriched_info.get('url')
                                if not item.get('product_name') or item.get('product_name') == product_name:
                                    if enriched_info.get('name'):
                                        item['product_name'] = enriched_info.get('name')
                                if enriched_info.get('fetched_at'):
                                    item['enriched_at'] = enriched_info.get('fetched_at')
                                
                                # Update unit_price for Costco from knowledge base (for quantity estimation)
                                if vendor_key == 'costco' and enriched_info.get('unit_price'):
                                    # Use unit_price from knowledge base for quantity estimation
                                    try:
                                        kb_unit_price = float(enriched_info.get('unit_price'))
                                        item['vendor_price'] = kb_unit_price  # Store knowledge base price
                                        # Don't overwrite unit_price yet - let quantity estimation handle it
                                    except (ValueError, TypeError):
                                        pass
                                
                                # For RD: Store vendor_price from knowledge base for reference
                                # But calculate unit_price from total_price / quantity (not from knowledge base)
                                if vendor_key == 'restaurant_depot' and enriched_info.get('price_total'):
                                    price_str = enriched_info.get('price_total', '').replace('$', '').strip()
                                    if price_str != 'N/A':
                                        try:
                                            kb_price = float(price_str)
                                            item['vendor_price'] = kb_price  # Store knowledge base price for reference
                                            # For RD, unit_price should be calculated from total_price / quantity
                                            # Not directly from knowledge base
                                            total_price = item.get('total_price', 0)
                                            quantity = item.get('quantity', 1.0)
                                            if total_price > 0 and quantity > 0:
                                                item['unit_price'] = total_price / quantity
                                                item['price_source'] = 'calculated_from_receipt'
                                        except (ValueError, TypeError):
                                            pass
                            else:
                                logger.warning(f"  [{idx}/{total_items}] Failed to enrich item '{product_name[:50]}...'")
                    
                    enriched_items.append(item)
                
                receipt['items'] = enriched_items
                
                # Normalize item names and derive simple size fields
                for it in receipt.get('items', []):
                    self._normalize_item_fields(it)
                
                # Attempt to resolve missing prices using KB when qty present
                try:
                    from . import vendor_profiles as _vp_mod
                    for it in receipt.get('items', []):
                        q = it.get('quantity') or it.get('qty')
                        u = it.get('unit_price')
                        t = it.get('total_price') or it.get('total')
                        if (u in (None, 0, 0.0)) and (t in (None, 0, 0.0)) and q not in (None, 0, 0.0):
                            sig = {
                                'item_number': it.get('item_number') or '',
                                'upc': it.get('upc') or '',
                                'name': it.get('product_name') or it.get('name') or '',
                            }
                            kb = _vp_mod.lookup_cached_dict(vendor_key, sig)
                            if kb and kb.get('unit_price'):
                                try:
                                    up = float(kb['unit_price'])
                                    it['unit_price'] = up
                                    it['total_price'] = round(float(q) * up, 2)
                                    it['price_status'] = 'price_filled_from_kb'
                                    it['needs_handoff'] = False
                                    it['confidence'] = max(0.7, float(it.get('confidence') or 0.0))
                                except Exception:
                                    pass
                except Exception:
                    pass
                
                # For Costco receipts: Use knowledge base unit_price to estimate quantity for items
                # This must happen AFTER enrichment but BEFORE verification
                if vendor_key == 'costco':
                    for item in receipt.get('items', []):
                        if not item.get('is_fee', False):
                            # Check if we have vendor_price from knowledge base but quantity hasn't been estimated
                            vendor_price = item.get('vendor_price')
                            item_number = item.get('item_number')
                            
                            if vendor_price and item_number and item.get('total_price', 0) > 0:
                                current_qty = item.get('quantity', 1.0)
                                current_unit_price = item.get('unit_price', 0)
                                total_price = item.get('total_price', 0)
                                
                                # Estimate quantity if it's still 1.0 or unit_price equals total_price
                                if current_qty == 1.0 or (current_unit_price > 0 and abs(current_unit_price - total_price) < 0.01):
                                    inferred = self._infer_qty_from_total_decimal(float(vendor_price), float(total_price))
                                    estimated_qty = inferred if inferred is not None else (total_price / vendor_price)
                                    if 0.5 <= estimated_qty <= 100:
                                        item['quantity'] = estimated_qty
                                        item['unit_price'] = float(vendor_price)
                                        item['price_source'] = 'knowledge_base'
                                        if inferred is not None:
                                            item['price_status'] = 'qty_inferred_from_unit'
                                else:
                                    # If unit_price is not 1.0, calculate quantity based on unit_price
                                    item['quantity'] = total_price / current_unit_price
                                    item['price_source'] = 'calculated_from_receipt'
                
                # For Costco: vendor_key is already set from vendor_profiles processing above
                pass  # Continue to quantity verification below
        
        # For Group 1 receipts (Costco, ParkToShop, RD, Jewel-Osco, Aldi, Mariano's, etc.): 
        # Verify calculated quantities against items_sold from receipt (OUTSIDE vendor_profiles block)
        # Normalize vendor name if vendor_profiles didn't process it
        vendor = receipt.get('vendor', '')
        if not vendor_key and vendor:
            vendor_lower = vendor.lower().strip()
            vendor_key = vendor_lower.replace('-', '_').replace(' ', '_')
            # Map common variants
            vendor_key_map = {
                'parktoshop': 'parktoshop',
                'park_to_shop': 'parktoshop',
                'jewel_osco': 'jewel_osco',
                'jewelosco': 'jewel_osco',
                'mariano': 'mariano',
                'marianos': 'mariano',
            }
            vendor_key = vendor_key_map.get(vendor_key, vendor_key)
        
        # Check if this is a Group 1 vendor (Excel-based receipts)
        # group1 deprecated - check for localgrocery vendors directly
        is_group1_vendor = vendor_key and vendor_key in ['costco', 'restaurant_depot', 'parktoshop', 'jewel_osco', 'aldi'] or \
                           receipt.get('source_type') == 'localgrocery_based' or \
                           receipt.get('source_type') == 'excel'
        
        if is_group1_vendor and receipt.get('items_sold'):
                    total_calculated_qty = sum(item.get('quantity', 1.0) for item in receipt.get('items', []) if not item.get('is_fee', False))
                    items_sold = float(receipt.get('items_sold', 0))
                    
                    # Check if quantities match (allow small rounding differences)
                    if abs(total_calculated_qty - items_sold) > 0.5:
                        logger.warning(f"⚠️  Quantity mismatch for {vendor} receipt: calculated total quantity ({total_calculated_qty:.1f}) doesn't match items_sold ({items_sold:.1f})")
                        logger.info(f"   Attempting to adjust quantities to match items_sold...")
                        
                        # Try to adjust quantities while preserving mathematically correct calculations
                        if total_calculated_qty > 0 and items_sold > 0:
                            adjustment_factor = items_sold / total_calculated_qty
                            
                            # Only adjust if factor is reasonable (between 0.5 and 2.0)
                            if 0.5 <= adjustment_factor <= 2.0:
                                # For Costco: identify items with mathematically correct quantities (from knowledge base)
                                # For other vendors: adjust all items proportionally (simpler approach)
                                if vendor_key == 'costco':
                                    # Costco: preserve mathematically correct quantities from knowledge base
                                    protected_items = []
                                    adjustable_items = []
                                    
                                    for item in receipt.get('items', []):
                                        if not item.get('is_fee', False):
                                            vendor_price = item.get('vendor_price')
                                            total_price = item.get('total_price', 0)
                                            
                                            # Calculate what the quantity should be based on prices
                                            if vendor_price and vendor_price > 0 and total_price > 0:
                                                calculated_qty = total_price / vendor_price
                                                current_qty = item.get('quantity', 1.0)
                                                
                                                # If current quantity matches calculated quantity (within 0.01), it's mathematically correct
                                                if abs(calculated_qty - current_qty) < 0.01:
                                                    protected_items.append(item)
                                                    logger.debug(f"   Protecting {item.get('product_name', 'Item')}: qty={current_qty:.1f} (calculated: ${total_price:.2f} / ${vendor_price:.2f} = {calculated_qty:.4f})")
                                                else:
                                                    adjustable_items.append(item)
                                            else:
                                                adjustable_items.append(item)
                                    
                                    # Adjust only the adjustable items to close the gap
                                    if adjustable_items:
                                        protected_total = sum(item.get('quantity', 0) for item in protected_items)
                                        adjustable_total = sum(item.get('quantity', 0) for item in adjustable_items)
                                        target_adjustable = items_sold - protected_total
                                        
                                        if adjustable_total > 0 and target_adjustable > 0:
                                            adjustment_factor_adjustable = target_adjustable / adjustable_total
                                            
                                            for item in adjustable_items:
                                                old_qty = item.get('quantity', 1.0)
                                                new_qty = old_qty * adjustment_factor_adjustable
                                                
                                                # Round to nearest whole number if close, otherwise to nearest 0.5
                                                if abs(new_qty - round(new_qty)) < 0.2:
                                                    new_qty = round(new_qty)  # Prefer whole numbers
                                                else:
                                                    new_qty = round(new_qty * 2) / 2  # Round to 0.5
                                                item['quantity'] = new_qty
                                                
                                                # Keep knowledge base unit_price if available
                                                vendor_price = item.get('vendor_price')
                                                item_number = item.get('item_number')
                                                if vendor_price and item_number:
                                                    item['unit_price'] = float(vendor_price)
                                                    if item.get('price_source') != 'knowledge_base':
                                                        item['price_source'] = 'knowledge_base'
                                                elif item.get('total_price') and new_qty > 0:
                                                    item['unit_price'] = item['total_price'] / new_qty
                                                
                                                logger.debug(f"   Adjusted {item.get('product_name', 'Item')}: {old_qty:.1f} → {new_qty:.1f}")
                                            
                                            logger.info(f"   ✅ Preserved {len(protected_items)} mathematically correct quantities, adjusted {len(adjustable_items)} items")
                                        else:
                                            # Fall back to adjusting all items proportionally
                                            logger.warning(f"   ⚠️  Cannot adjust only adjustable items, adjusting all items proportionally")
                                            adjustment_factor = items_sold / total_calculated_qty
                                            for item in receipt.get('items', []):
                                                if not item.get('is_fee', False):
                                                    old_qty = item.get('quantity', 1.0)
                                                    new_qty = old_qty * adjustment_factor
                                                    
                                                    # Round to nearest whole number if close, otherwise to nearest 0.5
                                                    if abs(new_qty - round(new_qty)) < 0.2:
                                                        new_qty = round(new_qty)  # Prefer whole numbers
                                                    else:
                                                        new_qty = round(new_qty * 2) / 2  # Round to 0.5
                                                    item['quantity'] = new_qty
                                                    
                                                    # Recalculate unit_price
                                                    if item.get('total_price') and new_qty > 0:
                                                        item['unit_price'] = item['total_price'] / new_qty
                                                    
                                                    logger.debug(f"   Adjusted {item.get('product_name', 'Item')}: {old_qty:.1f} → {new_qty:.1f}")
                                            
                                            logger.info(f"   ✅ Adjusted all quantities by factor {adjustment_factor:.3f}")
                                    else:
                                        # All items are protected (mathematically correct) - don't adjust
                                        logger.info(f"   ℹ️  All quantities are mathematically correct, skipping adjustment")
                                else:
                                    # For other Group 1 vendors (ParkToShop, RD, Jewel-Osco, Aldi, Mariano's): 
                                    # Adjust all items proportionally to match items_sold
                                    for item in receipt.get('items', []):
                                        if not item.get('is_fee', False):
                                            old_qty = item.get('quantity', 1.0)
                                            new_qty = old_qty * adjustment_factor
                                            
                                            # Round to nearest whole number if close, otherwise to nearest 0.5
                                            if abs(new_qty - round(new_qty)) < 0.2:
                                                new_qty = round(new_qty)  # Prefer whole numbers
                                            else:
                                                new_qty = round(new_qty * 2) / 2  # Round to 0.5
                                            item['quantity'] = new_qty
                                            
                                            # Recalculate unit_price
                                            if item.get('total_price') and new_qty > 0:
                                                item['unit_price'] = item['total_price'] / new_qty
                                            
                                            logger.debug(f"   Adjusted {item.get('product_name', 'Item')}: {old_qty:.1f} → {new_qty:.1f}")
                                    
                                    logger.info(f"   ✅ Adjusted all quantities by factor {adjustment_factor:.3f}")
                                
                                # Verify after adjustment
                                new_total = sum(item.get('quantity', 1.0) for item in receipt.get('items', []) if not item.get('is_fee', False))
                                logger.info(f"   New total quantity: {new_total:.1f} (target: {items_sold:.1f})")
                            else:
                                logger.warning(f"   ⚠️  Adjustment factor {adjustment_factor:.3f} seems unreasonable, skipping adjustment")
                    else:
                        logger.info(f"✅ Quantity verification passed: calculated total ({total_calculated_qty:.1f}) matches items_sold ({items_sold:.1f})")
        
        # RD aggregation: collapse repeated lines into one (sum qty/total)
        if is_group1_vendor and vendor_key == 'restaurant_depot' and receipt.get('items'):
            receipt['items'] = self._aggregate_duplicate_lines(receipt['items'])
        
        # 3. Apply validation and review flagging
        receipt = self._apply_validation_and_review_flagging(receipt)
        
        # 4. Add verification block (items sold and totals)
        self._add_verification_block(receipt)

        # 5. Apply fallback rules (ensure receipt is never dropped)
        receipt = self._apply_fallback_rules(receipt, filename)
        
        return receipt

    # ---------------- helpers: normalization/aggregation/verification ----------------
    def _normalize_item_fields(self, it: Dict) -> None:
        name = (it.get('product_name') or it.get('name') or '').strip()
        if name:
            # Title case while keeping acronyms
            try:
                t = name.lower().title()
            except Exception:
                t = name
            # Common expansions
            repl = {
                'Basil Leave': 'Basil Leaves',
                'Fz Mozz Stx It Brd': 'Mozzarella Sticks, Breaded',
                'Org': 'Organic',
            }
            for k, v in repl.items():
                if t.startswith(k):
                    t = v + t[len(k):]
            # Extract simple size suffix like " 7LB" or " 32 OZ"
            import re as _re
            m = _re.search(r"\b(\d+(?:\.\d+)?)\s*(LB|LBS|OZ|QT|GAL)\b", name, _re.IGNORECASE)
            if m and not it.get('size'):
                size_qty = m.group(1)
                size_uom = m.group(2).upper().replace('LBS','LB')
                it['size'] = f"{size_qty} {size_uom}"
            it['display_name'] = t
        # Confidence baseline
        qty = float(it.get('quantity') or 0)
        has_prices = (it.get('unit_price') not in (None, 0)) or (it.get('total_price') not in (None, 0))
        it.setdefault('confidence', 0.8 if has_prices and qty > 0 else 0.5)

    def _aggregate_duplicate_lines(self, items: list) -> list:
        from collections import defaultdict
        groups = {}
        def key_fn(it):
            item_no = it.get('item_number') or it.get('upc') or (it.get('product_name') or '').strip().lower()
            unit_price = round(float(it.get('unit_price') or 0.0), 4)
            return (item_no, unit_price)
        counts = defaultdict(int)
        for it in items:
            k = key_fn(it)
            if k in groups:
                base = groups[k]
                base['quantity'] = float(base.get('quantity', 0)) + float(it.get('quantity') or 0)
                base['total_price'] = float(base.get('total_price') or 0) + float(it.get('total_price') or 0)
                counts[k] += 1
            else:
                groups[k] = it.copy()
                counts[k] = 1
        out = []
        for k, it in groups.items():
            collapsed = counts[k]
            if collapsed > 1:
                it['lines_collapsed'] = collapsed
            out.append(it)
        return out

    def _add_verification_block(self, receipt: Dict) -> None:
        items = receipt.get('items', []) or []
        items_sold_declared = receipt.get('items_sold')
        items_sold_calc = sum(float(it.get('quantity') or 0) for it in items if not it.get('is_fee', False))
        sum_lines = sum(float(it.get('total_price') or 0) for it in items if not it.get('is_fee', False))
        fees = sum(float(it.get('total_price') or 0) for it in items if it.get('is_fee', False))
        grand_total_declared = receipt.get('total')
        status = 'unknown'
        try:
            if grand_total_declared is not None:
                status = 'match' if abs((sum_lines + fees) - float(grand_total_declared)) < 0.01 else 'mismatch'
        except Exception:
            status = 'unknown'
        receipt['verification'] = {
            'items_sold_declared': items_sold_declared,
            'items_sold_calc': items_sold_calc,
            'sum_lines': round(sum_lines, 2),
            'fees': round(fees, 2),
            'grand_total_declared': grand_total_declared,
            'status': status,
        }
    
    def _apply_validation_and_review_flagging(self, receipt: Dict) -> Dict:
        """Apply validation and review flagging according to rules"""
        review_reasons = []
        
        # Check vendor confidence (relaxed: don't flag filename-based identification)
        vendor_source = receipt.get('vendor_source', 'unknown')
        if vendor_source == 'unknown':
            # Only flag if truly unknown, not if inferred from filename
            review_reasons.append("Vendor not confidently identified")
        
        # Check items
        items = receipt.get('items', [])
        if not items:
            review_reasons.append("No items recognized")
        
        # Check for items with PDF stream data (relaxed: require 3+ markers instead of 2)
        pdf_markers = ['%PDF', '/Filter', 'stream', 'endstream', 'obj <<', '/Type /Page', 'FlateDecode']
        invalid_items = []
        for item in items:
            product_name = item.get('product_name', '')
            line_text = item.get('line_text', '')
            combined_text = (product_name + ' ' + line_text)[:500]  # Check first 500 chars
            pdf_marker_count = sum(1 for marker in pdf_markers if marker in combined_text)
            if pdf_marker_count >= 3:  # Relaxed: require 3+ markers instead of 2
                invalid_items.append(item.get('product_name', 'Unknown')[:50])
        
        if invalid_items:
            review_reasons.append(f"Items contain PDF stream data (extraction failure): {len(invalid_items)} item(s) - {', '.join(invalid_items[:3])}")
        
        # Check UoM confidence (relaxed: only flag if >80% unknown, was 30%)
        unknown_uom_count = sum(1 for item in items if item.get('purchase_uom') == 'unknown' or item.get('purchase_uom') is None)
        if unknown_uom_count > 0:
            unknown_percentage = (unknown_uom_count / len(items)) * 100 if items else 0
            if unknown_percentage > 80:  # Relaxed: Only flag if >80% unknown (was 30%)
                review_reasons.append(f"UoM unknown on {unknown_percentage:.1f}% of items ({unknown_uom_count}/{len(items)})")
        
        # Check total mismatch
        if self.total_validator:
            is_valid, error_msg = self.total_validator.validate_totals(receipt)
            if not is_valid:
                if self.total_validator.flag_on_mismatch:
                    review_reasons.append(error_msg or "Total mismatch beyond tolerance")
        
        # Flag zero-priced non-fee items as missing price
        zero_priced = [
            it for it in items
            if not it.get('is_fee', False)
            and float(it.get('quantity') or 0) > 0
            and float(it.get('unit_price') or 0) == 0.0
            and float(it.get('total_price') or 0) == 0.0
        ]
        if zero_priced:
            review_reasons.append(f"{len(zero_priced)} non-fee items have missing price")
            for it in zero_priced:
                it['unit_price'] = None
                it['total_price'] = None
                it['needs_review'] = True
                it['price_status'] = 'missing'
                it['needs_handoff'] = True
                it['confidence'] = 0.3
            try:
                import logging as _logging
                _logging.getLogger(__name__).info("Flagged %d non-fee items with missing price (excluded from totals)", len(zero_priced))
            except Exception:
                pass
        
        # Set needs_review flag
        if review_reasons:
            receipt['needs_review'] = True
            receipt['review_reasons'] = review_reasons
        else:
            receipt['needs_review'] = False
            receipt['review_reasons'] = []
        
        return receipt
    
    def _apply_fallback_rules(self, receipt: Dict, filename: str) -> Dict:
        """Apply fallback rules - ensure receipt is never dropped"""
        fallback_config = self.fallback_rules.get('fallbacks', {})
        json_flags = self.fallback_rules.get('json_flags', {})
        
        # Ensure receipt has minimum required fields
        if not receipt.get('filename'):
            receipt['filename'] = filename.strip()
        
        if not receipt.get('vendor'):
            # Try filename fallback
            if fallback_config.get('vendor_from_filename', True) and self.vendor_matcher:
                vendor = self.vendor_matcher.extract_vendor_from_filename(filename)
                if vendor:
                    receipt['vendor'] = vendor.strip()
                    receipt['vendor_source'] = 'filename'
                else:
                    receipt['vendor'] = 'Unknown'
                    receipt['vendor_source'] = 'unknown'
            else:
                receipt['vendor'] = 'Unknown'
                receipt['vendor_source'] = 'unknown'
        
        if not receipt.get('items'):
            receipt['items'] = []
        
        if not receipt.get('total'):
            receipt['total'] = 0.0
        
        return receipt
    
    def _extract_vendor_info(self, text: str) -> Dict:
        """Extract comprehensive vendor information from receipt text
        
        Args:
            text: Receipt text
            
        Returns:
            Dictionary with vendor information
        """
        vendor_info = {
            'name': None,
            'store_name': None,
            'store_id': None,
            'store_number': None,
            'address': None,
            'city': None,
            'state': None,
            'zip_code': None,
            'phone': None,
            'website': None,
            'member_number': None,
            'receipt_number': None,
            'other_info': {}
        }
        
        lines = text.split('\n')
        
        # Extract store/vendor name from first few lines
        for i, line in enumerate(lines[:15]):
            line = line.strip()
            if not line:
                continue
            
            # Store name patterns (ALDI, Costco, etc.)
            # Note: RD is Restaurant Depot
            store_match = re.search(r'^(ALDI|Costco|Jewel[\s-]?Osco|Mariano\'?s?|Park\s+to\s+Shop|RD|R\s*D|Restaurant\s+Depot)', line, re.IGNORECASE)
            if store_match and not vendor_info['name']:
                vendor_info['name'] = store_match.group(1).strip()
                vendor_info['store_name'] = store_match.group(1).strip()
                # Normalize vendor name
                if self.vendor_matcher:
                    vendor_info['name'] = self.vendor_matcher._normalize_vendor_name(vendor_info['name'])
            
            # Store number patterns (e.g., "store #003", "LINCOLN PARK #380")
            store_num_match = re.search(r'(?:store\s*#|#|store\s*number\s*|warehouse\s*#)[:]*\s*(\d+)', line, re.IGNORECASE)
            if store_num_match:
                vendor_info['store_number'] = store_num_match.group(1)
                vendor_info['store_id'] = store_num_match.group(1)
            
            # Store location patterns (e.g., "LINCOLN PARK #380")
            location_match = re.search(r'([A-Z][A-Za-z\s]+)\s*#(\d+)', line)
            if location_match:
                vendor_info['store_name'] = location_match.group(1).strip()
                vendor_info['store_number'] = location_match.group(2)
            
            # Address patterns (e.g., "4900 N. BROADWAY", "2746 N CLYBOURN AVE")
            address_match = re.search(r'(\d+[\s\d]*[NSEW]?[\s.]*[A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Circle|Cir|WAY|PARKWAY))', line, re.IGNORECASE)
            if address_match and not vendor_info['address']:
                vendor_info['address'] = address_match.group(1).strip()
            
            # City, State, ZIP pattern (e.g., "CHICAGO, IL 60614", "Chicago, IL 60640")
            city_state_zip = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', line)
            if city_state_zip:
                vendor_info['city'] = city_state_zip.group(1).strip()
                vendor_info['state'] = city_state_zip.group(2).strip()
                vendor_info['zip_code'] = city_state_zip.group(3).strip()
            
            # Phone number patterns
            phone_match = re.search(r'(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}|\d{3}[-.]?\d{3}[-.]?\d{4})', line)
            if phone_match and not vendor_info['phone']:
                vendor_info['phone'] = phone_match.group(1).strip()
            
            # Website patterns
            website_match = re.search(r'(https?://[^\s]+|[a-zA-Z0-9.-]+\.(?:com|org|net|us|edu))', line, re.IGNORECASE)
            if website_match and not vendor_info['website']:
                vendor_info['website'] = website_match.group(1).strip()
        
        # Extract receipt number (usually long number string, often at top)
        receipt_num_match = re.search(r'\b(\d{15,})\b', text[:500])
        if receipt_num_match:
            vendor_info['receipt_number'] = receipt_num_match.group(1)
        
        # Extract member number (Costco, etc.)
        member_match = re.search(r'(?:Member|Member\s*#|Member\s*Number)[:\s]*(\d+)', text, re.IGNORECASE)
        if member_match:
            vendor_info['member_number'] = member_match.group(1).strip()
        
        # Warehouse/Terminal info (Costco: "Whse: 380", "Trm: 7", "Trn: 221")
        whse_match = re.search(r'(?:Whse|Warehouse)[:\s]*(\d+)', text, re.IGNORECASE)
        if whse_match:
            vendor_info['other_info']['warehouse'] = whse_match.group(1)
        
        term_match = re.search(r'(?:Trm|Terminal)[:\s]*(\d+)', text, re.IGNORECASE)
        if term_match:
            vendor_info['other_info']['terminal'] = term_match.group(1)
        
        transaction_match = re.search(r'(?:Trn|Transaction)[:\s]*(\d+)', text, re.IGNORECASE)
        if transaction_match:
            vendor_info['other_info']['transaction'] = transaction_match.group(1)
        
        return vendor_info
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime object"""
        formats = [
            '%Y-%m-%d',
            '%m/%d/%Y',
            '%d/%m/%Y',
            '%Y/%m/%d',
            '%B %d, %Y',
            '%b %d, %Y',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        return None
    
    def _extract_order_id_from_filename(self, filename: str) -> Optional[str]:
        """Extract order ID from PDF filename"""
        # Filename format: Uni_Uni_Uptown_2025-09-01_17892079670490780.pdf
        match = re.search(r'(\d{17})', filename)
        if match:
            return match.group(1)
        return None
    
    def save_extracted_data(self, receipt_data: Dict, output_path: str):
        """
        Save extracted receipt data to disk.
        - .json  => pretty JSON
        - .jsonl/.ndjson => append one JSON object per line
        - directory path => writes <filename>.json inside the directory
        """
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        
        # If a directory is provided, write as filename.json inside it
        if p.exists() and p.is_dir():
            filename = receipt_data.get('filename', f"receipt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            p = p / (Path(filename).stem + ".json")

        suffix = p.suffix.lower()
        if suffix in ('.jsonl', '.ndjson'):
            with p.open('a', encoding='utf-8') as f:
                f.write(json.dumps(receipt_data, ensure_ascii=False, default=str) + "\n")
        else:
            if suffix == '':
                p = p.with_suffix('.json')
            with p.open('w', encoding='utf-8') as f:
                json.dump(receipt_data, f, ensure_ascii=False, indent=2, default=str)
        
        logger.info(f"Saved extracted data to: {p}")

    # Robust qty inference using Decimal to avoid floating point drift
    def _infer_qty_from_total_decimal(self, unit_price: float, total: float) -> Optional[int]:
        try:
            if unit_price <= 0 or total <= 0:
                return None
            u = Decimal(str(unit_price))
            t = Decimal(str(total))
            ratio = t / u
            q = int(ratio.to_integral_value(rounding=ROUND_HALF_UP))
            abs_eps = Decimal('0.06')
            rel_eps = (t * Decimal('0.02'))
            if rel_eps < abs_eps:
                rel_eps = abs_eps
            def ok(cand: int) -> bool:
                if cand < 1:
                    return False
                return (t - (u * Decimal(cand))).copy_abs() <= rel_eps
            if ok(q):
                return q
            base = int(ratio)
            if ok(base):
                return base
            if ok(base + 1):
                return base + 1
            return None
        except Exception:
            return None

