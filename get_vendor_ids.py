#!/usr/bin/env python3
"""
Get actual vendor IDs from Odoo database for the extracted vendor names
"""

import json


def get_vendor_names():
    """Get all unique vendor names from the receipt data"""

    vendor_names = set()

    # Check all receipt sources
    sources = ['amazon_based', 'instacart_based', 'localgrocery_based']

    for source_dir in sources:
        try:
            with open(f'data/step1_output/{source_dir}/extracted_data.json', 'r') as f:
                receipt_data = json.load(f)

            for receipt in receipt_data.values():
                vendor = receipt.get('vendor', '').strip()
                if vendor:
                    vendor_names.add(vendor)
        except Exception as e:
            print(f"Error reading {source_dir}: {e}")

    return sorted(vendor_names)


def generate_vendor_id_queries():
    """Generate SQL queries to find vendor IDs"""

    vendor_names = get_vendor_names()

    print("🔍 SQL Queries to Find Vendor IDs in Odoo")
    print("=" * 50)
    print()

    print("📋 All vendor names found in receipts:")
    for name in vendor_names:
        print(f"   - {name}")
    print()

    print("🗄️  Run these queries in your Odoo database:")
    print()

    # Query for exact matches
    print("-- 1. Find exact matches:")
    vendor_list = "', '".join(vendor_names)
    print(f"SELECT id, name, supplier FROM res_partner WHERE name IN ('{vendor_list}') ORDER BY name;")
    print()

    # Query for partial matches (in case names are slightly different)
    print("-- 2. Find partial matches (if exact names don't work):")
    print("SELECT id, name, supplier FROM res_partner")
    print("WHERE supplier = true AND (")
    conditions = []
    for name in vendor_names:
        # Create flexible matching conditions
        if ' ' in name:
            words = name.split()
            word_conditions = " OR ".join([f"name ILIKE '%{word}%'" for word in words])
            conditions.append(f"({word_conditions})")
        else:
            conditions.append(f"name ILIKE '%{name}%'")
    print("    OR ".join(conditions))
    print(") ORDER BY name;")
    print()

    # Query for all suppliers (to see what's available)
    print("-- 3. See all suppliers (if needed for manual mapping):")
    print("SELECT id, name FROM res_partner WHERE supplier = true ORDER BY name LIMIT 50;")
    print()

    return vendor_names


def create_mapping_template(vendor_names):
    """Create a mapping template for updating the SQL"""

    print("📝 Mapping Template (update with actual IDs):")
    print("=" * 50)
    print()

    print("# Copy this into data/odoo_id_mapping.py and update the IDs")
    print("ID_MAPPING = {")
    print("    'currency_id': 1,  # USD")
    print("    'picking_type_id': 1,  # Purchase")
    print("    'partners': {")

    for name in vendor_names:
        clean_name = name.replace("'", "\\'")  # Escape single quotes
        print(f"        '{clean_name}': 1,  # ← UPDATE THIS ID")

    print("    },")
    print("    'products': {")
    print("        # Add product mappings here")
    print("    },")
    print("    'uoms': {")
    print("        'each': 1,")
    print("        'lb': 3,")
    print("        'lbs': 3,")
    print("        'kg': 4,")
    print("    },")
    print("}")
    print()

    print("💡 After updating the IDs, run:")
    print("python create_id_replacement_script.py --replace")


if __name__ == '__main__':
    vendor_names = generate_vendor_id_queries()
    create_mapping_template(vendor_names)
