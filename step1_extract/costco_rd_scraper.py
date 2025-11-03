#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
costco_rd_scraper.py - Standalone Utility Script
----------------------------------
Reads Step 1 extracted_data.json, extracts Costco & RD products with item numbers/UPC,
looks up specs & prices from a knowledge base, and writes costco_rd_specs.csv.

This is a standalone utility script for batch processing product specifications.
Not used by the main workflow - for manual analysis and knowledge base updates.

Usage:
  python costco_rd_scraper.py --report data/step1_output/group1/extracted_data.json --out costco_rd_specs.csv
  python costco_rd_scraper.py --kb-file data/step1_input/knowledge_base.json --report data/step1_output/group1/extracted_data.json

Notes:
- Uses a local knowledge base (JSON file or hardcoded) for item lookups
- No web scraping or API calls - simple and reliable
- Knowledge base can be manually updated as new items are encountered
- Standalone script - not imported by main workflow
"""

import argparse
import csv
import json
import random
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Union

from bs4 import BeautifulSoup

def _import_scrape_libs():
    import cloudscraper  # type: ignore
    from bs4 import BeautifulSoup as _BSoup  # noqa: F401
    return cloudscraper


UPC_RE = re.compile(r'\b(\d{8,14})\b')
ITEM_NUM_RE = re.compile(r'\b(\d{5,12})\b')

# Cache directory
CACHE_DIR = Path('cache')
CACHE_DIR.mkdir(exist_ok=True)

# Global debug flag
DEBUG = False

def _get_cache_path(url: str) -> Path:
    """Generate cache file path from URL"""
    import hashlib
    cache_key = hashlib.md5(url.encode('utf-8')).hexdigest()
    return CACHE_DIR / f"{cache_key}.html"

def debug_print(msg: str):
    """Print debug message if DEBUG mode is enabled"""
    if DEBUG:
        print(f"[DEBUG] {msg}")

def safe_get(scraper, url: str, headers: Dict, timeout: int = 20, max_retries: int = 3) -> Optional[object]:
    """
    Safely fetch URL with retries and caching.
    
    Args:
        scraper: cloudscraper scraper instance
        url: URL to fetch
        headers: HTTP headers
        timeout: Request timeout in seconds
        max_retries: Maximum number of retries
        
    Returns:
        Response object if successful, None if all retries fail
    """
    global RATE_LIMIT_MULTIPLIER
    
    # Check cache first
    cache_path = _get_cache_path(url)
    debug_print(f"Cache path: {cache_path}")
    if cache_path.exists():
        debug_print(f"Cache file exists, size: {cache_path.stat().st_size} bytes")
        print(f"  Using cached file for {url[:60]}...")
        try:
            with open(cache_path, 'r', encoding='utf-8', errors='ignore') as f:
                cached_html = f.read()
            debug_print(f"Loaded {len(cached_html)} characters from cache")
            # Create a mock response object with the cached content
            class MockResponse:
                def __init__(self, text, status_code=200):
                    self.text = text
                    self.status_code = status_code
                    self.headers = {}
            return MockResponse(cached_html, 200)
        except Exception as e:
            print(f"  Warning: Could not read cache file {cache_path}: {e}")
            debug_print(f"Cache read error: {type(e).__name__}: {e}")
            # Continue to fetch from web
    
    # Retry logic
    delay = 2.0  # Initial delay in seconds
    last_error = None
    
    debug_print(f"Starting fetch for {url} (timeout={timeout}s, max_retries={max_retries})")
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  Fetching {url[:60]}... (attempt {attempt}/{max_retries})")
            debug_print(f"Attempt {attempt}: Making request to {url}")
            debug_print(f"Headers: {list(headers.keys())}")
            
            response = scraper.get(url, headers=headers, timeout=timeout)
            debug_print(f"Response status: {response.status_code}")
            debug_print(f"Response headers: {dict(list(response.headers.items())[:5])}")
            
            # Check if response is successful
            if response.status_code == 200:
                debug_print(f"Success! Response size: {len(response.text)} characters")
                # Reset rate limit multiplier on success
                if RATE_LIMIT_MULTIPLIER > 1.0:
                    RATE_LIMIT_MULTIPLIER = max(1.0, RATE_LIMIT_MULTIPLIER * 0.8)  # Gradually reduce back to 1.0
                    debug_print(f"Reducing rate limit multiplier to {RATE_LIMIT_MULTIPLIER:.2f}")
                # Save to cache
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        f.write(response.text)
                    debug_print(f"Saved to cache: {cache_path}")
                except Exception as e:
                    print(f"  Warning: Could not save to cache: {e}")
                    debug_print(f"Cache save error: {type(e).__name__}: {e}")
                
                return response
            elif response.status_code == 429:
                # Rate limited - increase delay significantly
                RATE_LIMIT_MULTIPLIER = min(RATE_LIMIT_MULTIPLIER * 2.0, 10.0)  # Cap at 10x
                print(f"  ⚠ Rate limited (429) - increasing delays to {RATE_LIMIT_MULTIPLIER:.1f}x")
                debug_print(f"Rate limited! Multiplier now: {RATE_LIMIT_MULTIPLIER:.2f}")
                if attempt < max_retries:
                    extended_delay = delay * RATE_LIMIT_MULTIPLIER
                    print(f"  Waiting {extended_delay:.1f}s before retry...")
                    debug_print(f"Sleeping {extended_delay:.1f}s (base {delay:.1f}s * {RATE_LIMIT_MULTIPLIER:.2f}x)...")
                    time.sleep(extended_delay)
                    delay *= 2
                else:
                    print(f"  Failed after {max_retries} attempts (rate limited)")
                    debug_print(f"Final failure after {max_retries} attempts with rate limit (429)")
                    return None
            else:
                print(f"  HTTP {response.status_code} for {url[:60]}...")
                debug_print(f"Non-200 status: {response.status_code}, response text preview: {response.text[:200]}")
                if attempt < max_retries:
                    print(f"  Retrying in {delay:.1f}s...")
                    debug_print(f"Sleeping {delay:.1f}s before retry...")
                    time.sleep(delay)
                    delay *= 2
                else:
                    print(f"  Failed after {max_retries} attempts")
                    debug_print(f"Final failure after {max_retries} attempts with status {response.status_code}")
                    return None
                    
        except Exception as e:
            last_error = e
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"  Error ({error_type}): {error_msg[:100]}...")
            debug_print(f"Exception details: {error_type}: {error_msg}")
            debug_print(f"Exception traceback: {traceback.format_exc()}")
            
            if attempt < max_retries:
                print(f"  Retrying in {delay:.1f}s...")
                debug_print(f"Sleeping {delay:.1f}s before retry...")
                time.sleep(delay)
                delay *= 2
            else:
                print(f"  Failed after {max_retries} attempts: {error_type}")
                debug_print(f"Final failure after {max_retries} attempts with {error_type}: {error_msg}")
                return None
    
    return None

def load_extracted_data_json(path):
    """Load extracted data from JSON file (from Step 1 output)"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def parse_json_to_records(json_data):
    """Parse JSON extracted data to records with vendor, item_name, UPC, and item_number"""
    records = []
    
    # json_data is a dict where keys are receipt IDs and values are receipt data
    for receipt_id, receipt_data in json_data.items():
        vendor = receipt_data.get('vendor', '').strip()
        items = receipt_data.get('items', [])
        
        # Only process Costco and RD receipts
        vendor_lower = vendor.lower()
        if 'costco' not in vendor_lower and 'restaurant' not in vendor_lower and 'rd' not in vendor_lower:
            continue
        
        for item in items:
            item_name = item.get('product_name', '').strip()
            item_number = item.get('item_number') or item.get('item_code')
            upc = item.get('upc')
            
            # Convert to string if numeric
            if item_number is not None:
                item_number = str(item_number).strip()
            if upc is not None:
                upc = str(upc).strip()
            
            # Only include items with item_number or UPC
            if item_number or upc:
                records.append({
                    'vendor': vendor,
                    'item_name': item_name,
                    'item_number': item_number if item_number else '',
                    'upc': upc if upc else ''
                })
    
    return records

