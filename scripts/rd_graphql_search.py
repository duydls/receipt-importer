#!/usr/bin/env python3
"""
RD GraphQL Search - Direct GraphQL API access for Restaurant Depot search
Uses www.instacart.com/graphql endpoint
"""

import json
import sys
import urllib.parse
from typing import Dict, Any, List, Optional

import requests
import browser_cookie3

# GraphQL endpoint
GRAPHQL_URL = 'https://www.instacart.com/graphql'

def get_cookies(domain: str = 'instacart.com') -> Dict[str, str]:
    """Get cookies from browser"""
    try:
        cj = browser_cookie3.chrome(domain_name=domain)
        cookies = {}
        for cookie in cj:
            cookies[cookie.name] = cookie.value
        return cookies
    except Exception as e:
        print(f"Error getting cookies: {e}")
        return {}

def search_by_upc_graphql(upc: str, shop_id: str = '596493', operation_name: str = None, query_hash: str = None) -> Optional[Dict[str, Any]]:
    """
    Search for products by UPC using GraphQL API
    
    Args:
        upc: UPC code to search for
        shop_id: Shop ID (596493 for Restaurant Depot)
        operation_name: GraphQL operation name (if known)
        query_hash: Persisted query hash (if known)
    
    Returns:
        GraphQL response data or None
    """
    cookies = get_cookies('instacart.com')
    if not cookies:
        print("No cookies found")
        return None
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.instacart.com',
        'Referer': f'https://www.instacart.com/store/restaurant-depot/s?k={upc}',
        'x-client-identifier': 'web',
    }
    
    # If we have the operation name and hash, use them
    if operation_name and query_hash:
        params = {
            'operationName': operation_name,
            'variables': json.dumps({
                'query': upc,
                'shopId': shop_id,
            }),
            'extensions': json.dumps({
                'persistedQuery': {
                    'version': 1,
                    'sha256Hash': query_hash
                }
            })
        }
    else:
        # Try DataPollingQuery first (from the curl command)
        params = {
            'operationName': 'DataPollingQuery',
            'variables': '{}',
            'extensions': json.dumps({
                'persistedQuery': {
                    'version': 1,
                    'sha256Hash': '0969c660c46025bc74394c1f8f5126bc214de966e07da994b1f3f93866956118'
                }
            })
        }
    
    try:
        resp = requests.get(GRAPHQL_URL, params=params, cookies=cookies, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error making GraphQL request: {e}")
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python rd_graphql_search.py <UPC> [operation_name] [query_hash]")
        print("\nExample:")
        print("  python rd_graphql_search.py 76069502838")
        print("\nTo find the search query:")
        print("  1. Open browser DevTools")
        print("  2. Go to Network tab")
        print("  3. Filter by 'graphql'")
        print("  4. Search for a UPC")
        print("  5. Find the search query request")
        print("  6. Copy operationName and sha256Hash")
        sys.exit(1)
    
    upc = sys.argv[1]
    operation_name = sys.argv[2] if len(sys.argv) > 2 else None
    query_hash = sys.argv[3] if len(sys.argv) > 3 else None
    
    print(f"Searching for UPC: {upc}")
    print(f"Using operation: {operation_name or 'DataPollingQuery'}")
    print(f"Query hash: {query_hash or '0969c660c46025bc74394c1f8f5126bc214de966e07da994b1f3f93866956118'}")
    print("=" * 80)
    
    result = search_by_upc_graphql(upc, operation_name=operation_name, query_hash=query_hash)
    
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("No results found")

if __name__ == '__main__':
    main()

