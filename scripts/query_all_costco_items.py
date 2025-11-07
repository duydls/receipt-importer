#!/usr/bin/env python3
"""
Query all Costco item numbers from receipts using Instacart Costco search.

This script:
1. Loads Costco item numbers from costco_item_numbers.json
2. Queries each item number using Instacart Costco search
3. Shows all search results for each item number
"""

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Any

# Import the Instacart Costco search function
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))
try:
    from instacart_costco_search import get_session, search_by_upc_graphql
except ImportError:
    import importlib.util
    spec = importlib.util.spec_from_file_location("instacart_costco_search", scripts_dir / "instacart_costco_search.py")
    instacart_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instacart_module)
    get_session = instacart_module.get_session
    search_by_upc_graphql = instacart_module.search_by_upc_graphql

COSTCO_ITEM_NUMBERS_PATH = Path('data/step1_input/costco_item_numbers.json')


def load_costco_item_numbers() -> Dict:
    """Load Costco item numbers from JSON file."""
    if not COSTCO_ITEM_NUMBERS_PATH.exists():
        print(f"Error: Costco item numbers file not found at {COSTCO_ITEM_NUMBERS_PATH}", file=sys.stderr)
        sys.exit(1)
    
    with COSTCO_ITEM_NUMBERS_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def query_item_number(session, item_number: str, shop_id: str = '83', postal_code: str = '60601', zone_id: str = '974') -> List[Dict[str, Any]]:
    """Query a single item number using Instacart Costco search."""
    try:
        results = search_by_upc_graphql(session, item_number, shop_id=shop_id, postal_code=postal_code, zone_id=zone_id, debug=False)
        return results
    except Exception as e:
        print(f"  Error querying {item_number}: {e}", file=sys.stderr)
        return []


def main():
    print("Loading Costco item numbers...")
    data = load_costco_item_numbers()
    
    items = data.get('items', {})
    print(f"Found {len(items)} Costco item numbers\n")
    print("=" * 100)
    
    # Create session
    print("Creating session...")
    session = get_session(auto_cookie=True)
    
    # Query each item number
    all_results = {}
    for item_number, item_data in sorted(items.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        product_names = item_data.get('product_names', [])
        product_name = product_names[0] if product_names else 'Unknown'
        
        print(f"\n{'=' * 100}")
        print(f"Item Number: {item_number}")
        print(f"Product Name: {product_name}")
        print(f"Found in {item_data.get('receipt_count', 0)} receipt(s)")
        print('-' * 100)
        
        # Query
        results = query_item_number(session, item_number)
        
        if results:
            print(f"Found {len(results)} results:")
            all_results[item_number] = {
                'product_name': product_name,
                'results': results
            }
            
            # Check for exact matches
            exact_matches = []
            for i, product in enumerate(results, 1):
                product_id = product.get('productId') or product.get('item_number') or 'N/A'
                name = product.get('name', 'N/A')
                brand = product.get('brand', 'N/A')
                size = product.get('size', 'N/A')
                upc = product.get('UPC') or product.get('barcode', 'N/A')
                
                # Check if productId matches item_number
                match_status = '✓ EXACT MATCH' if str(product_id) == str(item_number) else '✗ NO MATCH'
                
                if str(product_id) == str(item_number):
                    exact_matches.append(product)
                
                print(f"\n  Result {i}: {match_status}")
                print(f"    productId: {product_id}")
                print(f"    name: {name}")
                print(f"    brand: {brand}")
                print(f"    size: {size}")
                print(f"    UPC: {upc}")
            
            if exact_matches:
                print(f"\n  ✓ Found {len(exact_matches)} exact match(es)!")
            else:
                print(f"\n  ✗ No exact matches found")
        else:
            print("  No results found")
            all_results[item_number] = {
                'product_name': product_name,
                'results': []
            }
        
        # Delay between requests
        time.sleep(1.5)
    
    # Summary
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    
    total_items = len(items)
    items_with_results = sum(1 for r in all_results.values() if r.get('results'))
    items_with_exact_matches = 0
    
    for item_number, data in all_results.items():
        results = data.get('results', [])
        if results:
            # Check if any result matches the item number
            for product in results:
                product_id = str(product.get('productId') or product.get('item_number') or '')
                if product_id == item_number:
                    items_with_exact_matches += 1
                    break
    
    print(f"Total Costco items queried: {total_items}")
    print(f"Items with search results: {items_with_results}")
    print(f"Items with exact matches: {items_with_exact_matches}")
    print(f"Items with no matches: {total_items - items_with_exact_matches}")
    
    # Save results
    output_path = Path('data/step1_input/costco_item_search_results.json')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        'total_items': total_items,
        'items_with_results': items_with_results,
        'items_with_exact_matches': items_with_exact_matches,
        'items': {
            item_number: {
                'product_name': data['product_name'],
                'result_count': len(data.get('results', [])),
                'has_exact_match': any(
                    str(p.get('productId') or p.get('item_number') or '') == item_number
                    for p in data.get('results', [])
                ),
                'results': data.get('results', [])
            }
            for item_number, data in all_results.items()
        }
    }
    
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved results to: {output_path}")


if __name__ == '__main__':
    main()