def polite_sleep(a=1.0, b=3.0, delay_multiplier=1.0):
    """Sleep with configurable delay multiplier for rate limiting"""
    actual_delay = random.uniform(a, b) * delay_multiplier
    debug_print(f"Sleeping for {actual_delay:.2f}s (base: {a}-{b}s, multiplier: {delay_multiplier}x)")
    time.sleep(actual_delay)

# Global rate limit multiplier (increases when rate-limited)
RATE_LIMIT_MULTIPLIER = 1.0

def search_costco_by_name(session, headers, product_name, receipt_item_number=None):
    """
    Search Costco by product name and extract item numbers from search results.
    Returns the item number that best matches the product name and/or receipt item number.
    """
    debug_print(f"search_costco_by_name: product_name='{product_name}', receipt_item_number={receipt_item_number}")
    
    try:
        import requests
        from bs4 import BeautifulSoup as BS
        from difflib import SequenceMatcher
        import re
        
        # Normalize product name for fuzzy matching
        def normalize_text(text):
            """Normalize text for comparison"""
            if not text:
                return ""
            # Remove special characters, convert to lowercase
            text = re.sub(r'[^\w\s]', '', text.lower())
            # Remove extra whitespace
            text = ' '.join(text.split())
            return text
        
        normalized_search = normalize_text(product_name)
        
        # Search URL
        search_url = f"https://www.costco.com/CatalogSearch?dept=All&keyword={product_name.replace(' ', '+')}"
        debug_print(f"Costco search URL: {search_url}")
        
        try:
            print(f"    Searching Costco.com for: '{product_name}'")
            r = session.get(search_url, headers=headers, timeout=30)
            debug_print(f"Search response: {r.status_code}")
            
            if r.status_code != 200:
                debug_print(f"Search failed with status {r.status_code}")
                return None
            
            soup = BS(r.text, "lxml")
            
            # Find product items in search results
            # Costco search results typically have product cards
            products = []
            
            # Try different selectors for product cards
            product_selectors = [
                "div.product",
                "div[data-product-id]",
                "div.product-tile",
                "a.product-image",
                ".product-wrapper"
            ]
            
            for selector in product_selectors:
                items = soup.select(selector)
                if items:
                    debug_print(f"Found {len(items)} products using selector: {selector}")
                    for item in items[:10]:  # Limit to first 10 results
                        try:
                            # Extract product name
                            name_el = item.select_one("span.description, .description, a.product-name, h3, .product-title")
                            if not name_el:
                                continue
                            
                            product_name_text = name_el.get_text(strip=True)
                            if not product_name_text:
                                continue
                            
                            # Extract product link to get item number
                            link = item.select_one("a[href]") or name_el.find("a")
                            if not link or not link.get('href'):
                                continue
                            
                            href = link.get('href')
                            
                            # Extract item number from URL
                            # Costco URLs typically: /...product.html?item=XXXXX or /product.XXXXX.html
                            item_num_match = re.search(r'item[=_](\d+)', href) or re.search(r'\.(\d{4,8})\.', href) or re.search(r'/(\d{5,8})(?:\.html|/)', href)
                            item_num = None
                            if item_num_match:
                                item_num = item_num_match.group(1)
                            else:
                                # Try to find item number in product text or data attributes
                                item_num_el = item.select_one("[data-item-id], [data-product-id], [itemid]")
                                if item_num_el:
                                    item_num = item_num_el.get('data-item-id') or item_num_el.get('data-product-id') or item_num_el.get('itemid')
                            
                            if product_name_text:
                                products.append({
                                    'name': product_name_text,
                                    'name_normalized': normalize_text(product_name_text),
                                    'item_number': item_num,
                                    'url': href
                                })
                        except Exception as e:
                            debug_print(f"Error parsing product item: {type(e).__name__}: {e}")
                            continue
                    
                    if products:
                        break  # Found products, stop trying other selectors
            
            if not products:
                debug_print("No products found in search results")
                return None
            
            debug_print(f"Found {len(products)} products in search results")
            
            # Find best match
            best_match = None
            best_score = 0.0
            
            for product in products:
                score = 0.0
                
                # Score based on name similarity
                name_similarity = SequenceMatcher(None, normalized_search, product['name_normalized']).ratio()
                score += name_similarity * 0.7  # 70% weight on name match
                
                # Score bonus if item number matches
                if receipt_item_number and product['item_number']:
                    if str(receipt_item_number) == str(product['item_number']):
                        score += 0.3  # 30% bonus for item number match
                
                debug_print(f"  Product: '{product['name'][:50]}...' (item#: {product['item_number']}), score: {score:.2f}")
                
                if score > best_score:
                    best_score = score
                    best_match = product
            
            if best_match and best_score > 0.4:  # Minimum threshold
                matched_item_num = best_match['item_number']
                if matched_item_num:
                    print(f"    Best match: '{best_match['name'][:50]}...' (item#: {matched_item_num}, score: {best_score:.2f})")
                    return matched_item_num
                else:
                    debug_print(f"Best match found but no item number: {best_match['name']}")
            
            debug_print(f"No good match found (best score: {best_score:.2f})")
            return None
            
        except requests.RequestException as e:
            debug_print(f"Search request failed: {type(e).__name__}: {e}")
            return None
        except Exception as e:
            debug_print(f"Search parsing failed: {type(e).__name__}: {e}")
            return None
            
    except Exception as e:
        debug_print(f"search_costco_by_name error: {type(e).__name__}: {e}")
        return None

