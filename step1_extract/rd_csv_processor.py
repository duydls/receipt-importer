#!/usr/bin/env python3
"""
RD CSV Processor
Processes Restaurant Depot CSV receipts.

CSV Format:
- Header rows with store info and customer info
- Invoice line: "Invoice: 15011","Terminal: 13","2025/09/02 9:00 am"
- Column headers: UPC,Description,"Unit Qty","Case Qty",Price
- Item rows with UPC, Description, Unit Qty, Case Qty, Price
"""

import logging
import re
import csv
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class RDCSVProcessor:
    """Process Restaurant Depot CSV receipts"""
    
    def __init__(self, rule_loader, input_dir=None):
        """
        Initialize RD CSV processor
        
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
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Process an RD CSV file
        
        Args:
            file_path: Path to CSV file
            detected_vendor_code: Vendor code from detection (optional)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        try:
            receipt_data: Dict[str, Any] = {
                'filename': file_path.name,
                'vendor': 'RD',
                'vendor_name': 'Restaurant Depot',
                'items': [],
                'subtotal': 0.0,
                'tax': 0.0,
                'total': 0.0,
                'currency': 'USD',
                'parsed_by': 'rd_csv_v1',
            }
            
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = list(reader)
            
            # Find invoice line (contains "Invoice:")
            invoice_line_idx = None
            for i, row in enumerate(rows):
                row_str = ','.join(row)
                if 'Invoice:' in row_str:
                    invoice_line_idx = i
                    break
            
            if invoice_line_idx is None:
                logger.warning(f"Could not find invoice line in {file_path.name}")
                return None
            
            # Extract invoice number and date from invoice line
            invoice_line = rows[invoice_line_idx]
            invoice_str = ','.join(invoice_line)
            
            # Extract invoice number: "Invoice: 15011"
            invoice_match = re.search(r'Invoice:\s*(\d+)', invoice_str, re.IGNORECASE)
            if invoice_match:
                receipt_data['receipt_number'] = invoice_match.group(1)
                receipt_data['order_id'] = invoice_match.group(1)
            
            # Extract date: "2025/09/02 9:00 am"
            date_match = re.search(r'(\d{4}/\d{2}/\d{2})\s+(\d+):(\d+)\s*(am|pm)', invoice_str, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(1)
                # Convert "2025/09/02" to "09/02/2025"
                try:
                    parsed_date = datetime.strptime(date_str, '%Y/%m/%d')
                    receipt_data['transaction_date'] = parsed_date.strftime('%m/%d/%Y')
                except ValueError:
                    pass
            
            # Find header row (contains "UPC" and "Description")
            header_line_idx = None
            for i in range(invoice_line_idx + 1, len(rows)):
                row_str = ','.join(rows[i])
                if 'UPC' in row_str and 'Description' in row_str:
                    header_line_idx = i
                    break
            
            if header_line_idx is None:
                logger.warning(f"Could not find header row in {file_path.name}")
                return None
            
            # Parse header row to find column indices
            header_row = rows[header_line_idx]
            upc_idx = None
            desc_idx = None
            unit_qty_idx = None
            case_qty_idx = None
            price_idx = None
            
            for i, col in enumerate(header_row):
                col_upper = col.upper().strip()
                if 'UPC' in col_upper:
                    upc_idx = i
                elif 'DESCRIPTION' in col_upper:
                    desc_idx = i
                elif 'UNIT QTY' in col_upper or 'UNITQTY' in col_upper:
                    unit_qty_idx = i
                elif 'CASE QTY' in col_upper or 'CASEQTY' in col_upper:
                    case_qty_idx = i
                elif 'PRICE' in col_upper:
                    price_idx = i
            
            if upc_idx is None or desc_idx is None or price_idx is None:
                logger.warning(f"Could not find required columns in {file_path.name}")
                return None
            
            # Extract items and totals from rows after header
            for i in range(header_line_idx + 1, len(rows)):
                row = rows[i]
                
                # Skip if row is too short
                if len(row) <= max(upc_idx or 0, desc_idx or 0, price_idx or 0):
                    continue
                
                upc = str(row[upc_idx]).strip() if upc_idx is not None else ''
                description = str(row[desc_idx]).strip() if desc_idx is not None else ''
                price_str = str(row[price_idx]).strip() if price_idx is not None else ''
                
                # Skip header rows or empty rows
                if not description or not price_str:
                    continue
                
                # Check if UPC is positive numeric (valid product)
                upc_is_positive = upc.isdigit() and int(upc) > 0
                
                # If UPC is not positive, this is a summary line (subtotal, tax, total)
                if not upc_is_positive:
                    description_upper = description.upper()
                    price_str_clean = price_str.replace('$', '').replace(',', '').strip()
                    
                    try:
                        price_value = float(price_str_clean)
                        
                        # Extract subtotal (total before tax)
                        # Match "SUB-TOTAL" or "SUBTOTAL" but not "TOTAL" alone
                        if ('SUB-TOTAL' in description_upper or 'SUBTOTAL' in description_upper) and description_upper.strip() != 'TOTAL':
                            if receipt_data.get('subtotal', 0) == 0.0:
                                receipt_data['subtotal'] = price_value
                                logger.debug(f"RD CSV: Extracted subtotal: ${price_value:.2f}")
                        
                        # Extract tax (must have TAX but not SUBTOTAL)
                        elif 'TAX' in description_upper and 'SUBTOTAL' not in description_upper and 'SUB-TOTAL' not in description_upper:
                            if receipt_data.get('tax', 0) == 0.0:
                                receipt_data['tax'] = price_value
                                logger.debug(f"RD CSV: Extracted tax: ${price_value:.2f}")
                        
                        # Extract total (final total) - must have TOTAL but not SUBTOTAL or SUB-TOTAL
                        elif 'TOTAL' in description_upper and 'SUBTOTAL' not in description_upper and 'SUB-TOTAL' not in description_upper:
                            # Could be "TOTAL", "TRANSACTION TOTAL", "FINAL TOTAL", etc.
                            # But not "SUBTOTAL" or "SUB-TOTAL"
                            if receipt_data.get('total', 0) == 0.0:
                                receipt_data['total'] = price_value
                                logger.debug(f"RD CSV: Extracted total: ${price_value:.2f}")
                    except ValueError:
                        pass
                    
                    # Skip summary rows (don't process as items)
                    continue
                
                # Skip summary rows by description (safety check)
                if description.upper() in ['PREVIOUS BALANCE', 'SUBTOTAL', 'TOTAL', 'TAX']:
                    continue
                
                # Parse quantity (use Unit Qty if available, otherwise Case Qty)
                # Default to 1.0 if no quantity specified
                quantity = 1.0
                if unit_qty_idx is not None and unit_qty_idx < len(row):
                    try:
                        qty_str = str(row[unit_qty_idx]).strip()
                        if qty_str and qty_str != '':
                            qty_val = float(qty_str)
                            if qty_val > 0:
                                quantity = qty_val
                    except (ValueError, IndexError):
                        pass
                
                # If Unit Qty is 0 or missing, try Case Qty
                if quantity == 1.0 and case_qty_idx is not None and case_qty_idx < len(row):
                    try:
                        qty_str = str(row[case_qty_idx]).strip()
                        if qty_str and qty_str != '':
                            qty_val = float(qty_str)
                            if qty_val > 0:
                                quantity = qty_val
                    except (ValueError, IndexError):
                        pass
                
                # Parse price (remove $ and commas)
                price_str_clean = price_str.replace('$', '').replace(',', '').strip()
                try:
                    total_price = float(price_str_clean)
                    unit_price = round(total_price / quantity, 2) if quantity > 0 else total_price
                except ValueError:
                    logger.debug(f"Could not parse price: {price_str}")
                    continue
                
                # Extract item number from UPC (last 5-10 digits)
                item_number = None
                if upc and upc.isdigit():
                    # Try to extract item number from UPC (RD format)
                    # Item number is typically 5-10 digits
                    if len(upc) >= 5:
                        item_number = upc[-7:] if len(upc) >= 7 else upc[-5:]
                
                item = {
                    'product_name': description,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': total_price,
                    'upc': upc,
                    'item_number': item_number,
                    'vendor_item_no': item_number,
                    'purchase_uom': 'each',  # Default, will be extracted from description if available
                }
                
                # Extract UoM from description if present (e.g., "10LB", "6/5LB")
                uom_match = re.search(r'(\d+(?:/\d+)?)\s*(LB|LBS|OZ|CT|EACH|EA)', description, re.IGNORECASE)
                if uom_match:
                    size = uom_match.group(1)
                    unit = uom_match.group(2).lower()
                    if unit in ['lb', 'lbs']:
                        item['purchase_uom'] = 'lb'
                        item['size_spec'] = f"{size} lb"
                    elif unit in ['oz', 'ozs']:
                        item['purchase_uom'] = 'oz'
                        item['size_spec'] = f"{size} oz"
                    elif unit in ['ct', 'each', 'ea']:
                        item['purchase_uom'] = 'ct'
                        item['size_spec'] = f"{size} ct"
                
                receipt_data['items'].append(item)
                receipt_data['subtotal'] += total_price
            
            # Enrich with knowledge base (same as Excel processor for RD)
            receipt_data['items'] = self._enrich_rd_items(receipt_data.get('items', []))
            
            # Calculate totals if not extracted from summary lines
            # Prefer extracted subtotal/tax/total from summary lines over calculated values
            if not receipt_data.get('subtotal'):
                receipt_data['subtotal'] = sum(item.get('total_price', 0) for item in receipt_data['items'])
            
            # If total is not set, calculate from subtotal + tax
            if not receipt_data.get('total') and receipt_data.get('subtotal') and receipt_data.get('tax'):
                receipt_data['total'] = round(receipt_data['subtotal'] + receipt_data['tax'], 2)
            
            # Apply date hierarchy
            try:
                from .date_normalizer import apply_date_hierarchy
                receipt_data = apply_date_hierarchy(receipt_data)
            except Exception as e:
                logger.debug(f"Date normalization skipped for RD CSV: {e}")
            
            logger.info(f"Extracted {len(receipt_data['items'])} items from RD CSV {file_path.name}")
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing RD CSV {file_path.name}: {e}", exc_info=True)
            return None
    
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
            upc = str(item.get('upc', '')).strip()
            
            # Try UPC first, then item_number for KB lookup
            kb_entry = None
            kb_key = None
            
            if upc and upc.isdigit():
                kb_entry = kb.get(upc)
                if kb_entry:
                    kb_key = upc
                    logger.debug(f"RD KB: Found entry by UPC: {upc}")
            
            if not kb_entry and item_number:
                kb_entry = kb.get(item_number)
                if kb_entry:
                    kb_key = item_number
                    logger.debug(f"RD KB: Found entry by item_number: {item_number}")
            
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

