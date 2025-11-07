#!/usr/bin/env python3
"""
Script to help find the RD search GraphQL query by monitoring network requests
Run this while manually searching in your browser, or use it to analyze saved network data
"""

import json
import sys
from pathlib import Path

def analyze_saved_requests():
    """Analyze saved network requests for search queries"""
    requests_file = Path('/tmp/all_requests_76069502838.json')
    if not requests_file.exists():
        print("No saved requests found. Run test_rd_playwright.py first.")
        return
    
    with open(requests_file, 'r') as f:
        requests = json.load(f)
    
    print(f"Analyzing {len(requests)} requests...")
    print("\nGraphQL requests:")
    for req in requests:
        url = req['url']
        if 'graphql' in url.lower():
            # Extract operation name
            if 'operationName=' in url:
                op_name = url.split('operationName=')[1].split('&')[0]
                print(f"  {op_name}: {url[:100]}...")
    
    print("\nSearching for search-related requests:")
    for req in requests:
        url = req['url'].lower()
        if any(keyword in url for keyword in ['search', 'product', 'item', 'query']):
            if 'graphql' in url or 'api' in url:
                print(f"  {req['url'][:150]}...")
                print(f"    Method: {req['method']}")

def create_browser_script():
    """Create a browser console script to capture search queries"""
    script = """
// Run this in browser console while on the search page
// It will log all GraphQL requests

(function() {
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        const url = args[0];
        if (typeof url === 'string' && url.includes('graphql')) {
            console.log('GraphQL Request:', url);
            if (args[1] && args[1].body) {
                console.log('Request Body:', args[1].body);
            }
        }
        return originalFetch.apply(this, args);
    };
    
    // Also intercept XMLHttpRequest
    const originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        if (url.includes('graphql')) {
            console.log('GraphQL XHR:', method, url);
        }
        return originalOpen.apply(this, [method, url, ...args]);
    };
    
    console.log('GraphQL interceptor installed. Navigate to search page and search for a UPC.');
})();
"""
    print("\nBrowser Console Script:")
    print("=" * 80)
    print(script)
    print("=" * 80)
    print("\nInstructions:")
    print("1. Open member.restaurantdepot.com in your browser")
    print("2. Open DevTools (F12)")
    print("3. Go to Console tab")
    print("4. Paste the script above")
    print("5. Navigate to search page and search for a UPC")
    print("6. Check console for GraphQL requests")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--browser-script':
        create_browser_script()
    else:
        analyze_saved_requests()
        print("\n" + "=" * 80)
        print("To get browser console script, run:")
        print("  python scripts/find_rd_search_query.py --browser-script")