# Knowledge base for item specifications
# Structure: Item_Number: [product_name, store, standard_spec, estimated_unit_price]
KNOWLEDGE_BASE = {
    # Costco item numbers
    "506970": ["HEAVY CREAM", "Costco", "64 fl oz", 15.99],
    "1362911": ["ORG MANGOS", "Costco", "3.3 lbs bag", 9.89],
    "512515": ["ORG STRAWBRY", "Costco", "2 lbs carton", 8.99],
    "83345": ["LEMONS", "Costco", "5 lbs bag", 7.99],
    "3923": ["LIMES", "Costco", "5 lbs bag", 7.99],  # From receipt data
    
    # Restaurant Depot (RD) item numbers
    "980356": ["CHX NUGGET BTRD TY", "RD", "10 lbs bag", 28.67],
    "12235": ["OIL SHRT CRM LQ SR B", "RD", "35 lbs", 32.15],
    "77232": ["CHIX BREAST BNLS SKLS", "RD", "1 lb", 1.785],
    "1530299": ["CREAM JF 36% UHT 32Z", "RD", "32 fl oz", 54.51],
    "40213": ["FF ZESTY WAFFLE 27LB", "RD", "27 lbs box", 45.09],
    "69259": ["PANKO PLAIN CQ 25LB", "RD", "25 lbs bag", 28.14],
    "14001": ["SUGAR EFG DOMINO 25LB", "RD", "25 lbs bag", 19.84],
}

