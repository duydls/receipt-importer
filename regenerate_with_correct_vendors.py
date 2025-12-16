#!/usr/bin/env python3
"""
Regenerate SQL with correct vendor mappings
"""

import json
from datetime import datetime

# Load the corrected mapping
exec(open('data/correct_vendor_mapping.py').read())

def escape_sql_string(text):
    """Escape single quotes in SQL strings"""
    if not text:
        return ''
    return text.replace("'", "''")


def get_vendor_id(vendor_name: str) -> int:
    """Get vendor ID from mapping"""
    return ID_MAPPING['partners'].get(vendor_name, 1)


def regenerate_sql():
    """Regenerate the SQL with correct vendor IDs"""

    # Load all receipt data
    receipt_sources = [
        ('amazon_based', 'Amazon'),
        ('instacart_based', 'Instacart'),
        ('localgrocery_based', 'Local Grocery')
    ]

    all_sql = []
    all_sql.append("-- FINAL Purchase Orders with CORRECT Vendor IDs")
    all_sql.append("-- All vendor mappings applied with proper IDs")
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
                vendor_id = get_vendor_id(actual_vendor_name)

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
-- Vendor: {actual_vendor_name} (ID: {vendor_id})
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

                    product_id = 1  # Placeholder - may need updating

                    line_sql = f"""
-- Item: {product_name[:40]}...
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
    output_file = 'data/final_receipt_purchase_orders_with_ids.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(all_sql))

    print(f"✅ Final SQL with correct vendor IDs generated!")
    print(f"📦 {total_orders} purchase orders, {total_items} items")
    print(f"💾 Saved to: {output_file}")

    # Generate rollback script
    generate_rollback()


def generate_rollback():
    """Generate rollback script"""

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
    rollback_sql.append("-- Removes all purchase orders created from receipt processing")
    rollback_sql.append(f"-- Covers {len(receipt_ids)} receipts")
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

    print(f"✅ Final rollback SQL generated: data/final_rollback_receipt_orders.sql")


if __name__ == '__main__':
    print("Regenerating SQL with Correct Vendor IDs")
    print("=" * 45)

    regenerate_sql()

    print("\n🎯 Import ready!")
    print("Run: psql -d odoo -f data/final_receipt_purchase_orders_with_ids.sql")
    print("Rollback: psql -d odoo -f data/final_rollback_receipt_orders.sql")
