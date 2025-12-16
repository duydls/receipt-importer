#!/usr/bin/env python3
"""
Create rollback SQL for November orders
"""

# Load extracted Odoo data
import json
from datetime import datetime

with open('data/step1_output/odoo_based/extracted_data.json', 'r') as f:
    odoo_data = json.load(f)

order_names = list(odoo_data.keys())

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
with open('data/rollback_november_orders.sql', 'w') as f:
    f.write('\n'.join(rollback_sql))

print(f"Rollback SQL created for {len(order_names)} orders: data/rollback_november_orders.sql")