def load_knowledge_base_from_file(knowledge_base_file=None):
    """
    Load knowledge base from JSON file if provided, otherwise use default.
    
    Args:
        knowledge_base_file: Optional path to JSON file with knowledge base
        
    Returns:
        Dictionary with item_number -> [name, store, spec, price]
    """
    if knowledge_base_file:
        kb_path = Path(knowledge_base_file)
        if kb_path.exists():
            try:
                with open(kb_path, 'r', encoding='utf-8') as f:
                    loaded_kb = json.load(f)
                    debug_print(f"Loaded knowledge base from {kb_path}: {len(loaded_kb)} items")
                    return loaded_kb
            except Exception as e:
                debug_print(f"Failed to load knowledge base from {kb_path}: {e}")
                print(f"  ⚠️ Warning: Could not load knowledge base from file, using default")
    
    return KNOWLEDGE_BASE

def lookup_item_in_knowledge_base(item_number, knowledge_base=None):
    """
    Look up item specification and price from knowledge base.
    
    Args:
        item_number: Item number as string
        knowledge_base: Optional knowledge base dict (uses default if None)
        
    Returns:
        Dictionary with product info or None if not found
    """
    if knowledge_base is None:
        knowledge_base = KNOWLEDGE_BASE
    
    item_no = str(item_number).strip()
    if item_no in knowledge_base:
        name, store, spec, unit_price = knowledge_base[item_no]
        
        return {
            "title": name,
            "price": f"${unit_price:.2f}",
            "spec": spec,
            "store": store,
            "source": "knowledge_base"
        }
    
    return None

def scrape_costco(item_number, item_name=None):
    """
    Look up Costco product from knowledge base (no web scraping).
    """
    debug_print(f"scrape_costco called with item_number: {item_number}, item_name: {item_name}")
    
    # Try knowledge base lookup first
    result = lookup_item_in_knowledge_base(item_number)
    if result:
        print(f"  ✅ Found in knowledge base: {result['title']} ({result['spec']}) - {result['price']}")
        debug_print(f"Knowledge base lookup successful: {result}")
        
        # Return in expected format
        specs = {"Size": result['spec'], "Store": result['store']}
        return {
            "title": result['title'],
            "price": result['price'],
            "url": f"https://www.costco.com/.product.{item_number}.html",  # Constructed URL
            "specs_json": json.dumps(specs, ensure_ascii=False)
        }
    else:
        print(f"  ⚠️ Item number {item_number} not found in knowledge base")
        debug_print(f"Knowledge base lookup failed for item_number: {item_number}")
        return None

