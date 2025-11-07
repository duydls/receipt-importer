#!/usr/bin/env python3
"""
Instacart Costco UPC Search
Searches Instacart's Costco storefront for products by UPC.

Usage:
    python scripts/instacart_costco_search.py 1362911 --cookie "YOUR_COOKIE_STRING"
    python scripts/instacart_costco_search.py 1362911 --auto-cookie
"""

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# Optional browser cookie support
try:
    import browser_cookie3
    BROWSER_COOKIE_AVAILABLE = True
except ImportError:
    BROWSER_COOKIE_AVAILABLE = False

# Optional Playwright support for JavaScript-rendered content
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)

STORE_URL = "https://www.instacart.com/store/costco"
GRAPHQL_URL = "https://www.instacart.com/graphql"


def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    """Parse cookie string into dictionary."""
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def get_session(cookie: Optional[str] = None, auto_cookie: bool = False) -> requests.Session:
    """Create a requests session with cookies."""
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_UA})
    
    if auto_cookie:
        if not BROWSER_COOKIE_AVAILABLE:
            raise RuntimeError("browser-cookie3 not installed. pip install browser-cookie3")
        
        # Try to get cookies from browser
        cj = None
        for loader_name in ("chrome", "edge", "firefox", "chromium"):
            fn = getattr(browser_cookie3, loader_name, None)
            if not fn:
                continue
            try:
                cj = fn(domain_name="instacart.com")
                break
            except Exception:
                continue
        
        if not cj:
            raise RuntimeError("Could not read cookies from any browser profile for instacart.com")
        
        for c in cj:
            if "instacart.com" in (c.domain or ""):
                session.cookies.set(c.name, c.value, domain=c.domain)
    
    elif cookie:
        cookies = parse_cookie_string(cookie)
        for k, v in cookies.items():
            session.cookies.set(k, v, domain=".instacart.com")
    
    return session


