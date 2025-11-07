#!/usr/bin/env python3
"""
Test script to fetch RD product data using Playwright
This script waits for JavaScript execution and monitors network requests
"""

import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright
import browser_cookie3

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

def get_cookies_from_browser():
    """Get cookies from browser for member.restaurantdepot.com"""
    try:
        cj = browser_cookie3.chrome(domain_name='member.restaurantdepot.com')
        cookies = []
        for cookie in cj:
            # Playwright requires domain format: .domain.com or domain.com
            domain = cookie.domain
            # Remove leading dot if present, then add it back
            domain = domain.lstrip('.')
            if domain and '.' in domain:
                domain = f".{domain}"
            
            cookie_dict = {
                'name': cookie.name,
                'value': cookie.value,
                'domain': domain or '.member.restaurantdepot.com',
                'path': cookie.path or '/',
            }
            
            # Add optional fields if present
            if hasattr(cookie, 'expires') and cookie.expires:
                cookie_dict['expires'] = cookie.expires
            
            if hasattr(cookie, 'httpOnly'):
                cookie_dict['httpOnly'] = bool(cookie.httpOnly)
            
            if hasattr(cookie, 'secure'):
                cookie_dict['secure'] = bool(cookie.secure)
            
            if hasattr(cookie, 'sameSite'):
                cookie_dict['sameSite'] = cookie.sameSite
            
            cookies.append(cookie_dict)
        return cookies
    except Exception as e:
        print(f"Error getting cookies: {e}")
        import traceback
        traceback.print_exc()
        return []