def scrape_upcitemdb_free(upc):
    """Free UPC lookup using UPCitemdb.com API (no API key required)"""
    debug_print(f"Trying free UPCitemdb API for UPC: {upc}")
    try:
        import requests
        url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={upc}"
        debug_print(f"UPCitemdb API URL: {url}")
        
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            debug_print(f"UPCitemdb API response: {data}")
            
            if data.get('code') == 'OK' and data.get('total', 0) > 0:
                item = data.get('items', [{}])[0]
                title = item.get('title', '')
                brand = item.get('brand', '')
                
                # Extract size from title or specs
                size = item.get('size', '') or item.get('dimension', '')
                
                return {
                    "title": title,
                    "brand": brand,
                    "size": size,
                    "url": f"https://www.upcitemdb.com/upc/{upc}",
                    "specs_json": json.dumps(item, ensure_ascii=False),
                    "source_api": "upcitemdb_free"
                }
    except Exception as e:
        debug_print(f"UPCitemdb API error: {type(e).__name__}: {e}")
    
    return None

def scrape_barcode_lookup(upc, use_free_first=True):
    """
    Look up UPC - tries free APIs first, then falls back to scraping
    
    Args:
        upc: UPC code
        use_free_first: If True, try free APIs first (default: True)
    """
    debug_print(f"scrape_barcode_lookup called with UPC: {upc}")
    
    # Try free API first (no scraping needed)
    if use_free_first:
        free_result = scrape_upcitemdb_free(upc)
        if free_result:
            debug_print(f"Successfully retrieved from free API")
            return free_result
    
    # Fall back to scraping barcodelookup.com (may have rate limits)
    debug_print(f"Trying barcodelookup.com scraping (fallback)")
    cloudscraper = _import_scrape_libs()
    scraper = cloudscraper.create_scraper(browser={
        "browser": "chrome", "platform": "windows", "mobile": False
    })
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/117.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    from bs4 import BeautifulSoup as BS
    url = f"https://www.barcodelookup.com/{upc}"
    debug_print(f"Barcode lookup URL: {url}")
    
    r = safe_get(scraper, url, headers, timeout=20)
    if not r or r.status_code != 200:
        debug_print(f"Barcode lookup failed: {r.status_code if r else 'None'}")
        return None
    debug_print(f"Barcode lookup successful, parsing...")
    
    soup = BS(r.text, 'lxml')
    title_el = soup.select_one("h4.product-title, h2.product-title, h1")
    details = {}
    for row in soup.select("table tr"):
        th = row.find('th')
        td = row.find('td')
        if th and td:
            key = th.get_text(strip=True)
            val = td.get_text(strip=True)
            if key and val:
                details[key] = val
    brand = details.get('Brand', '') or details.get('Manufacturer', '')
    size = details.get('Size', '') or details.get('Weight', '')
    return {
        "title": title_el.get_text(strip=True) if title_el else "",
        "brand": brand,
        "size": size,
        "url": url,
        "specs_json": json.dumps(details, ensure_ascii=False),
        "source_api": "barcodelookup_scrape"
    }

