"""
Amazon CSV Processor
Processes Amazon Orders CSV as the authoritative source for receipt data.
CSV structure: One row per item (multiple rows can have the same Order ID).
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
import pandas as pd

logger = logging.getLogger(__name__)


class AmazonCSVProcessor:
    """
    Process Amazon Orders CSV file (monthly export).
    Treat CSV as authoritative source of truth.
    """
    
    def __init__(self, rule_loader):
        self.rule_loader = rule_loader
        self.amazon_rules = rule_loader.get_amazon_csv_rules() if hasattr(rule_loader, 'get_amazon_csv_rules') else {}
    
    def find_amazon_csv(self, input_dir: Path) -> Optional[Path]:
        """
        Find Amazon CSV file. Supports both input_dir/AMAZON and input_dir/Receipts/AMAZON.
        
        Args:
            input_dir: Base input directory
            
        Returns:
            Path to CSV file or None
        """
        candidate_dirs = [
            input_dir / 'Receipts' / 'AMAZON',
            input_dir / 'AMAZON',
        ]
        for amazon_dir in candidate_dirs:
            if not amazon_dir.exists():
                continue
            # Look for orders_from_*.csv pattern
            csv_files = list(amazon_dir.glob('orders_from_*.csv'))
            if csv_files:
                logger.info(f"Found Amazon CSV: {csv_files[0]}")
                return csv_files[0]
            # Fallback: any CSV in AMAZON folder
            csv_files = list(amazon_dir.glob('*.csv'))
            if csv_files:
                logger.info(f"Found Amazon CSV (fallback): {csv_files[0]}")
                return csv_files[0]
        return None
    
    def load_and_parse_csv(self, csv_path: Path) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load Amazon CSV and group by Order ID.
        
        Args:
            csv_path: Path to Amazon orders CSV
            
        Returns:
            Dict mapping Order ID to list of item rows
        """
        logger.info(f"Loading Amazon CSV: {csv_path.name}")
        
        try:
            # Read CSV with all columns as strings initially
            df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
            
            logger.info(f"Loaded {len(df)} rows from Amazon CSV")
            logger.debug(f"Columns: {list(df.columns)}")
            
            # Check required columns
            required_cols = ['Order ID', 'Title']
            missing = [col for col in required_cols if col not in df.columns]
            if missing:
                logger.error(f"Missing required columns: {missing}")
                return {}
            
            # Group by Order ID
            orders_data = {}
            for order_id, group in df.groupby('Order ID'):
                orders_data[str(order_id)] = group.to_dict('records')
            
            logger.info(f"Grouped into {len(orders_data)} unique orders")
            return orders_data
            
        except Exception as e:
            logger.error(f"Failed to load Amazon CSV: {e}", exc_info=True)
            return {}
    
    def extract_order_id_from_pdf(self, pdf_path: Path) -> Optional[str]:
        """
        Extract Order ID from PDF filename or path.
        Pattern: ###-#######-#######
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Order ID string or None
        """
        # Try filename first
        match = re.search(r'(\d{3}-\d{7}-\d{7})', pdf_path.name)
        if match:
            return match.group(1)
        
        # Try parent folder name
        match = re.search(r'(\d{3}-\d{7}-\d{7})', str(pdf_path.parent.name))
        if match:
            return match.group(1)
        
        return None
    
    def _clean_excel_number(self, value: str) -> str:
        """
        Clean Excel-style quoted numbers like ="98109" → 98109
        
        Args:
            value: String value from CSV
            
        Returns:
            Cleaned string
        """
        if not value:
            return value
        
        # Remove Excel formula quotes: ="..." → ...
        if value.startswith('="') and value.endswith('"'):
            value = value[2:-1]
        
        return value
    
    def _parse_numeric(self, value: str, default: float = 0.0) -> float:
        """
        Parse numeric value from CSV, handling various formats.
        
        Args:
            value: String value
            default: Default value if parsing fails
            
        Returns:
            Float value
        """
        if not value or value.strip() == '':
            return default
        
        try:
            # Remove currency symbols and commas
            cleaned = str(value).replace('$', '').replace(',', '').strip()
            
            # Handle parentheses as negative
            if cleaned.startswith('(') and cleaned.endswith(')'):
                cleaned = '-' + cleaned[1:-1]
            
            return float(cleaned)
        except (ValueError, AttributeError):
            return default
    
    def process_order(
        self, 
        order_id: str, 
        csv_rows: List[Dict[str, Any]],
        pdf_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Process a single order from CSV rows.
        
        Args:
            order_id: Amazon Order ID
            csv_rows: List of CSV row dicts for this order
            pdf_path: Optional PDF file for validation
            
        Returns:
            Receipt data dictionary
        """
        if not csv_rows:
            return None
        
        # Get order metadata from first row (same across all rows for an order)
        first_row = csv_rows[0]
        
        # Extract order metadata
        order_date = first_row.get('Order Date', '')
        shipment_date = first_row.get('Shipment Date', '')
        order_status = first_row.get('Order Status', '')
        seller = first_row.get('Seller Name', '')
        seller_city = first_row.get('Seller City', '')
        seller_state = first_row.get('Seller State', '')
        seller_zip = self._clean_excel_number(first_row.get('Seller ZipCode', ''))
        buyer_name = first_row.get('Account User', '')
        buyer_email = first_row.get('Account User Email', '')
        
        # Initialize receipt data
        receipt_data = {
            'order_id': order_id,
            'vendor': 'Amazon Business',
            'vendor_code': 'AMAZON',
            'order_date': order_date,
            'shipment_date': shipment_date,
            'order_status': order_status,
            'seller': seller,
            'seller_location': f"{seller_city}, {seller_state} {seller_zip}".strip(),
            'buyer_name': buyer_name,
            'buyer_email': buyer_email,
            'source_type': 'amazon_based',
            'source_group': 'amazon_based',
            'parsed_by': 'amazon_csv_v1',
            'items': [],
            'needs_review': False,
            'review_reasons': []
        }
        
        # Process items
        items = []
        for row in csv_rows:
            item = self._process_item_row(row, receipt_data)
            if item:
                items.append(item)
        
        receipt_data['items'] = items
        
        # Aggregate order-level charges into fees
        fees = self._aggregate_fees(csv_rows)
        if fees:
            receipt_data['items'].extend(fees)
        
        # Calculate totals from CSV
        csv_totals = self._calculate_csv_totals(csv_rows)
        receipt_data['subtotal'] = csv_totals['subtotal']
        receipt_data['tax'] = csv_totals['tax']
        receipt_data['total'] = csv_totals['total']
        receipt_data['csv_total'] = csv_totals['total']  # Store CSV total separately
        
        # PDF validation (if available)
        if pdf_path and pdf_path.exists():
            self._validate_with_pdf(receipt_data, pdf_path)
        
        # Final validation
        self._validate_order(receipt_data)
        
        return receipt_data
    
    def _process_item_row(self, row: Dict[str, Any], receipt_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process a single CSV row into an item dict.
        
        Args:
            row: CSV row dict
            receipt_data: Receipt data (for adding review reasons)
            
        Returns:
            Item dict or None
        """
        title = row.get('Title', '').strip()
        if not title:
            return None
        
        # Extract item fields
        asin = row.get('ASIN', '').strip()
        quantity = self._parse_numeric(row.get('Item Quantity', ''), default=0.0)
        unit_price = self._parse_numeric(row.get('Purchase PPU', ''), default=0.0)
        item_subtotal = self._parse_numeric(row.get('Item Subtotal', ''), default=0.0)
        item_tax = self._parse_numeric(row.get('Item Tax', ''), default=0.0)
        item_total = self._parse_numeric(row.get('Item Net Total', ''), default=0.0)
        
        # Calculate line_total (prefer Item Subtotal, then calculate from unit × qty)
        if item_subtotal != 0:
            line_total = item_subtotal
        elif unit_price != 0 and quantity > 0:
            line_total = round(unit_price * quantity, 2)
        else:
            line_total = 0.0
            receipt_data['needs_review'] = True
            if 'Missing item subtotal and unable to calculate' not in receipt_data['review_reasons']:
                receipt_data['review_reasons'].append('Missing item subtotal and unable to calculate')
        
        # Back-compute unit_price if missing
        if unit_price == 0 and line_total != 0 and quantity > 0:
            unit_price = round(line_total / quantity, 4)
        
        # Build item dict
        item = {
            'product_name': title,
            'quantity': quantity,
            'unit_price': unit_price,
            'total_price': line_total,
            'external_id': asin,  # ASIN
            'item_tax': item_tax,
            'item_net_total': item_total,
            'parsed_by': 'amazon_csv_v1'
        }
        
        # Add optional fields
        brand = row.get('Brand', '').strip()
        if brand:
            item['brand'] = brand
        
        manufacturer = row.get('Manufacturer', '').strip()
        if manufacturer:
            item['manufacturer'] = manufacturer
        
        category = row.get('Amazon-Internal Product Category', '').strip()
        if category:
            item['category'] = category
        
        # Add UNSPSC taxonomy fields for better classification
        segment = row.get('Segment', '').strip()
        if segment:
            item['unspsc_segment'] = segment
        
        family = row.get('Family', '').strip()
        if family:
            item['unspsc_family'] = family
        
        commodity = row.get('Commodity', '').strip()
        if commodity:
            item['unspsc_commodity'] = commodity
        
        # UoM extraction (will be done later by UoM extractor)
        item['raw_uom_text'] = None
        
        return item
    
    def _aggregate_fees(self, csv_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aggregate order-level charges into fee items.
        
        Args:
            csv_rows: List of CSV rows for this order
            
        Returns:
            List of fee item dicts
        """
        # Aggregate fees across all rows (they should be the same per order, but sum to be safe)
        fee_fields = {
            'Shipping Charges': 'Shipping',
            'Shipping Tax': 'Shipping Tax',
            'Item Subtotal Tax': 'Item Tax',
            'Gift Wrap': 'Gift Wrap',
            'Gift Wrap Tax': 'Gift Wrap Tax',
            'Item Promotions': 'Promotions',
            'Ship Promotion Discount': 'Ship Promotion Discount',
            'Handling': 'Handling',
            'Recycling Fee': 'Recycling Fee',
            'Postal Fee': 'Postal Fee',
            'Other Fee': 'Other Fee'
        }
        
        fee_totals = {}
        for field, label in fee_fields.items():
            total = sum(self._parse_numeric(row.get(field, ''), default=0.0) for row in csv_rows)
            if total != 0:  # Only include non-zero fees
                fee_totals[label] = total
        
        # Convert to fee items
        fees = []
        for label, amount in fee_totals.items():
            fee = {
                'product_name': label,
                'quantity': 1.0,
                'unit_price': amount,
                'total_price': amount,
                'is_fee': True,
                'parsed_by': 'amazon_csv_v1'
            }
            fees.append(fee)
        
        return fees
    
    def _calculate_csv_totals(self, csv_rows: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Calculate order totals from CSV data.
        
        Args:
            csv_rows: List of CSV rows for this order
            
        Returns:
            Dict with subtotal, tax, total
        """
        # Sum item subtotals
        subtotal = sum(self._parse_numeric(row.get('Item Subtotal', ''), default=0.0) for row in csv_rows)
        
        # Sum all taxes
        item_tax = sum(self._parse_numeric(row.get('Item Subtotal Tax', ''), default=0.0) for row in csv_rows)
        shipping_tax = sum(self._parse_numeric(row.get('Shipping Tax', ''), default=0.0) for row in csv_rows)
        gift_wrap_tax = sum(self._parse_numeric(row.get('Gift Wrap Tax', ''), default=0.0) for row in csv_rows)
        total_tax = item_tax + shipping_tax + gift_wrap_tax
        
        # Sum all charges
        shipping = sum(self._parse_numeric(row.get('Shipping Charges', ''), default=0.0) for row in csv_rows)
        gift_wrap = sum(self._parse_numeric(row.get('Gift Wrap', ''), default=0.0) for row in csv_rows)
        handling = sum(self._parse_numeric(row.get('Handling', ''), default=0.0) for row in csv_rows)
        recycling = sum(self._parse_numeric(row.get('Recycling Fee', ''), default=0.0) for row in csv_rows)
        postal = sum(self._parse_numeric(row.get('Postal Fee', ''), default=0.0) for row in csv_rows)
        other = sum(self._parse_numeric(row.get('Other Fee', ''), default=0.0) for row in csv_rows)
        
        # Sum promotions/discounts (these are negative)
        item_promos = sum(self._parse_numeric(row.get('Item Promotions', ''), default=0.0) for row in csv_rows)
        ship_promos = sum(self._parse_numeric(row.get('Ship Promotion Discount', ''), default=0.0) for row in csv_rows)
        
        # Calculate grand total
        total = subtotal + total_tax + shipping + gift_wrap + handling + recycling + postal + other + item_promos + ship_promos
        
        return {
            'subtotal': round(subtotal, 2),
            'tax': round(total_tax, 2),
            'total': round(total, 2)
        }
    
    def _validate_with_pdf(self, receipt_data: Dict[str, Any], pdf_path: Path):
        """
        Validate CSV data against PDF (if available).
        Extract Order ID and grand total from PDF for comparison.
        
        Args:
            receipt_data: Receipt data dict (modified in place)
            pdf_path: Path to PDF file
        """
        try:
            import PyPDF2
            
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ''
                for page in reader.pages:
                    text += page.extract_text()
            
            # Extract Order ID from PDF
            order_id_match = re.search(r'Order #?(\d{3}-\d{7}-\d{7})', text, re.IGNORECASE)
            if order_id_match:
                pdf_order_id = order_id_match.group(1)
                if pdf_order_id != receipt_data['order_id']:
                    receipt_data['needs_review'] = True
                    receipt_data['review_reasons'].append(f'PDF Order ID mismatch: {pdf_order_id} vs {receipt_data["order_id"]}')
            
            # Extract grand total from PDF
            total_patterns = [
                r'Grand Total:\s*\$?([\d,]+\.?\d*)',
                r'Total for This Shipment:\s*\$?([\d,]+\.?\d*)',
                r'Order Total:\s*\$?([\d,]+\.?\d*)'
            ]
            
            pdf_total = None
            for pattern in total_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    pdf_total = self._parse_numeric(match.group(1))
                    break
            
            if pdf_total is not None:
                receipt_data['pdf_total'] = pdf_total
                csv_total = receipt_data.get('csv_total', 0.0)
                
                # Compare totals (allow 1 cent tolerance)
                diff = abs(pdf_total - csv_total)
                if diff > 0.01:
                    receipt_data['needs_review'] = True
                    receipt_data['review_reasons'].append(f'PDF total mismatch: PDF ${pdf_total:.2f} vs CSV ${csv_total:.2f}')
        
        except Exception as e:
            logger.warning(f"Failed to validate with PDF {pdf_path.name}: {e}")
    
    def _validate_order(self, receipt_data: Dict[str, Any]):
        """
        Final validation checks on the order.
        
        Args:
            receipt_data: Receipt data dict (modified in place)
        """
        items = [item for item in receipt_data['items'] if not item.get('is_fee')]
        
        # Check for missing UoM
        missing_uom_count = sum(1 for item in items if not item.get('raw_uom_text') and not item.get('uom'))
        if missing_uom_count > 0:
            pct = (missing_uom_count / len(items) * 100) if items else 0
            receipt_data['review_reasons'].append(f'UoM unknown on {pct:.1f}% of items ({missing_uom_count}/{len(items)})')
        
        # Check for missing prices
        missing_price_count = sum(1 for item in items if item.get('unit_price', 0) == 0 and not item.get('is_fee'))
        if missing_price_count > 0:
            receipt_data['needs_review'] = True
            receipt_data['review_reasons'].append(f'{missing_price_count} non-fee items have missing price')
        
        # Check for zero quantities
        zero_qty_count = sum(1 for item in items if item.get('quantity', 0) == 0)
        if zero_qty_count > 0:
            receipt_data['needs_review'] = True
            receipt_data['review_reasons'].append(f'{zero_qty_count} items have zero quantity')

