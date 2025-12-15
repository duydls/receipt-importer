#!/usr/bin/env python3
"""
Generate SQL INSERT statements for creating purchase orders in Odoo database
Uses Step 1 extracted data with product matching already done
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def format_sql_value(value) -> str:
    """Format a value for SQL INSERT"""
    if value is None or value == '' or value == '\\N':
        return 'NULL'
    elif isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, str):
        # Escape single quotes
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    else:
        # Convert to string and escape
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"


def get_uom_id_by_name(conn, uom_name: str) -> Optional[int]:
    """Get UoM ID from Odoo database by name"""
    if not uom_name:
        return None
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Try exact match first
            cur.execute("""
                SELECT id FROM uom_uom 
                WHERE name->>'en_US' = %s 
                LIMIT 1
            """, (uom_name,))
            result = cur.fetchone()
            if result:
                return result['id']
            
            # Try case-insensitive match
            cur.execute("""
                SELECT id FROM uom_uom 
                WHERE LOWER(name->>'en_US') = LOWER(%s)
                LIMIT 1
            """, (uom_name,))
            result = cur.fetchone()
            if result:
                return result['id']
            
            return None
    except Exception as e:
        print(f"Error looking up UoM '{uom_name}': {e}")
        return None


def get_product_product_id(conn, product_id: int) -> Optional[int]:
    """Convert product_template ID to product_product ID, or return product_product ID if already one
    
    Returns the product_product ID to use in purchase_order_line.product_id
    """
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # First try as product_product ID
            cur.execute("""
                SELECT pp.id as product_id
                FROM product_product pp
                WHERE pp.id = %s
                LIMIT 1
            """, (product_id,))
            result = cur.fetchone()
            if result:
                return result['product_id']
            
            # If not found, try as product_template ID
            cur.execute("""
                SELECT pp.id as product_id
                FROM product_template pt
                LEFT JOIN product_product pp ON pp.product_tmpl_id = pt.id
                WHERE pt.id = %s
                ORDER BY pp.id
                LIMIT 1
            """, (product_id,))
            result = cur.fetchone()
            if result and result['product_id']:
                return result['product_id']
            
            return None
    except Exception as e:
        print(f"Error getting product_product ID for {product_id}: {e}")
        return None


def get_product_default_uom(conn, product_id: int) -> Optional[Dict]:
    """Get product's default UoM ID, name, and category from database
    
    Handles both product_product IDs and product_template IDs.
    If product_id is a template ID, finds the corresponding product_product.
    """
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # First try as product_product ID
            cur.execute("""
                SELECT 
                    pt.uom_id as default_uom_id,
                    uom.name->>'en_US' as default_uom_name,
                    uom.category_id as default_uom_category_id,
                    uom.factor as default_uom_factor
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                WHERE pp.id = %s
                LIMIT 1
            """, (product_id,))
            result = cur.fetchone()
            
            if result:
                return {
                    'uom_id': result['default_uom_id'],
                    'uom_name': result['default_uom_name'],
                    'category_id': result['default_uom_category_id'],
                    'factor': result['default_uom_factor'] or 1.0
                }
            
            # If not found, try as product_template ID
            cur.execute("""
                SELECT 
                    pt.uom_id as default_uom_id,
                    uom.name->>'en_US' as default_uom_name,
                    uom.category_id as default_uom_category_id,
                    uom.factor as default_uom_factor
                FROM product_template pt
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                WHERE pt.id = %s
                LIMIT 1
            """, (product_id,))
            result = cur.fetchone()
            
            if result:
                return {
                    'uom_id': result['default_uom_id'],
                    'uom_name': result['default_uom_name'],
                    'category_id': result['default_uom_category_id'],
                    'factor': result['default_uom_factor'] or 1.0
                }
            
            return None
    except Exception as e:
        print(f"Error getting product default UoM for product {product_id}: {e}")
        return None


def get_uom_info(conn, uom_id: int) -> Optional[Dict]:
    """Get UoM information including category"""
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    id,
                    name->>'en_US' as uom_name,
                    category_id,
                    factor
                FROM uom_uom
                WHERE id = %s
                LIMIT 1
            """, (uom_id,))
            result = cur.fetchone()
            if result:
                return {
                    'uom_id': result['id'],
                    'uom_name': result['uom_name'],
                    'category_id': result['category_id'],
                    'factor': result['factor'] or 1.0
                }
            return None
    except Exception as e:
        print(f"Error getting UoM info for UoM {uom_id}: {e}")
        return None


def convert_uom_quantity(quantity: float, from_uom_factor: float, to_uom_factor: float) -> float:
    """
    Convert quantity from one UoM to another using factors.
    
    In Odoo, factor means: 1 reference unit = factor × this UoM
    So: 1 of this UoM = 1/factor reference units
    
    To convert FROM purchase UoM TO product default UoM:
    1. Convert to reference: qty / from_factor
    2. Convert from reference: (qty / from_factor) × to_factor
    """
    if from_uom_factor == 0 or to_uom_factor == 0:
        return quantity
    
    # Convert to reference unit, then to target UoM
    # If factor is 0.0833, it means 1 reference = 0.0833 of this UoM
    # So 1 of this UoM = 1/0.0833 reference units
    # Convert Decimal to float if needed (from database)
    from_factor = float(from_uom_factor) if from_uom_factor else 0.0
    to_factor = float(to_uom_factor) if to_uom_factor else 0.0
    
    ref_quantity = quantity / from_factor if from_factor != 0 else quantity
    converted_quantity = ref_quantity * to_factor if to_factor != 0 else ref_quantity
    
    return converted_quantity


# Global variable to track IDs within a single run
_last_used_id = {}

def get_next_id(conn, table_name: str, check_sql_files: bool = True) -> int:
    """Get next available ID for a table
    
    Args:
        conn: Database connection
        table_name: Table name (e.g., 'purchase_order')
        check_sql_files: If True, also check existing SQL files for allocated IDs
    
    Returns:
        Next available ID
    """
    max_id = 0
    
    # First, check database
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT MAX(id) FROM {table_name}")
            result = cur.fetchone()
            if result[0]:
                max_id = max(max_id, result[0])
    except Exception as e:
        print(f"Warning: Could not query database for MAX(id): {e}")
    
    # Also check existing SQL files to avoid reusing IDs
    if check_sql_files and table_name == 'purchase_order':
        sql_dir = Path('data/sql')
        if sql_dir.exists():
            import re
            for sql_file in sql_dir.glob('purchase_order_*.sql'):
                if '_rollback' not in sql_file.name:
                    try:
                        with open(sql_file, 'r', encoding='utf-8') as f:
                            content = f.read()
                            # Find PO ID in purchase_order INSERT statement
                            # Pattern: INSERT INTO purchase_order ... SELECT\n    (\d+),\n    id,  -- partner_id
                            # We need to match only purchase_order, not purchase_order_line
                            # Stop at the semicolon to avoid matching purchase_order_line
                            po_match = re.search(
                                r"INSERT INTO purchase_order[^;]*?SELECT\s+(\d+),\s*\n\s*id,\s*-- partner_id[^;]*?;",
                                content,
                                re.MULTILINE | re.DOTALL
                            )
                            if po_match:
                                po_id = int(po_match.group(1))
                                # Only accept reasonable IDs (less than 1000 to avoid line IDs)
                                # Purchase order IDs should be small integers, line IDs are typically po_id * 1000 + sequence
                                if po_id < 1000:
                                    max_id = max(max_id, po_id)
                    except Exception as e:
                        # Skip files that can't be read
                        pass
    
    next_id = max_id + 1
    
    # Track IDs within a single run to ensure sequential assignment
    global _last_used_id
    if table_name in _last_used_id:
        if next_id <= _last_used_id[table_name]:
            next_id = _last_used_id[table_name] + 1
    _last_used_id[table_name] = next_id
    
    return next_id


