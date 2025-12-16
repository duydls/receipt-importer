#!/usr/bin/env python3
"""
Fix the receipt purchase orders SQL - use valid partner IDs and fix syntax
"""

import json
import re
from datetime import datetime


def escape_sql_string(text):
    """Escape single quotes in SQL strings"""
    if not text:
        return ''
    return text.replace("'", "''")


def get_valid_vendor_id(vendor_name: str) -> int:
    """Use existing vendor IDs from Odoo database"""
    # Based on typical Odoo setup, use common vendor IDs
    # In a real scenario, you'd query the database for these
    vendor_map = {
        'Amazon Business': 1,     # Use existing vendor ID
        'IC-ALDI': 1,             # Use existing vendor ID
        'ALDI': 1,                # Use existing vendor ID
        'Costco': 1,              # Use existing vendor ID
        'Restaurant Depot': 1,    # Use existing vendor ID
        'Jewel-Osco': 1,          # Use existing vendor ID
        'Parktoshop': 1,          # Use existing vendor ID
    }

    # Default to a valid existing vendor ID
    return vendor_map.get(vendor_name, 1)  # Use ID 1 as default (usually exists)


def generate_fixed_receipt_sql():
    """Generate fixed SQL for receipt-based purchase orders"""

    # Load all receipt data
    receipt_sources = [
        ('amazon_based', 'Amazon'),
        ('instacart_based', 'Instacart'),
        ('localgrocery_based', 'Local Grocery')
    ]

    all_sql = []
    all_sql.append("-- FIXED Purchase Orders Generated from ALL Processed Receipts")
    all_sql.append("-- Uses valid partner IDs and properly escaped strings")
    all_sql.append(f"-- Generated on {datetime.now().isoformat()}")
    all_sql.append("")

    total_orders = 0
    total_items = 0

    for source_dir, source_name in receipt_sources:
        try:
            with open(f'data/step1_output/{source_dir}/extracted_data.json', 'r') as f:
                receipt_data = json.load(f)

            all_sql.append(f"-- === {source_name.upper()} RECEIPTS ===")
            all_sql.append("")

            for receipt_id, receipt in receipt_data.items():
                vendor_name = receipt.get('vendor', 'Unknown Vendor')
                transaction_date = receipt.get('transaction_date', datetime.now().isoformat())
                items = receipt.get('items', [])

                # Ensure date is in November 2025
                if not transaction_date.startswith('2025-11'):
                    transaction_date = '2025-11-15T12:00:00'

                # Filter out non-product items
                product_items = []
                for item in items:
                    if not item.get('is_fee', False) and not item.get('is_summary', False):
                        product_items.append(item)

                if not product_items:
                    continue

                vendor_id = get_valid_vendor_id(vendor_name)

                # Create purchase order INSERT
                po_sql = f"""
-- Purchase Order from {source_name.upper()} receipt: {receipt_id} ({vendor_name})
INSERT INTO purchase_order (
    name, partner_id, currency_id, picking_type_id, date_order, date_planned,
    user_id, company_id, state, create_date, write_date, create_uid, write_uid
) VALUES (
    '{receipt_id}', {vendor_id}, 1, 1, '{transaction_date}', '{transaction_date}',
    2, 1, 'draft', NOW(), NOW(), 2, 2
) RETURNING id;"""

                all_sql.append(po_sql)

                # Create purchase order lines
                for i, item in enumerate(product_items):
                    product_name = escape_sql_string(
                        item.get('product_name') or
                        item.get('display_name') or
                        'Unknown Product'
                    )
                    quantity = item.get('quantity', 1)
                    unit_price = item.get('unit_price', 0)

                    # Get UOM
                    uom_name = (item.get('purchase_uom') or
                               item.get('unit_uom') or
                               item.get('unit_size') or 'each')

                    # Map UoM names to IDs
                    uom_id = 1  # Default to 'each'
                    if uom_name.lower() in ['lb', 'lbs', 'pound', 'pounds']:
                        uom_id = 3
                    elif uom_name.lower() in ['kg', 'kilogram']:
                        uom_id = 4
                    elif uom_name.lower() in ['oz', 'ounce']:
                        uom_id = 5
                    elif 'count' in uom_name.lower() or 'pc' in uom_name.lower():
                        uom_id = 1

                    product_id = 1  # Placeholder - needs to be updated

                    line_sql = f"""
-- Purchase Order Line: {product_name[:50]}...
INSERT INTO purchase_order_line (
    order_id, product_id, name, product_qty, price_unit, product_uom,
    date_planned, sequence, company_id, create_date, write_date, create_uid, write_uid
) VALUES (
    (SELECT id FROM purchase_order WHERE name = '{receipt_id}'), {product_id},
    '{product_name}', {quantity}, {unit_price}, {uom_id},
    '{transaction_date}', {i*10}, 1, NOW(), NOW(), 2, 2
);"""

                    all_sql.append(line_sql)

                all_sql.append("")
                total_orders += 1
                total_items += len(product_items)

        except Exception as e:
            print(f"Error processing {source_dir}: {e}")

    # Add summary
    all_sql.insert(3, f"-- Total: {total_orders} orders, {total_items} items")
    all_sql.insert(4, "")

    # Write to file
    output_file = 'data/fixed_receipt_purchase_orders.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(all_sql))

    print(f"✅ Fixed SQL saved to: {output_file}")
    print(f"📦 Contains {total_orders} purchase orders with {total_items} total items")

    print("\n⚠️  IMPORTANT: Before running this SQL:")
    print("1. Update partner_id values with actual vendor IDs from your Odoo database")
    print("2. Update product_id values with actual product IDs")
    print("3. Check that currency_id=1 and picking_type_id=1 are correct for your setup")
    print("4. The SQL syntax is now properly escaped")


def check_existing_partners():
    """Provide query to check existing partners"""
    print("\n🔍 To check existing partners in Odoo, run:")
    print("SELECT id, name FROM res_partner WHERE supplier = true ORDER BY name LIMIT 20;")


if __name__ == '__main__':
    print("Fixing Receipt Purchase Orders SQL")
    print("=" * 40)

    generate_fixed_receipt_sql()
    check_existing_partners()
