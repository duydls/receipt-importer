#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Restaurant Depot (member.restaurantdepot.com) — UPC lookup (requires login)

Outputs exactly 7 normalized fields per product:
  brand, category, item_number, pack_size, minimum_order_qty, barcode, name

How to use (choose ONE cookie method):

A) Read cookies from your existing browser profile (no password in code)
   - pip install browser-cookie3 bs4 requests
   - python rd_member_upc_client.py 76069502838 --auto-cookie --pretty --json-fields

B) Paste a Cookie: header string manually
   - python rd_member_upc_client.py 76069502838 \
       --cookie "JSESSIONID=...; other=..." --pretty --json-fields

Optional: override the URL template if your store path differs
   --url-template "https://member.restaurantdepot.com/store/jetro-restaurant-depot/s?k={upc}"

Notes:
- Respect the site's Terms of Use. Do not hammer (script has basic backoff).
- If your account is tied to a different warehouse, switch warehouses in the browser,
  re-grab cookies, and rerun.
- HTML structure may change; the parser tries multiple selectors and key/value scans.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# Optional Playwright support for JavaScript-rendered content
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# --------------------------- Config ---------------------------
DEFAULT_URL_TEMPLATE = (
    "https://member.restaurantdepot.com/store/jetro-restaurant-depot/s?k={upc}"
)
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)
RD_DOMAIN = "member.restaurantdepot.com"

# ---------------------- Normalization ------------------------
PUBLIC_KEYS: Dict[str, List[str]] = {
    "brand": ["Brand", "brand"],
    "category": ["Category", "category", "Department", "department"],
    "item_number": ["Item Number", "itemNumber", "Item #", "item_number", "SKU", "sku", "Item"],
    "pack_size": ["Pack Size", "packSize", "pack_size", "Case Pack", "Pack", "Size"],
    "minimum_order_qty": ["Minimum Order Qty", "minOrderQty", "min_order_qty", "MOQ", "Min"],
    "barcode": ["Barcode (UPC)", "UPC", "upc", "barcode", "EAN", "ean"],
    "name": ["name", "Product Name", "Title", "title"],
}


def to_public_json(d: Dict[str, Any]) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for key, aliases in PUBLIC_KEYS.items():
        val: Optional[Any] = None
        for a in aliases:
            if a in d and d[a]:
                val = d[a]
                break
        # synthesize pack_size from structured 'pack'
        if key == "pack_size" and val is None and isinstance(d.get("pack"), dict):
            p = d["pack"]
            if p.get("raw"):
                val = p["raw"]
            elif p.get("caseQty") and p.get("uom"):
                part = f"{p['caseQty']}/"
                each = p.get("each")
                if each and each not in (1, 1.0):
                    part += f"{each}"
                part += str(p["uom"])
                val = part
        out[key] = (str(val).strip() if val is not None else None)
    return out

# ------------------------ HTTP layer -------------------------

def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    jar: Dict[str, str] = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar


def get_session(cookie: Optional[str], auto_cookie: bool, user_agent: Optional[str], insecure: bool) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent or DEFAULT_UA})
    if auto_cookie:
        try:
            import browser_cookie3  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("browser-cookie3 not installed. pip install browser-cookie3") from e
        # Try common browsers; filter by RD domain
        cj = None
        for loader_name in ("chrome", "edge", "firefox", "chromium"):
            fn = getattr(browser_cookie3, loader_name, None)
            if not fn:
                continue
            try:
                cj = fn(domain_name=RD_DOMAIN)
                break
            except Exception:
                continue
        if not cj:
            raise RuntimeError("Could not read cookies from any browser profile for member.restaurantdepot.com")
        for c in cj:
            if RD_DOMAIN in (c.domain or "") and c.name and c.value:
                s.cookies.set(c.name, c.value, domain=c.domain)
    elif cookie:
        s.cookies.update(parse_cookie_string(cookie))
    s.verify = not insecure
    return s


def fetch_html(session: requests.Session, url: str, retries: int = 3, backoff: float = 0.8) -> str:
    last_err: Optional[Exception] = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=25)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(backoff * (2 ** i))
    raise RuntimeError(f"GET failed for {url}: {last_err}")