def parse_date(date_str: str, receipt_id: str = None) -> Optional[datetime]:
    """Parse date string to datetime. Returns None if cannot parse (caller should handle)."""
    # Helper function to extract date from receipt_id
    def extract_date_from_receipt_id(rid: str) -> Optional[datetime]:
        if not rid:
            return None
        import re
        # Look for YYYYMMDD pattern in receipt_id
        date_match = re.search(r'(\d{8})', rid)
        if date_match:
            date_str = date_match.group(1)
            # Convert YYYYMMDD to YYYY-MM-DD
            try:
                formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                return datetime.strptime(formatted_date, '%Y-%m-%d')
            except ValueError:
                pass
        return None
    
    # If date_str is empty or just a single digit (invalid), try receipt_id
    if not date_str or (len(date_str.strip()) <= 1 and date_str.strip().isdigit()):
        if receipt_id:
            extracted = extract_date_from_receipt_id(receipt_id)
            if extracted:
                return extracted
        return None
    
    # Try various formats
    formats = [
        '%Y-%m-%dT%H:%M:%S',  # ISO format: 2025-10-04T21:55:00
        '%Y-%m-%d %H:%M:%S',   # Standard: 2025-10-04 21:55:00
        '%m/%d/%y',            # MM/DD/YY: 10/21/25
        '%m/%d/%Y',            # MM/DD/YYYY: 10/21/2025
        '%Y-%m-%d',            # Date only: 2025-10-04
        '%m/%d/%Y',            # US format: 10/04/2025
        '%m/%d/%Y %H:%M:%S',   # US format with time: 10/04/2025 21:55:00
        '%Y-%m-%dT%H:%M:%S.%f',  # ISO with microseconds
        '%Y-%m-%dT%H:%M:%SZ',  # ISO with Z
        '%Y%m%d',              # YYYYMMDD format: 20251001
        '%B %d, %Y',           # Full month name: November 3, 2025
        '%b %d, %Y',           # Abbreviated month: Nov 3, 2025
        '%B %d %Y',            # Full month name without comma: November 3 2025
        '%b %d %Y',            # Abbreviated month without comma: Nov 3 2025
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    
    # Handle month-only dates (e.g., "October", "Oct")
    month_names = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    
    date_lower = date_str.lower().strip()
    if date_lower in month_names:
        # Use current year and 1st of the month as default
        current_year = datetime.now().year
        month = month_names[date_lower]
        return datetime(current_year, month, 1)
    
    # If all formats fail, try to extract date part only
    # Handle cases like "2025-10-04T21:55:00" where T separator might cause issues
    try:
        # Extract just the date part before 'T' or space
        date_part = date_str.split('T')[0].split(' ')[0]
        return datetime.strptime(date_part, '%Y-%m-%d')
    except (ValueError, IndexError):
        pass
    
    # Try to extract date from receipt_id if provided
    if receipt_id:
        import re
        # Look for YYYYMMDD pattern in receipt_id
        date_match = re.search(r'(\d{8})', receipt_id)
        if date_match:
            date_str_from_id = date_match.group(1)
            try:
                formatted_date = f"{date_str_from_id[:4]}-{date_str_from_id[4:6]}-{date_str_from_id[6:8]}"
                return datetime.strptime(formatted_date, '%Y-%m-%d')
            except ValueError:
                pass
    
    return None  # Return None instead of datetime.now() - caller must handle


def infer_uom_from_cost(
    conn,
    product_id: int,
    receipt_unit_price: float,
    receipt_total_price: float,
    receipt_quantity: float,
    tolerance: float = 0.15  # 15% tolerance for price matching
) -> Optional[Dict]:
    """
    Infer the correct UoM for a BBI product by comparing receipt unit price 
    to historical purchase prices in Odoo database.
    
    Args:
        conn: Database connection
        product_id: Product ID (product_product ID)
        receipt_unit_price: Unit price from receipt
        receipt_total_price: Total price from receipt
        receipt_quantity: Quantity from receipt
        tolerance: Price matching tolerance (default 15%)
    
    Returns:
        Dict with 'uom_id', 'uom_name', 'quantity', 'unit_price' if match found, None otherwise
    """
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query historical purchase prices for this product with different UoMs
            query = """
                SELECT 
                    pol.product_uom,
                    uom.name->>'en_US' as uom_name,
                    pol.product_qty,
                    pol.product_uom_qty,
                    pol.price_unit,
                    pol.price_subtotal,
                    po.date_order,
                    COUNT(*) OVER (PARTITION BY pol.product_uom) as purchase_count
                FROM purchase_order_line pol
                JOIN purchase_order po ON pol.order_id = po.id
                JOIN uom_uom uom ON pol.product_uom = uom.id
                WHERE pol.product_id = %s
                  AND pol.state IN ('purchase', 'done')
                  AND pol.price_unit > 0
                  AND pol.product_qty > 0
                  AND po.date_order >= '2024-01-01'  -- Recent orders only
                ORDER BY po.date_order DESC
                LIMIT 50
            """
            
            cur.execute(query, (product_id,))
            historical_purchases = cur.fetchall()
            
            if not historical_purchases:
                return None
            
            # Group by UoM and calculate average unit price per UoM
            uom_prices = {}
            for purchase in historical_purchases:
                uom_id = purchase['product_uom']
                uom_name = purchase['uom_name']
                
                # Calculate effective unit price
                # If product_uom_qty != product_qty, there's a UoM conversion
                qty = float(purchase['product_qty'])
                uom_qty = float(purchase['product_uom_qty']) if purchase['product_uom_qty'] else qty
                price_unit = float(purchase['price_unit'])
                
                # Effective unit price in the purchase UoM
                if uom_qty > 0:
                    effective_unit_price = price_unit * (qty / uom_qty) if qty != uom_qty else price_unit
                else:
                    effective_unit_price = price_unit
                
                if uom_id not in uom_prices:
                    uom_prices[uom_id] = {
                        'uom_id': uom_id,
                        'uom_name': uom_name,
                        'prices': [],
                        'purchase_count': 0
                    }
                
                uom_prices[uom_id]['prices'].append(effective_unit_price)
                uom_prices[uom_id]['purchase_count'] = purchase['purchase_count']
            
            # Calculate average price for each UoM and find best match
            best_match = None
            best_score = float('inf')
            
            for uom_id, uom_data in uom_prices.items():
                prices = uom_data['prices']
                if not prices:
                    continue
                
                avg_price = sum(prices) / len(prices)
                min_price = min(prices)
                max_price = max(prices)
                
                # Calculate price difference ratio
                price_diff_ratio = abs(receipt_unit_price - avg_price) / avg_price if avg_price > 0 else float('inf')
                
                # Score based on price match (lower is better)
                # Also consider purchase count (more purchases = more reliable)
                score = price_diff_ratio / (1 + uom_data['purchase_count'] * 0.1)
                
                if price_diff_ratio <= tolerance and score < best_score:
                    best_match = {
                        'uom_id': uom_id,
                        'uom_name': uom_data['uom_name'],
                        'avg_price': avg_price,
                        'min_price': min_price,
                        'max_price': max_price,
                        'price_diff_ratio': price_diff_ratio,
                        'purchase_count': uom_data['purchase_count'],
                        'quantity': receipt_quantity,  # Keep original quantity
                        'unit_price': receipt_unit_price
                    }
                    best_score = score
            
            if best_match:
                print(f"  💰 Price-based UoM inference: {best_match['uom_name']} (avg: ${best_match['avg_price']:.2f}, receipt: ${receipt_unit_price:.2f}, diff: {best_match['price_diff_ratio']*100:.1f}%)")
            
            return best_match
            
    except Exception as e:
        print(f"  ⚠️  Error inferring UoM from cost: {e}")
        return None


def generate_purchase_order_sql(
    receipt_id: str,
    receipt_data: Dict,
    po_id: int,
    conn
) -> Tuple[str, str]:
    """
    Generate SQL INSERT statement for purchase_order
    
    Returns:
        (sql, vendor_name, is_instacart_order) tuple
    """
    # Check if this is a BBI order
    is_bbi_order = (
        receipt_data.get('vendor', '').upper() in ['BBI', 'BOBA BARON INC', 'BOBA BARON'] or
        receipt_data.get('detected_vendor_code', '').upper() == 'BBI' or
        receipt_data.get('detected_source_type', '').lower() == 'bbi_based' or
        'UNI_' in str(receipt_id).upper()
    )
    
    # Initialize is_instacart_order
    is_instacart_order = False
    
    # For BBI orders, ALWAYS use "BOBA BARON INC" as vendor
    if is_bbi_order:
        vendor_name = "BOBA BARON INC"
    else:
        # For Instacart orders, use vendor (IC-Costco) instead of store_name (Costco)
        # This ensures we match the correct IC- prefixed partner in the database
        is_instacart_order = receipt_data.get('source_type') == 'instacart_based' or receipt_data.get('source_group') == 'instacart_based'
        vendor_name = receipt_data.get('vendor', 'Unknown Vendor')
    
    # For BBI orders, ALWAYS use Oct 30, 2025 for all dates
    if is_bbi_order:
        order_date_str = "2025-10-30"
        date_order = "2025-10-30 00:00:00"
        date_planned = "2025-10-30 00:00:00"
    else:
        # Parse order date - use receipt date, not today's date
        order_date_str = (
            receipt_data.get('transaction_date') or 
            receipt_data.get('order_date') or 
            receipt_data.get('delivery_date') or  # Fallback to delivery date if order date not available
            receipt_data.get('date', '')
        )
        order_date = parse_date(order_date_str, receipt_id)
        if not order_date:
            raise ValueError(f"Cannot parse date from receipt {receipt_id}. Available date fields: transaction_date={receipt_data.get('transaction_date')}, order_date={receipt_data.get('order_date')}, delivery_date={receipt_data.get('delivery_date')}, date={receipt_data.get('date')}")
        date_order = order_date.strftime('%Y-%m-%d %H:%M:%S')
        date_planned = date_order
    
    # Calculate totals
    total = float(receipt_data.get('total', 0.0))
    tax = float(receipt_data.get('tax', 0.0))
    shipping = float(receipt_data.get('shipping', 0.0))
    amount_untaxed = total - tax - shipping
    amount_tax = tax
    amount_total = total
    
    # Generate order name (use receipt_id or generate)
    order_name = receipt_data.get('order_id') or receipt_data.get('receipt_number') or f"P{po_id:05d}"
    partner_ref = receipt_data.get('order_id') or receipt_data.get('receipt_number') or receipt_id
    
    create_date = date_planned  # Use date_planned instead of current date
    write_date = date_planned    # Use date_planned instead of current date
    effective_date = date_planned  # Order deadline - same as expected arrival date
    
    sql = f"""-- ================================================
-- Purchase Order: {order_name}
-- Receipt ID: {receipt_id}
-- Vendor: {vendor_name}
-- Date: {date_order}
-- Total: ${amount_total:.2f}
-- ================================================

-- Look up vendor/partner ID by name
-- Vendor Name: {vendor_name}
INSERT INTO purchase_order (
    id, partner_id, dest_address_id, currency_id, invoice_count, 
    fiscal_position_id, payment_term_id, incoterm_id, user_id, company_id, 
    create_uid, write_uid, access_token, name, priority, origin, partner_ref, 
    state, invoice_status, notes, amount_untaxed, amount_tax, amount_total, 
    amount_total_cc, currency_rate, mail_reminder_confirmed, mail_reception_confirmed, 
    mail_reception_declined, date_order, date_approve, date_planned, 
    date_calendar_start, create_date, write_date, picking_type_id, group_id, 
    incoterm_location, receipt_status, effective_date
)
SELECT 
    {po_id}, 
    id,  -- partner_id from res_partner lookup
    NULL,  -- dest_address_id
    1,  -- currency_id (USD)
    0,  -- invoice_count
    NULL,  -- fiscal_position_id
    NULL,  -- payment_term_id
    NULL,  -- incoterm_id
    2,  -- user_id (admin)
    1,  -- company_id
    2,  -- create_uid (admin)
    2,  -- write_uid (admin)
    NULL,  -- access_token
    {format_sql_value(order_name)},  -- name
    0,  -- priority
    NULL,  -- origin
    {format_sql_value(partner_ref)},  -- partner_ref
    'draft',  -- state
    'no',  -- invoice_status
    NULL,  -- notes
    {amount_untaxed},  -- amount_untaxed
    {amount_tax},  -- amount_tax
    {amount_total},  -- amount_total
    {amount_total},  -- amount_total_cc
    1.0,  -- currency_rate
    FALSE,  -- mail_reminder_confirmed
    FALSE,  -- mail_reception_confirmed
    NULL,  -- mail_reception_declined
    {format_sql_value(date_order)},  -- date_order
    NULL,  -- date_approve
    {format_sql_value(date_planned)},  -- date_planned (expected arrival)
    {format_sql_value(date_planned)},  -- date_calendar_start
    {format_sql_value(create_date)},  -- create_date
    {format_sql_value(write_date)},  -- write_date
    1,  -- picking_type_id
    NULL,  -- group_id
    NULL,  -- incoterm_location
    NULL,  -- receipt_status
    {format_sql_value(effective_date)}  -- effective_date (order deadline)
FROM res_partner 
WHERE (name = {format_sql_value(vendor_name)} 
   OR name ILIKE {format_sql_value(f'%{vendor_name}%')}
   OR name ILIKE {format_sql_value(f'%Restaurant Depot%')}  -- RD abbreviation expansion
   OR {format_sql_value(vendor_name)} LIKE CONCAT('%', name, '%'))"""
    
    # Add IC- exclusion for non-Instacart orders
    if not is_instacart_order:
        sql += "\n   AND name NOT LIKE 'IC-%'  -- Exclude IC- prefixed vendors for non-Instacart orders"
    
    sql += f"""
ORDER BY 
    CASE WHEN name = {format_sql_value(vendor_name)} THEN 1 
         WHEN name ILIKE {format_sql_value(f'%{vendor_name}%')} THEN 2
         WHEN name ILIKE '%Restaurant Depot%' THEN 2  -- Restaurant Depot matches
         WHEN {format_sql_value(vendor_name)} LIKE CONCAT('%', name, '%') THEN 3
         ELSE 4 END,
    name
LIMIT 1;
"""
    
    return sql, vendor_name, is_instacart_order, date_planned


def generate_purchase_order_line_sql(
    item: Dict,
    po_line_id: int,
    po_id: int,
    sequence: int,
    vendor_name: str,
    conn,
    receipt_data: Dict,
    receipt_id: str = None,
    is_instacart_order: bool = False,
    price_tax: float = 0.0,
    tax_id: Optional[int] = None
) -> Optional[str]:
    """
    Generate SQL INSERT statement for purchase_order_line
    
    Returns:
        SQL string or None if product_id is missing
    """
    # Get product ID from matched product (may be template ID or product_product ID)
    product_id_raw = item.get('odoo_product_id')
    if not product_id_raw:
        print(f"  ⚠️  Skipping item: No Odoo product ID found")
        return None
    
    # Convert to product_product ID if needed (purchase_order_line.product_id must be product_product ID)
    product_product_id = get_product_product_id(conn, product_id_raw)
    if not product_product_id:
        print(f"  ⚠️  Skipping item: Could not find product_product ID for {product_id_raw}")
        return None
    
    # Use product_product_id for SQL, but use original ID for UoM lookup (works with both)
    product_id = product_product_id
    
    # Get product's default UoM from database (can use template ID or product_product ID)
    product_default_uom = get_product_default_uom(conn, product_id_raw)
    if not product_default_uom:
        print(f"  ⚠️  Skipping item: Could not get product default UoM for product {product_id_raw}")
        return None
    
    default_uom_id = product_default_uom['uom_id']
    default_uom_name = product_default_uom['uom_name']
    default_uom_category_id = product_default_uom['category_id']
    default_uom_factor = product_default_uom['factor']
    
    # Check if this is a BBI order - use cost-based UoM inference
    is_bbi_order = (
        receipt_data.get('vendor', '').upper() in ['BBI', 'BOBA BARON INC', 'BOBA BARON'] or
        receipt_data.get('detected_vendor_code', '').upper() == 'BBI' or
        receipt_data.get('detected_source_type', '').lower() == 'bbi_based' or
        'UNI_' in str(receipt_id).upper()
    )
    
    # For BBI orders, try to infer UoM from historical purchase prices
    inferred_uom = None
    if is_bbi_order:
        receipt_unit_price = float(item.get('unit_price', 0))
        receipt_total_price = float(item.get('total_price', 0))
        receipt_quantity = float(item.get('quantity', 1))
        
        if receipt_unit_price > 0:
            inferred_uom = infer_uom_from_cost(
                conn, product_id, receipt_unit_price, 
                receipt_total_price, receipt_quantity
            )
            
            if inferred_uom:
                # Use inferred UoM - override purchase_uom
                purchase_uom_id_override = inferred_uom['uom_id']
                purchase_uom_name_override = inferred_uom['uom_name']
                print(f"  ✓ Using price-inferred UoM: {purchase_uom_name_override}")
    
    # Get purchase UoM from receipt
    purchase_uom = item.get('purchase_uom') or item.get('unit_uom', 'Units')
    unit_size = item.get('unit_size')
    unit_uom = item.get('unit_uom', '')
    
    # Check if purchase_uom is actually a volume/weight unit but quantity is in units
    # This happens when receipt says "fl_oz" but quantity is actually units (e.g., 2 units × 64 fl oz each)
    # OR when we have a size-specific UoM like "35-lb" where quantity is in units
    is_unit_based_purchase = False
    if purchase_uom in ['fl_oz', 'oz', 'lb', 'gal', 'qt', 'pt', 'ml', 'l'] and unit_size and unit_size > 1:
        # If unit_size is significantly larger than 1 (e.g., 35, 64), it's likely a size-specific UoM
        # Example: quantity=4, unit_size=35, purchase_uom="lb" means 4 units × 35 lb = 140 lb
        # But if unit_size is close to 1 (e.g., 0.33, 1.0), quantity might already be in that unit
        if unit_size >= 5:  # Large unit_size (35, 64, etc.) indicates quantity is in units
            is_unit_based_purchase = True
        elif purchase_uom == unit_uom and unit_size < 2:
            # Small unit_size (0.33, 1.0) with matching UoMs means quantity is already in that unit
            # Example: quantity=6.15, unit_size=0.33, purchase_uom="lb" means 6.15 lb total
            is_unit_based_purchase = False
        else:
            # UoMs don't match, quantity is likely in units
            is_unit_based_purchase = True
    
    # Check for fl oz pattern BEFORE normalizing (especially for "each" + unit_size + unit_uom)
    fl_oz_pattern = None
    fl_oz_number = None
    if unit_size and unit_uom and unit_uom.lower() in ['oz', 'fl_oz', 'fl oz']:
        # Construct fl oz UoM from unit_size and unit_uom
        # Example: unit_size=64.0, unit_uom="oz" -> "64 -fl oz(US)"
        fl_oz_number = str(int(unit_size)) if unit_size == int(unit_size) else str(unit_size)
        fl_oz_pattern = f"{fl_oz_number} fl oz"
    
    # Normalize purchase UoM name (handle cases like "dozen" -> "Dozens", "50-pc" -> "50-pc")
    purchase_uom_name = purchase_uom
    if purchase_uom == 'dozen':
        purchase_uom_name = 'Dozens'
    elif purchase_uom == 'unit' or purchase_uom == 'each':
        # Only normalize to "Units" if we don't have a fl oz pattern
        if not fl_oz_pattern:
            purchase_uom_name = 'Units'
        else:
            # Keep as "each" temporarily, we'll use the fl oz UoM instead
            purchase_uom_name = purchase_uom
    elif unit_size and purchase_uom in ['pc', 'lb']:
        # Format as "X-pc" or "X-lb" if size is available
        # BUT: if purchase_uom == unit_uom AND unit_size is small (< 2), quantity is already in that unit
        # If unit_size is large (>= 5), it's a size-specific UoM and we should format it
        if purchase_uom == unit_uom and unit_size < 2:
            # Quantity is already in the purchase UoM (e.g., 6.15 lb with unit_size 0.33), keep original UoM name
            purchase_uom_name = purchase_uom
        elif isinstance(unit_size, float) and unit_size.is_integer():
            purchase_uom_name = f"{int(unit_size)}-{purchase_uom}"
        else:
            purchase_uom_name = f"{unit_size}-{purchase_uom}"
    
    # Also check for fl oz patterns in purchase_uom_name itself
    if 'fl' in purchase_uom_name.lower() and 'oz' in purchase_uom_name.lower():
        # Try to extract number from patterns like "64 fl oz", "64-fl-oz", etc.
        fl_oz_match = re.search(r'(\d+(?:\.\d+)?)\s*[- ]?\s*fl\s*[- ]?\s*oz', purchase_uom_name.lower())
        if fl_oz_match:
            fl_oz_pattern = fl_oz_match.group(0)  # Keep original case/spacing
            fl_oz_number = fl_oz_match.group(1)
    
    # Try to extract size from purchase UoM name (e.g., "1500-pc" -> 1500, "3-lb" -> 3)
    # Also handle complex formats like "6*3-kg" (6 bags × 3kg each = 18kg per pack)
    size_from_uom = None
    base_uom_from_compound = None
    
    # First check for multiplication format: "6*3-kg", "20*1-kg", etc.
    mult_match = re.match(r'(\d+(?:\.\d+)?)\s*\*\s*(\d+(?:\.\d+)?)\s*-\s*(kg|g|lb|oz|pc|ct)', purchase_uom_name.lower())
    if mult_match:
        count = float(mult_match.group(1))  # e.g., 6 bags
        size = float(mult_match.group(2))    # e.g., 3kg per bag
        unit = mult_match.group(3)          # e.g., kg
        # Calculate total: 6 * 3 = 18kg per pack
        total_size = count * size
        size_from_uom = total_size
        base_uom_from_compound = unit
        # Update purchase_uom_name to the calculated total (e.g., "18-kg")
        purchase_uom_name = f"{int(total_size) if total_size.is_integer() else total_size}-{unit}"
    
    # Then check for simple compound format: "1500-pc" -> 1500, "3-lb" -> 3
    if not mult_match:
        uom_match = re.match(r'(\d+(?:\.\d+)?)\s*-\s*(pc|lb|pound|pounds|kg|g|oz)', purchase_uom_name.lower())
        if uom_match:
            size_from_uom = float(uom_match.group(1))
            base_uom_from_compound = uom_match.group(2)
            if base_uom_from_compound in ['pound', 'pounds']:
                base_uom_from_compound = 'lb'
    
    # fl_oz_pattern and fl_oz_number are now set above before normalization
    
    # Get purchase UoM ID and info from database
    # IMPORTANT: First try the compound UoM as-is (e.g., "3-lb", "2-lb", "2-pc")
    # If it exists in the database, we should use it with quantity 1, not convert to base unit
    
    # For BBI orders, prioritize inferred UoM from cost comparison
    # If inferred UoM found, use it directly and skip normal UoM processing
    use_inferred_uom = False
    if inferred_uom:
        purchase_uom_id = inferred_uom['uom_id']
        purchase_uom_name = inferred_uom['uom_name']
        purchase_uom_info = get_uom_info(conn, purchase_uom_id)
        use_inferred_uom = True
        print(f"  ✓ Using price-inferred UoM: {purchase_uom_name} (ID: {purchase_uom_id})")
    else:
        purchase_uom_id = get_uom_id_by_name(conn, purchase_uom_name)
        purchase_uom_info = None
    
    # If compound UoM not found, try variations (especially for fl oz)
    if not purchase_uom_id and fl_oz_pattern and fl_oz_number:
        # Try variations like "64 -fl oz(US)", "64-fl-oz", etc.
        number = fl_oz_number
        variations = [
            f"{number} -fl oz(US)",  # "64 -fl oz(US)" - matches database format (ID 67)
            f"{number}-fl oz(US)",
            f"{number} fl oz(US)",
            f"{number} fl oz",
            f"{number}-fl-oz",
        ]
        # Also try variations from purchase_uom_name if it contains fl oz
        if 'fl' in purchase_uom_name.lower() and 'oz' in purchase_uom_name.lower():
            variations.extend([
                purchase_uom_name.replace('fl oz', '-fl oz(US)'),
                purchase_uom_name.replace('fl oz', ' -fl oz(US)'),
                purchase_uom_name.replace('fl_oz', '-fl oz(US)'),
            ])
        for var in variations:
            purchase_uom_id = get_uom_id_by_name(conn, var)
            if purchase_uom_id:
                purchase_uom_name = var  # Update to match database name
                break
    
    # If still not found and we have a compound UoM, try base UoM
    if not purchase_uom_id and base_uom_from_compound:
        purchase_uom_id = get_uom_id_by_name(conn, base_uom_from_compound)
    
    if purchase_uom_id:
        purchase_uom_info = get_uom_info(conn, purchase_uom_id)
    
    # Determine which UoM to use: check if purchase UoM is in same category as product default UoM
    use_uom_id = default_uom_id
    use_uom_name = default_uom_name
    use_uom_factor = default_uom_factor
    conversion_applied = False
    
    # IMPORTANT: Preserve original quantity BEFORE any conversions for unit_price calculation
    original_quantity_for_price = float(item.get('quantity', 1.0))
    original_quantity = float(item.get('quantity', 1.0))
    
    # If we have an inferred UoM from cost comparison (BBI orders), use it directly
    if use_inferred_uom and inferred_uom:
        use_uom_id = inferred_uom['uom_id']
        use_uom_name = inferred_uom['uom_name']
        use_uom_factor = float(purchase_uom_info['factor']) if purchase_uom_info else default_uom_factor
        converted_quantity = original_quantity  # Keep original quantity
        print(f"  ✓ Using inferred UoM: {use_uom_name} with quantity {converted_quantity}")
    else:
        # Continue with normal UoM processing...
        # For weight-based items, prefer picked_weight over quantity if available
        # This is more accurate for produce items where weight may vary
        if purchase_uom in ['lb', 'oz', 'kg', 'g'] and item.get('picked_weight'):
            try:
                picked_weight = float(item.get('picked_weight'))
                if picked_weight > 0:
                    original_quantity = picked_weight
            except (ValueError, TypeError):
                pass  # Use original quantity if picked_weight can't be parsed
        
        converted_quantity = original_quantity
        
        # Initialize similar_uom_found flag (may be set in the elif block below)
        similar_uom_found = False
        
        # CRITICAL: If compound UoM exists in database, use it directly with original quantity
        # Example: quantity=1, purchase_uom="3-lb" (exists in DB) -> use quantity=1, UoM="3-lb"
        # Example: quantity=2, unit_size=64, unit_uom="oz" -> use quantity=2, UoM="64 -fl oz(US)"
        # This applies even if category doesn't match - we want to preserve the compound UoM
        # BUT: Skip if we already found a similar UoM (similar_uom_found flag set in elif block)
        compound_uom_exists = (purchase_uom_id and purchase_uom_info and 
                              (size_from_uom is not None or (fl_oz_pattern and fl_oz_number)) and
                              not similar_uom_found)
        
        # Check if purchase UoM exists in DB and is in same category as product default
        # If so, use it directly (user's rule: "If original UoM is of same subcat and existed in database, you can use original UoM")
        if purchase_uom_id and purchase_uom_info and purchase_uom_info['category_id'] == default_uom_category_id:
            # Purchase UoM exists in DB and is in same category - use it directly
            use_uom_id = purchase_uom_id
            use_uom_name = purchase_uom_info['uom_name']
            use_uom_factor = float(purchase_uom_info['factor'])
            converted_quantity = original_quantity  # Keep original quantity
            purchase_uom_for_lookup = purchase_uom_name
            conversion_applied = False  # Don't mark as converted - we're using the purchase UoM directly
            if size_from_uom is not None:
                print(f"  ℹ️  Using purchase UoM: {original_quantity} {purchase_uom_name} (exists in DB, same category as product default)")
            else:
                print(f"  ℹ️  Using purchase UoM: {purchase_uom_name} (exists in DB, same category as product default)")
        elif compound_uom_exists:
            # Compound UoM exists in DB - use it directly with original quantity
            use_uom_id = purchase_uom_id
            use_uom_name = purchase_uom_info['uom_name']
            use_uom_factor = float(purchase_uom_info['factor'])
            converted_quantity = original_quantity  # Keep original quantity (e.g., 1 bag, 1 box, 1 pack)
            purchase_uom_for_lookup = purchase_uom_name
            conversion_applied = False  # Don't mark as converted - we're using the compound UoM directly
            print(f"  ℹ️  Using compound UoM: {original_quantity} {purchase_uom_name} (exists in DB)")
        elif size_from_uom is not None and base_uom_from_compound:
            # Compound UoM doesn't exist in DB - try to find a similar compound UoM first
            # Example: "3000-pc" not found, try "2000-pc" or "1000-pc"
            total_pieces = original_quantity * size_from_uom
            similar_uom_found = False
            
            if default_uom_category_id:
                # Get all UoMs in the same category
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT id, name->>'en_US' as uom_name, factor
                        FROM uom_uom
                        WHERE category_id = %s
                        ORDER BY name->>'en_US'
                    """, (default_uom_category_id,))
                    available_uoms = cur.fetchall()
                    
                    # Try to find a compound UoM close to size_from_uom (e.g., 2000-pc for 3000-pc)
                    best_match = None
                    best_diff = float('inf')
                    for uom_row in available_uoms:
                        uom_name = uom_row['uom_name']
                        # Extract number from UoM name (e.g., "2000-pc" -> 2000)
                        uom_match = re.match(r'(\d+(?:\.\d+)?)\s*-\s*(pc|ct)', uom_name.lower())
                        if uom_match:
                            uom_size = float(uom_match.group(1))
                            # Calculate how many units we'd need with this UoM
                            units_needed = total_pieces / uom_size
                            # Prefer UoMs that result in whole numbers or close to whole numbers
                            if units_needed >= 1 and abs(units_needed - round(units_needed)) < 0.01:
                                diff = abs(uom_size - size_from_uom)
                                if diff < best_diff:
                                    best_match = uom_row
                                    best_diff = diff
                    
                    if best_match:
                        # Use the similar UoM - set it directly and skip further processing
                        purchase_uom_id = best_match['id']
                        purchase_uom_name = best_match['uom_name']
                        purchase_uom_info = get_uom_info(conn, purchase_uom_id)
                        # Calculate the quantity in terms of the similar UoM
                        # Example: 3 packs × 3000-pc = 9000 pieces, similar UoM is 1000-pc, so quantity = 9000 / 1000 = 9.0
                        similar_uom_size = float(re.match(r'(\d+(?:\.\d+)?)\s*-\s*(pc|ct)', best_match['uom_name'].lower()).group(1))
                        converted_quantity = total_pieces / similar_uom_size
                        purchase_uom_for_lookup = purchase_uom_name
                        similar_uom_found = True
                        
                        # Set use_uom directly to skip further processing
                        use_uom_id = purchase_uom_id
                        use_uom_name = purchase_uom_info['uom_name']
                        use_uom_factor = float(purchase_uom_info['factor'])
                        # DO NOT modify original_quantity - keep it as the receipt quantity for reference
                        conversion_applied = False  # Don't mark as converted - we're using the similar UoM directly
                        
                        print(f"  ℹ️  Using similar UoM: {converted_quantity:.4f} {purchase_uom_name} (receipt: {item.get('quantity', 1.0)} × {size_from_uom}-pc = {total_pieces:.0f} pieces)")
                        print(f"  ✓ Set converted_quantity={converted_quantity}, use_uom_id={use_uom_id}, use_uom_name={use_uom_name}")
            
            if not similar_uom_found:
                # No similar UoM found - convert to base unit
                # Adjust original_quantity to be in base unit
                original_quantity = original_quantity * size_from_uom
                # Use base UoM for further processing
                purchase_uom_for_lookup = base_uom_from_compound
                # Re-check purchase UoM info with base UoM
                if not purchase_uom_info:
                    purchase_uom_id = get_uom_id_by_name(conn, purchase_uom_for_lookup)
                    if purchase_uom_id:
                        purchase_uom_info = get_uom_info(conn, purchase_uom_id)
        else:
            purchase_uom_for_lookup = purchase_uom_name
        
        # Use the base UoM name for display/logging if we have a compound UoM
        display_uom_name = purchase_uom_for_lookup if (size_from_uom is not None and base_uom_from_compound) else purchase_uom_name
        
        # Check if we already set use_uom_id above (when compound UoM exists or similar UoM found)
        # If we already set it, skip further processing
        if similar_uom_found:
            # Similar UoM was found and set above - use_uom_id, use_uom_name, and converted_quantity are already set
            # Skip ALL further processing - don't modify converted_quantity or use_uom_id
            print(f"  ✓ Skipping further UoM processing (similar UoM already found: {use_uom_name})")
            pass
        elif use_uom_id != default_uom_id:
            # Already set above for compound UoM or purchase UoM, skip further processing
            print(f"  ✓ Skipping further UoM processing (UoM already set: {use_uom_name})")
            pass
        elif purchase_uom_info:
            # Purchase UoM is in different category - check if we should use purchase UoM anyway
            # First check if this is a unit-based purchase (e.g., 2 units × 64 fl oz)
            purchase_category = purchase_uom_info['category_id']
            # Category 2 = Weight, Category 6 = Volume
            # If purchase is weight/volume and product default is Units (category 1), use purchase UoM
            # Check if this is a unit-based purchase (e.g., 2 units × 64 fl oz = 128 fl oz)
            # This happens when purchase_uom is "each"/"Units" but unit_uom is a volume/weight unit
            if (purchase_category == 1 and unit_uom and unit_uom in ['fl_oz', 'oz', 'lb', 'gal', 'qt', 'pt', 'ml', 'l'] and unit_size and unit_size > 1):
                # This is a unit-based purchase (e.g., 2 units × 64 fl oz = 128 fl oz)
                # Convert: quantity × unit_size = total in unit_uom, then convert to product default UoM
                total_in_unit_uom = original_quantity * unit_size
                
                # Try to find the unit_uom in database
                unit_uom_id = get_uom_id_by_name(conn, unit_uom)
                if unit_uom_id:
                    unit_uom_info = get_uom_info(conn, unit_uom_id)
                    if unit_uom_info and unit_uom_info['category_id'] == default_uom_category_id:
                        # Same category - convert using factors
                        converted_quantity = convert_uom_quantity(total_in_unit_uom, float(unit_uom_info['factor']), default_uom_factor)
                        conversion_applied = True
                        print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} → {converted_quantity:.4f} {default_uom_name}")
                    else:
                        # Different category or not found - try manual conversions
                        if unit_uom.lower() in ['fl_oz', 'oz', 'fl oz', 'fluid ounce', 'fluid ounces'] and default_uom_name.lower() in ['gal (us)', 'gallon (us)', 'gal']:
                            converted_quantity = total_in_unit_uom / 128.0
                            conversion_applied = True
                            print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} → {converted_quantity:.4f} {default_uom_name} (manual: 128 fl_oz = 1 gal)")
                        else:
                            converted_quantity = total_in_unit_uom
                            conversion_applied = True
                            print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} (category mismatch, using as-is)")
                else:
                    # Unit UoM not found - try manual conversions
                    if unit_uom.lower() in ['fl_oz', 'oz', 'fl oz', 'fluid ounce', 'fluid ounces'] and default_uom_name.lower() in ['gal (us)', 'gallon (us)', 'gal']:
                        converted_quantity = total_in_unit_uom / 128.0
                        conversion_applied = True
                        print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} → {converted_quantity:.4f} {default_uom_name} (manual: 128 fl_oz = 1 gal)")
                    else:
                        converted_quantity = total_in_unit_uom
                        conversion_applied = True
                        print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} (UoM not found, using as-is)")
            elif purchase_category in [2, 6] and default_uom_category_id == 1:
                # Use purchase UoM (weight/volume) instead of product default (Units)
                use_uom_id = purchase_uom_id
                use_uom_name = purchase_uom_info['uom_name']
                use_uom_factor = float(purchase_uom_info['factor'])
                converted_quantity = original_quantity
                if size_from_uom is not None and base_uom_from_compound:
                    print(f"  ℹ️  Using compound UoM: {item.get('quantity', 1.0)} {purchase_uom_name} = {original_quantity:.4f} {display_uom_name} (purchase UoM is weight/volume, product default is Units)")
                else:
                    print(f"  ℹ️  Using purchase UoM {display_uom_name} (weight/volume) instead of product default {default_uom_name} (Units)")
            # If purchase is Units (category 1) and product default is weight/volume, use purchase UoM (Units/pc)
            # We can't convert count to weight/volume without knowing the weight per unit
            elif purchase_category == 1 and default_uom_category_id in [2, 6]:
                # Use purchase UoM (Units/pc) instead of product default (weight/volume)
                use_uom_id = purchase_uom_id
                use_uom_name = purchase_uom_info['uom_name']
                use_uom_factor = float(purchase_uom_info['factor'])
                converted_quantity = original_quantity
                if size_from_uom is not None and base_uom_from_compound:
                    print(f"  ℹ️  Using compound UoM: {item.get('quantity', 1.0)} {purchase_uom_name} = {original_quantity:.4f} {display_uom_name} (purchase UoM is count, product default is weight/volume)")
                else:
                    print(f"  ℹ️  Using purchase UoM {display_uom_name} (count) instead of product default {default_uom_name} (weight/volume)")
            else:
                # Other category mismatches - try to convert
                purchase_factor = float(purchase_uom_info['factor'])
                converted_quantity = convert_uom_quantity(original_quantity, purchase_factor, default_uom_factor)
                conversion_applied = True
                if size_from_uom is not None and base_uom_from_compound:
                    print(f"  ℹ️  Converting {item.get('quantity', 1.0)} {purchase_uom_name} = {original_quantity:.4f} {display_uom_name} (cat: {purchase_uom_info['category_id']}) → {converted_quantity:.4f} {default_uom_name} (cat: {default_uom_category_id})")
                else:
                    print(f"  ℹ️  Converting {original_quantity} {display_uom_name} (cat: {purchase_uom_info['category_id']}) → {converted_quantity:.4f} {default_uom_name} (cat: {default_uom_category_id})")
        else:
            # Purchase UoM is NOT in same category or not found - use product default UoM and convert quantity
            purchase_category = purchase_uom_info['category_id'] if purchase_uom_info else None
        
        # Initialize purchase_category if not already set
        if 'purchase_category' not in locals():
            purchase_category = purchase_uom_info['category_id'] if purchase_uom_info else None
        
        if purchase_uom_info and not similar_uom_found and use_uom_id == default_uom_id:
            # Convert quantity from purchase UoM to product default UoM
            # But skip if we already found a similar UoM or if compound UoM exists (use_uom_id != default_uom_id)
            purchase_factor = float(purchase_uom_info['factor'])
            converted_quantity = convert_uom_quantity(original_quantity, purchase_factor, default_uom_factor)
            conversion_applied = True
            if size_from_uom is not None and base_uom_from_compound:
                print(f"  ℹ️  Converting {item.get('quantity', 1.0)} {purchase_uom_name} = {original_quantity:.4f} {display_uom_name} (cat: {purchase_uom_info['category_id']}) → {converted_quantity:.4f} {default_uom_name} (cat: {default_uom_category_id})")
            else:
                print(f"  ℹ️  Converting {original_quantity} {display_uom_name} (cat: {purchase_uom_info['category_id']}) → {converted_quantity:.4f} {default_uom_name} (cat: {default_uom_category_id})")
        elif not similar_uom_found and ((is_unit_based_purchase and unit_size) or ((purchase_category == 1 or not purchase_uom_info) and unit_uom and unit_uom in ['fl_oz', 'oz', 'lb', 'gal', 'qt', 'pt', 'ml', 'l'] and unit_size and unit_size > 1)):
            # Purchase UoM is Units but unit_uom is a volume/weight unit - quantity is in units
            # Example: quantity=2, purchase_uom="each", unit_uom="fl_oz", unit_size=64 means 2 units × 64 fl oz = 128 fl oz
            # Example: quantity=4, purchase_uom="each", unit_uom="lb", unit_size=35 means 4 units × 35 lb = 140 lb
            # First convert to the unit_uom, then to product default UoM
            total_in_unit_uom = original_quantity * unit_size
            
            # Try to find the unit_uom in database
            purchase_uom_id_temp = get_uom_id_by_name(conn, unit_uom)
            if purchase_uom_id_temp:
                purchase_uom_info_temp = get_uom_info(conn, purchase_uom_id_temp)
                if purchase_uom_info_temp and purchase_uom_info_temp['category_id'] == default_uom_category_id:
                    # Same category - convert using factors
                    converted_quantity = convert_uom_quantity(total_in_unit_uom, float(purchase_uom_info_temp['factor']), default_uom_factor)
                    conversion_applied = True
                    print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} → {converted_quantity:.4f} {default_uom_name}")
                else:
                    # Different category or not found - use unit_size directly
                    converted_quantity = total_in_unit_uom
                    conversion_applied = True
                    print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} (category mismatch, using as-is)")
            else:
                # Unit UoM not found - try manual conversions for common cases
                # fl_oz to gal (US): 128 fl_oz = 1 gal (US)
                if unit_uom.lower() in ['fl_oz', 'fl oz', 'fluid ounce', 'fluid ounces'] and default_uom_name.lower() in ['gal (us)', 'gallon (us)', 'gal']:
                    converted_quantity = total_in_unit_uom / 128.0
                    conversion_applied = True
                    print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} → {converted_quantity:.4f} {default_uom_name} (manual: 128 fl_oz = 1 gal)")
                else:
                    # Unit UoM not found - use unit_size directly
                    converted_quantity = total_in_unit_uom
                    conversion_applied = True
                    print(f"  ℹ️  Converting {original_quantity} units × {unit_size} {unit_uom} = {total_in_unit_uom} {unit_uom} (UoM not found, using as-is)")
        elif size_from_uom is not None and base_uom_from_compound and not similar_uom_found and use_uom_id == default_uom_id:
            # We already adjusted original_quantity above, now convert from base UoM to product default UoM
            # But skip if we already found a similar UoM or if purchase UoM is already set (use_uom_id != default_uom_id)
            # Try to find base UoM in database
            base_uom_id = get_uom_id_by_name(conn, base_uom_from_compound)
            if base_uom_id:
                base_uom_info = get_uom_info(conn, base_uom_id)
                if base_uom_info and base_uom_info['category_id'] == default_uom_category_id:
                    # Same category - use base UoM
                    use_uom_id = base_uom_id
                    use_uom_name = base_uom_info['uom_name']
                    use_uom_factor = float(base_uom_info['factor'])
                    converted_quantity = original_quantity  # Already adjusted above
                    print(f"  ℹ️  Using compound UoM: {item.get('quantity', 1.0)} {purchase_uom_name} = {original_quantity:.4f} {base_uom_from_compound} (same category as product default)")
                else:
                    # Different category - convert
                    if base_uom_info:
                        converted_quantity = convert_uom_quantity(original_quantity, float(base_uom_info['factor']), default_uom_factor)
                        conversion_applied = True
                        print(f"  ℹ️  Converting {item.get('quantity', 1.0)} {purchase_uom_name} = {original_quantity:.4f} {base_uom_from_compound} → {converted_quantity:.4f} {default_uom_name}")
                    else:
                        converted_quantity = original_quantity
                        conversion_applied = True
                        print(f"  ℹ️  Using compound UoM: {item.get('quantity', 1.0)} {purchase_uom_name} = {original_quantity:.4f} {base_uom_from_compound} (base UoM not found, using as-is)")
            else:
                # Base UoM not found - use as-is
                converted_quantity = original_quantity
                conversion_applied = True
                print(f"  ℹ️  Using compound UoM: {item.get('quantity', 1.0)} {purchase_uom_name} = {original_quantity:.4f} {base_uom_from_compound} (base UoM not found)")
        elif size_from_uom is not None and use_uom_id == default_uom_id:
            # Purchase UoM not found in DB, but we can extract size from UoM name (e.g., "1500-pc", "3000-pc")
            # Try to find a similar UoM in the same category (e.g., 2000-pc, 1000-pc for 3000-pc)
            # But skip if purchase UoM is already set (use_uom_id != default_uom_id)
            total_pieces = original_quantity * size_from_uom
            
            # Try to find a similar compound UoM in the same category
            similar_uom_found = False
            if default_uom_category_id:
                # Get all UoMs in the same category
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT id, name->>'en_US' as uom_name, factor
                        FROM uom_uom
                        WHERE category_id = %s
                        ORDER BY name->>'en_US'
                    """, (default_uom_category_id,))
                    available_uoms = cur.fetchall()
                    
                    # Try to find a compound UoM close to size_from_uom (e.g., 2000-pc for 3000-pc)
                    # Look for patterns like "2000-pc", "1000-pc", etc.
                    best_match = None
                    best_diff = float('inf')
                    for uom_row in available_uoms:
                        uom_name = uom_row['uom_name']
                        # Extract number from UoM name (e.g., "2000-pc" -> 2000)
                        uom_match = re.match(r'(\d+(?:\.\d+)?)\s*-\s*(pc|ct)', uom_name.lower())
                        if uom_match:
                            uom_size = float(uom_match.group(1))
                            # Calculate how many units we'd need with this UoM
                            units_needed = total_pieces / uom_size
                            # Prefer UoMs that result in whole numbers or close to whole numbers
                            if units_needed >= 1 and abs(units_needed - round(units_needed)) < 0.01:
                                diff = abs(uom_size - size_from_uom)
                                if diff < best_diff:
                                    best_match = uom_row
                                    best_diff = diff
                    
                    if best_match:
                        # Use the similar UoM
                        use_uom_id = best_match['id']
                        use_uom_name = best_match['uom_name']
                        use_uom_factor = float(best_match['factor'])
                        converted_quantity = total_pieces / float(re.match(r'(\d+(?:\.\d+)?)\s*-\s*(pc|ct)', best_match['uom_name'].lower()).group(1))
                        conversion_applied = True
                        similar_uom_found = True
                        print(f"  ℹ️  Using similar UoM: {converted_quantity:.4f} {use_uom_name} (instead of {original_quantity} {purchase_uom_name}, total: {total_pieces:.0f} pieces)")
            
            if not similar_uom_found:
                # No similar UoM found - convert to total pieces and use default UoM
                converted_quantity = total_pieces
                conversion_applied = True
                print(f"  ℹ️  Converting {original_quantity} {purchase_uom_name} → {converted_quantity:.4f} {default_uom_name} (using size {size_from_uom} from UoM name)")
        elif not similar_uom_found and use_uom_id == default_uom_id and unit_size and unit_size > 1:
            # Use unit_size if available (e.g., unit_size = 12 means 12 pieces per unit)
            # But only if purchase_uom is not a volume/weight unit (handled above)
            # And skip if we already found a similar UoM or if compound UoM exists (use_uom_id != default_uom_id)
            converted_quantity = original_quantity * unit_size
            conversion_applied = True
            print(f"  ℹ️  Converting {original_quantity} {purchase_uom_name} → {converted_quantity:.4f} {default_uom_name} (using unit_size {unit_size})")
        else:
            # Purchase UoM not found and no size info - use default UoM with original quantity
            print(f"  ⚠️  Purchase UoM '{purchase_uom_name}' not found, using product default UoM '{default_uom_name}' with original quantity")
    
    # Get item data
    product_name = item.get('product_name') or item.get('display_name', 'Unknown Product')
    standard_name = item.get('standard_name', '') or default_uom_name  # Use Odoo product name
    if not standard_name:
        standard_name = product_name  # Fallback to receipt name if no standard name
    
    quantity = converted_quantity
    
    original_unit_price = float(item.get('unit_price', 0.0))
    total_price = float(item.get('total_price', 0.0))
    
    # price_tax is passed as parameter (pre-calculated to ensure sum matches receipt tax)
    
    # Calculate unit_price correctly:
    # Ensure unit_price corresponds to the UoM being used in the line
    # unit_price = total_price / quantity (where quantity is in the target UoM)
    if quantity > 0 and total_price > 0:
        unit_price = total_price / quantity
    elif quantity > 0 and original_unit_price > 0:
        # If total_price missing but we have unit price and conversion happened
        # Adjust unit price by ratio of original/new quantity
        # e.g. $65/pack * (3 packs / 9000 pieces) = $0.0216/piece
        if original_quantity_for_price > 0:
             unit_price = original_unit_price * (original_quantity_for_price / quantity)
        else:
             unit_price = original_unit_price # Fallback
    else:
        unit_price = original_unit_price
    
    # product_uom_qty is the quantity in the UoM being used
    product_uom_qty = quantity
    
    # Check if this is a BBI order
    is_bbi_order = (
        receipt_data.get('vendor', '').upper() in ['BBI', 'BOBA BARON INC', 'BOBA BARON'] or
        receipt_data.get('detected_vendor_code', '').upper() == 'BBI' or
        receipt_data.get('detected_source_type', '').lower() == 'bbi_based' or
        'UNI_' in str(receipt_id).upper() if receipt_id else False
    )
    
    # Get dates - use receipt order date for all dates (create_date, write_date, date_planned)
    # For BBI orders, ALWAYS use Oct 30, 2025
    if is_bbi_order:
        date_planned = "2025-10-30 00:00:00"
        create_date = date_planned
        write_date = date_planned
    else:
        receipt_order_date_str = (
            receipt_data.get('transaction_date') or 
            receipt_data.get('order_date') or 
            receipt_data.get('date', '')
        )
        # Use receipt_id parameter if provided, otherwise get from receipt_data
        receipt_id_for_date = receipt_id or receipt_data.get('receipt_id') or receipt_data.get('order_id') or ''
        order_date = parse_date(receipt_order_date_str, receipt_id_for_date)
        if not order_date:
            # Fallback: try to extract from receipt_id in receipt_data
            if receipt_id:
                order_date = parse_date('', receipt_id)
        if not order_date:
            raise ValueError(f"Cannot parse date for purchase order line. receipt_id={receipt_id}, date_str={receipt_order_date_str}")
        date_planned = order_date.strftime('%Y-%m-%d %H:%M:%S')
        create_date = date_planned  # Use date_planned instead of current date
        write_date = date_planned    # Use date_planned instead of current date
    
    # Build comment
    comment_lines = [
        f"-- Line {sequence // 10}: {standard_name}",
        f"--   Product ID: {product_id}",
        f"--   Odoo Product Name: {standard_name}",
        f"--   Receipt Product Name: {product_name[:60]}",
    ]
    
    if conversion_applied:
        comment_lines.extend([
            f"--   Original Quantity: {original_quantity} {purchase_uom_name} (category: {purchase_uom_info['category_id'] if purchase_uom_info else 'N/A'})",
            f"--   Converted Quantity: {quantity:.4f} {use_uom_name} (category: {default_uom_category_id})",
            f"--   Unit Price: ${unit_price:.4f}",
            f"--   Total: ${total_price:.2f}",
        ])
    else:
        comment_lines.extend([
            f"--   Quantity: {quantity} {use_uom_name}",
            f"--   Unit Price: ${unit_price:.2f}",
            f"--   Total: ${total_price:.2f}",
        ])
    
    comment = '\n'.join(comment_lines) + '\n'
    
    sql = f"""{comment}
INSERT INTO purchase_order_line (
    id, sequence, product_uom, product_id, order_id, company_id, partner_id, 
    currency_id, product_packaging_id, create_uid, write_uid, state, 
    qty_received_method, display_type, analytic_distribution, name, product_qty, 
    discount, price_unit, price_subtotal, price_total, qty_invoiced, qty_received, 
    qty_received_manual, qty_to_invoice, is_downpayment, date_planned, create_date, 
    write_date, product_uom_qty, price_tax, product_packaging_qty, orderpoint_id, 
    location_final_id, group_id, product_description_variants, propagate_cancel
)
SELECT 
    {po_line_id},  -- id
    {sequence},  -- sequence
    {use_uom_id},  -- product_uom (using product's default UoM or purchase UoM if same category)
    {product_id},  -- product_id
    {po_id},  -- order_id
    1,  -- company_id
    rp.id,  -- partner_id (from res_partner lookup)
    1,  -- currency_id (USD)
    NULL,  -- product_packaging_id
    2,  -- create_uid (admin)
    2,  -- write_uid (admin)
    'draft',  -- state
    'stock_moves',  -- qty_received_method
    NULL,  -- display_type
    NULL,  -- analytic_distribution
    {format_sql_value(standard_name)},  -- name (Odoo product name)
    {quantity},  -- product_qty (converted if needed)
    0.00,  -- discount
    {unit_price},  -- price_unit (adjusted if conversion applied)
    {total_price},  -- price_subtotal
    {total_price + price_tax:.2f},  -- price_total (subtotal + tax)
    0.00,  -- qty_invoiced
    0.00,  -- qty_received
    0.00,  -- qty_received_manual
    {quantity},  -- qty_to_invoice
    NULL,  -- is_downpayment
    {format_sql_value(date_planned)},  -- date_planned
    {format_sql_value(date_planned)},  -- create_date (same as date_planned)
    {format_sql_value(date_planned)},  -- write_date (same as date_planned)
    {product_uom_qty},  -- product_uom_qty
    {price_tax:.2f},  -- price_tax (calculated proportionally)
    0,  -- product_packaging_qty
    NULL,  -- orderpoint_id
    NULL,  -- location_final_id
    NULL,  -- group_id
    NULL,  -- product_description_variants
    TRUE  -- propagate_cancel
FROM res_partner rp 
WHERE (rp.name = {format_sql_value(vendor_name)} 
   OR rp.name ILIKE {format_sql_value(f'%{vendor_name}%')}
   OR rp.name ILIKE '%Restaurant Depot%'  -- RD abbreviation expansion
   OR {format_sql_value(vendor_name)} LIKE CONCAT('%', rp.name, '%'))"""
    
    # Add IC- exclusion for non-Instacart orders
    if not is_instacart_order:
        sql += "\n   AND rp.name NOT LIKE 'IC-%'  -- Exclude IC- prefixed vendors for non-Instacart orders"
    
    sql += f"""
ORDER BY 
    CASE WHEN rp.name = {format_sql_value(vendor_name)} THEN 1 
         WHEN rp.name ILIKE {format_sql_value(f'%{vendor_name}%')} THEN 2
         WHEN rp.name ILIKE '%Restaurant Depot%' THEN 2  -- Restaurant Depot matches
         WHEN {format_sql_value(vendor_name)} LIKE CONCAT('%', rp.name, '%') THEN 3
         ELSE 4 END,
    rp.name
LIMIT 1;
"""
    
    # Add tax assignment if tax_id is provided and price_tax > 0
    if tax_id and price_tax > 0:
        sql += f"""

-- Assign tax to this line item (so tax shows in Odoo UI)
INSERT INTO account_tax_purchase_order_line_rel (purchase_order_line_id, account_tax_id)
VALUES ({po_line_id}, {tax_id});
"""
    
    return sql


