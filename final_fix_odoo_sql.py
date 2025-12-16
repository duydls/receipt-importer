#!/usr/bin/env python3
"""
Final fix for Odoo purchase order SQL - add missing picking_type_id
"""

import json
from datetime import datetime


def fix_sql_with_picking_type():
    # Load extracted Odoo data
    with open('data/step1_output/odoo_based/extracted_data.json', 'r') as f:
        odoo_data = json.load(f)

    print(f"Creating final fixed SQL for {len(odoo_data)} purchase orders...")

    # Generate SQL for each receipt
    all_sql = []
    all_sql.append("-- FINAL FIXED SQL for All Odoo Purchase Orders (November 2025)")
    all_sql.append("-- Added all required fields: currency_id, picking_type_id")
    all_sql.append(f"-- Generated on {datetime.now().isoformat()}")
    all_sql.append("-- All order dates are in November 2025")
    all_sql.append("")

    # Sort orders by date for consistent ordering
    sorted_receipts = sorted(odoo_data.items(), key=lambda x: x[1].get('order_date', ''))

    total_items = 0
    total_value = 0

    for receipt_id, receipt_data in sorted_receipts:
        vendor_name = receipt_data.get('vendor', 'Unknown Vendor')
        order_date = receipt_data.get('order_date', datetime.now().isoformat())
        items = receipt_data.get('items', [])

        # Ensure date is in November 2025
        if order_date.startswith('2025-11'):
            pass  # Already correct
        else:
            order_date = '2025-11-15T12:00:00'

        # Create purchase order INSERT with ALL required fields
        po_sql = f"""
-- Purchase Order: {receipt_id} ({vendor_name})
INSERT INTO purchase_order (
    name, partner_id, currency_id, picking_type_id, date_order, date_planned,
    user_id, company_id, state, create_date, write_date, create_uid, write_uid
) VALUES (
    '{receipt_id}', 1, 1, 1, '{order_date}', '{order_date}',
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
    output_file = 'data/final_november_purchase_orders.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(all_sql))

    print(f"Final fixed SQL saved to: {output_file}")
    print(f"Contains {len(odoo_data)} purchase orders with {total_items} total items worth ${total_value:.2f}")

    print("\nNote: This SQL contains placeholder IDs. You will need to:")
    print("1. Update partner_id values with actual vendor IDs from your Odoo database")
    print("2. Update product_id values with actual product IDs")
    print("3. Update currency_id (currently set to 1, may need to be different)")
    print("4. Update picking_type_id (currently set to 1, may need to be different)")
    print("5. Update uom_id values with actual unit of measure IDs")
    print("6. Review and adjust the SQL before running it in Odoo")


if __name__ == '__main__':
    fix_sql_with_picking_type()
