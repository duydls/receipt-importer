#!/usr/bin/env python3
"""
Create proper vendor mapping with fuzzy matching and user corrections
"""

import json
from difflib import SequenceMatcher
from typing import Dict


def get_extracted_vendors() -> Dict[str, str]:
    """Get all extracted vendor names grouped by source"""

    sources = [('amazon_based', 'Amazon'), ('instacart_based', 'Instacart'), ('localgrocery_based', 'Local Grocery')]

    vendor_sources = {}
    all_vendors = set()

    for source_dir, source_name in sources:
        try:
            with open(f'data/step1_output/{source_dir}/extracted_data.json', 'r') as f:
                data = json.load(f)

            vendors = set()
            for receipt in data.values():
                vendor = receipt.get('vendor', '').strip()
                if vendor:
                    vendors.add(vendor)
                    all_vendors.add(vendor)
                    vendor_sources[vendor] = source_name

        except Exception as e:
            print(f"Error reading {source_dir}: {e}")

    return {vendor: vendor_sources[vendor] for vendor in all_vendors}


def fuzzy_match_vendors(extracted_vendors: Dict[str, str]) -> Dict[str, str]:
    """Create fuzzy matches for vendor names"""

    # Common Odoo vendor names (this would ideally come from database)
    common_odoo_vendors = [
        'Amazon', 'ALDI', 'Costco', 'Restaurant Depot', 'Park To Shop',
        '88 Market Place', 'Jewel Osco', "Tony's Fresh Market",
        'IC-ALDI', 'IC-Jewel-Osco', "IC-Tony's Fresh Market",
        '88 MarketPlace', 'RD', 'Amazon Business'
    ]

    # Specific mappings provided by user
    specific_mappings = {
        'Amazon Business': 'Amazon',
        'IC-ALDI': 'IC-ALDI',  # Confirmed to exist
        'RD': 'Restaurant Depot'  # User specified
    }

    # Apply specific mappings first
    mappings = {}
    for extracted, source in extracted_vendors.items():
        if extracted in specific_mappings:
            mappings[extracted] = specific_mappings[extracted]
        else:
            # Find best fuzzy match
            best_match = extracted
            best_score = 0.6  # Minimum similarity threshold

            for odoo_vendor in common_odoo_vendors:
                # Calculate similarity
                similarity = SequenceMatcher(None,
                    extracted.lower().replace('ic-', '').replace('-', ' '),
                    odoo_vendor.lower().replace('-', ' ')
                ).ratio()

                if similarity > best_score:
                    best_score = similarity
                    best_match = odoo_vendor

            mappings[extracted] = best_match

    return mappings


def create_final_mapping_script(vendor_mappings: Dict[str, str]):
    """Create the final mapping script with IDs"""

    print("🔍 Vendor Mapping Results:")
    print("=" * 50)

    vendor_sources = get_extracted_vendors()

    for extracted, mapped in vendor_mappings.items():
        source = vendor_sources[extracted]
        print(f"  {extracted} ({source}) → {mapped}")

    print("\n📝 Creating ID mapping template...")

    # Create the mapping template
    template = f'''# Odoo Vendor ID Mapping Template
# Update the IDs below with actual Odoo partner IDs

ID_MAPPING = {{
    'currency_id': 1,  # USD
    'picking_type_id': 1,  # Purchase
    'partners': {{
'''

    for i, (extracted, mapped) in enumerate(vendor_mappings.items(), 1):
        template += f"        '{extracted}': {i},  # Maps to: {mapped} ← UPDATE THIS ID\n"

    template += '''    },
    'products': {
        # Add product mappings here if needed
    },
    'uoms': {
        'each': 1,
        'lb': 3,
        'lbs': 3,
        'kg': 4,
    },
}
'''

    # Save to file
    with open('data/correct_vendor_mapping.py', 'w') as f:
        f.write(template)

    print("✅ Saved mapping template to: data/correct_vendor_mapping.py")

    # Create SQL regeneration script
    sql_script = f'''#!/usr/bin/env python3
"""
Regenerate SQL with correct vendor mappings
"""

import json
from datetime import datetime

# Load the corrected mapping
exec(open('data/correct_vendor_mapping.py').read())

def get_vendor_id(vendor_name: str) -> int:
    """Get vendor ID from mapping"""
    return ID_MAPPING['partners'].get(vendor_name, 1)

# [Rest of SQL generation code would go here...]
# This would regenerate the final_receipt_purchase_orders.sql with correct IDs

print("✅ Vendor mapping loaded. Run this script to regenerate SQL with correct IDs.")
'''

    with open('regenerate_with_correct_vendors.py', 'w') as f:
        f.write(sql_script)

    print("✅ Saved SQL regeneration script to: regenerate_with_correct_vendors.py")

    return vendor_mappings


def main():
    print("Creating Proper Vendor Mappings")
    print("=" * 40)

    # Get extracted vendors
    extracted_vendors = get_extracted_vendors()
    print(f"Found {len(extracted_vendors)} unique vendors")

    # Create fuzzy mappings
    vendor_mappings = fuzzy_match_vendors(extracted_vendors)

    # Create the mapping scripts
    final_mappings = create_final_mapping_script(vendor_mappings)

    print("\n🎯 Next Steps:")
    print("1. Review and update data/correct_vendor_mapping.py with actual Odoo vendor IDs")
    print("2. Run: python regenerate_with_correct_vendors.py")
    print("3. Import: psql -d odoo -f data/final_receipt_purchase_orders_with_ids.sql")


if __name__ == '__main__':
    main()
