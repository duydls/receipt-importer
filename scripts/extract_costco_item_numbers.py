#!/usr/bin/env python3
"""
Extract item numbers from Costco receipts.

This script:
1. Loads Costco receipts from extracted_data.json
2. Extracts all item numbers from Costco receipts
3. Outputs a list of unique item numbers with their product names
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

KB_PATH = Path('data/step1_input/knowledge_base.json')
EXTRACTED_DATA_PATH = Path('data/step1_output/localgrocery_based/extracted_data.json')


def load_extracted_data() -> Dict:
    """Load extracted data from JSON file."""
    if not EXTRACTED_DATA_PATH.exists():
        print(f"Error: Extracted data not found at {EXTRACTED_DATA_PATH}", file=sys.stderr)
        sys.exit(1)
    
    with EXTRACTED_DATA_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def extract_costco_item_numbers(extracted_data: Dict) -> List[Tuple[str, str, str]]:
    """
    Extract item numbers from Costco receipts.
    
    Returns:
        List of tuples: (item_number, product_name, receipt_id)
    """
    item_numbers = []
    
    for receipt_id, receipt_data in extracted_data.items():
        vendor = receipt_data.get('vendor', '').upper()
        detected_vendor = receipt_data.get('detected_vendor_code', '').upper()
        
        # Check if this is a Costco receipt
        if 'COSTCO' not in vendor and 'COSTCO' not in detected_vendor:
            continue
        
        items = receipt_data.get('items', [])
        for item in items:
            if item.get('is_fee', False):
                continue
            
            item_number = item.get('item_number') or item.get('item_code')
            product_name = item.get('product_name') or item.get('name') or ''
            
            if item_number:
                # Convert to string and strip
                item_number = str(item_number).strip()
                product_name = str(product_name).strip()
                
                if item_number:
                    item_numbers.append((item_number, product_name, receipt_id))
    
    return item_numbers


def get_unique_item_numbers(item_numbers: List[Tuple[str, str, str]]) -> Dict[str, Dict]:
    """
    Get unique item numbers with their product names.
    
    Returns:
        Dict mapping item_number to {product_names: List[str], receipt_ids: List[str]}
    """
    unique_items = {}
    
    for item_number, product_name, receipt_id in item_numbers:
        if item_number not in unique_items:
            unique_items[item_number] = {
                'product_names': [],
                'receipt_ids': []
            }
        
        # Add product name if not already present
        if product_name and product_name not in unique_items[item_number]['product_names']:
            unique_items[item_number]['product_names'].append(product_name)
        
        # Add receipt ID if not already present
        if receipt_id and receipt_id not in unique_items[item_number]['receipt_ids']:
            unique_items[item_number]['receipt_ids'].append(receipt_id)
    
    return unique_items


def main():
    print("Loading extracted data...")
    extracted_data = load_extracted_data()
    
    print("Extracting Costco item numbers...")
    item_numbers = extract_costco_item_numbers(extracted_data)
    
    print(f"Found {len(item_numbers)} item number entries")
    
    print("Getting unique item numbers...")
    unique_items = get_unique_item_numbers(item_numbers)
    
    print(f"\nFound {len(unique_items)} unique Costco item numbers\n")
    print("=" * 100)
    
    # Sort by item number
    sorted_items = sorted(unique_items.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)
    
    # Print all item numbers
    for item_number, data in sorted_items:
        product_names = data['product_names']
        receipt_ids = data['receipt_ids']
        
        print(f"\nItem Number: {item_number}")
        print(f"  Product Names: {', '.join(product_names) if product_names else 'N/A'}")
        print(f"  Found in {len(receipt_ids)} receipt(s)")
        if len(receipt_ids) <= 3:
            print(f"  Receipt IDs: {', '.join(receipt_ids)}")
        else:
            print(f"  Receipt IDs: {', '.join(receipt_ids[:3])}... (and {len(receipt_ids) - 3} more)")
    
    # Summary
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"Total unique item numbers: {len(unique_items)}")
    print(f"Total item number entries: {len(item_numbers)}")
    
    # Save to JSON
    output_path = Path('data/step1_input/costco_item_numbers.json')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        'total_unique_items': len(unique_items),
        'total_entries': len(item_numbers),
        'items': {
            item_number: {
                'product_names': data['product_names'],
                'receipt_count': len(data['receipt_ids']),
                'receipt_ids': data['receipt_ids']
            }
            for item_number, data in sorted_items
        }
    }
    
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved to: {output_path}")


if __name__ == '__main__':
    main()