def generate_rollback_sql(
    receipt_id: str,
    receipt_data: Dict,
    po_id: int,
    conn
) -> str:
    """Generate rollback SQL to delete the purchase order and lines"""
    
    items = receipt_data.get('items', [])
    # Filter out not-picked items (same filtering as in generate_sql_for_receipt)
    filtered_items, _ = filter_not_picked_items(items)
    po_line_id = po_id * 1000  # Start line IDs from PO_ID * 1000
    
    sql_parts = []
    sql_parts.append("-- ================================================")
    sql_parts.append(f"-- ROLLBACK SCRIPT for Purchase Order: {po_id}")
    sql_parts.append(f"-- Receipt ID: {receipt_id}")
    sql_parts.append("-- ================================================")
    sql_parts.append("-- This script will DELETE the purchase order and all its lines")
    sql_parts.append("-- Use this if you need to rollback the purchase order creation")
    sql_parts.append("")
    sql_parts.append("BEGIN;")
    sql_parts.append("")
    
    # Delete purchase order lines first (foreign key constraint)
    sql_parts.append("-- Delete Purchase Order Lines")
    line_ids = []
    for idx, item in enumerate(filtered_items, 1):
        if item.get('odoo_product_id'):
            line_ids.append(str(po_line_id + idx))
    
    if line_ids:
        line_ids_str = ', '.join(line_ids)
        sql_parts.append(f"DELETE FROM purchase_order_line WHERE id IN ({line_ids_str});")
        sql_parts.append(f"-- Deleted {len(line_ids)} purchase order line(s)")
    else:
        sql_parts.append("-- No purchase order lines to delete")
    
    sql_parts.append("")
    
    # Delete purchase order
    sql_parts.append("-- Delete Purchase Order")
    sql_parts.append(f"DELETE FROM purchase_order WHERE id = {po_id};")
    sql_parts.append(f"-- Deleted purchase order ID: {po_id}")
    sql_parts.append("")
    
    sql_parts.append("COMMIT;")
    sql_parts.append("")
    sql_parts.append("-- Rollback complete")
    
    return '\n'.join(sql_parts)


