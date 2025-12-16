#!/usr/bin/env python3
"""
Generate purchase orders from ALL processed receipts (except Odoo orders)
"""

import json
from datetime import datetime
from typing import Dict, List, Any


def get_vendor_id_from_receipt(vendor_name: str) -> int:
    """Map receipt vendor names to Odoo partner IDs (placeholders)"""
    vendor_map = {
        'Amazon Business': 200,      # Amazon
        'IC-ALDI': 201,              # Instacart ALDI
        'Costco': 202,               # Costco
        'Restaurant Depot': 203,     # RD
        'ALDI': 204,                 # ALDI
        'Jewel-Osco': 205,           # Jewel
        'Parktoshop': 206,           # Parktoshop
    }

    # Try exact match first
    if vendor_name in vendor_map:
        return vendor_map[vendor_name]

    # Try partial matches
    for key, value in vendor_map.items():
        if key.lower() in vendor_name.lower():
            return value

    return 100  # Default unknown vendor


def process_receipt_data(receipt_data: Dict[str, Any], source_type: str) -> tuple:
    """Process a single receipt into purchase order data"""

    receipt_id = receipt_data.get('receipt_id', f"{source_type}_{id(receipt_data)}")
    vendor_name = receipt_data.get('vendor', 'Unknown Vendor')
    transaction_date = receipt_data.get('transaction_date', datetime.now().isoformat())
    items = receipt_data.get('items', [])

    # Ensure date is in November 2025 (assume these are November purchases)
    if transaction_date.startswith('2025-11'):
        pass  # Already correct
    else:
        transaction_date = '2025-11-15T12:00:00'  # Default to mid-November

    # Filter out non-product items
    product_items = []
    for item in items:
        if not item.get('is_fee', False) and not item.get('is_summary', False):
            product_items.append(item)

    if not product_items:
        return None, None  # No products to order

    # Create purchase order data
    po_data = {
        'receipt_id': receipt_id,
        'vendor_name': vendor_name,
        'order_date': transaction_date,
        'source_type': source_type,
        'items': product_items
    }

    # Calculate totals
    total_value = sum(item.get('total_price', 0) for item in product_items)

    return po_data, total_value


def generate_purchase_order_sql(po_data: Dict[str, Any]) -> str:
    """Generate SQL for a single purchase order from receipt data"""

    receipt_id = po_data['receipt_id']
    vendor_name = po_data['vendor_name']
    order_date = po_data['order_date']
    source_type = po_data['source_type']
    items = po_data['items']

    vendor_id = get_vendor_id_from_receipt(vendor_name)

    # Create purchase order INSERT
    po_sql = f"""
-- Purchase Order from {source_type.upper()} receipt: {receipt_id} ({vendor_name})
INSERT INTO purchase_order (
    name, partner_id, currency_id, picking_type_id, date_order, date_planned,
    user_id, company_id, state, create_date, write_date, create_uid, write_uid
) VALUES (
    '{receipt_id}', {vendor_id}, 1, 1, '{order_date}', '{order_date}',
    2, 1, 'draft', NOW(), NOW(), 2, 2
) RETURNING id;"""

    # Create purchase order lines
    line_sqls = []
    for i, item in enumerate(items):
        product_name = item.get('product_name') or item.get('display_name') or 'Unknown Product'
        quantity = item.get('quantity', 1)
        unit_price = item.get('unit_price', 0)

        # Try to get UOM from various fields
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
            uom_id = 5  # Assuming 5 is oz
        elif 'count' in uom_name.lower() or 'pc' in uom_name.lower():
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

        line_sqls.append(line_sql)

    return po_sql + '\n'.join(line_sqls) + '\n'


def main():
    print("Generating Purchase Orders from ALL Processed Receipts")
    print("=" * 60)

    # Process all receipt types except Odoo
    receipt_sources = [
        ('amazon_based', 'Amazon'),
        ('instacart_based', 'Instacart'),
        ('localgrocery_based', 'Local Grocery')
    ]

    all_sql = []
    all_sql.append("-- Purchase Orders Generated from ALL Processed Receipts")
    all_sql.append("-- Excludes Odoo orders (already imported separately)")
    all_sql.append(f"-- Generated on {datetime.now().isoformat()}")
    all_sql.append("")

    total_orders = 0
    total_items = 0
    total_value = 0
    source_stats = {}

    for source_dir, source_name in receipt_sources:
        try:
            with open(f'data/step1_output/{source_dir}/extracted_data.json', 'r') as f:
                receipt_data = json.load(f)

            source_stats[source_name] = {'receipts': 0, 'items': 0, 'value': 0}

            all_sql.append(f"-- === {source_name.upper()} RECEIPTS ===")
            all_sql.append("")

            for receipt_id, receipt in receipt_data.items():
                po_data, receipt_value = process_receipt_data(receipt, source_name.lower())

                if po_data:
                    sql = generate_purchase_order_sql(po_data)
                    all_sql.append(sql)

                    item_count = len(po_data['items'])
                    total_orders += 1
                    total_items += item_count
                    total_value += receipt_value

                    source_stats[source_name]['receipts'] += 1
                    source_stats[source_name]['items'] += item_count
                    source_stats[source_name]['value'] += receipt_value

        except Exception as e:
            print(f"Error processing {source_dir}: {e}")

    # Add summary
    all_sql.insert(3, f"-- Total: {total_orders} orders, {total_items} items, ${total_value:.2f}")
    all_sql.insert(4, "")

    # Write to file
    output_file = 'data/all_receipt_purchase_orders.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(all_sql))

    print(f"✅ Generated SQL for {total_orders} purchase orders from receipts")
    print(f"📦 Total items: {total_items}, Total value: ${total_value:.2f}")
    print(f"💾 Saved to: {output_file}")
    print()

    print("📊 Breakdown by source:")
    for source, stats in source_stats.items():
        print(f"  {source}: {stats['receipts']} receipts, {stats['items']} items, ${stats['value']:.2f}")

    print("\n⚠️  IMPORTANT: Before running this SQL:")
    print("1. Update partner_id values with actual vendor IDs from your Odoo database")
    print("2. Update product_id values with actual product IDs")
    print("3. Update currency_id (currently set to 1, may need to be different)")
    print("4. Update picking_type_id (currently set to 1, may need to be different)")
    print("5. Update uom_id values with actual unit of measure IDs")
    print("6. Review dates - all set to November 2025")

    # Generate rollback for these orders too
    generate_receipt_rollback()


def generate_receipt_rollback():
    """Generate rollback SQL for receipt-based purchase orders"""

    # Collect all receipt IDs that will be created
    receipt_ids = []

    for source_dir in ['amazon_based', 'instacart_based', 'localgrocery_based']:
        try:
            with open(f'data/step1_output/{source_dir}/extracted_data.json', 'r') as f:
                receipt_data = json.load(f)

            for receipt_id in receipt_data.keys():
                receipt_ids.append(receipt_id)
        except:
            pass

    if not receipt_ids:
        return

    rollback_sql = []
    rollback_sql.append("-- Rollback SQL for Receipt-Based Purchase Orders")
    rollback_sql.append("-- This will delete purchase orders created from receipt processing")
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
    with open('data/rollback_receipt_orders.sql', 'w') as f:
        f.write('\n'.join(rollback_sql))

    print(f"🔄 Rollback SQL created: data/rollback_receipt_orders.sql")


if __name__ == '__main__':
    main()
