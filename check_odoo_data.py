#!/usr/bin/env python3
import json

# Load the extracted data
with open('data/step1_output/odoo_based/extracted_data.json', 'r') as f:
    odoo_data = json.load(f)

print('Found Odoo receipts:')
for receipt_id, data in odoo_data.items():
    vendor = data.get('vendor', 'Unknown')
    total = data.get('total_amount', 0)
    item_count = len(data.get('items', []))
    print(f'  {receipt_id}: {vendor} - {item_count} items - ${total:.2f}')

print(f'\nTotal: {len(odoo_data)} Odoo receipts ready for SQL generation')
