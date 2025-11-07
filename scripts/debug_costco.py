#!/usr/bin/env python3
"""Debug script to inspect Instacart Costco page structure."""
import requests
from bs4 import BeautifulSoup
import json
import re

url = 'https://www.instacart.com/store/costco/s?k=1362911'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}
resp = requests.get(url, headers=headers, timeout=15)
soup = BeautifulSoup(resp.text, 'html.parser')

print('=== Searching for product cards ===')
cards = soup.select('[data-test="product-card"], a[href*="/items/"]')
print(f'Found {len(cards)} cards with data-test or /items/')

# Try other selectors
print('\n=== Trying other selectors ===')
testid_selector = '[data-testid="product-card"]'
items_selector = 'a[href*="/items/"]'
product_class = '.product-card'
product_attr = '[class*="product"]'
print(f'[data-testid="product-card"]: {len(soup.select(testid_selector))}')
print(f'a[href*="/items/"]: {len(soup.select(items_selector))}')
print(f'.product-card: {len(soup.select(product_class))}')
print(f'[class*="product"]: {len(soup.select(product_attr))}')

# Check if there's JSON data in script tags
scripts = soup.select('script[type="application/json"]')
print(f'\n=== JSON script tags: {len(scripts)} ===')
for i, script in enumerate(scripts):
    content = script.string or ''
    if len(content) > 10000:  # Focus on large scripts
        print(f'\nScript {i}: {len(content)} chars')
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                print(f'  Valid JSON! Top-level keys: {list(data.keys())[:20]}')
                # Look for product-related keys
                for key in data.keys():
                    if 'product' in key.lower() or 'item' in key.lower() or 'search' in key.lower():
                        print(f'    Found relevant key: {key}')
                        if isinstance(data[key], (list, dict)) and len(str(data[key])) < 500:
                            print(f'      Preview: {str(data[key])[:200]}')
            elif isinstance(data, list):
                print(f'  Valid JSON array with {len(data)} items')
                if len(data) > 0 and isinstance(data[0], dict):
                    print(f'    First item keys: {list(data[0].keys())[:10]}')
        except Exception as e:
            print(f'  JSON parse error: {e}')

# Look for window.__INITIAL_STATE__ or similar
print('\n=== Looking for window.__INITIAL_STATE__ or similar ===')
for script in soup.select('script'):
    text = script.string or ''
    if '__INITIAL_STATE__' in text or 'window.__' in text or 'hydrate' in text.lower():
        print(f'Found script with state/hydrate: {len(text)} chars')
        # Try to extract JSON
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                print(f'  Extracted JSON with keys: {list(data.keys())[:10] if isinstance(data, dict) else "list/other"}')
            except:
                pass

