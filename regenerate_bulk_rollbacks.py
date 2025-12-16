#!/usr/bin/env python3
"""
Regenerate bulk rollback scripts for November and receipt orders
"""

import json


def generate_november_rollback():
    """Generate rollback for November orders"""
    try:
        with open('data/step1_output/odoo_based/extracted_data.json', 'r') as f:
            odoo_data = json.load(f)

        order_names = list(odoo_data.keys())

        rollback_sql = []
        rollback_sql.append("-- Rollback SQL for November 2025 Purchase Orders")
        rollback_sql.append("-- This will delete the purchase orders and related records created above")
        rollback_sql.append("-- Generated for: " + ", ".join(order_names))
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

        print(f"✅ Regenerated November rollback: data/rollback_november_orders.sql")
        return True

    except Exception as e:
        print(f"❌ Failed to generate November rollback: {e}")
        return False


def generate_receipt_rollback():
    """Generate rollback for receipt-based purchase orders"""
    try:
        receipt_ids = []

        # Collect receipt IDs from all sources
        for source_dir in ['amazon_based', 'instacart_based', 'localgrocery_based']:
            try:
                with open(f'data/step1_output/{source_dir}/extracted_data.json', 'r') as f:
                    receipt_data = json.load(f)
                receipt_ids.extend(receipt_data.keys())
            except:
                pass

        if not receipt_ids:
            print("❌ No receipt IDs found")
            return False

        rollback_sql = []
        rollback_sql.append("-- Rollback SQL for Receipt-Based Purchase Orders")
        rollback_sql.append("-- This will delete purchase orders created from receipt processing")
        rollback_sql.append(f"-- Covers {len(receipt_ids)} receipts")
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

        print(f"✅ Regenerated receipt rollback: data/rollback_receipt_orders.sql")
        return True

    except Exception as e:
        print(f"❌ Failed to generate receipt rollback: {e}")
        return False


def main():
    print("Regenerating Bulk Rollback Scripts")
    print("=" * 40)

    success1 = generate_november_rollback()
    success2 = generate_receipt_rollback()

    if success1 and success2:
        print("\n✅ All rollback scripts regenerated successfully!")
        print("\n📄 Available rollback scripts:")
        print("  - data/rollback_november_orders.sql (4 November orders)")
        print("  - data/rollback_receipt_orders.sql (25 receipt orders)")
        print("  - scripts/rollback_purchase_order_validation.sql (general validation rollback)")
        print("  - Individual order rollbacks in data/sql/, data/ama_sql/, data/ins_sql/")
    else:
        print("\n❌ Some rollbacks failed to generate")


if __name__ == '__main__':
    main()