def filter_not_picked_items(items: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Filter out items that were not picked/delivered (quantity 0 or $0.00 total).
    
    Returns:
        Tuple of (filtered_items, removed_items)
    """
    filtered_items = []
    removed_items = []
    
    for item in items:
        total_price = float(item.get('total_price', 0) or 0)
        picked_qty = item.get('picked_quantity', '')
        quantity = item.get('quantity', 0)
        
        # Remove if:
        # 1. Total price is 0 or negative (except discounts which can be negative)
        # 2. Picked quantity is explicitly 0 (for Instacart orders)
        # 3. Quantity is 0 or negative (except discounts)
        is_discount = 'discount' in item.get('product_name', '').lower() or 'discount' in item.get('standard_name', '').lower()
        
        should_remove = False
        reason = None
        
        if not is_discount:
            if total_price == 0.0:
                should_remove = True
                reason = "total price is $0.00"
            elif picked_qty and str(picked_qty) == '0':
                should_remove = True
                reason = f"picked quantity is 0 (ordered but not picked)"
            elif quantity == 0 or (isinstance(quantity, (int, float)) and quantity <= 0):
                should_remove = True
                reason = f"quantity is {quantity}"
        
        if should_remove:
            removed_items.append((item, reason))
        else:
            filtered_items.append(item)
    
    return filtered_items, removed_items


def generate_sql_for_receipt(
    receipt_id: str,
    receipt_data: Dict,
    po_id: int,
    conn
) -> str:
    """Generate complete SQL for one receipt (PO + all lines)"""
    
    sql_parts = []
    
    # Add transaction wrapper
    sql_parts.append("-- ================================================")
    sql_parts.append("-- TRANSACTION: Purchase Order Creation")
    sql_parts.append("-- ================================================")
    sql_parts.append("-- This script creates a purchase order and its lines in 'draft' state.")
    sql_parts.append("-- The transaction will be committed so the PO is visible in Odoo web UI.")
    sql_parts.append("-- You will CONFIRM the purchase order from the web interface.")
    sql_parts.append("--")
    sql_parts.append("-- To rollback before commit, use: ROLLBACK;")
    sql_parts.append("")
    sql_parts.append("BEGIN;")
    sql_parts.append("")
    
    # Generate Purchase Order SQL
    po_sql, vendor_name, is_instacart_order, date_planned = generate_purchase_order_sql(receipt_id, receipt_data, po_id, conn)
    sql_parts.append(po_sql)
    sql_parts.append("")
    
    # Generate Purchase Order Lines SQL
    items = receipt_data.get('items', [])
    
    # Filter out not-picked items (quantity 0 or $0.00)
    filtered_items, removed_items = filter_not_picked_items(items)
    
    if removed_items:
        sql_parts.append("-- ================================================")
        sql_parts.append("-- FILTERED ITEMS (Not included in purchase order)")
        sql_parts.append("-- ================================================")
        for item, reason in removed_items:
            item_name = item.get('product_name', '')[:50] or item.get('standard_name', '')[:50] or 'Unknown'
            sql_parts.append(f"--   - {item_name}: {reason}")
        sql_parts.append("")
    
    # Tax will be added as a separate line item, so no tax on product lines
    tax_total = float(receipt_data.get('tax', 0.0))
    
    # Determine tax ID and Grocery Tax product ID
    tax_id = None
    grocery_tax_product_id = None
    if tax_total > 0:
        try:
            with conn.cursor() as cur:
                # Get Grocery 2.25% tax (ID 4)
                cur.execute("SELECT id FROM account_tax WHERE id = 4 AND active = true")
                result = cur.fetchone()
                if result:
                    tax_id = result[0]
                else:
                    # Fallback: get first active tax
                    cur.execute("SELECT id FROM account_tax WHERE active = true LIMIT 1")
                    result = cur.fetchone()
                    if result:
                        tax_id = result[0]
                
                # Get Grocery Tax product_product ID (template ID 1959 -> product_product ID 705)
                # purchase_order_line.product_id references product_product, not product_template
                cur.execute("""
                    SELECT pp.id 
                    FROM product_product pp
                    JOIN product_template pt ON pp.product_tmpl_id = pt.id
                    WHERE pt.id = 1959
                    LIMIT 1
                """)
                result = cur.fetchone()
                if result:
                    grocery_tax_product_id = result[0]
        except Exception as e:
            print(f"  ⚠️  Could not determine tax_id or grocery_tax_product_id: {e}")
    
    po_line_id = po_id * 1000  # Start line IDs from PO_ID * 1000
    
    # Add product line items (no tax)
    for idx, item in enumerate(filtered_items, 1):
        sequence = idx * 10  # Sequence: 10, 20, 30, ...
        line_sql = generate_purchase_order_line_sql(
            item, po_line_id + idx, po_id, sequence, vendor_name, conn, receipt_data, receipt_id, is_instacart_order, 0.0, None  # No tax on product lines
        )
        if line_sql:
            sql_parts.append(line_sql)
            sql_parts.append("")
        else:
            sql_parts.append(f"-- Line {idx}: SKIPPED - No product ID")
            sql_parts.append("")
    
    # Add Grocery Tax as a separate line item
    if tax_total > 0 and grocery_tax_product_id and tax_id:
        tax_line_id = po_line_id + len(filtered_items) + 1
        tax_sequence = (len(filtered_items) + 1) * 10
        
        sql_parts.append("-- ================================================")
        sql_parts.append("-- GROCERY TAX LINE ITEM")
        sql_parts.append("-- ================================================")
        sql_parts.append(f"-- Tax Amount: ${tax_total:.2f}")
        sql_parts.append("")
        
        tax_line_sql = f"""-- Grocery Tax Line Item
INSERT INTO purchase_order_line (
    id, sequence, product_uom, product_id, order_id, company_id, partner_id, 
    currency_id, product_packaging_id, create_uid, write_uid, state, 
    qty_received_method, display_type, analytic_distribution, name, product_qty, 
    discount, price_unit, price_subtotal, price_total, qty_invoiced, qty_received, 
    qty_received_manual, qty_to_invoice, is_downpayment, date_planned, create_date, 
    write_date, product_uom_qty, price_tax, product_packaging_qty, orderpoint_id, 
    location_final_id, group_id, product_description_variants, propagate_cancel
)
SELECT 
    {tax_line_id},  -- id
    {tax_sequence},  -- sequence
    1,  -- product_uom (Units)
    {grocery_tax_product_id},  -- product_id (Grocery Tax)
    {po_id},  -- order_id
    1,  -- company_id
    rp.id,  -- partner_id (from res_partner lookup)
    1,  -- currency_id (USD)
    NULL,  -- product_packaging_id
    2,  -- create_uid (admin)
    2,  -- write_uid (admin)
    'draft',  -- state
    'stock_moves',  -- qty_received_method
    NULL,  -- display_type
    NULL,  -- analytic_distribution
    {format_sql_value('Grocery Tax')},  -- name
    {tax_total:.2f},  -- product_qty (tax amount - Odoo Grocery Tax has fixed unit_price = $1.00)
    0.00,  -- discount
    1.00,  -- price_unit (fixed at $1.00 for Grocery Tax in Odoo)
    {tax_total:.2f},  -- price_subtotal (Amount field in Odoo - set to tax amount so it displays correctly)
    {tax_total:.2f},  -- price_total (tax amount = quantity × unit_price = {tax_total:.2f} × 1.00)
    0.00,  -- qty_invoiced
    0.00,  -- qty_received
    0.00,  -- qty_received_manual
    0.00,  -- qty_to_invoice
    NULL,  -- is_downpayment
    {format_sql_value(date_planned)},  -- date_planned
    {format_sql_value(date_planned)},  -- create_date
    {format_sql_value(date_planned)},  -- write_date
    {tax_total:.2f},  -- product_uom_qty (same as product_qty)
    0.00,  -- price_tax (Grocery Tax line itself has no tax)
    0,  -- product_packaging_qty
    NULL,  -- orderpoint_id
    NULL,  -- location_final_id
    NULL,  -- group_id
    NULL,  -- product_description_variants
    TRUE  -- propagate_cancel
FROM res_partner rp 
WHERE (rp.name = {format_sql_value(vendor_name)} 
   OR rp.name ILIKE {format_sql_value(f'%{vendor_name}%')}
   OR rp.name ILIKE '%Restaurant Depot%'  -- RD abbreviation expansion
   OR {format_sql_value(vendor_name)} LIKE CONCAT('%', rp.name, '%'))"""
        
        # Add IC- exclusion for non-Instacart orders
        if not is_instacart_order:
            tax_line_sql += "\n   AND rp.name NOT LIKE 'IC-%'  -- Exclude IC- prefixed vendors for non-Instacart orders"
        
        tax_line_sql += f"""
ORDER BY 
    CASE WHEN rp.name = {format_sql_value(vendor_name)} THEN 1 
         WHEN rp.name ILIKE {format_sql_value(f'%{vendor_name}%')} THEN 2
         WHEN rp.name ILIKE '%Restaurant Depot%' THEN 2  -- Restaurant Depot matches
         WHEN {format_sql_value(vendor_name)} LIKE CONCAT('%', rp.name, '%') THEN 3
         ELSE 4 END,
    rp.name
LIMIT 1;
"""
        
        sql_parts.append(tax_line_sql)
        sql_parts.append("")
    
    # Add commit statement with clarification about web UI confirmation
    sql_parts.append("-- ================================================")
    sql_parts.append("-- COMMIT TRANSACTION (Records will be visible in Odoo web UI)")
    sql_parts.append("-- ================================================")
    sql_parts.append("-- This commits the transaction so the purchase order is visible in the web UI.")
    sql_parts.append("-- The purchase order is in 'draft' state - you will CONFIRM it from the web interface.")
    sql_parts.append("--")
    sql_parts.append("-- To review before committing, you can:")
    sql_parts.append(f"--   SELECT * FROM purchase_order WHERE id = {po_id};")
    sql_parts.append(f"--   SELECT * FROM purchase_order_line WHERE order_id = {po_id};")
    sql_parts.append("--")
    sql_parts.append("-- If you need to rollback before committing:")
    sql_parts.append("--   ROLLBACK;")
    sql_parts.append("--")
    sql_parts.append("COMMIT;")
    sql_parts.append("")
    sql_parts.append("-- ================================================")
    sql_parts.append("-- NEXT STEPS:")
    sql_parts.append("-- ================================================")
    sql_parts.append(f"-- 1. Go to Odoo web UI: Purchase > Purchase Orders")
    sql_parts.append(f"-- 2. Find Purchase Order ID: {po_id}")
    sql_parts.append("-- 3. Review the purchase order details")
    sql_parts.append("-- 4. CONFIRM the purchase order from the web UI when ready")
    sql_parts.append("--")
    sql_parts.append("-- Note: The purchase order is in 'draft' state and needs to be")
    sql_parts.append("--       confirmed from the Odoo web interface, not via SQL.")
    sql_parts.append("")
    
    return '\n'.join(sql_parts)


def main():
    """Generate SQL for one receipt as example"""
    
    # Connect to database
    print("Connecting to Odoo database...")
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to database")
        return
    
    try:
        import sys
        
        # Load all Step 1 output files
        json_files = list(Path('data/step1_output').glob('**/extracted_data.json'))
        if not json_files:
            print("ERROR: No extracted_data.json found in data/step1_output/")
            return
        
        # Load all receipts
        all_receipts = {}
        for json_file in json_files:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Check if it's the new format with receipts key
                    if 'receipts' in data:
                        for receipt in data['receipts']:
                            receipt_id = receipt.get('receipt_id') or receipt.get('order_id')
                            if receipt_id:
                                all_receipts[receipt_id] = receipt
                    else:
                        # Old format - receipts are keys
                        all_receipts.update(data)
        
        # Check if receipt ID provided as argument
        if len(sys.argv) > 1:
            receipt_id = sys.argv[1]
        else:
            # Find the next receipt that doesn't have SQL yet
            sql_dir = Path('data/sql')
            existing_sql = set()
            if sql_dir.exists():
                for sql_file in sql_dir.glob('purchase_order_*.sql'):
                    if '_rollback' not in sql_file.name:
                        # Extract receipt ID from filename
                        name = sql_file.stem.replace('purchase_order_', '')
                        existing_sql.add(name)
            
            # Find first receipt without SQL
            receipt_id = None
            for rid in sorted(all_receipts.keys()):
                if rid.replace("/", "_") not in existing_sql:
                    receipt_id = rid
                    break
            
            if not receipt_id:
                print("All receipts already have SQL files generated!")
                return
        
        if receipt_id not in all_receipts:
            print(f"ERROR: Receipt '{receipt_id}' not found")
            print(f"Available receipts: {', '.join(sorted(all_receipts.keys())[:10])}...")
            return
        
        receipt_data = all_receipts[receipt_id]
        
        print(f"\nGenerating SQL for receipt: {receipt_id}")
        print(f"Vendor: {receipt_data.get('vendor', 'N/A')}")
        print(f"Items: {len(receipt_data.get('items', []))}")
        
        # Get next available PO ID
        po_id = get_next_id(conn, 'purchase_order')
        print(f"Using PO ID: {po_id}")
        
        # Generate SQL
        sql = generate_sql_for_receipt(receipt_id, receipt_data, po_id, conn)
        
        # Generate rollback SQL
        rollback_sql = generate_rollback_sql(receipt_id, receipt_data, po_id, conn)
        
        # Save main SQL file
        output_file = Path(f'data/sql/purchase_order_{receipt_id.replace("/", "_")}.sql')
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(sql)
        
        # Save rollback SQL file
        rollback_file = Path(f'data/sql/purchase_order_{receipt_id.replace("/", "_")}_rollback.sql')
        with open(rollback_file, 'w', encoding='utf-8') as f:
            f.write(rollback_sql)
        
        print(f"\n✅ SQL generated: {output_file}")
        print(f"✅ Rollback SQL generated: {rollback_file}")
        print(f"\nTo execute this SQL:")
        print(f"  psql -h <host> -U <user> -d odoo -f {output_file}")
        print(f"\nTo rollback (if needed):")
        print(f"  psql -h <host> -U <user> -d odoo -f {rollback_file}")
        print(f"\nOr within psql session:")
        print(f"  \\i {output_file}     -- Execute")
        print(f"  ROLLBACK;            -- Rollback before commit")
        print(f"  \\i {rollback_file}  -- Or use rollback script after commit")
        
    finally:
        conn.close()


if __name__ == '__main__':
    main()