# ------------------------ Parsers ----------------------------

KV_LABEL_RE = re.compile(r"\s*([^:：]+)\s*[:：]\s*(.+)")
UPC_RE = re.compile(r"\b(UPC|Barcode)\b[:：]?\s*([0-9]{8,14})", re.I)


def _clean(x: str) -> str:
    return re.sub(r"\s+", " ", x).strip()


def extract_kv_from_table(soup: BeautifulSoup) -> Dict[str, str]:
    kv: Dict[str, str] = {}

    # dl lists
    for dl in soup.select("dl"):
        dts = dl.select("dt")
        dds = dl.select("dd")
        if len(dts) == len(dds) and dts:
            for dt, dd in zip(dts, dds):
                lab = _clean(dt.get_text(" "))
                val = _clean(dd.get_text(" "))
                if lab and val:
                    kv[lab] = val

    # th/td tables or two-column tables
    for tbl in soup.select("table"):
        for tr in tbl.select("tr"):
            ths = tr.select("th")
            tds = tr.select("td")
            if len(ths) == 1 and len(tds) == 1:
                lab = _clean(ths[0].get_text(" "))
                val = _clean(tds[0].get_text(" "))
                if lab and val:
                    kv[lab] = val
            elif len(tds) >= 2 and not ths:
                lab = _clean(tds[0].get_text(" "))
                val = _clean(tds[1].get_text(" "))
                if lab and val and len(lab) <= 40:
                    kv[lab] = val

    # inline p/li pairs
    for node in soup.select("p, li"):
        txt = _clean(node.get_text(" "))
        m = KV_LABEL_RE.match(txt)
        if m:
            lab, val = _clean(m.group(1)), _clean(m.group(2))
            if lab and val:
                kv[lab] = val

    return kv


