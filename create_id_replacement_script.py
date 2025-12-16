#!/usr/bin/env python3
"""
Script to replace placeholder IDs in Odoo purchase order SQL
"""

import re
from pathlib import Path


def create_id_mapping_template():
    """Create a template for ID mappings"""
    template = """
# Odoo ID Mapping Template
# Replace the placeholder values below with actual IDs from your Odoo database

ID_MAPPING = {
    # Currency IDs (usually 1 for USD)
    'currency_id': 1,  # USD currency

    # Vendor/Partner IDs (run: SELECT id, name FROM res_partner WHERE supplier = true)
    'partners': {
        '88 MarketPlace': 123,        # Replace with actual ID
        'Park To Shop': 124,          # Replace with actual ID
        'Pick & Get': 125,            # Replace with actual ID
        'Young Shing Foods, Inc': 126, # Replace with actual ID
    },

    # Product IDs (run: SELECT pp.id, pt.name FROM product_product pp JOIN product_template pt ON pp.product_tmpl_id = pt.id)
    'products': {
        'Basil': 1,                           # Replace with actual ID
        'Tapioca Pearl (white)': 2,           # Replace with actual ID
        'Chicken Breast': 3,                  # Replace with actual ID
        'Chicken Paws': 4,                    # Replace with actual ID
        'Poke Bone': 5,                       # Replace with actual ID
        'Mango flavor ice cream': 6,          # Replace with actual ID
        'Vegetable Oil': 7,                   # Replace with actual ID
        'Scallion Pancake': 8,                # Replace with actual ID
        'Tornado Potato': 9,                  # Replace with actual ID
        'Difference': 10,                     # Replace with actual ID
        'Whipped Cream Stabilizer Powder': 11, # Replace with actual ID
    },

    # Unit of Measure IDs (run: SELECT id, name FROM uom_uom)
    'uoms': {
        'each': 1,    # Unit
        'lb': 3,      # Pound
        'lbs': 3,     # Pound
        'kg': 4,      # Kilogram
        '5-pc': 1,    # Each (pack of 5)
    },
}
"""
    return template


def replace_ids_in_sql(sql_file, mapping_file):
    """Replace placeholder IDs in SQL file using mapping"""

    # Read the mapping file
    with open(mapping_file, 'r') as f:
        mapping_content = f.read()

    # Extract the ID_MAPPING dictionary (this is a bit hacky but works)
    # In a real scenario, you'd want to import this as a Python module
    mapping = {}

    try:
        # Execute the mapping content to get the dictionary
        exec(mapping_content, {}, mapping)
        id_mapping = mapping.get('ID_MAPPING', {})
    except Exception as e:
        print(f"Error reading mapping file: {e}")
        return False

    # Read the SQL file
    with open(sql_file, 'r') as f:
        sql_content = f.read()

    # Replace currency_id
    currency_id = id_mapping.get('currency_id', 1)
    sql_content = re.sub(r'currency_id,\s*(\d+)', f'currency_id, {currency_id}', sql_content)

    # Replace partner IDs
    partners = id_mapping.get('partners', {})
    for vendor_name, partner_id in partners.items():
        # Replace in purchase_order inserts
        pattern = f"'{re.escape(vendor_name)}',\\s*(\\d+),"
        replacement = f"'{vendor_name}', {partner_id},"
        sql_content = re.sub(pattern, replacement, sql_content)

    # Replace product IDs
    products = id_mapping.get('products', {})
    for product_name, product_id in products.items():
        # Replace in purchase_order_line inserts
        pattern = f"'{re.escape(product_name)}',\\s*(\\d+),"
        replacement = f"'{product_name}', {product_id},"
        sql_content = re.sub(pattern, replacement, sql_content)

    # Replace UOM IDs
    uoms = id_mapping.get('uoms', {})
    for uom_name, uom_id in uoms.items():
        # This is trickier since UOMs are referenced by ID, not name
        # For now, we'll leave this as-is since the SQL already has the right UOM IDs

        # Write back the updated SQL
        output_file = sql_file.replace('.sql', '_with_ids.sql')
        with open(output_file, 'w') as f:
            f.write(sql_content)

        print(f"Updated SQL saved to: {output_file}")
        return True


def main():
    print("Odoo SQL ID Replacement Tool")
    print("=" * 40)

    # Create the mapping template
    mapping_file = 'data/odoo_id_mapping.py'
    with open(mapping_file, 'w') as f:
        f.write(create_id_mapping_template())

    print(f"Created ID mapping template: {mapping_file}")
    print("\nInstructions:")
    print("1. Edit the ID_MAPPING dictionary with actual IDs from your Odoo database")
    print("2. Run: python create_id_replacement_script.py --replace")
    print("3. The updated SQL will be saved as 'fixed_all_odoo_purchase_orders_with_ids.sql'")

    # Check if --replace flag is provided
    import sys
    if '--replace' in sys.argv:
        sql_file = 'data/fixed_all_odoo_purchase_orders.sql'
        if Path(sql_file).exists():
            print(f"\nReplacing IDs in {sql_file}...")
            success = replace_ids_in_sql(sql_file, mapping_file)
            if success:
                print("✅ ID replacement completed!")
            else:
                print("❌ ID replacement failed!")
        else:
            print(f"❌ SQL file not found: {sql_file}")


if __name__ == '__main__':
    main()