def search_by_upc_graphql(session: requests.Session, upc: str, shop_id: str = '83', postal_code: str = '60601', zone_id: str = '974', debug: bool = False) -> List[Dict[str, Any]]:
    """Search Instacart Costco by UPC using GraphQL SearchResultsPlacements query."""
    import uuid
    
    # Generate session IDs
    page_view_id = str(uuid.uuid4())
    search_id = str(uuid.uuid4())
    
    # Get user ID from session if available (try to extract from cookies or use default)
    user_id = None
    try:
        # Try to get user ID from a test query
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
        test_resp = session.get(GRAPHQL_URL, params=test_params, timeout=15)
        if test_resp.status_code == 200:
            test_data = test_resp.json()
            user_id = test_data.get('data', {}).get('currentUser', {}).get('id')
    except Exception:
        pass
    
    # Use default user ID if not found
    if not user_id:
        user_id = "176554901"
    
    # Build variables for SearchResultsPlacements
    variables = {
        'filters': [],
        'action': None,
        'query': upc,
        'pageViewId': page_view_id,
        'retailerInventorySessionToken': f'v1.6813ea9.{user_id}-{postal_code}-04188x18761-1-5-111-1-0',
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
        'shopId': shop_id,
        'postalCode': postal_code,
        'zoneId': zone_id,
        'first': 20,
    }
    
    headers = {
        'User-Agent': DEFAULT_UA,
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.instacart.com',
        'Referer': f'{STORE_URL}/s?k={upc}',
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
        resp = session.get(GRAPHQL_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        # Debug: check for errors
        if 'errors' in data:
            print(f"GraphQL errors: {data['errors']}", file=sys.stderr)
        
        if debug:
            print(f"GraphQL response status: {resp.status_code}", file=sys.stderr)
            print(f"GraphQL response keys: {list(data.keys())}", file=sys.stderr)
            if 'data' in data:
                print(f"GraphQL data keys: {list(data['data'].keys())}", file=sys.stderr)
        
        # Parse product items from response
        results = []
        placements = data.get('data', {}).get('searchResultsPlacements', {}).get('placements', [])
        
        if debug:
            print(f"Found {len(placements)} placements", file=sys.stderr)
        
        for placement_idx, placement in enumerate(placements):
            if debug:
                print(f"Placement {placement_idx + 1} keys: {list(placement.keys())}", file=sys.stderr)
            
            content = placement.get('content', {})
            if debug:
                print(f"  Content keys: {list(content.keys())}", file=sys.stderr)
            
            # Try different structures
            items = []
            if 'placement' in content and 'items' in content['placement']:
                items = content['placement']['items']
            elif 'items' in content:
                items = content['items']
            elif 'placement' in content:
                placement_data = content['placement']
                if isinstance(placement_data, dict) and 'items' in placement_data:
                    items = placement_data['items']
            
            if debug:
                print(f"  Found {len(items)} items in placement {placement_idx + 1}", file=sys.stderr)
            
            for item in items:
                # Extract price information
                price_data = item.get('price', {})
                price_value = None
                price_string = None
                if price_data:
                    view_section = price_data.get('viewSection', {})
                    price_value_str = view_section.get('priceValueString', '')
                    price_string = view_section.get('priceString', '')
                    # Try to extract numeric price
                    if price_value_str:
                        try:
                            price_value = float(price_value_str)
                        except (ValueError, TypeError):
                            pass
                    # If priceValueString not available, try to extract from priceString
                    if price_value is None and price_string:
                        price_match = re.search(r'[\d.]+', price_string.replace('$', '').replace(',', ''))
                        if price_match:
                            try:
                                price_value = float(price_match.group())
                            except (ValueError, TypeError):
                                pass
                
                # Extract product data
                product = {
                    'name': item.get('name', ''),
                    'Product Name': item.get('name', ''),
                    'Brand': item.get('brandName', ''),
                    'brand': item.get('brandName', ''),
                    'Size': item.get('size', ''),
                    'size': item.get('size', ''),
                    'productId': item.get('productId'),
                    'Item Number': item.get('productId'),
                    'item_number': item.get('productId'),
                    'legacyId': item.get('legacyId', ''),
                    'evergreenUrl': item.get('evergreenUrl', ''),
                    'detail_url': f"{STORE_URL}/storefront/items/{item.get('productId', '')}" if item.get('productId') else '',
                    'price': price_value,
                    'priceString': price_string,
                }
                
                # Extract UPC from viewSection.retailerLookupCodeString
                view_section = item.get('viewSection', {})
                lookup_code = view_section.get('retailerLookupCodeString', '')
                if lookup_code:
                    # Extract UPC from "UPC: 051141357577" format
                    upc_match = re.search(r'UPC:\s*(\d+)', lookup_code, re.I)
                    if upc_match:
                        upc_value = upc_match.group(1)
                        product['UPC'] = upc_value
                        product['barcode'] = upc_value
                        product['Barcode (UPC)'] = upc_value
                    # Also check if lookup_code itself is a UPC (numeric)
                    elif lookup_code.strip().isdigit() and len(lookup_code.strip()) >= 12:
                        product['UPC'] = lookup_code.strip()
                        product['barcode'] = lookup_code.strip()
                        product['Barcode (UPC)'] = lookup_code.strip()
                
                # Fallback: Check if legacyId might be the UPC
                if 'UPC' not in product:
                    legacy_id = item.get('legacyId', '')
                    if legacy_id and len(legacy_id) >= 12 and legacy_id.isdigit():
                        # Legacy ID might be UPC
                        product['UPC'] = legacy_id
                        product['barcode'] = legacy_id
                        product['Barcode (UPC)'] = legacy_id
                
                results.append(product)
        
        # Filter by UPC if provided
        if upc:
            # First, try exact match on UPC/barcode fields
            filtered = [p for p in results if str(p.get('UPC', '') or p.get('barcode', '') or '').strip() == upc]
            if filtered:
                return filtered
            
            # If no exact match, check if UPC is in legacyId
            filtered = [p for p in results if str(p.get('legacyId', '')).strip() == upc]
            if filtered:
                return filtered
        
        return results
    except Exception as e:
        print(f"GraphQL search failed: {e}", file=sys.stderr)
        return []


def search_by_upc(session: requests.Session, upc: str, use_playwright: bool = False, use_graphql: bool = True) -> List[Dict[str, Any]]:
    """Search Instacart Costco by UPC."""
    # Try GraphQL first (fastest and most reliable)
    if use_graphql:
        try:
            graphql_results = search_by_upc_graphql(session, upc)
            if graphql_results:
                return graphql_results
        except Exception as e:
            print(f"GraphQL search failed, falling back to HTML: {e}", file=sys.stderr)
    
    # Fallback to HTML parsing (not implemented yet)
    return []


def main():
    parser = argparse.ArgumentParser(description="Search Instacart Costco by UPC")
    parser.add_argument("upc", help="UPC or item number to search for")
    parser.add_argument("--cookie", help="Cookie string from browser")
    parser.add_argument("--auto-cookie", action="store_true", help="Read cookies from browser automatically")
    parser.add_argument("--use-playwright", action="store_true", help="Use Playwright for JavaScript-rendered content")
    parser.add_argument("--use-graphql", action="store_true", default=True, help="Use GraphQL API directly (default: True)")
    parser.add_argument("--no-graphql", dest="use_graphql", action="store_false", help="Disable GraphQL API and use HTML parsing")
    parser.add_argument("--shop-id", default="83", help="Shop ID (default: 83 for Costco)")
    parser.add_argument("--postal-code", default="60601", help="Postal code (default: 60601)")
    parser.add_argument("--zone-id", default="974", help="Zone ID (default: 974)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--debug", action="store_true", help="Print debug information")
    
    args = parser.parse_args()
    
    if not (args.cookie or args.auto_cookie):
        print("Error: Must provide --cookie or --auto-cookie", file=sys.stderr)
        sys.exit(1)
    
    if args.use_playwright and not PLAYWRIGHT_AVAILABLE:
        print("Error: Playwright not available. Install with: pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(1)
    
    session = get_session(cookie=args.cookie, auto_cookie=args.auto_cookie)
    
    # Try GraphQL first if enabled
    results = []
    if args.use_graphql:
        try:
            results = search_by_upc_graphql(session, args.upc, shop_id=args.shop_id, postal_code=args.postal_code, zone_id=args.zone_id, debug=args.debug)
        except Exception as e:
            print(f"GraphQL search failed: {e}", file=sys.stderr)
            if args.debug:
                import traceback
                traceback.print_exc()
    
    # Fallback to regular search if GraphQL didn't return results
    if not results:
        results = search_by_upc(session, args.upc, use_playwright=args.use_playwright, use_graphql=False)
    
    print(json.dumps(results, indent=2 if args.pretty else None, ensure_ascii=False))


if __name__ == "__main__":
    main()

