#!/usr/bin/env python3
"""
Instacart Costco Fetcher
Fetches Costco product data from Instacart's Costco storefront.

Usage:
    python scripts/instacart_costco_fetch.py --actid <actid> --item 1362911
    python scripts/instacart_costco_fetch.py --actid <actid> --upc 123456789012
    python scripts/instacart_costco_fetch.py --actid <actid> --zip 60640 --max 200
"""

import json
import re
import time
import argparse
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

import requests
from bs4 import BeautifulSoup  # type: ignore

logger = logging.getLogger(__name__)


# Costco Same-Day URL (sameday.costco.com) - preferred
STORE_URL_SAMEDAY = "https://sameday.costco.com/store/costco/storefront"
# Fallback: Regular Instacart Costco URL
STORE_URL_INSTACART = "https://www.instacart.com/store/costco"


def _get_cookie_header(cookie_string: Optional[str] = None) -> Dict[str, str]:
    """Parse cookie string into header format."""
    if not cookie_string:
        return {}
    # Cookie string format: "name1=value1; name2=value2; ..."
    return {"Cookie": cookie_string}


def _get_chrome_cookies(domain: str = "instacart.com") -> Optional[str]:
    """Try to extract cookies from Chrome for the given domain."""
    try:
        # Try to use the chrome_cookies.py script
        script_path = Path(__file__).parent / "chrome_cookies.py"
        if script_path.exists():
            result = subprocess.run(
                ["python", str(script_path), "--domain", domain, "--format", "header"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                cookie_string = result.stdout.strip()
                # Filter out empty cookies (name=)
                cookies = [c.strip() for c in cookie_string.split(";") if "=" in c and not c.strip().endswith("=")]
                if cookies:
                    return "; ".join(cookies)
    except Exception as e:
        pass
    return None


def search_instacart_costco(query: str, actid: str, zipcode: Optional[str] = None, timeout: int = 15, headers: Optional[Dict[str, str]] = None, cookie_header: Optional[str] = None, use_sameday: bool = True) -> List[Dict[str, Any]]:
    """Search Costco Same-Day or Instacart Costco storefront by query (UPC or keyword) and extract product cards."""
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        hdrs.update(headers)
    
    # Add cookie header if provided
    if cookie_header:
        cookie_hdrs = _get_cookie_header(cookie_header)
        hdrs.update(cookie_hdrs)

    # Use Costco Same-Day URL (sameday.costco.com) by default, fallback to Instacart
    if use_sameday:
        # Costco Same-Day: try /store/costco/s?k= format (without /storefront)
        base_url = "https://sameday.costco.com/store/costco"
        if zipcode:
            url = f"{base_url}/s?k={requests.utils.quote(query)}&zipcode={zipcode}"
        else:
            url = f"{base_url}/s?k={requests.utils.quote(query)}"
    else:
        # Regular Instacart Costco URL
        base_url = STORE_URL_INSTACART
        if zipcode:
            url = f"{base_url}/s?k={requests.utils.quote(query)}&zipcode={zipcode}"
        else:
            url = f"{base_url}/s?k={requests.utils.quote(query)}"
    
    try:
        # Use session to maintain cookies (for Costco Same-Day)
        session = requests.Session()
        session.headers.update(hdrs)
        
        # For Costco Same-Day, first visit storefront to get session cookies
        if use_sameday:
            storefront_url = "https://sameday.costco.com/store/costco/storefront"
            try:
                # Visit storefront first to establish session
                session.get(storefront_url, timeout=timeout, allow_redirects=True)
                # If zipcode provided, try setting it via query param
                if zipcode:
                    zipcode_url = f"{storefront_url}?zipcode={zipcode}"
                    session.get(zipcode_url, timeout=timeout, allow_redirects=True)
            except Exception:
                pass  # Continue even if storefront visit fails
        
        resp = session.get(url, headers=hdrs, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
        
        # Debug: log response status and URL
        if len(html) < 1000:
            print(f"Debug: Response is short ({len(html)} chars), might be an error page")
            print(f"Debug: URL was: {url}")
            print(f"Debug: Status: {resp.status_code}")
        
        # Check if redirected to landing page
        if 'Enter your ZIP code' in html or 'Enter ZIP code' in html:
            logger.debug(f"Redirected to landing page - page may be JavaScript-rendered")
            # Continue anyway - might have data in JSON scripts
        
        soup = BeautifulSoup(html, "html.parser")

        products: List[Dict[str, Any]] = []
        
        # First, try to extract from JSON script tags (for JavaScript-rendered pages)
        scripts = soup.select('script[type="application/json"]')
        for script in scripts:
            content = script.string or ''
            if len(content) > 1000:
                # Try to parse as JSON or extract JSON-like data
                try:
                    # Look for JSON objects in the content
                    import json as _json
                    # Try to find JSON-like structures
                    json_match = re.search(r'\{[^{}]{100,}\}', content[:10000], re.DOTALL)
                    if json_match:
                        try:
                            data = _json.loads(json_match.group(0))
                            if isinstance(data, dict):
                                # Look for product-related keys
                                for key, value in data.items():
                                    if 'product' in key.lower() or 'item' in key.lower():
                                        logger.debug(f"Found product data in JSON: {key}")
                        except:
                            pass
                except:
                    pass
        
        # Product cards often use data-test="product-card" or role list items
        for card in soup.select('[data-test="product-card"], a[href*="/items/"]'):
            text = card.get_text(" \n", strip=True)
            # Extract basic fields heuristically
            name = None
            size = None
            brand = None
            dept = None

            # Try common selectors
            title_el = card.select_one('[data-test="product-card-title"], [data-testid="product-card-title"], .css-1p8v1v7, h3, h2')
            if title_el:
                name = title_el.get_text(strip=True)
            # size
            size_el = card.select_one('[data-test="product-card-unit-quantity"], .css-1bqeu6n, .css-1k2tj9p')
            if size_el:
                size = size_el.get_text(strip=True)
            # brand sometimes appears as first token or separate label
            brand_el = card.select_one('[data-test="product-card-brand"], .css-1w8l4v0')
            if brand_el:
                brand = brand_el.get_text(strip=True)
            else:
                # Heuristic: brand prefix before name (ALL CAPS word)
                if name:
                    m = re.match(r"^([A-Z][A-Z0-9&'\- ]{1,30})\s+(.+)$", name)
                    if m:
                        brand = m.group(1).strip()
                        name = m.group(2).strip()

            # Extract unit price from product card
            unit_price = None
            # Try price selectors
            price_el = card.select_one('[data-test="product-card-price"], [data-testid="product-card-price"], .price, [class*="price"]')
            if price_el:
                price_text = price_el.get_text(strip=True)
                # Extract numeric price (e.g., "$12.99" or "12.99")
                price_match = re.search(r'\$?(\d+\.?\d*)', price_text.replace(',', ''))
                if price_match:
                    try:
                        unit_price = float(price_match.group(1))
                    except ValueError:
                        pass
            
            # Fallback: search for price pattern in card text
            if unit_price is None:
                price_patterns = [
                    r'\$\s*(\d+\.?\d*)',  # $12.99
                    r'(\d+\.\d{2})\s*$',  # 12.99 at end
                    r'Price[:\s]+\$?(\d+\.?\d*)',  # Price: $12.99
                ]
                for pattern in price_patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        try:
                            unit_price = float(match.group(1))
                            break
                        except ValueError:
                            continue

            # department text may be in breadcrumbs or aria-labels; try a broad scan
            if not dept:
                m = re.search(r"Department\s*:\s*([^\n]+)", text, re.I)
                if m:
                    dept = m.group(1).strip()

            if name:
                product_data = {
                    "name": name,
                    "brand": brand or "",
                    "size": size or "",
                    "department": dept or "",
                    "query": query,
                    "url": url,
                }
                if unit_price is not None:
                    product_data["unit_price"] = unit_price
                products.append(product_data)

        return products
    except Exception as e:
        print(f"Error searching Instacart Costco: {e}")
        return []


def fetch_by_item_number(item_number: str, actid: str, zipcode: Optional[str] = None, cookie_header: Optional[str] = None, use_sameday: bool = True) -> Optional[Dict[str, Any]]:
    """Fetch Costco product by item number from Costco Same-Day or Instacart."""
    # Try searching by item number
    results = search_instacart_costco(item_number, actid, zipcode, cookie_header=cookie_header, use_sameday=use_sameday)
    if results:
        # Return first result
        return results[0]
    return None


def fetch_by_upc(upc: str, actid: str, zipcode: Optional[str] = None, cookie_header: Optional[str] = None, use_sameday: bool = True) -> Optional[Dict[str, Any]]:
    """Fetch Costco product by UPC from Costco Same-Day or Instacart."""
    # Try searching by UPC
    results = search_instacart_costco(upc, actid, zipcode, cookie_header=cookie_header, use_sameday=use_sameday)
    if results:
        # Return first result
        return results[0]
    return None


def load_costco_identifiers(extracted_path: Path) -> List[str]:
    """Load Costco item numbers and UPCs from extracted_data.json."""
    data = {}
    if extracted_path.exists():
        with extracted_path.open('r', encoding='utf-8') as f:
            data = json.load(f)
    ids: List[str] = []
    for oid, rec in data.items():
        vendor = (rec.get('vendor') or rec.get('vendor_name') or rec.get('detected_vendor_code') or '').upper()
        if vendor not in ('COSTCO', 'COSTCO WHOLESALE'):
            continue
        for it in rec.get('items', []):
            if it.get('is_fee'):
                continue
            upc = (it.get('upc') or '').strip()
            item_no = (it.get('item_number') or '').strip()
            if upc:
                ids.append(upc)
            elif item_no:
                ids.append(item_no)
    # de-duplicate
    seen = set()
    out: List[str] = []
    for v in ids:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def merge_into_kb(kb_path: Path, entries: List[Dict[str, Any]], allow_external_updates: bool = False) -> int:
    """
    Merge Instacart Costco entries into knowledge base.
    
    KB format: {item_number: [product_name, vendor, size_text, unit_price]}
    
    Args:
        kb_path: Path to knowledge base JSON file
        entries: List of product entries from Instacart
        allow_external_updates: If False, only add new entries, don't update existing ones
                                (prevents overwriting receipt-based prices with external prices)
    """
    kb = {}
    if kb_path.exists():
        with kb_path.open('r', encoding='utf-8') as f:
            try:
                kb = json.load(f)
            except Exception:
                kb = {}
    
    # KB format: item_number -> [product_name, store, size_spec, unit_price]
    merged = 0
    for e in entries:
        item_number = str(e.get('item_number', '')).strip()
        if not item_number:
            # Try to extract from query if it's numeric
            query = str(e.get('query', '')).strip()
            if re.fullmatch(r'\d{5,12}', query):
                item_number = query
            else:
                continue
        
        # Get unit price from Instacart if available
        instacart_unit_price = e.get('unit_price')
        
        # KB format: [product_name, store, size_spec, unit_price]
        if item_number in kb:
            # Only update if allow_external_updates is True
            if allow_external_updates:
                old_entry = kb[item_number]
                if isinstance(old_entry, list) and len(old_entry) >= 4:
                    old_price = old_entry[3]
                    # Use Instacart price if available, otherwise keep existing price
                    final_price = instacart_unit_price if instacart_unit_price is not None and instacart_unit_price > 0 else old_price
                    # Update entry with new info
                    kb[item_number] = [
                        e.get('name', old_entry[0]) or old_entry[0],
                        'Costco',
                        e.get('size', old_entry[2]) or old_entry[2],
                        final_price
                    ]
                    if instacart_unit_price is not None and instacart_unit_price > 0:
                        logger.info(f"Updated KB {item_number} with Instacart unit price: ${instacart_unit_price:.2f} (was ${old_price:.2f})")
                    merged += 1
            else:
                # Skip updating existing entries - keep receipt-based prices
                logger.debug(f"Skipped updating {item_number} - external updates disabled")
        else:
            # Add new entry
            entry = [
                e.get('name', ''),
                'Costco',
                e.get('size', ''),
                instacart_unit_price if instacart_unit_price is not None and instacart_unit_price > 0 else 0.0,
            ]
            kb[item_number] = entry
            merged += 1
    
    if merged > 0:
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        with kb_path.open('w', encoding='utf-8') as f:
            json.dump(kb, f, ensure_ascii=False, indent=2)
    
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description='Fetch Instacart Costco data and merge to KB')
    ap.add_argument('--actid', required=True, help='Instacart actid from storefront URL')
    ap.add_argument('--item', help='Costco item number to fetch')
    ap.add_argument('--upc', help='UPC code to fetch')
    ap.add_argument('--max', type=int, default=50, help='Max queries to attempt (when loading from extracted_data.json)')
    ap.add_argument('--zip', dest='zipcode', help='ZIP code for storefront localization (e.g., 60640)')
    ap.add_argument('--delay', type=float, default=0.8, help='Delay between queries (s)')
    ap.add_argument('--cookie', help='Cookie string for authenticated requests (e.g., "session_id=...; csrf_token=...")')
    ap.add_argument('--use-chrome-cookies', action='store_true', help='Automatically extract cookies from Chrome')
    ap.add_argument('--use-instacart', action='store_true', help='Use regular Instacart URL instead of Costco Same-Day')
    args = ap.parse_args()
    
    root = Path(__file__).resolve().parents[1]
    extracted_path = root / 'data/step1_output/localgrocery_based/extracted_data.json'
    kb_path = root / 'data/step1_input/knowledge_base.json'

    use_sameday = not args.use_instacart
    
    # Auto-extract cookies from Chrome if requested or if no cookie provided (for Costco Same-Day)
    cookie_header = args.cookie
    if args.use_chrome_cookies or (not cookie_header and use_sameday):
        print("Extracting cookies from Chrome...")
        # Try both instacart.com and costco.com domains
        chrome_cookies = _get_chrome_cookies("instacart.com")
        if not chrome_cookies:
            chrome_cookies = _get_chrome_cookies("costco.com")
        if chrome_cookies:
            cookie_header = chrome_cookies
            print(f"✅ Extracted {len(chrome_cookies.split(';'))} cookies from Chrome")
        else:
            if args.use_chrome_cookies:
                print("⚠️  Could not extract cookies from Chrome (may be encrypted)")
                print("   Try manually copying cookies from browser DevTools")
            elif use_sameday:
                print("ℹ️  No cookies provided - trying without cookies (may need cookies for Costco Same-Day)")
    
    if args.item:
        # Single item lookup
        source = "Costco Same-Day" if use_sameday else "Instacart"
        print(f"Fetching Costco item {args.item} from {source}...")
        result = fetch_by_item_number(args.item, args.actid, args.zipcode, cookie_header=cookie_header, use_sameday=use_sameday)
        if result:
            result['item_number'] = args.item
            print(json.dumps(result, indent=2, ensure_ascii=False))
            merged = merge_into_kb(kb_path, [result], allow_external_updates=False)
            if merged > 0:
                print(f"✅ Merged into {kb_path} (new entries only, no updates to existing)")
        else:
            print(f"❌ Item {args.item} not found")
    elif args.upc:
        # Single UPC lookup
        source = "Costco Same-Day" if use_sameday else "Instacart"
        print(f"Fetching Costco product by UPC {args.upc} from {source}...")
        result = fetch_by_upc(args.upc, args.actid, args.zipcode, cookie_header=cookie_header, use_sameday=use_sameday)
        if result:
            result['upc'] = args.upc
            print(json.dumps(result, indent=2, ensure_ascii=False))
            merged = merge_into_kb(kb_path, [result], allow_external_updates=False)
            if merged > 0:
                print(f"✅ Merged into {kb_path} (new entries only, no updates to existing)")
        else:
            print(f"❌ UPC {args.upc} not found")
    else:
        # Batch mode: load from extracted_data.json
        ids = load_costco_identifiers(extracted_path)
        if not ids:
            print('No Costco identifiers found in extracted_data.json')
            return
        ids = ids[: args.max]
        print(f"Found {len(ids)} Costco identifiers, fetching up to {args.max}...")
        all_entries: List[Dict[str, Any]] = []
        for q in ids:
            try:
                results = search_instacart_costco(q, args.actid, zipcode=args.zipcode, cookie_header=cookie_header, use_sameday=use_sameday)
                # Attach the query as item_number or upc
                for r in results:
                    if re.fullmatch(r'\d{8,14}', q):
                        r['upc'] = q
                    else:
                        r['item_number'] = q
                if results:
                    all_entries.extend(results[:3])  # keep top few
            except Exception as e:
                print(f"  Error fetching {q}: {e}")
                pass
            time.sleep(args.delay)

        merged = merge_into_kb(kb_path, all_entries, allow_external_updates=False)
        print(f"Merged {merged} Costco entries into {kb_path} (new entries only, no updates to existing)")


if __name__ == "__main__":
    exit(main())

