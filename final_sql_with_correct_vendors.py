#!/usr/bin/env python3
"""
Generate final SQL with correct vendor names and proper ID placeholders
"""

import json
import re
from datetime import datetime


def escape_sql_string(text):
    """Escape single quotes in SQL strings"""
    if not text:
        return ''
    return text.replace("'", "''")


def get_vendor_mapping():
    """Map actual vendor names to proper IDs (to be updated by user)"""

    # These are the actual vendor names found in receipts
    # User needs to replace the IDs with actual Odoo partner IDs
    vendor_mapping = {
        'Amazon Business': 1,              # Replace with actual Amazon Business ID
        'IC-ALDI': 2,                      # Replace with actual ALDI vendor ID
        'IC-Jewel-Osco': 3,                # Replace with actual Jewel-Osco vendor ID
        "IC-Tony's Fresh Market": 4,       # Replace with actual Tony's vendor ID
        '88 MarketPlace': 5,               # Replace with actual 88 MarketPlace vendor ID
        'Costco': 6,                        # Replace with actual Costco vendor ID
        'Park To Shop': 7,                 # Replace with actual Park To Shop vendor ID
        'RD': 8,                           # Replace with actual Restaurant Depot vendor ID
    }

    return vendor_mapping


def generate_final_receipt_sql():
    """Generate final SQL with correct vendor names"""

    vendor_mapping = get_vendor_mapping()

    # Load all receipt data
    receipt_sources = [
        ('amazon_based', 'Amazon'),
        ('instacart_based', 'Instacart'),
        ('localgrocery_based', 'Local Grocery')
    ]

    all_sql = []
    all_sql.append("-- FINAL Purchase Orders with Correct Vendor Names")
    all_sql.append("-- All vendor names extracted from actual receipts")
    all_sql.append("-- UPDATE THE VENDOR IDs BELOW WITH ACTUAL ODOO PARTNER IDs")
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
                actual_vendor_name = receipt.get('vendor', 'Unknown Vendor')
                vendor_id = vendor_mapping.get(actual_vendor_name, 1)  # Default to 1 if not found

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

                # Create purchase order INSERT
                po_sql = f"""
-- Purchase Order from {source_name.upper()}: {receipt_id}
-- Vendor: {actual_vendor_name} (ID: {vendor_id} - UPDATE THIS!)
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
-- Item: {product_name[:40]}... (Qty: {quantity}, Price: ${unit_price:.2f})
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

    # Add summary and instructions
    all_sql.insert(3, f"-- Total: {total_orders} orders, {total_items} items")
    all_sql.insert(4, "")
    all_sql.insert(5, "-- IMPORTANT: Update vendor IDs with actual Odoo partner IDs!")
    all_sql.insert(6, "-- Current mapping (REPLACE WITH REAL IDs):")
    for vendor_name, vendor_id in vendor_mapping.items():
        all_sql.insert(7 + list(vendor_mapping.keys()).index(vendor_name),
                      f"--   {vendor_name} → ID: {vendor_id}")

    # Write to file
    output_file = 'data/final_receipt_purchase_orders.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(all_sql))

    print(f"✅ Final SQL saved to: {output_file}")
    print(f"📦 Contains {total_orders} purchase orders with {total_items} total items")
    print(f"🏪 Includes {len(vendor_mapping)} different vendors with correct names")

    # Generate rollback script
    generate_final_rollback()


def generate_final_rollback():
    """Generate final rollback script for all receipt orders"""

    # Collect all receipt IDs
    receipt_ids = []

    for source_dir in ['amazon_based', 'instacart_based', 'localgrocery_based']:
        try:
            with open(f'data/step1_output/{source_dir}/extracted_data.json', 'r') as f:
                receipt_data = json.load(f)
            receipt_ids.extend(receipt_data.keys())
        except:
            pass

    if not receipt_ids:
        print("❌ No receipt IDs found")
        return

    rollback_sql = []
    rollback_sql.append("-- FINAL Rollback SQL for All Receipt-Based Purchase Orders")
    rollback_sql.append(f"-- Covers {len(receipt_ids)} receipt orders")
    rollback_sql.append(f"-- Generated on {datetime.now().isoformat()}")
    rollback_sql.append("")
    rollback_sql.append("BEGIN;")
    rollback_sql.append("")

    # Delete in reverse order to handle dependencies
    rollback_sql.append("-- Delete purchase order lines first")
    receipt_ids_str = "', '".join(receipt_ids)
    rollback_sql.append(f"DELETE FROM purchase_order_line WHERE order_id IN (SELECT id FROM purchase_order WHERE name IN ('{receipt_ids_str}'));")
    rollback_sql.append("")

    rollback_sql.append("-- Delete purchase orders")
    rollback_sql.append(f"DELETE FROM purchase_order WHERE name IN ('{receipt_ids_str}');")
    rollback_sql.append("")

    rollback_sql.append("COMMIT;")
    rollback_sql.append("")
    rollback_sql.append("-- Note: This rollback only removes the purchase orders themselves.")
    rollback_sql.append("-- If you have validated/received these orders, use the full rollback script instead.")

    # Write to file
    with open('data/final_rollback_receipt_orders.sql', 'w') as f:
        f.write('\n'.join(rollback_sql))

    print(f"✅ Final rollback SQL saved to: data/final_rollback_receipt_orders.sql")


if __name__ == '__main__':
    generate_final_receipt_sql()