def process_records(records, out_csv, knowledge_base=None, limit=None, dry_run=False):
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = ["vendor","item_name","upc","item_number","title","price","brand","size","url","specs_json","source"]
    with out_csv.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        count = 0
        for rec in records:
            if limit and count >= limit:
                break
            vendor = (rec.get('vendor') or '').strip()
            item_name = (rec.get('item_name') or '').strip()
            upc = (rec.get('upc') or '').strip()
            item_number = (rec.get('item_number') or '').strip()

            result = {
                "vendor": vendor,
                "item_name": item_name,
                "upc": upc,
                "item_number": item_number,
                "title": "", "price": "", "brand": "", "size": "",
                "url": "", "specs_json": "", "source": ""
            }

            try:
                if dry_run:
                    w.writerow(result)
                    count += 1
                    continue

                # Try knowledge base lookup for Costco
                if vendor.lower().startswith('costco') and item_number:
                    print(f"  Looking up Costco item_number: {item_number} ({item_name})")
                    lookup_result = lookup_item_in_knowledge_base(item_number, knowledge_base)
                    if lookup_result:
                        result.update({
                            "title": lookup_result["title"],
                            "price": lookup_result["price"],
                            "size": lookup_result["spec"],
                            "url": f"https://www.costco.com/.product.{item_number}.html",
                            "specs_json": json.dumps({"Size": lookup_result["spec"], "Store": lookup_result["store"]}, ensure_ascii=False),
                            "source": "knowledge_base"
                        })
                        print(f"  ✅ Found: {lookup_result['title']} ({lookup_result['spec']}) - {lookup_result['price']}")
                        w.writerow(result)
                        count += 1
                        continue
                    else:
                        print(f"  ⚠️ Not found in knowledge base")
                
                # Try knowledge base lookup for RD by item_number
                if ('restaurant' in vendor.lower() or 'rd' in vendor.lower()) and item_number:
                    print(f"  Looking up RD item_number: {item_number} ({item_name})")
                    lookup_result = lookup_item_in_knowledge_base(item_number, knowledge_base)
                    if lookup_result:
                        result.update({
                            "title": lookup_result["title"],
                            "price": lookup_result["price"],
                            "size": lookup_result["spec"],
                            "url": "",
                            "specs_json": json.dumps({"Size": lookup_result["spec"], "Store": lookup_result["store"]}, ensure_ascii=False),
                            "source": "knowledge_base"
                        })
                        print(f"  ✅ Found: {lookup_result['title']} ({lookup_result['spec']}) - {lookup_result['price']}")
                        w.writerow(result)
                        count += 1
                        continue
                    else:
                        print(f"  ⚠️ Not found in knowledge base")
                
                # Write row even if not found (for manual review)
                w.writerow(result)
                count += 1

            except Exception as e:
                result["specs_json"] = json.dumps({"error": str(e)})
                w.writerow(result)
                count += 1
                polite_sleep(min_delay * 0.5, max_delay * 0.5, RATE_LIMIT_MULTIPLIER)

def main():
    import argparse
    from pathlib import Path
    global DEBUG
    
    ap = argparse.ArgumentParser(description="Look up Costco and RD product information from knowledge base")
    ap.add_argument("--report", type=str, default="data/step1_output/group1/extracted_data.json", 
                    help="Path to extracted_data.json (default: data/step1_output/group1/extracted_data.json)")
    ap.add_argument("--out", type=str, default="costco_rd_specs.csv", help="Output CSV path")
    ap.add_argument("--kb-file", type=str, default=None, help="Path to knowledge base JSON file (optional)")
    ap.add_argument("--limit", type=int, default=None, help="Limit number of rows to query")
    ap.add_argument("--dry-run", action="store_true", help="Only parse report and write rows without lookups")
    ap.add_argument("--debug", action="store_true", help="Enable debug mode with verbose output")
    args = ap.parse_args()
    
    # Set global debug flag
    DEBUG = args.debug
    if DEBUG:
        print("[DEBUG] Debug mode enabled - verbose output will be shown")
        print(f"[DEBUG] Output file: {args.out}")
    
    # Load knowledge base
    knowledge_base = load_knowledge_base_from_file(args.kb_file)
    print(f"Using knowledge base with {len(knowledge_base)} items")
    if args.kb_file:
        print(f"Knowledge base loaded from: {args.kb_file}")
    else:
        print("Using default knowledge base (hardcoded)")
    
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"Extracted data file not found: {report_path}", file=sys.stderr)
        print(f"Tried to read: {report_path.absolute()}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Loading extracted data from: {report_path}")
    json_data = load_extracted_data_json(report_path)
    recs = parse_json_to_records(json_data)
    
    # Filter to only Costco and RD items with item_number or UPC
    filtered = []
    for r in recs:
        vend = (r.get('vendor') or '').lower()
        has_identifier = r.get('item_number') or r.get('upc')
        if ('costco' in vend or 'restaurant' in vend or 'rd' in vend) and has_identifier:
            filtered.append(r)
    
    print(f"Found {len(recs)} items from receipts; {len(filtered)} items have identifiers (item_number or UPC).")
    if args.limit:
        print(f"Processing first {args.limit} items...")
    
    process_records(filtered, Path(args.out), knowledge_base=knowledge_base, 
                    limit=args.limit, dry_run=args.dry_run)
    print(f"Done! Results written to: {args.out}")

if __name__ == "__main__":
    main()
