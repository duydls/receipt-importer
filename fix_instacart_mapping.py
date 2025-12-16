#!/usr/bin/env python3
"""
Fix Instacart vendor mappings to keep IC- prefix
"""

import json


def get_vendor_sources():
    """Get vendors grouped by source"""
    sources = [('amazon_based', 'Amazon'), ('instacart_based', 'Instacart'), ('localgrocery_based', 'Local Grocery')]

    vendor_sources = {}
    for source_dir, source_name in sources:
        try:
            with open(f'data/step1_output/{source_dir}/extracted_data.json', 'r') as f:
                data = json.load(f)

            for receipt in data.values():
                vendor = receipt.get('vendor', '').strip()
                if vendor:
                    vendor_sources[vendor] = source_name
        except Exception as e:
            print(f"Error reading {source_dir}: {e}")

    return vendor_sources


def create_corrected_mapping():
    """Create mapping with IC- prefix for Instacart vendors"""

    vendor_sources = get_vendor_sources()

    # Specific mappings with corrections
    corrected_mappings = {
        # Amazon
        'Amazon Business': 'Amazon',

        # Instacart - KEEP IC- prefix
        'IC-ALDI': 'IC-ALDI',
        'IC-Jewel-Osco': 'IC-Jewel-Osco',  # Keep IC- prefix
        "IC-Tony's Fresh Market": "IC-Tony's Fresh Market",  # Keep IC- prefix

        # Local Grocery
        '88 MarketPlace': '88 MarketPlace',
        'Costco': 'Costco',
        'Park To Shop': 'Park To Shop',
        'RD': 'Restaurant Depot',
    }

    print("✅ Corrected Vendor Mappings:")
    print("=" * 50)

    for extracted, mapped in corrected_mappings.items():
        source = vendor_sources.get(extracted, 'Unknown')
        status = "✅ IC- prefix kept" if source == 'Instacart' and mapped.startswith('IC-') else "✅ Corrected"
        print(f"  {extracted} ({source}) → {mapped} {status}")

    # Update the mapping template
    template = '''# Odoo Vendor ID Mapping Template - CORRECTED
# Instacart vendors keep IC- prefix
# Update the IDs below with actual Odoo partner IDs

ID_MAPPING = {
    'currency_id': 1,  # USD
    'picking_type_id': 1,  # Purchase
    'partners': {
'''

    for i, (extracted, mapped) in enumerate(corrected_mappings.items(), 1):
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

    # Save updated template
    with open('data/correct_vendor_mapping.py', 'w') as f:
        f.write(template)

    print("\n✅ Updated mapping template: data/correct_vendor_mapping.py")
    print("🎯 All Instacart vendors now keep the IC- prefix!")

    return corrected_mappings


def main():
    print("Fixing Instacart Vendor Mappings")
    print("=" * 40)

    corrected_mappings = create_corrected_mapping()

    print("\n📋 Final Vendor Mappings:")
    for extracted, mapped in corrected_mappings.items():
        print(f"   {extracted} → {mapped}")

    print("\n🎯 Next Steps:")
    print("1. Update the IDs in data/correct_vendor_mapping.py with actual Odoo vendor IDs")
    print("2. Run: python regenerate_with_correct_vendors.py")
    print("3. Import: psql -d odoo -f data/final_receipt_purchase_orders_with_ids.sql")


if __name__ == '__main__':
    main()