async def fetch_rd_product_with_playwright(upc: str):
    """Fetch RD product data using Playwright"""
    cookies = get_cookies_from_browser()
    print(f"Found {len(cookies)} cookies")
    
    search_url = f"https://member.restaurantdepot.com/store/jetro-restaurant-depot/s?k={upc}"
    print(f"Fetching: {search_url}")
    
    graphql_requests = []
    product_data = []
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        
        # Add cookies
        if cookies:
            try:
                await context.add_cookies(cookies)
                print(f"Added {len(cookies)} cookies")
            except Exception as e:
                print(f"Warning: Could not add all cookies: {e}")
                # Try to add cookies one by one
                for cookie in cookies:
                    try:
                        await context.add_cookies([cookie])
                    except:
                        pass
        
        # Create page
        page = await context.new_page()
        
        # Monitor ALL network requests
        all_requests = []
        all_responses = []
        
        async def handle_request(request):
            url = request.url
            all_requests.append({
                'url': url,
                'method': request.method,
                'headers': dict(request.headers),
            })
            if 'graphql' in url.lower():
                print(f"\nGraphQL Request: {url}")
                graphql_requests.append({
                    'url': url,
                    'method': request.method,
                    'headers': dict(request.headers),
                })
                # Try to get request body
                try:
                    post_data = request.post_data
                    if post_data:
                        print(f"  Request body: {post_data[:200]}...")
                except:
                    pass
        
        async def handle_response(response):
            url = response.url
            all_responses.append({
                'url': url,
                'status': response.status,
            })
            if 'graphql' in url.lower():
                try:
                    body = await response.body()
                    text = body.decode('utf-8')
                    print(f"\nGraphQL Response from {url}:")
                    print(f"  Status: {response.status}")
                    try:
                        data = json.loads(text)
                        print(f"  Response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                        # Save response for inspection
                        with open(f'/tmp/graphql_response_{upc}_{len(all_responses)}.json', 'w') as f:
                            json.dump(data, f, indent=2)
                        print(f"  Saved response to /tmp/graphql_response_{upc}_{len(all_responses)}.json")
                    except:
                        print(f"  Response preview: {text[:500]}...")
                except Exception as e:
                    print(f"  Error reading response: {e}")
        
        page.on('request', handle_request)
        page.on('response', handle_response)
        
        # Navigate to search page
        print("\nNavigating to search page...")
        await page.goto(search_url, wait_until='networkidle', timeout=30000)
        
        # Wait for product results to load
        print("\nWaiting for product results...")
        try:
            # Try to wait for product elements
            await page.wait_for_selector('.product, .product-card, .item, [data-testid*="product"]', timeout=10000)
            print("Found product elements!")
        except:
            print("No product elements found with common selectors")
        
        # Try to find product data in the page
        print("\nExtracting product data from page...")
        
        # Method 1: Look for product links
        product_links = await page.query_selector_all('a[href*="/product"], a[href*="/item"]')
        print(f"Found {len(product_links)} product links")
        
        # Method 2: Look for product cards/items
        product_cards = await page.query_selector_all('.product, .product-card, .item-card, [class*="product"]')
        print(f"Found {len(product_cards)} product cards")
        
        # Method 3: Extract text content
        page_text = await page.inner_text('body')
        if 'no results' in page_text.lower() or 'no products' in page_text.lower():
            print("Page indicates no results found")
        elif 'log in' in page_text.lower() or 'login' in page_text.lower():
            print("Page requires login")
        
        # Method 4: Look for JSON data in script tags
        script_tags = await page.query_selector_all('script')
        print(f"Found {len(script_tags)} script tags")
        for i, script in enumerate(script_tags[:5]):
            content = await script.inner_text()
            if 'product' in content.lower() and '{' in content:
                print(f"Script {i} contains product data")
                # Try to extract JSON
                import re
                json_matches = re.findall(r'\{[^{}]*"product"[^{}]*\}', content, re.I)
                if json_matches:
                    print(f"  Found {len(json_matches)} potential JSON objects")
        
        # Method 5: Check for GraphQL data in window object
        graphql_data = await page.evaluate("""
            () => {
                // Look for GraphQL data in window
                if (window.__APOLLO_STATE__) return {type: 'apollo', data: window.__APOLLO_STATE__};
                if (window.__INITIAL_STATE__) return {type: 'initial', data: window.__INITIAL_STATE__};
                if (window.__NEXT_DATA__) return {type: 'next', data: window.__NEXT_DATA__};
                return null;
            }
        """)
        if graphql_data:
            print(f"\nFound GraphQL data in window: {graphql_data['type']}")
            with open(f'/tmp/graphql_window_{upc}.json', 'w') as f:
                json.dump(graphql_data['data'], f, indent=2)
            print(f"Saved to /tmp/graphql_window_{upc}.json")
        
        # Get page title
        title = await page.title()
        print(f"\nPage title: {title}")
        
        # Take a screenshot for debugging
        await page.screenshot(path=f'/tmp/rd_search_{upc}.png', full_page=True)
        print(f"Screenshot saved to /tmp/rd_search_{upc}.png")
        
        # Save HTML
        html = await page.content()
        with open(f'/tmp/rd_search_{upc}.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"HTML saved to /tmp/rd_search_{upc}.html")
        
        await browser.close()
    
    # Save all requests/responses for analysis
    with open(f'/tmp/all_requests_{upc}.json', 'w') as f:
        json.dump(all_requests, f, indent=2)
    with open(f'/tmp/all_responses_{upc}.json', 'w') as f:
        json.dump(all_responses, f, indent=2)
    print(f"\nSaved {len(all_requests)} requests and {len(all_responses)} responses")
    
    return {
        'graphql_requests': graphql_requests,
        'product_links': len(product_links),
        'product_cards': len(product_cards),
        'all_requests': len(all_requests),
        'all_responses': len(all_responses),
    }

async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_rd_playwright.py <UPC>")
        sys.exit(1)
    
    upc = sys.argv[1]
    print(f"Testing RD product lookup for UPC: {upc}")
    print("=" * 80)
    
    results = await fetch_rd_product_with_playwright(upc)
    
    print("\n" + "=" * 80)
    print("Results:")
    print(f"  GraphQL requests found: {len(results['graphql_requests'])}")
    print(f"  Product links found: {results['product_links']}")
    print(f"  Product cards found: {results['product_cards']}")

if __name__ == '__main__':
    asyncio.run(main())

