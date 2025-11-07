#!/usr/bin/env python3
"""Debug script to see raw GraphQL response for UPC search"""
import json
import sys
import requests
import browser_cookie3

def debug_graphql_search(upc: str):
    """Debug GraphQL search to see raw response"""
    graphql_url = 'https://member.restaurantdepot.com/graphql'
    
    # Get cookies
    try:
        cj = browser_cookie3.chrome(domain_name='member.restaurantdepot.com')
    except:
        print("Error: Could not read cookies. Make sure you're logged in to Restaurant Depot in Chrome.")
        return
    
    session = requests.Session()
    for c in cj:
        if 'member.restaurantdepot.com' in (c.domain or ''):
            session.cookies.set(c.name, c.value, domain=c.domain)
    
    # Get user ID
    user_id = None
    try:
        test_params = {
            'operationName': 'LandingCurrentUser',
            'variables': '{}',
            'extensions': json.dumps({
                'persistedQuery': {
                    'version': 1,
                    'sha256Hash': '91549410d9d88d0829db6c6b3ff323fbc7641ec3a2a53532b1c300b8e08763a2'
                }
            })
        }
        test_resp = session.get(graphql_url, params=test_params)
        if test_resp.status_code == 200:
            test_data = test_resp.json()
            user_id = test_data.get('data', {}).get('currentUser', {}).get('id')
            print(f"User ID: {user_id}")
    except Exception as e:
        print(f"Could not get user ID: {e}")
    
    # Build GraphQL query
    import uuid
    page_view_id = str(uuid.uuid4())
    search_id = str(uuid.uuid4())
    
    variables = {
        'filters': [],
        'action': None,
        'query': upc,
        'pageViewId': page_view_id,
        'retailerInventorySessionToken': f'v1.deaf425.{user_id or "18238936739404192"}-60640-04197x18765-1-7933-473323-0-0',
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
        'contentManagementSearchParams': {'itemGridColumnCount': 4},
        'shopId': '59693',
        'postalCode': '60640',
        'zoneId': '974',
        'first': 20,
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://member.restaurantdepot.com',
        'Referer': f'https://member.restaurantdepot.com/store/jetro-restaurant-depot/s?k={upc}',
        'x-client-identifier': 'web',
    }
    if user_id:
        headers['x-client-user-id'] = str(user_id)
    
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
    
    print(f"\nSearching for UPC: {upc}")
    print(f"GraphQL URL: {graphql_url}")
    print(f"Variables: {json.dumps(variables, indent=2)}")
    print("\n" + "="*80 + "\n")
    
    try:
        resp = session.get(graphql_url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        
        # Print full response
        print("Full GraphQL Response:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        # Extract and print product details
        print("\n" + "="*80 + "\n")
        print("Extracted Products:")
        
        placements = data.get('data', {}).get('searchResultsPlacements', {}).get('placements', [])
        print(f"Found {len(placements)} placements\n")
        
        for placement_idx, placement in enumerate(placements):
            content = placement.get('content', {})
            if 'placement' in content and 'items' in content['placement']:
                items = content['placement']['items']
                print(f"Placement {placement_idx + 1}: {len(items)} items")
                
                for item_idx, item in enumerate(items):
                    print(f"\n  Item {item_idx + 1}:")
                    print(f"    name: {item.get('name', 'N/A')}")
                    print(f"    productId: {item.get('productId', 'N/A')}")
                    print(f"    legacyId: {item.get('legacyId', 'N/A')}")
                    print(f"    brandName: {item.get('brandName', 'N/A')}")
                    print(f"    size: {item.get('size', 'N/A')}")
                    
                    view_section = item.get('viewSection', {})
                    lookup_code = view_section.get('retailerLookupCodeString', '')
                    print(f"    retailerLookupCodeString: {lookup_code}")
                    
                    # Check all fields for the UPC
                    item_str = json.dumps(item, indent=2)
                    if upc in item_str:
                        print(f"    *** UPC {upc} FOUND IN THIS ITEM ***")
                    else:
                        print(f"    UPC {upc} not found in this item")
                    
                    print()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    upc = sys.argv[1] if len(sys.argv) > 1 else '76069502838'
    debug_graphql_search(upc)

