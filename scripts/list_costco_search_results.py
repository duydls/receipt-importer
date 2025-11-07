#!/usr/bin/env python3
"""
List all search results for Costco products from Instacart Costco.
"""

import json
import sys
from pathlib import Path

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

KB_PATH = Path('data/step1_input/knowledge_base.json')


def get_costco_items(kb):
    """Extract all Costco items from knowledge base."""
    costco_items = []
    for item_number, item_data in kb.items():
        if isinstance(item_data, list) and len(item_data) >= 2 and item_data[1] == 'Costco':
            costco_items.append((item_number, item_data))
        elif isinstance(item_data, dict) and item_data.get('store') == 'Costco':
            costco_items.append((item_number, item_data))
    return costco_items


def main():
    # Load knowledge base
    with KB_PATH.open('r', encoding='utf-8') as f:
        kb = json.load(f)
    
    # Get Costco items
    costco_items = get_costco_items(kb)
    print(f'Found {len(costco_items)} Costco items\n')
    print('=' * 100)
    
    # Create session
    session = get_session(auto_cookie=True)
    
    # Search each item
    all_results = {}
    for item_number, item_data in costco_items:
        if isinstance(item_data, list):
            product_name = item_data[0] if len(item_data) > 0 else 'Unknown'
        elif isinstance(item_data, dict):
            product_name = item_data.get('name') or item_data.get('product_name') or 'Unknown'
        else:
            product_name = 'Unknown'
        
        print(f'\n{"=" * 100}')
        print(f'Item Number: {item_number}')
        print(f'Product Name: {product_name}')
        print('-' * 100)
        
        # Search
        try:
            results = search_by_upc_graphql(session, item_number, shop_id='83', postal_code='60601', zone_id='974', debug=False)
            
            if results:
                print(f'Found {len(results)} results:')
                all_results[item_number] = {
                    'product_name': product_name,
                    'results': results
                }
                
                for i, product in enumerate(results, 1):
                    product_id = product.get('productId') or product.get('item_number') or 'N/A'
                    name = product.get('name', 'N/A')
                    brand = product.get('brand', 'N/A')
                    size = product.get('size', 'N/A')
                    upc = product.get('UPC') or product.get('barcode', 'N/A')
                    
                    # Check if productId matches item_number
                    match_status = '✓ MATCH' if str(product_id) == str(item_number) else '✗ NO MATCH'
                    
                    print(f'\n  Result {i}: {match_status}')
                    print(f'    productId: {product_id}')
                    print(f'    name: {name}')
                    print(f'    brand: {brand}')
                    print(f'    size: {size}')
                    print(f'    UPC: {upc}')
            else:
                print('  No results found')
                all_results[item_number] = {
                    'product_name': product_name,
                    'results': []
                }
        except Exception as e:
            print(f'  Error: {e}')
            all_results[item_number] = {
                'product_name': product_name,
                'results': [],
                'error': str(e)
            }
        
        print()
    
    # Summary
    print('\n' + '=' * 100)
    print('SUMMARY')
    print('=' * 100)
    
    total_items = len(costco_items)
    items_with_results = sum(1 for r in all_results.values() if r.get('results'))
    items_with_matches = 0
    
    for item_number, data in all_results.items():
        results = data.get('results', [])
        if results:
            # Check if any result matches the item number
            for product in results:
                product_id = str(product.get('productId') or product.get('item_number') or '')
                if product_id == item_number:
                    items_with_matches += 1
                    break
    
    print(f'Total Costco items: {total_items}')
    print(f'Items with search results: {items_with_results}')
    print(f'Items with exact matches: {items_with_matches}')
    print(f'Items with no matches: {total_items - items_with_matches}')


if __name__ == '__main__':
    main()

