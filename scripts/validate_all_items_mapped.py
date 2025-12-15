#!/usr/bin/env python3
"""
Validate that all product items are mapped to Odoo products
Reports any unmapped items and ensures data consistency
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def validate_mappings():
    """Validate that all product items have standard_name and odoo_product_id"""
    step1_output_dir = Path('data/step1_output')
    source_groups = ['localgrocery_based', 'instacart_based', 'amazon_based', 
                     'bbi_based', 'wismettac_based', 'wismettac_based']
    
    all_issues = []
    total_product_items = 0
    fully_mapped = 0
    
    for group in source_groups:
        data_file = step1_output_dir / group / 'extracted_data.json'
        if not data_file.exists():
            continue
            
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            for receipt_id, receipt in data.items():
                items = receipt.get('items', [])
                for item in items:
                    # Skip fees and summary items (they don't need product mapping)
                    if item.get('is_fee', False) or item.get('is_summary', False):
                        continue
                    
                    total_product_items += 1
                    
                    has_standard_name = bool(item.get('standard_name'))
                    has_odoo_product_id = bool(item.get('odoo_product_id'))
                    
                    if has_standard_name and has_odoo_product_id:
                        fully_mapped += 1
                    else:
                        issue = {
                            'receipt_id': receipt_id,
                            'source_group': group,
                            'product_name': item.get('product_name', 'N/A'),
                            'has_standard_name': has_standard_name,
                            'has_odoo_product_id': has_odoo_product_id,
                            'standard_name': item.get('standard_name'),
                            'odoo_product_id': item.get('odoo_product_id'),
                            'quantity': item.get('quantity'),
                            'total_price': item.get('total_price')
                        }
                        all_issues.append(issue)
    
    # Report results
    print("=" * 80)
    print("MAPPING VALIDATION REPORT")
    print("=" * 80)
    print(f"\nTotal product items: {total_product_items}")
    print(f"Fully mapped: {fully_mapped}")
    print(f"Unmapped or partially mapped: {len(all_issues)}\n")
    
    if all_issues:
        print("⚠ ISSUES FOUND:")
        print("=" * 80)
        
        # Group by source
        by_group = defaultdict(list)
        for issue in all_issues:
            by_group[issue['source_group']].append(issue)
        
        for group, issues in by_group.items():
            print(f"\n{group}: {len(issues)} unmapped items")
            for issue in issues:
                print(f"\n  Receipt: {issue['receipt_id']}")
                print(f"  Product: {issue['product_name'][:60]}")
                print(f"  Quantity: {issue['quantity']}, Price: ${issue['total_price']}")
                
                if not issue['has_standard_name'] and not issue['has_odoo_product_id']:
                    print(f"  ❌ Completely unmapped (missing both standard_name and odoo_product_id)")
                elif issue['has_standard_name'] and not issue['has_odoo_product_id']:
                    print(f"  ⚠ Partially mapped: has standard_name='{issue['standard_name']}' but missing odoo_product_id")
                elif issue['has_odoo_product_id'] and not issue['has_standard_name']:
                    print(f"  ⚠ Partially mapped: has odoo_product_id={issue['odoo_product_id']} but missing standard_name")
        
        print("\n" + "=" * 80)
        print("❌ VALIDATION FAILED: Some items are not fully mapped")
        print("=" * 80)
        return False
    else:
        print("=" * 80)
        print("✓ VALIDATION PASSED: All product items are fully mapped")
        print("=" * 80)
        return True


def main():
    """Main function"""
    success = validate_mappings()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