def parse_pack_size(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = _clean(text.upper())
    out: Dict[str, Any] = {"raw": text}

    # patterns like 6/5LB, 24/12OZ, 12/1L, 4/GAL, 100CT
    m = re.match(r"^(\d+)\s*/\s*(\d+(?:\.\d+)?)\s*(LB|KG|G|OZ|ML|L|GAL|CT)\b", s)
    if m:
        out.update({"caseQty": int(m.group(1)), "each": float(m.group(2)), "uom": m.group(3)})
        return out

    # #10 cans
    m = re.match(r"^(\d+)\s*/\s*(?:A?10|#10)\b", s)
    if m:
        out.update({"caseQty": int(m.group(1)), "uom": "#10_can"})
        return out

    # single-unit sizes like 10LB, 1L, 500ML, SGAL
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(LB|KG|G|OZ|ML|L|CT|GAL|S?GAL)\b", s)
    if m:
        out.update({"caseQty": 1, "each": float(m.group(1)), "uom": m.group(2)})
        return out

    return out


def discover_detail_links(search_url: str, soup: BeautifulSoup) -> List[str]:
    hrefs: List[str] = []
    for a in soup.select("a"):
        href = a.get("href") or ""
        if not href:
            continue
        if re.search(r"/product/|/products/|productId=|sku=|/dp/", href, re.I):
            hrefs.append(href)
    # absolutize
    out: List[str] = []
    seen: set[str] = set()
    origin = re.match(r"^(https?://[^/]+)/?", search_url)
    base = origin.group(1) if origin else "https://member.restaurantdepot.com"
    for h in hrefs:
        full = h if h.startswith("http") else (base + (h if h.startswith("/") else "/" + h))
        if full not in seen:
            seen.add(full)
            out.append(full)
    return out


def parse_detail_page(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    kv = extract_kv_from_table(soup)

    # title/name candidates
    name_el = soup.select_one("h1, .product-title, .title, [data-test=product-title], .pdp-title")
    if name_el and "name" not in kv:
        kv["name"] = _clean(name_el.get_text(" "))

    # hint selectors for common PDP blocks
    hints = {
        "Brand": [".brand", ".product-brand", "[data-test=brand]"],
        "Category": [".category", ".product-category", "[data-test=category]", ".breadcrumbs a:last-child"],
        "Item Number": [".sku", ".item-number", "#item-number", "[data-test=sku]", ".product-sku"],
        "Pack Size": [".pack-size", ".case-pack", "[data-test=pack]", ".product-pack"],
        "Minimum Order Qty": [".min-order", ".moq", "[data-test=moq]", ".product-min-order"],
        "UPC": [".upc", ".barcode", "[data-test=upc]", ".product-upc"],
    }
    for label, sels in hints.items():
        if label in kv:
            continue
        for sel in sels:
            el = soup.select_one(sel)
            if el:
                kv[label] = _clean(el.get_text(" "))
                break

    # pack struct
    if "Pack Size" in kv:
        kv["pack"] = parse_pack_size(kv.get("Pack Size"))

    # try regex for UPC anywhere in page text
    m = UPC_RE.search(html)
    if m and "UPC" not in kv and "Barcode (UPC)" not in kv:
        kv["UPC"] = m.group(2)

    return kv


def parse_search_page(html: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    soup = BeautifulSoup(html, "html.parser")

    # Try extracting inline product cards (varies by FE)
    results: List[Dict[str, Any]] = []
    for card in soup.select(".product, .product-card, .card, .result, .list-item, [data-test=product-card]"):
        entry: Dict[str, Any] = {}
        name_el = card.select_one(".name, .title, .product-name, a, [data-test=product-name]")
        if name_el:
            entry["name"] = _clean(name_el.get_text(" "))
            if name_el.has_attr("href"):
                entry["detail_url"] = name_el["href"]
        entry.update(extract_kv_from_table(card))
        if entry:
            results.append(entry)

    links = discover_detail_links("https://member.restaurantdepot.com", soup)
    return results, links

# ------------------------- Client ----------------------------

def build_search_url(template: str, upc: str) -> str:
    if "{upc}" not in template:
        raise ValueError("--url-template must contain '{upc}' placeholder")
    return template.replace("{upc}", requests.utils.quote(upc))


async def fetch_by_upc_playwright(upc: str, url_template: str, cookies: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Fetch RD product data using Playwright (for JavaScript-rendered content)"""
    if not PLAYWRIGHT_AVAILABLE:
        return []
    
    search_url = build_search_url(url_template, upc)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        
        # Add cookies if provided
        if cookies:
            # Try to add cookies, handling __Host- cookies separately
            valid_cookies = []
            for cookie in cookies:
                try:
                    # __Host- cookies need special handling
                    if cookie.get('name', '').startswith('__Host-'):
                        # Ensure required fields for __Host- cookies
                        cookie['path'] = '/'
                        cookie['secure'] = True
                        if 'domain' in cookie:
                            del cookie['domain']
                    await context.add_cookies([cookie])
                    valid_cookies.append(cookie)
                except Exception:
                    # Skip invalid cookies
                    pass
        
        page = await context.new_page()
        
        # Monitor network for GraphQL queries (including product detail queries)
        graphql_responses = []
        product_detail_responses = []
        
        async def handle_response(response):
            url = response.url
            if 'graphql' in url.lower():
                try:
                    body = await response.body()
                    text = body.decode('utf-8')
                    data = json.loads(text)
                    # Check if it's a product detail query
                    if 'item' in url.lower() or 'product' in url.lower() or 'detail' in url.lower():
                        if 'search' not in url.lower():
                            product_detail_responses.append(data)
                    graphql_responses.append(data)
                except:
                    pass
        
        page.on('response', handle_response)
        
        # Navigate and wait for content
        await page.goto(search_url, wait_until='networkidle', timeout=30000)
        
        # Wait for product results
        try:
            await page.wait_for_selector('.product, .product-card, .item, [data-testid*="product"], img[alt*="product"], a[href*="/items/"]', timeout=10000)
        except:
            pass
        
        # Wait a bit for page to fully load
        await page.wait_for_timeout(2000)
        
        # Find product images/links and click them to open pop-ups
        results = []
        
        # Try to find product images/links - look for clickable product elements
        product_selectors = [
            'a[href*="/items/"]',
            '[data-testid*="product"]',
            '[data-testid*="item"]',
            '.product-card',
            '.item-card',
            '[class*="product-card"]',
            '[class*="item-card"]',
            'img[alt*="product"]',
            '[role="button"][aria-label*="product"]',
        ]
        
        product_elements = []
        for selector in product_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    product_elements = elements[:10]  # Limit to first 10 products
                    print(f'Found {len(elements)} elements with selector: {selector}')
                    break
            except:
                pass
        
        if not product_elements:
            # Try to find any clickable elements that might be products
            all_links = await page.query_selector_all('a[href*="item"], a[href*="product"]')
            if all_links:
                product_elements = all_links[:10]
                print(f'Found {len(all_links)} product links')
        
        print(f'Will click on {len(product_elements)} product elements')
        
        # Click on each product to open pop-up and extract data
        for i, element in enumerate(product_elements[:5]):  # Limit to first 5
            try:
                # Scroll element into view
                await element.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)
                
                # Click on the product
                await element.click()
                await page.wait_for_timeout(1500)  # Wait for pop-up to open
                
                # Wait for modal/dialog to appear
                try:
                    await page.wait_for_selector('[role="dialog"], .modal, .popup, [data-testid*="modal"], [data-testid*="popup"]', timeout=3000)
                except:
                    pass
                
                # Extract data from pop-up
                popup_data = await page.evaluate("""
                    () => {
                        // Look for product detail modal/popup
                        const selectors = [
                            '[role="dialog"]',
                            '.modal',
                            '.popup',
                            '[data-testid*="modal"]',
                            '[data-testid*="popup"]',
                            '[data-testid*="dialog"]',
                            '[class*="modal"]',
                            '[class*="popup"]',
                            '[class*="dialog"]',
                            '[aria-modal="true"]',
                        ];
                        
                        for (const selector of selectors) {
                            const modals = document.querySelectorAll(selector);
                            for (const modal of modals) {
                                // Check if visible
                                const style = window.getComputedStyle(modal);
                                if (style.display !== 'none' && style.visibility !== 'hidden' && modal.offsetParent !== null) {
                                    return {
                                        text: modal.innerText || modal.textContent || '',
                                        html: modal.outerHTML.substring(0, 3000)
                                    };
                                }
                            }
                        }
                        return null;
                    }
                """)
                
                if popup_data:
                    # Parse pop-up data
                    soup = BeautifulSoup(popup_data.get('html', ''), 'html.parser')
                    text = popup_data.get('text', '')
                    
                    # Extract product information
                    product = {}
                    
                    # Extract name
                    name_elem = soup.select_one('h1, h2, h3, [class*="name"], [class*="title"], [data-testid*="name"]')
                    if name_elem:
                        product['name'] = name_elem.get_text(strip=True)
                        product['Product Name'] = product['name']
                    
                    # Extract UPC - try multiple patterns
                    upc_patterns = [
                        r'UPC[:\s]*(\d{12,14})',
                        r'Barcode[:\s]*(\d{12,14})',
                        r'(\d{12,14})',  # Any 12-14 digit number
                    ]
                    for pattern in upc_patterns:
                        upc_match = re.search(pattern, text, re.I)
                        if upc_match:
                            upc_value = upc_match.group(1)
                            product['UPC'] = upc_value
                            product['barcode'] = upc_value
                            product['Barcode (UPC)'] = upc_value
                            break
                    
                    # Extract price
                    price_match = re.search(r'\$?([\d,]+\.?\d*)', text)
                    if price_match:
                        product['price'] = price_match.group(1)
                    
                    # Extract size
                    size_match = re.search(r'(\d+(?:/\d+)?)\s*(lb|lbs|oz|ct|each|ea|pack|pk|fl\s*oz)', text, re.I)
                    if size_match:
                        product['size'] = f"{size_match.group(1)} {size_match.group(2)}"
                        product['Size'] = product['size']
                    
                    # Extract brand
                    brand_match = re.search(r'Brand[:\s]*([^\n]+)', text, re.I)
                    if brand_match:
                        product['brand'] = brand_match.group(1).strip()
                        product['Brand'] = product['brand']
                    
                    if product:
                        results.append(product)
                        print(f'  Extracted product {i+1}: {product.get("name", "")[:50]}')
                
                # Close pop-up (press Escape or click outside)
                await page.keyboard.press('Escape')
                await page.wait_for_timeout(500)
                
            except Exception as e:
                # Continue with next product
                print(f'  Error clicking product {i+1}: {e}')
                pass
        
        # Also check for product detail GraphQL responses
        if product_detail_responses:
            print(f'Found {len(product_detail_responses)} product detail GraphQL responses')
            for resp_data in product_detail_responses:
                # Parse product detail from GraphQL response
                # This would need the actual structure of the product detail query
                pass
        
        await browser.close()
        
        return results


def fetch_by_upc_graphql(session: requests.Session, upc: str, shop_id: str = '59693', postal_code: str = '60640', zone_id: str = '974') -> List[Dict[str, Any]]:
    """Fetch RD product data using GraphQL SearchResultsPlacements query"""
    graphql_url = 'https://member.restaurantdepot.com/graphql'
    
    # Get user ID from session if available
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
        test_resp = session.get(graphql_url, params=test_params)
        if test_resp.status_code == 200:
            test_data = test_resp.json()
            user_id = test_data.get('data', {}).get('currentUser', {}).get('id')
    except:
        pass
    
    # Generate session token (simplified - in production, this should be obtained from the page)
    import uuid
    import time
    page_view_id = str(uuid.uuid4())
    search_id = str(uuid.uuid4())
    
    # Build variables for SearchResultsPlacements
    variables = {
        'filters': [],
        'action': None,
        'query': upc,
        'pageViewId': page_view_id,
        'retailerInventorySessionToken': f'v1.deaf425.{user_id or "18238936739404192"}-{postal_code}-04197x18765-1-7933-473323-0-0',
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
        'shopId': shop_id,
        'postalCode': postal_code,
        'zoneId': zone_id,
        'first': 20,
    }
    
    headers = {
        'User-Agent': DEFAULT_UA,
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
    
    try:
        resp = session.get(graphql_url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        
        # Parse product items from response
        results = []
        placements = data.get('data', {}).get('searchResultsPlacements', {}).get('placements', [])
        
        for placement in placements:
            content = placement.get('content', {})
            if 'placement' in content and 'items' in content['placement']:
                items = content['placement']['items']
                for item in items:
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
                        'detail_url': f"https://member.restaurantdepot.com/store/jetro-restaurant-depot/storefront/items/{item.get('productId', '')}" if item.get('productId') else '',
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
        return []


def fetch_by_upc(session: requests.Session, upc: str, url_template: str, detail_follow: int = 10, use_playwright: bool = False, use_graphql: bool = True) -> List[Dict[str, Any]]:
    # Try GraphQL first (fastest and most reliable)
    if use_graphql:
        try:
            graphql_results = fetch_by_upc_graphql(session, upc)
            if graphql_results:
                # Filter by UPC if we can find it, otherwise return all
                return graphql_results
        except Exception as e:
            # Fall back to HTML parsing
            pass
    
    search_url = build_search_url(url_template, upc)
    html = fetch_html(session, search_url)
    page_results, links = parse_search_page(html)

    # If no results and Playwright is available, try Playwright
    if not page_results and not links and use_playwright and PLAYWRIGHT_AVAILABLE:
        try:
            import asyncio
            import browser_cookie3
            
            # Get cookies from session
            cookies = []
            for cookie in session.cookies:
                cookie_dict = {
                    'name': cookie.name,
                    'value': cookie.value,
                    'path': cookie.path or '/',
                    'secure': bool(cookie.secure) if hasattr(cookie, 'secure') else True,
                    'httpOnly': bool(cookie.has_nonstandard_attr('HttpOnly')) if hasattr(cookie, 'has_nonstandard_attr') else False,
                }
                
                # Handle __Host- prefixed cookies (must not have domain, must have secure, must have path=/)
                if cookie.name.startswith('__Host-'):
                    cookie_dict['path'] = '/'
                    cookie_dict['secure'] = True
                    # Don't set domain for __Host- cookies
                else:
                    domain = cookie.domain or 'member.restaurantdepot.com'
                    # Playwright requires domain format: .domain.com
                    if domain and '.' in domain and not domain.startswith('.'):
                        domain = f".{domain}"
                    cookie_dict['domain'] = domain
                
                cookies.append(cookie_dict)
            
            # Try Playwright
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            playwright_results = loop.run_until_complete(fetch_by_upc_playwright(upc, url_template, cookies))
            loop.close()
            
            if playwright_results:
                return playwright_results
        except Exception as e:
            # Fall back to regular parsing
            pass

    out: List[Dict[str, Any]] = []
    followed = 0
    for href in links:
        if followed >= detail_follow:
            break
        # absolutize relative hrefs against the member host
        origin = re.match(r"^(https?://[^/]+)/?", search_url)
        base = origin.group(1) if origin else "https://member.restaurantdepot.com"
        detail_url = href if href.startswith("http") else base + (href if href.startswith("/") else "/" + href)
        try:
            dhtml = fetch_html(session, detail_url)
            detail = parse_detail_page(dhtml)
            detail["detail_url"] = detail_url
            out.append(detail)
            followed += 1
        except Exception as e:  # noqa: BLE001
            out.append({"detail_url": detail_url, "_error": str(e)})

    if not out and page_results:
        out = page_results

    # Prefer entries whose UPC equals the query
    filtered: List[Dict[str, Any]] = []
    for d in out:
        for k in ("UPC", "Barcode (UPC)", "barcode", "upc"):
            if str(d.get(k) or "").strip() == upc:
                filtered.append(d)
                break
    return filtered or out

# --------------------------- CLI -----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Restaurant Depot member site – UPC fetcher (cookie-based)")
    ap.add_argument("upcs", nargs="+", help="One or more UPCs to lookup")
    ap.add_argument("--url-template", default=DEFAULT_URL_TEMPLATE,
                    help="Search URL template containing '{upc}'. Default points to Jetro Chicago store")
    ap.add_argument("--cookie", help="Cookie header string (from your logged-in browser)")
    ap.add_argument("--auto-cookie", action="store_true", help="Read cookies from local browser profiles for member.restaurantdepot.com")
    ap.add_argument("--user-agent", default=None, help="Custom User-Agent")
    ap.add_argument("--insecure", action="store_true", help="Disable TLS verification (not recommended)")
    ap.add_argument("--detail-follow", type=int, default=10, help="Max detail links to follow per UPC")
    ap.add_argument("--json-fields", action="store_true", help="Output only the 7 normalized fields")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    ap.add_argument("--use-playwright", action="store_true", help="Use Playwright for JavaScript-rendered content (requires playwright installed)")
    ap.add_argument("--use-graphql", action="store_true", default=True, help="Use GraphQL API directly (default: True)")
    ap.add_argument("--no-graphql", dest="use_graphql", action="store_false", help="Disable GraphQL API and use HTML parsing")
    args = ap.parse_args()
    
    if args.use_playwright and not PLAYWRIGHT_AVAILABLE:
        raise SystemExit("Playwright not available. Install with: pip install playwright && playwright install chromium")

    if not (args.cookie or args.auto_cookie):
        raise SystemExit("Provide --cookie or --auto-cookie to authenticate.")

    sess = get_session(args.cookie, args.auto_cookie, args.user_agent, args.insecure)

    all_rows: List[Dict[str, Any]] = []
    for upc in args.upcs:
        try:
            details = fetch_by_upc(sess, upc, args.url_template, detail_follow=args.detail_follow, use_playwright=args.use_playwright, use_graphql=args.use_graphql)
            if args.json_fields:
                all_rows.extend([to_public_json(d) for d in details])
            else:
                for d in details:
                    row = dict(d)
                    row["_normalized"] = to_public_json(d)
                    all_rows.append(row)
        except Exception as e:  # noqa: BLE001
            all_rows.append({"upc": upc, "_error": str(e)})

    print(json.dumps(all_rows, indent=2 if args.pretty else None, ensure_ascii=False))


if __name__ == "__main__":
    main()
