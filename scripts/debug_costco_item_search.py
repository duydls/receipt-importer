#!/usr/bin/env python3
"""
Debug Costco item number search to see the full response structure.
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


def debug_item_search(item_number: str):
    """Debug search for a specific item number."""
    print(f"Searching for item number: {item_number}")
    print("=" * 100)
    
    session = get_session(auto_cookie=True)
    
    # Search with debug enabled
    results = search_by_upc_graphql(session, item_number, shop_id='83', postal_code='60601', zone_id='974', debug=True)
    
    print(f"\nFound {len(results)} results\n")
    
    # Print full JSON for first result to see all fields
    if results:
        print("First result (full JSON):")
        print(json.dumps(results[0], indent=2, ensure_ascii=False))
        
        print("\n" + "=" * 100)
        print("Checking for item number in all fields:")
        print("=" * 100)
        
        for i, product in enumerate(results, 1):
            print(f"\nResult {i}:")
            # Check all fields for the item number
            for key, value in product.items():
                value_str = str(value)
                if item_number in value_str:
                    print(f"  ✓ Found '{item_number}' in field '{key}': {value}")
                # Also check if any part of the value matches
                if key in ['productId', 'item_number', 'Item Number', 'legacyId', 'UPC', 'barcode']:
                    print(f"  {key}: {value}")
    
    # Also try to get the raw GraphQL response
    print("\n" + "=" * 100)
    print("Raw GraphQL Response Structure:")
    print("=" * 100)
    
    # Modify the search function temporarily to return raw response
    import requests
    import uuid
    
    page_view_id = str(uuid.uuid4())
    search_id = str(uuid.uuid4())
    
    user_id = "176554901"  # Default user ID
    
    variables = {
        'filters': [],
        'action': None,
        'query': item_number,
        'pageViewId': page_view_id,
        'retailerInventorySessionToken': f'v1.19b3e93.{user_id}-60601-04188x18761-1-449-30404-0-0',
        'elevatedProductId': None,
        'searchId': search_id,
        'searchSource': 'search',
        'disableReformulation': False,
        'disableLlm': False,
        'forceInspiration': False,
        'orderBy': 'bestMatch',
        'clusterId': None,
        'includeDebugInfo': False,
        'clusteringStrategy': None,
        'contentManagementSearchParams': {'itemGridColumnCount': 2},
        'shopId': '16',
        'postalCode': '60601',
        'zoneId': '974',
        'first': 20,
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.instacart.com',
        'Referer': f'https://www.instacart.com/store/costco/s?k={item_number}',
        'x-client-identifier': 'web',
        'x-client-user-id': str(user_id),
    }
    
    params = {
        'operationName': 'SearchResultsPlacements',
        'variables': json.dumps(variables),
        'extensions': json.dumps({
            'persistedQuery': {
                'version': 1,
                'sha256Hash': '819dd293c5db11a19f5dc0d1eb8ede045911567a4ec0cd7964763b081213e357'
            }
        })
    }
    
    try:
        resp = session.get('https://www.instacart.com/graphql', params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        # Look for item number in the raw response
        data_str = json.dumps(data)
        if item_number in data_str:
            print(f"\n✓ Found '{item_number}' in raw GraphQL response!")
            # Find where it appears
            import re
            matches = list(re.finditer(re.escape(item_number), data_str))
            print(f"  Found {len(matches)} occurrences")
            
            # Show context around first few matches
            for i, match in enumerate(matches[:3], 1):
                start = max(0, match.start() - 100)
                end = min(len(data_str), match.end() + 100)
                context = data_str[start:end]
                print(f"\n  Match {i} context:")
                print(f"    ...{context}...")
        else:
            print(f"\n✗ Item number '{item_number}' not found in raw GraphQL response")
        
        # Print structure of first placement with items
        placements = data.get('data', {}).get('searchResultsPlacements', {}).get('placements', [])
        for placement in placements:
            content = placement.get('content', {})
            if 'items' in content:
                items = content['items']
                if items:
                    print(f"\nFirst item structure (all fields):")
                    print(json.dumps(items[0], indent=2, ensure_ascii=False))
                    break
        
    except Exception as e:
        print(f"Error getting raw response: {e}")


if __name__ == '__main__':
    item_number = sys.argv[1] if len(sys.argv) > 1 else '3923'
    debug_item_search(item_number)

