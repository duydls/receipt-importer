#!/usr/bin/env python3
"""
Costco Product Fetcher
Fetches product information from Costco.com by item number.

Note: Costco.com has anti-scraping measures and may block requests.
For reliable price inference, the system uses knowledge_base.json which is
updated from actual receipts (total/qty calculation).

Current Workflow:
1. Knowledge Base Lookup (Primary): step1_extract/pdf_processor_unified.py
   - Queries kb.get(item_number) -> kb_entry[3] (price)
   - Updates KB from receipts automatically
2. Web Scraping (Optional/Experimental): This script
   - May fail due to anti-scraping measures
   - Use knowledge base approach for production

Usage:
    python scripts/costco_fetch.py --item 1362911
    python scripts/costco_fetch.py --item 1362911 --pretty
    python scripts/costco_fetch.py --item 1362911 --merge-kb
"""

import json
import re
import time
import argparse
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup  # type: ignore

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

CACHE_DIR = Path("cache/costco")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_html(url: str, tries: int = 3, sleep: float = 2.0) -> str:
    """
    Fetch HTML with retries and caching.
    
    Note: Costco.com may have anti-scraping measures. If this fails,
    consider using cloudscraper or selenium for more robust scraping.
    """
    cache_path = CACHE_DIR / f"{hash(url) % 10**10}.html"
    
    # Check cache first
    if cache_path.exists():
        with open(cache_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    last_exc: Optional[Exception] = None
    for i in range(tries):
        try:
            r = requests.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                },
                timeout=20,
                allow_redirects=True,
            )
            if r.status_code == 200 and r.text:
                # Cache the response
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(r.text)
                return r.text
            elif r.status_code == 403:
                raise RuntimeError(f"Access forbidden (403) - Costco.com may be blocking requests. Try using cloudscraper or selenium.")
        except requests.exceptions.Timeout:
            last_exc = Exception(f"Timeout (attempt {i+1}/{tries})")
        except Exception as e:
            last_exc = e
        if i < tries - 1:
            time.sleep(sleep * (i + 1))  # Exponential backoff
    raise RuntimeError(f"fetch failed: {url} ({last_exc})")


def fetch_costco_by_item_number(item_number: str) -> Optional[Dict[str, Any]]:
    """
    Fetch Costco product by item number.
    
    Note: Costco.com has anti-scraping measures. This may fail with timeouts or 403 errors.
    For production use, consider:
    1. Using cloudscraper library (handles Cloudflare)
    2. Using selenium with a headless browser
    3. Using the knowledge base approach (already implemented in main workflow)
    
    Args:
        item_number: Costco item number (e.g., "1362911")
        
    Returns:
        Dictionary with product info or None if not found
    """
    # Costco product URL format: https://www.costco.com/.product.{item_number}.html
    url = f"https://www.costco.com/.product.{item_number}.html"
    
    try:
        html = get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract product name
        name = None
        name_selectors = [
            'h1[data-automation-id="productName"]',
            'h1.product-name',
            'h1.product-title',
            'h1',
        ]
        for selector in name_selectors:
            el = soup.select_one(selector)
            if el:
                name = el.get_text(strip=True)
                break
        
        # Extract price
        price = None
        price_selectors = [
            '[data-automation-id="productPrice"]',
            '.price',
            '.product-price',
            '[itemprop="price"]',
        ]
        for selector in price_selectors:
            el = soup.select_one(selector)
            if el:
                price_text = el.get_text(strip=True)
                # Extract numeric price
                price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
                if price_match:
                    try:
                        price = float(price_match.group(0))
                    except ValueError:
                        pass
                break
        
        # Extract size/spec
        size = None
        size_selectors = [
            '[data-automation-id="productSize"]',
            '.product-size',
            '.size',
        ]
        for selector in size_selectors:
            el = soup.select_one(selector)
            if el:
                size = el.get_text(strip=True)
                break
        
        # Extract brand
        brand = None
        brand_selectors = [
            '[data-automation-id="productBrand"]',
            '.product-brand',
            '.brand',
        ]
        for selector in brand_selectors:
            el = soup.select_one(selector)
            if el:
                brand = el.get_text(strip=True)
                break
        
        # Extract description
        description = None
        desc_selectors = [
            '[data-automation-id="productDescription"]',
            '.product-description',
            '.description',
        ]
        for selector in desc_selectors:
            el = soup.select_one(selector)
            if el:
                description = el.get_text(strip=True)
                break
        
        if name:
            return {
                "item_number": item_number,
                "name": name,
                "price": price,
                "size": size,
                "brand": brand,
                "description": description,
                "url": url,
            }
    except Exception as e:
        print(f"Error fetching Costco item {item_number}: {e}")
    
    return None


def merge_to_knowledge_base(item_data: Dict[str, Any], kb_path: Path) -> bool:
    """Merge item data into knowledge_base.json."""
    if not kb_path.exists():
        print(f"Knowledge base not found: {kb_path}")
        return False
    
    with open(kb_path) as f:
        kb = json.load(f)
    
    item_number = str(item_data.get("item_number", ""))
    if not item_number:
        print("No item number in item_data")
        return False
    
    # KB format: [product_name, store, size_spec, unit_price]
    entry = [
        item_data.get("name", ""),
        "Costco",
        item_data.get("size", ""),
        item_data.get("price", 0.0),
    ]
    
    kb[item_number] = entry
    
    with open(kb_path, 'w') as f:
        json.dump(kb, f, indent=2)
    
    print(f"✅ Merged {item_number} into knowledge base")
    return True


def main():
    parser = argparse.ArgumentParser(description="Fetch Costco product by item number")
    parser.add_argument("--item", required=True, help="Costco item number")
    parser.add_argument("--pretty", action="store_true", help="Pretty print JSON")
    parser.add_argument("--merge-kb", action="store_true", help="Merge into knowledge_base.json")
    parser.add_argument("--kb-path", default="data/step1_input/knowledge_base.json", help="Knowledge base path")
    
    args = parser.parse_args()
    
    item_data = fetch_costco_by_item_number(args.item)
    
    if item_data:
        if args.pretty:
            print(json.dumps(item_data, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(item_data, ensure_ascii=False))
        
        if args.merge_kb:
            kb_path = Path(args.kb_path)
            merge_to_knowledge_base(item_data, kb_path)
    else:
        print(f"❌ Item {args.item} not found")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())

