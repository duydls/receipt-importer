#!/usr/bin/env python3
"""
WebstaurantStore PDF Processor
Processes WebstaurantStore PDF invoices with tabular item data.
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from decimal import Decimal

logger = logging.getLogger(__name__)


class WebstaurantStorePDFProcessor:
    """Process WebstaurantStore PDF invoices"""
    
    def __init__(self, rule_loader, enable_lookup=False, cache_file=None):
        self.rule_loader = rule_loader
        # Note: WebstaurantStore PDF parser doesn't use layout rules currently
        # It parses directly from PDF text patterns
        
        # Optional: Enable product lookup for category mapping
        self.lookup = None
        if enable_lookup:
            try:
                from .webstaurantstore_lookup import WebstaurantStoreLookup
                self.lookup = WebstaurantStoreLookup(rule_loader, cache_file)
                logger.info("WebstaurantStore product lookup enabled")
            except ImportError:
                logger.warning("WebstaurantStore lookup not available (missing dependencies)")
    
    def process_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Process a WebstaurantStore PDF invoice
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Dictionary containing extracted receipt data
        """
        try:
            # Extract text from PDF
            pdf_text = self._extract_pdf_text(file_path)
            if not pdf_text:
                logger.warning(f"Could not extract text from {file_path.name}")
                return None
            
            # Parse receipt
            receipt_data = self._parse_receipt(pdf_text, file_path)
            
            if receipt_data:
                receipt_data['parsed_by'] = 'webstaurantstore_pdf_v1'
                receipt_data['detected_vendor_code'] = 'WEBSTAURANTSTORE'
                receipt_data['detected_source_type'] = 'webstaurantstore_based'
                receipt_data['source_file'] = str(file_path.name)
                receipt_data['needs_review'] = False
                receipt_data['review_reasons'] = []
                
                # Enrich items with product lookup (if enabled)
                if self.lookup and receipt_data.get('items'):
                    enriched_items = []
                    for item in receipt_data['items']:
                        enriched_item = self.lookup.enrich_item_with_lookup(item)
                        enriched_items.append(enriched_item)
                    receipt_data['items'] = enriched_items
            
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing WebstaurantStore PDF {file_path.name}: {e}", exc_info=True)
            return None
    
    def _extract_pdf_text(self, file_path: Path) -> str:
        """Extract text from PDF using multiple libraries"""
        text = ""
        
        # Try PyPDF2 first
        try:
            import PyPDF2
            with open(file_path, 'rb') as f:
                pdf = PyPDF2.PdfReader(f)
                for page in pdf.pages:
                    text += page.extract_text() + "\n"
            if len(text.strip()) > 100:
                return text
        except Exception as e:
            logger.debug(f"PyPDF2 extraction failed: {e}")
        
        # Try pdfplumber (better for tables)
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            if len(text.strip()) > 100:
                return text
        except Exception as e:
            logger.debug(f"pdfplumber extraction failed: {e}")
        
        # Try PyMuPDF
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            for page_num in range(len(doc)):
                page = doc[page_num]
                text += page.get_text() + "\n"
            doc.close()
        except Exception as e:
            logger.debug(f"PyMuPDF extraction failed: {e}")
        
        return text
    
    def _parse_receipt(self, text: str, file_path: Path) -> Dict[str, Any]:
        """Parse WebstaurantStore receipt from text"""
        # Clean text: remove null characters that sometimes appear in PDF text
        text = text.replace('\x00', '')
        
        receipt_data: Dict[str, Any] = {
            'filename': file_path.name,
            'vendor_name': 'WebstaurantStore',
            'items': [],
            'subtotal': 0.0,
            'shipping': 0.0,
            'tax': 0.0,
            'total': 0.0,
            'currency': 'USD'
        }
        
        # Extract order metadata
        # Pattern: Order Number User ID Date Ordered
        # Example: "Order Number User ID Date Ordered\n115711713 44487427 9/3/2025 at 4:09 PM"
        order_meta_match = re.search(r'Order Number\s+User ID\s+Date Ordered\s+(\d+)\s+(\d+)\s+(\d+/\d+/\d{4})', text)
        if order_meta_match:
            receipt_data['receipt_number'] = order_meta_match.group(1)
            receipt_data['order_id'] = order_meta_match.group(1)
            receipt_data['user_id'] = order_meta_match.group(2)
            receipt_data['transaction_date'] = order_meta_match.group(3)
        else:
            # Fallback: try individual patterns
            order_number_match = re.search(r'Order Number[^\d]*(\d+)', text)
            if order_number_match:
                receipt_data['receipt_number'] = order_number_match.group(1)
                receipt_data['order_id'] = order_number_match.group(1)
            
            user_id_match = re.search(r'User ID[^\d]*(\d+)', text)
            if user_id_match:
                receipt_data['user_id'] = user_id_match.group(1)
            
            date_match = re.search(r'Date Ordered[^\d]*(\d+/\d+/\d{4})', text)
            if date_match:
                receipt_data['transaction_date'] = date_match.group(1)
        
        # Extract items
        items = self._extract_items(text)
        receipt_data['items'] = items
        
        # Extract totals from summary section
        # IMPORTANT: Subtotal in summary is TAX EXCLUDED (sum of unit_price × quantity only)
        subtotal_match = re.search(r'Subtotal:\$([0-9,]+\.\d{2})', text)
        if subtotal_match:
            receipt_data['subtotal'] = float(subtotal_match.group(1).replace(',', ''))
        else:
            # Fallback: calculate from items (unit_price × quantity, tax excluded)
            receipt_data['subtotal'] = sum(float(item.get('unit_price', 0)) * float(item.get('quantity', 0)) for item in items)
        
        shipping_match = re.search(r'Shipping & Handling:\$([0-9,]+\.\d{2})', text)
        if shipping_match:
            receipt_data['shipping'] = float(shipping_match.group(1).replace(',', ''))
        else:
            # Default shipping to 0.0 if not found
            receipt_data['shipping'] = 0.0
            logger.debug("Shipping & Handling not found in PDF, defaulting to $0.00")
        
        # Tax can be "Est. Tax" or "Estimated Tax" (note: PDF may have typo "Esmated Tax")
        # IMPORTANT: Use summary tax as authoritative (may include tax on shipping, not just sum of item taxes)
        # Pattern: "Estimated Tax:$4.60" or "Est. Tax:$4.60" or "Esmated Tax:$3.96"
        tax_patterns = [
            r'Estimated\s+Tax[:\s]+\$([0-9,]+\.\d{2})',  # "Estimated Tax:$4.60"
            r'Esmated\s+Tax[:\s]+\$([0-9,]+\.\d{2})',  # "Esmated Tax:$3.96" (PDF typo)
            r'Es[tm]\.\s*Tax[:\s]+\$([0-9,]+\.\d{2})',  # "Est. Tax:$4.60"
            r'Es[tm]\.?\s*Tax[:\s]+\$([0-9,]+\.\d{2})',  # "Est Tax:$4.60"
        ]
        
        tax_value = None
        for pattern in tax_patterns:
            tax_match = re.search(pattern, text, re.IGNORECASE)
            if tax_match:
                tax_value = float(tax_match.group(1).replace(',', ''))
                break
        
        if tax_value is not None:
            receipt_data['tax'] = tax_value
            logger.debug(f"Extracted summary tax from PDF: ${tax_value:.2f}")
        else:
            # Fallback: sum item taxes if total tax not found
            items_tax_sum = sum(float(item.get('item_tax', 0)) for item in items)
            if items_tax_sum > 0:
                receipt_data['tax'] = items_tax_sum
                logger.warning(f"Total tax not found in PDF summary, using sum of item taxes: ${items_tax_sum:.2f}")
        
        total_match = re.search(r'Total:\$([0-9,]+\.\d{2})', text)
        if total_match:
            receipt_data['total'] = float(total_match.group(1).replace(',', ''))
        
        # Extract payment info
        payment_match = re.search(r'Payment Method:\s+([^-]+)\s+-\s+XXXX(\d+)\s+-\s+\$([0-9,]+\.\d{2})', text)
        if payment_match:
            receipt_data['payment_method'] = payment_match.group(1).strip()
            receipt_data['payment_card_last4'] = payment_match.group(2)
            receipt_data['payment_amount'] = float(payment_match.group(3).replace(',', ''))
        
        # Validate totals
        # IMPORTANT: WebstaurantStore structure:
        # - Subtotal (summary) = sum of (unit_price × quantity) for all items (TAX EXCLUDED)
        # - Tax (summary) = sum of item_tax for all items
        # - Total = subtotal + shipping + tax (TAX INCLUDED)
        
        # 1. Verify subtotal (summary) = sum of (unit_price × quantity) for all items (tax excluded)
        items_subtotal_from_unit = sum(float(item.get('unit_price', 0)) * float(item.get('quantity', 0)) for item in items)
        
        if abs(items_subtotal_from_unit - receipt_data['subtotal']) > 0.02:
            logger.warning(
                f"Subtotal mismatch: items unit×qty sum ${items_subtotal_from_unit:.2f} vs extracted subtotal ${receipt_data['subtotal']:.2f}"
            )
            receipt_data['needs_review'] = True
            if 'review_reasons' not in receipt_data:
                receipt_data['review_reasons'] = []
            receipt_data['review_reasons'].append(
                f'Subtotal mismatch: calculated ${items_subtotal_from_unit:.2f} (sum of unit×qty, tax excluded) vs PDF ${receipt_data["subtotal"]:.2f}'
            )
        
        # 2. Verify sum of item taxes vs total tax (summary)
        # NOTE: Summary tax is authoritative and may include tax on shipping,
        # so it's OK if summary tax differs from sum of item taxes
        items_tax_sum = sum(float(item.get('item_tax', 0)) for item in items)
        if abs(items_tax_sum - receipt_data['tax']) > 0.02:
            logger.debug(
                f"Tax difference: items tax sum ${items_tax_sum:.2f} vs summary tax ${receipt_data['tax']:.2f} "
                f"(difference may be shipping tax)"
            )
            # Don't flag as review - summary tax is authoritative
        
        # 3. Verify grand total: subtotal + shipping + tax = total (tax included)
        calculated_total = receipt_data['subtotal'] + receipt_data['shipping'] + receipt_data['tax']
        if abs(calculated_total - receipt_data['total']) > 0.02:
            receipt_data['needs_review'] = True
            if 'review_reasons' not in receipt_data:
                receipt_data['review_reasons'] = []
            receipt_data['review_reasons'].append(
                f'Total mismatch: calculated ${calculated_total:.2f} (subtotal ${receipt_data["subtotal"]:.2f} + shipping ${receipt_data["shipping"]:.2f} + tax ${receipt_data["tax"]:.2f}) vs PDF ${receipt_data["total"]:.2f}'
            )
        
        # 4. Verify item totals: each item total = (unit_price × quantity) + item_tax
        for item in items:
            unit_price = float(item.get('unit_price', 0))
            quantity = float(item.get('quantity', 0))
            item_tax = float(item.get('item_tax', 0))
            total_price = float(item.get('total_price', 0))
            
            calculated_item_total = (unit_price * quantity) + item_tax
            if abs(calculated_item_total - total_price) > 0.01:
                logger.warning(
                    f"Item {item.get('item_number')}: Total mismatch - "
                    f"calculated ${calculated_item_total:.2f} (${unit_price:.2f} × {quantity} + ${item_tax:.2f}) "
                    f"vs extracted ${total_price:.2f}"
                )
                item['needs_review'] = True
                if 'review_reasons' not in item:
                    item['review_reasons'] = []
                item['review_reasons'].append(
                    f'Item total mismatch: calculated ${calculated_item_total:.2f} vs PDF ${total_price:.2f}'
                )
        
        return receipt_data
    
    def _extract_items(self, text: str) -> List[Dict[str, Any]]:
        """Extract items from WebstaurantStore PDF text"""
        # Clean text: remove null characters
        text = text.replace('\x00', '')
        
        items = []
        
        # Find the item table section
        # Look for "Item Number" header and extract until "Subtotal:"
        table_start = text.find("Item Number")
        if table_start == -1:
            logger.warning("Could not find 'Item Number' header in PDF")
            return items
        
        # Find the end of the table (before "Subtotal:")
        table_end = text.find("Subtotal:", table_start)
        if table_end == -1:
            table_end = len(text)
        
        table_text = text[table_start:table_end]
        
        # Use regex to find all item rows
        # Pattern: ItemNumber (alphanumeric) + Description (until $) + UnitPrice + QTY + Tax + Total
        # Example: "373CH1000 Hydrion CH-1000 Chlorine 0-1000ppm High-Range Sanitizer / Disinfectant Test Strips - 100/Pack$12.96 2 $2.65 $28.57"
        
        # More flexible pattern: item number, description (can span multiple lines), then price fields
        item_pattern = r'^(\S+)\s+(.+?)\$([0-9,]+\.\d{2})\s+(\d+)\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})'
        
        # Split into lines but preserve multi-line context
        lines = table_text.split('\n')
        
        # Find header row
        header_idx = -1
        for i, line in enumerate(lines):
            if 'Item Number' in line and 'Descrip' in line:
                header_idx = i
                break
        
        if header_idx == -1:
            logger.warning("Could not find header row in PDF table")
            return items
        
        # Process item rows (skip header row)
        i = header_idx + 1
        current_description_lines = []
        current_item_number = None
        
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines
            if not line:
                i += 1
                continue
            
            # Stop at totals
            if line.startswith('Subtotal') or line.startswith('Shipping') or line.startswith('Total'):
                break
            
            # FIRST: Try to match single-line item (item number + description + all prices on one line)
            # Pattern: ItemNumber Description... UnitPrice QTY Tax Total
            # Example: "877RE012584 30 lb. IQF Whole Strawberries $61.99 2 $2.79 $126.77"
            single_line_match = re.match(r'^([A-Z0-9]{5,})\s+(.+?)\$([0-9,]+\.\d{2})\s+(\d+)\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})$', line)
            if single_line_match:
                # Found single-line item - extract all data
                item_number = single_line_match.group(1)
                description = single_line_match.group(2).strip()
                unit_price = float(single_line_match.group(3).replace(',', ''))
                quantity = float(single_line_match.group(4))
                item_tax = float(single_line_match.group(5).replace(',', ''))
                total_price_extracted = float(single_line_match.group(6).replace(',', ''))
                
                # Verify total: (unit_price × quantity) + item_tax = total_price
                calculated_total = (unit_price * quantity) + item_tax
                
                # Use calculated total if it matches (within 0.01 tolerance for rounding)
                if abs(calculated_total - total_price_extracted) <= 0.01:
                    total_price = calculated_total
                else:
                    # If mismatch, use extracted but log warning
                    total_price = total_price_extracted
                    logger.warning(
                        f"Item {item_number}: Total mismatch - "
                        f"calculated ${calculated_total:.2f} (${unit_price:.2f} × {quantity} + ${item_tax:.2f}) "
                        f"vs extracted ${total_price_extracted:.2f}"
                    )
                
                # Clean description
                description = re.sub(r'\s+', ' ', description).strip()
                
                # Extract UoM from description
                purchase_uom = None
                raw_uom_text = None
                
                # Look for pack/size patterns
                pack_match = re.search(r'(\d+)/Pack', description, re.IGNORECASE)
                if pack_match:
                    purchase_uom = f"{pack_match.group(1)}-pk"
                    raw_uom_text = f"{pack_match.group(1)}/Pack"
                else:
                    pack_match = re.search(r'(\d+)/Case', description, re.IGNORECASE)
                    if pack_match:
                        purchase_uom = f"{pack_match.group(1)}-cs"
                        raw_uom_text = f"{pack_match.group(1)}/Case"
                    else:
                        pack_match = re.search(r'(\d+)\s*Pack', description, re.IGNORECASE)
                        if pack_match:
                            purchase_uom = f"{pack_match.group(1)}-pk"
                            raw_uom_text = f"{pack_match.group(1)} Pack"
                
                item = {
                    'product_name': description,
                    'item_number': item_number,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': total_price,
                    'item_tax': item_tax,
                    'purchase_uom': purchase_uom,
                    'raw_uom_text': raw_uom_text,
                    'is_fee': False
                }
                
                items.append(item)
                logger.debug(
                    f"Extracted single-line item: {item_number} - {description[:50]}... "
                    f"Qty: {quantity}, Unit: ${unit_price:.2f}, Tax: ${item_tax:.2f}, Total: ${total_price:.2f}"
                )
                
                # Clear accumulated state
                current_description_lines = []
                current_item_number = None
                i += 1
                continue
            
            # SECOND: Check if line starts with item number (alphanumeric code) - multi-line item start
            # Item numbers are typically: digits + optional letters + optional digits
            # Examples: "373CH1000", "381384101CLM"
            item_num_match = re.match(r'^([A-Z0-9]{5,})', line)
            if item_num_match:
                # Line starts with item number - this is the start of a new item
                current_item_number = item_num_match.group(1)
                # Rest of line is start of description
                rest_of_line = line[len(current_item_number):].strip()
                current_description_lines = [rest_of_line] if rest_of_line else []
                i += 1
                continue
            
            # THIRD: Try to match item row pattern (line ending with prices) - multi-line item end
            # Look for line ending with price pattern: $XX.XX number $X.XX $XX.XX
            # Format: Unit Price | QTY | Est. Tax | Total
            # Pattern matches: $12.96 2 $2.65 $28.57
            item_match = re.search(r'\$([0-9,]+\.\d{2})\s+(\d+)\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})$', line)
            
            if item_match:
                # Found end of item row - extract all data
                # Item number should be from previous line(s)
                if not current_item_number:
                    # Try to extract from current line (fallback)
                    rest_of_line = line[:item_match.start()].strip()
                    item_num_match = re.match(r'^([A-Z0-9]{5,})', rest_of_line)
                    if item_num_match:
                        item_number = item_num_match.group(1)
                        description = rest_of_line[len(item_number):].strip()
                    else:
                        logger.warning(f"Could not find item number for line ending with prices: {rest_of_line[:50]}")
                        item_number = "UNKNOWN"
                        description = rest_of_line
                else:
                    # Item number was extracted from previous line
                    item_number = current_item_number
                    # Description continuation is on current line (before prices)
                    description_part = line[:item_match.start()].strip()
                    if description_part:
                        current_description_lines.append(description_part)
                    description = ' '.join(current_description_lines) if current_description_lines else ''
                
                # Clear accumulated description
                current_description_lines = []
                current_item_number = None
                
                unit_price = float(item_match.group(1).replace(',', ''))
                quantity = float(item_match.group(2))
                item_tax = float(item_match.group(3).replace(',', ''))
                total_price_extracted = float(item_match.group(4).replace(',', ''))
                
                # Verify total: (unit_price × quantity) + item_tax = total_price
                calculated_total = (unit_price * quantity) + item_tax
                
                # Use calculated total if it matches (within 0.01 tolerance for rounding)
                if abs(calculated_total - total_price_extracted) <= 0.01:
                    total_price = calculated_total
                else:
                    # If mismatch, use extracted but log warning
                    total_price = total_price_extracted
                    logger.warning(
                        f"Item {item_number}: Total mismatch - "
                        f"calculated ${calculated_total:.2f} (${unit_price:.2f} × {quantity} + ${item_tax:.2f}) "
                        f"vs extracted ${total_price_extracted:.2f}"
                    )
                
                # Clean description
                description = re.sub(r'\s+', ' ', description).strip()
                
                # Extract UoM from description
                purchase_uom = None
                raw_uom_text = None
                
                # Look for pack/size patterns
                pack_match = re.search(r'(\d+)/Pack', description, re.IGNORECASE)
                if pack_match:
                    purchase_uom = f"{pack_match.group(1)}-pk"
                    raw_uom_text = f"{pack_match.group(1)}/Pack"
                else:
                    pack_match = re.search(r'(\d+)/Case', description, re.IGNORECASE)
                    if pack_match:
                        purchase_uom = f"{pack_match.group(1)}-cs"
                        raw_uom_text = f"{pack_match.group(1)}/Case"
                    else:
                        pack_match = re.search(r'(\d+)\s*Pack', description, re.IGNORECASE)
                        if pack_match:
                            purchase_uom = f"{pack_match.group(1)}-pk"
                            raw_uom_text = f"{pack_match.group(1)} Pack"
                
                item = {
                    'product_name': description,
                    'item_number': item_number,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': total_price,
                    'item_tax': item_tax,
                    'purchase_uom': purchase_uom,
                    'raw_uom_text': raw_uom_text,
                    'is_fee': False
                }
                
                items.append(item)
                logger.debug(
                    f"Extracted item: {item_number} - {description[:50]}... "
                    f"Qty: {quantity}, Unit: ${unit_price:.2f}, Tax: ${item_tax:.2f}, Total: ${total_price:.2f}"
                )
            else:
                # Might be continuation of description on next line
                # Check if it looks like description continuation (not a new item, not prices)
                if current_item_number:
                    # We're in the middle of an item - accumulate description
                    if not re.match(r'^\$', line) and not re.match(r'^\S+\s+\$', line):
                        current_description_lines.append(line)
                # If we don't have a current item number, this might be a stray line
                # (but we'll try to handle it when we find the price line)
            
            i += 1
        
        logger.info(f"Extracted {len(items)} items from WebstaurantStore PDF")
        return items

