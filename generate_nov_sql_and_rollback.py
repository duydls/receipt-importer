#!/usr/bin/env python3
"""
Generate SQL for November 2025 purchase orders and rollback script
"""

import json
from datetime import datetime


def get_vendor_id(vendor_name: str) -> int:
    """Map vendor names to Odoo partner IDs (placeholders)"""
    vendor_map = {
        '88 MarketPlace': 123,
        'Park To Shop': 124,
        'Pick & Get': 125,
        'Young Shing Foods, Inc': 126,
    }
    return vendor_map.get(vendor_name, 1)


def generate_purchase_order_sql():
    """Generate SQL for all November purchase orders"""

    # Load extracted Odoo data
    with open('data/step1_output/odoo_based/extracted_data.json', 'r') as f:
        odoo_data = json.load(f)

    print(f"Generating SQL for {len(odoo_data)} November purchase orders...")

    # Generate SQL for each receipt
    all_sql = []
    all_sql.append("-- SQL for All Odoo Purchase Orders (November 2025)")
    all_sql.append("-- IMPORTANT: Replace placeholder IDs with actual Odoo IDs")
    all_sql.append(f"-- Generated on {datetime.now().isoformat()}")
    all_sql.append("-- All order dates are in November 2025")
    all_sql.append("")

    # Sort orders by date for consistent ordering
    sorted_receipts = sorted(odoo_data.items(), key=lambda x: x[1].get('order_date', ''))

    total_items = 0
    total_value = 0

    order_names = []  # For rollback script

    for receipt_id, receipt_data in sorted_receipts:
        vendor_name = receipt_data.get('vendor', 'Unknown Vendor')
        order_date = receipt_data.get('order_date', datetime.now().isoformat())
        items = receipt_data.get('items', [])

        # Ensure date is in November 2025
        if order_date.startswith('2025-11'):
            pass  # Already correct
        else:
            order_date = '2025-11-15T12:00:00'

        order_names.append(receipt_id)

        # Create purchase order INSERT with required fields
        po_sql = f"""
-- Purchase Order: {receipt_id} ({vendor_name})
INSERT INTO purchase_order (
    name, partner_id, currency_id, date_order, date_planned,
    user_id, company_id, state, create_date, write_date, create_uid, write_uid
) VALUES (
    '{receipt_id}', {get_vendor_id(vendor_name)}, 1, '{order_date}', '{order_date}',
    2, 1, 'draft', NOW(), NOW(), 2, 2
) RETURNING id;"""

        all_sql.append(po_sql)

        # Create purchase order lines
        if items:
            for i, item in enumerate(items):
                product_name = item.get('product_name', 'Unknown Product')
                quantity = item.get('quantity', 0)
                unit_price = item.get('unit_price', 0)
                uom_name = item.get('purchase_uom', 'each')

                # Map UoM names to IDs
                uom_id = 1  # Default to 'each'
                if uom_name.lower() in ['lb', 'lbs', 'pound', 'pounds']:
                    uom_id = 3
                elif uom_name.lower() in ['kg', 'kilogram']:
                    uom_id = 4
                elif 'pc' in uom_name.lower() or 'count' in uom_name.lower():
                    uom_id = 1

                # Use placeholder product_id
                product_id = 1

                line_sql = f"""
-- Purchase Order Line: {product_name}
INSERT INTO purchase_order_line (
    order_id, product_id, name, product_qty, price_unit, product_uom,
    date_planned, sequence, company_id, create_date, write_date, create_uid, write_uid
) VALUES (
    (SELECT id FROM purchase_order WHERE name = '{receipt_id}'), {product_id},
    '{product_name}', {quantity}, {unit_price}, {uom_id},
    '{order_date}', {i*10}, 1, NOW(), NOW(), 2, 2
);"""

                all_sql.append(line_sql)

        all_sql.append("")

        # Update totals
        total_items += len(items)
        total_value += sum(item.get('total_price', 0) for item in items)

    # Add summary comment
    all_sql.insert(3, f"-- Total: {len(odoo_data)} orders, {total_items} items, ${total_value:.2f}")
    all_sql.insert(4, "")

    # Write to file
    output_file = 'data/november_purchase_orders.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(all_sql))

    print(f"Purchase order SQL saved to: {output_file}")

    # Generate rollback script
    generate_rollback_sql(order_names)

    return order_names


def generate_rollback_sql(order_names):
    """Generate rollback script for November orders"""

    rollback_sql = []
    rollback_sql.append("-- Rollback SQL for November 2025 Purchase Orders")
    rollback_sql.append("-- This will delete the purchase orders and related records created above")
    rollback_sql.append(f"-- Generated on {datetime.now().isoformat()}")
    rollback_sql.append("")
    rollback_sql.append("BEGIN;")
    rollback_sql.append("")

    # Delete in reverse order to handle dependencies
    rollback_sql.append("-- Delete purchase order lines first")
    order_names_str = "', '".join(order_names)
    rollback_sql.append(f"DELETE FROM purchase_order_line WHERE order_id IN (SELECT id FROM purchase_order WHERE name IN ('{order_names_str}'));")
    rollback_sql.append("")

    rollback_sql.append("-- Delete purchase orders")
    rollback_sql.append(f"DELETE FROM purchase_order WHERE name IN ('{order_names_str}');")
    rollback_sql.append("")

    rollback_sql.append("COMMIT;")
    rollback_sql.append("")
    rollback_sql.append("-- Note: This rollback only removes the purchase orders themselves.")
    rollback_sql.append("-- If you have validated/received these orders, use the full rollback script instead.")

    # Write to file
    output_file = 'data/rollback_november_orders.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(rollback_sql))

    print(f"Rollback SQL saved to: {output_file}")


def main():
    print("Generating November 2025 Purchase Orders SQL and Rollback")
    print("=" * 60)

    order_names = generate_purchase_order_sql()

    print(f"\n✅ Generated SQL for {len(order_names)} November purchase orders")
    print("\n📋 Files created:")
    print("  - data/november_purchase_orders.sql (create orders)")
    print("  - data/rollback_november_orders.sql (rollback orders)")
    print("  - data/odoo_id_mapping.py (ID replacement template)")
    print("  - create_id_replacement_script.py (replacement tool)")

    print("\n⚠️  IMPORTANT: Before running the SQL:")
    print("1. Update all placeholder IDs (123, 124, 125, 126) with actual vendor IDs")
    print("2. Update product_id (1) with actual product IDs")
    print("3. Update currency_id (1) if needed")
    print("4. Update uom_id values if needed")

    print("\n🔧 To replace IDs automatically:")
    print("1. Edit data/odoo_id_mapping.py with actual IDs")
    print("2. Run: python create_id_replacement_script.py --replace")


if __name__ == '__main__':
    main()
