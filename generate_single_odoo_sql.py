#!/usr/bin/env python3
"""
Generate a single SQL file for all Odoo purchase orders from extracted Excel data
All dates are in November 2025
"""

import json
from datetime import datetime
from typing import Dict, List, Any


def get_vendor_id(vendor_name: str) -> int:
    """Map vendor names to Odoo partner IDs"""
    vendor_map = {
        '88 MarketPlace': 123,  # You'll need to update these with actual IDs
        'Park To Shop': 124,
        'Pick & Get': 125,
        'Young Shing Foods, Inc': 126,
        '88 MarketPlace': 123,
        'Park To Shop': 124,
        'Pick & Get': 125,
        'Young Shing Foods, Inc': 126
    }
    return vendor_map.get(vendor_name, 1)  # Default to admin user


def generate_purchase_order_sql(receipt_id: str, receipt_data: Dict[str, Any]) -> tuple:
    """Generate SQL for a single purchase order and its lines"""

    vendor_name = receipt_data.get('vendor', 'Unknown Vendor')
    vendor_id = get_vendor_id(vendor_name)
    order_date = receipt_data.get('order_date', datetime.now().isoformat())
    items = receipt_data.get('items', [])

    # Ensure date is in November 2025
    if order_date.startswith('2025-11'):
        pass  # Already correct
    else:
        # Fallback to November 15, 2025 if date is invalid
        order_date = '2025-11-15T12:00:00'

    # Create purchase order INSERT
    po_sql = f"""
-- Purchase Order: {receipt_id} ({vendor_name})
INSERT INTO purchase_order (
    name, partner_id, date_order, date_planned, user_id, company_id,
    state, create_date, write_date, create_uid, write_uid
) VALUES (
    '{receipt_id}', {vendor_id}, '{order_date}', '{order_date}', 2, 1,
    'draft', NOW(), NOW(), 2, 2
) RETURNING id;"""

    # Create purchase order lines
    line_sqls = []
    for i, item in enumerate(items):
        product_name = item.get('product_name', 'Unknown Product')
        quantity = item.get('quantity', 0)
        unit_price = item.get('unit_price', 0)
        uom_name = item.get('purchase_uom', 'each')

        # Map UoM names to IDs (simplified)
        uom_id = 1  # Default to 'each'
        if uom_name.lower() in ['lb', 'lbs', 'pound', 'pounds']:
            uom_id = 3  # Assuming 3 is lbs
        elif uom_name.lower() in ['kg', 'kilogram']:
            uom_id = 4  # Assuming 4 is kg
        elif 'pc' in uom_name.lower() or 'count' in uom_name.lower():
            uom_id = 1  # each/count

        # Create product if it doesn't exist (simplified - assumes products exist)
        product_id = 1  # Default product ID - you'll need to map actual products

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
        line_sqls.append(line_sql)

    return po_sql, line_sqls


def main():
    # Load extracted Odoo data
    with open('data/step1_output/odoo_based/extracted_data.json', 'r') as f:
        odoo_data = json.load(f)

    print(f"Generating single SQL file for {len(odoo_data)} purchase orders...")

    # Generate SQL for each receipt
    all_sql = []
    all_sql.append("-- Generated SQL for All Odoo Purchase Orders (November 2025)")
    all_sql.append(f"-- Generated on {datetime.now().isoformat()}")
    all_sql.append("-- All order dates are in November 2025")
    all_sql.append("")

    # Sort orders by date for consistent ordering
    sorted_receipts = sorted(odoo_data.items(), key=lambda x: x[1].get('order_date', ''))

    total_items = 0
    total_value = 0

    for receipt_id, receipt_data in sorted_receipts:
        po_sql, line_sqls = generate_purchase_order_sql(receipt_id, receipt_data)

        all_sql.append(po_sql)
        all_sql.extend(line_sqls)
        all_sql.append("")

        # Update totals
        items = receipt_data.get('items', [])
        total_items += len(items)
        total_value += sum(item.get('total_price', 0) for item in items)

    # Add summary comment
    all_sql.insert(3, f"-- Total: {len(odoo_data)} orders, {total_items} items, ${total_value:.2f}")
    all_sql.insert(4, "")

    # Write to file
    output_file = 'data/all_odoo_purchase_orders.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(all_sql))

    print(f"Single SQL file generated and saved to: {output_file}")
    print(f"Contains {len(odoo_data)} purchase orders with {total_items} total items worth ${total_value:.2f}")

    print("\nNote: This SQL contains placeholder IDs. You will need to:")
    print("1. Update vendor_id values with actual partner IDs from your Odoo database")
    print("2. Update product_id values with actual product IDs")
    print("3. Update uom_id values with actual unit of measure IDs")
    print("4. Review and adjust the SQL before running it in Odoo")


if __name__ == '__main__':
    main()
