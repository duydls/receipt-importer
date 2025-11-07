#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wismettac eCatalog fetcher → normalized JSON (7 fields):
  brand, category, item_number, pack_size, minimum_order_qty, barcode, name

Usage examples:
  # Search by keyword (branch can be code like CHI or numeric like 3)
  python wismettac_client.py "SKYLINE DSH SGAL" --branch CHI --json-fields --pretty

  # Search by item number as keyword
  python wismettac_client.py 15407 --branch 3 --json-fields --pretty

  # If the site requires login, pass your browser cookie string
  python wismettac_client.py 15407 --cookie "PHPSESSID=...; other=..." --json-fields

Notes:
- This script scrapes public pages intended for humans. Respect the site's Terms of Use.
- HTML structure may change. The parser uses heuristic selectors and key/value table scanning.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://ecatalog.wismettacusa.com"
SEARCH_PATH = "/products.php"  # ?keyword=...&branch=...
# Detail links are discovered from search results; we don't hardcode the path.

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/119.0 Safari/537.36"
)

# ------------------------------------------------------------
# Normalization helpers (public JSON shape)
# ------------------------------------------------------------
PUBLIC_KEYS: Dict[str, List[str]] = {
    "brand": ["Brand", "brand"],
    "category": ["Category", "category"],
    "item_number": ["Item Number", "itemNumber", "item_number", "sku", "productId"],
    "pack_size": ["Pack Size", "packSizeRaw", "pack_size", "casePack", "pack"],
    "minimum_order_qty": ["Minimum Order Qty", "minOrderQty", "min_order_qty", "MOQ"],
    "barcode": ["Barcode (UPC)", "barcode", "upc", "ean"],
    "name": ["name", "Product Name", "title"],
}


def to_public_json(d: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Produce the 7-field public JSON from any detail/search dict.
    If a value is missing, return None for that field.
    If a structured pack dict exists, synthesize pack_size when needed.
    """
    out: Dict[str, Optional[str]] = {}
    for key, aliases in PUBLIC_KEYS.items():
        val: Optional[Any] = None
        for a in aliases:
            if a in d and d[a]:
                val = d[a]
                break
        if key == "pack_size" and val is None and isinstance(d.get("pack"), dict):
            p = d["pack"]
            if p.get("raw"):
                val = p["raw"]
            elif p.get("caseQty") and p.get("uom"):
                each = p.get("each")
                part = f"{p['caseQty']}/"
                if each and each not in (1, 1.0):
                    part += f"{each}"
                part += f"{p['uom']}"
                val = part
        out[key] = str(val).strip() if isinstance(val, (str, int, float)) else (val if val is None else str(val))
    return out


# ------------------------------------------------------------
# HTTP utilities
# ------------------------------------------------------------

def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    jar: Dict[str, str] = {}
    for part in cookie_str.split(";"):
        if not part.strip():
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar


def get_session(cookie: Optional[str], user_agent: Optional[str], insecure: bool) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent or DEFAULT_UA})
    if cookie:
        s.cookies.update(parse_cookie_string(cookie))
    # Store verify flag on the session for convenience
    s.verify = not insecure
    return s


def fetch_html(session: requests.Session, url: str, *, retries: int = 3, backoff: float = 0.8) -> str:
    last_exc: Optional[Exception] = None
    for i in range(retries):
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"server returned {resp.status_code}")
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as e:  # noqa: BLE001
            last_exc = e
            time.sleep(backoff * (2 ** i))
    raise RuntimeError(f"Failed to GET {url}: {last_exc}")


# ------------------------------------------------------------
# Parsers
# ------------------------------------------------------------

KV_LABEL_RE = re.compile(r"\s*([^:：]+)\s*[:：]\s*(.+)")


def _clean_text(x: str) -> str:
    return re.sub(r"\s+", " ", x).strip()


def extract_kv_from_table(soup: BeautifulSoup) -> Dict[str, str]:
    """Scan common product detail layouts:
    - dl/dt/dd blocks
    - table with th/td or header/data columns
    - p or li with "Label: Value"
    Returns a dict of {Label: Value} in display casing.
    """
    kv: Dict[str, str] = {}

    # dl lists
    for dl in soup.select("dl"):
        dts = dl.select("dt")
        dds = dl.select("dd")
        if len(dts) == len(dds) and len(dts) > 0:
            for dt, dd in zip(dts, dds):
                lab = _clean_text(dt.get_text(" "))
                val = _clean_text(dd.get_text(" "))
                # Strip "#" prefix from Item Number
                if lab and "item" in lab.lower() and "number" in lab.lower():
                    val = val.lstrip("#").strip()
                if lab and val:
                    kv[lab] = val

    # tables
    for tbl in soup.select("table"):
        rows = tbl.select("tr")
        # th/td pairs
        for tr in rows:
            ths = tr.select("th")
            tds = tr.select("td")
            if len(ths) == 1 and len(tds) == 1:
                lab = _clean_text(ths[0].get_text(" "))
                val = _clean_text(tds[0].get_text(" "))
                # Strip "#" prefix from Item Number
                if lab and "item" in lab.lower() and "number" in lab.lower():
                    val = val.lstrip("#").strip()
                if lab and val:
                    kv[lab] = val
            elif len(tds) >= 2 and not ths:
                # two-column table without th
                lab = _clean_text(tds[0].get_text(" "))
                val = _clean_text(tds[1].get_text(" "))
                # Strip "#" prefix from Item Number
                if lab and "item" in lab.lower() and "number" in lab.lower():
                    val = val.lstrip("#").strip()
                if lab and val and len(lab) <= 40:
                    kv[lab] = val

    # paragraphs or list items containing "Label: Value"
    for node in soup.select("p, li"):
        txt = _clean_text(node.get_text(" "))
        m = KV_LABEL_RE.match(txt)
        if m:
            lab, val = _clean_text(m.group(1)), _clean_text(m.group(2))
            # Strip "#" prefix from Item Number
            if lab and "item" in lab.lower() and "number" in lab.lower():
                val = val.lstrip("#").strip()
            if lab and val:
                kv[lab] = val

    return kv


def discover_detail_links(soup: BeautifulSoup) -> List[str]:
    """From a search page, collect product detail hrefs.
    We accept links that look like product detail pages.
    """
    hrefs: List[str] = []
    for a in soup.select("a"):
        href = a.get("href") or ""
        if not href:
            continue
        # heuristics: product detail pages often include "products_detail" or have id param
        if "products_detail" in href or re.search(r"[?&](id|productId|sku)=", href):
            hrefs.append(href)
    # dedupe while preserving order
    seen: set[str] = set()
    out: List[str] = []
    for h in hrefs:
        full = h if h.startswith("http") else (BASE_URL + (h if h.startswith("/") else "/" + h))
        if full not in seen:
            seen.add(full)
            out.append(full)
    return out


def parse_pack_size(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse common pack/size formats into a structured dict.
    Returns None if no parse; otherwise {'raw': original, 'caseQty', 'each', 'uom', 'eachOz'} as available.
    """
    if not text:
        return None
    s = _clean_text(text.upper())
    out: Dict[str, Any] = {"raw": text}

    # #10 cans (e.g., 6/A10 or 6/#10)
    m = re.match(r"^(\d+)\s*/\s*(?:A?10|#10)\b", s, re.I)
    if m:
        out.update({"caseQty": int(m.group(1)), "uom": "#10_can"})
        return out

    # gallons (e.g., 4/SGAL or 4/GAL, or just SGAL/GAL)
    m = re.match(r"^(\d+)\s*/\s*S?GAL\b", s)
    if m:
        out.update({"caseQty": int(m.group(1)), "each": 1.0, "uom": "GAL", "eachOz": 128.0})
        return out
    m = re.match(r"^S?GAL\b", s)
    if m:
        out.update({"caseQty": 1, "each": 1.0, "uom": "GAL", "eachOz": 128.0})
        return out

    # patterns like 6/5LB, 6/10KG, 24/12OZ, 12/1L, 24/500ML
    m = re.match(r"^(\d+)\s*/\s*(\d+(?:\.\d+)?)\s*(LB|KG|G|OZ|ML|L)\b", s)
    if m:
        case_q = int(m.group(1))
        each = float(m.group(2))
        uom = m.group(3)
        each_oz = None
        if uom == "LB":
            each_oz = each * 16.0
        elif uom == "KG":
            each_oz = each * 35.274
        elif uom == "G":
            each_oz = each * 0.035274
        elif uom == "ML":
            each_oz = each * 0.033814
        elif uom == "L":
            each_oz = each * 33.814
        elif uom == "OZ":
            each_oz = each
        out.update({"caseQty": case_q, "each": each, "uom": uom, "eachOz": each_oz})
        return out

    # single-unit sizes like 10LB, 1L, 500ML, 100CT
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(LB|KG|G|OZ|ML|L|CT)\b", s)
    if m:
        qty = float(m.group(1))
        uom = m.group(2)
        out.update({"caseQty": 1, "each": qty, "uom": uom})
        return out

    return out


def parse_detail_page(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    kv = extract_kv_from_table(soup)

    # Try to find the product title/name - prioritize specific product name selectors
    # Avoid sidebar elements like "EXPLORE MORE"
    name_selectors = [
        "h1#product-name",
        "h1.col-lg-6",
        ".product-name h1",
        ".product-title h1",
        "h1.product-name",
        "h1",
        "h2.product-name",
        "h2"
    ]
    
    product_name = None
    for selector in name_selectors:
        title = soup.select_one(selector)
        if title:
            text = _clean_text(title.get_text(" "))
            # Skip common sidebar/header text
            if text and text.upper() not in ["EXPLORE MORE", "PRODUCTS", "CATEGORIES", "BRANDS"]:
                product_name = text
                break
    
    if product_name and "name" not in kv:
        kv["name"] = product_name
    elif "name" not in kv:
        # Fallback: try to find any h1/h2 that's not in common sidebar text
        for title in soup.select("h1, h2"):
            text = _clean_text(title.get_text(" "))
            if text and text.upper() not in ["EXPLORE MORE", "PRODUCTS", "CATEGORIES", "BRANDS"] and len(text) > 5:
                kv["name"] = text
                break

    # Some sites put key info under specific spans/divs; scrape obvious ones
    hints = {
        "Brand": [".brand", ".product-brand"],
        "Category": [".category", ".product-category"],
        "Item Number": [".sku", ".item-number", "#item-number"],
        "Pack Size": [".pack-size", ".case-pack"],
        "Minimum Order Qty": [".min-order", ".moq"],
        "Barcode (UPC)": [".upc", ".barcode"],
    }
    for label, sels in hints.items():
        if label in kv:
            continue
        for sel in sels:
            el = soup.select_one(sel)
            if el:
                text = _clean_text(el.get_text(" "))
                # Strip "#" prefix from Item Number
                if label == "Item Number":
                    text = text.lstrip("#").strip()
                kv[label] = text
                break

    # Attach structured pack parse for convenience
    if "Pack Size" in kv:
        kv["pack"] = parse_pack_size(kv.get("Pack Size"))

    return kv


def parse_search_page(html: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    soup = BeautifulSoup(html, "html.parser")

    # Collect detail links
    links = discover_detail_links(soup)

    # Attempt to get quick fields directly on the search page (if available)
    results: List[Dict[str, Any]] = []
    for card in soup.select(".product, .product-card, .card, .result, .list-item"):
        entry: Dict[str, Any] = {}
        name_el = card.select_one(".name, .title, .product-name, a")
        if name_el:
            entry["name"] = _clean_text(name_el.get_text(" "))
            href = name_el.get("href")
            if href:
                entry["detail_url"] = href if href.startswith("http") else BASE_URL + (href if href.startswith("/") else "/" + href)
        # A quick table within card
        entry.update(extract_kv_from_table(card))
        if entry:
            results.append(entry)

    return results, links


# ------------------------------------------------------------
# High-level client
# ------------------------------------------------------------

def build_search_url(keyword: str, branch: Union[str, int]) -> str:
    b = str(branch).strip()
    return f"{BASE_URL}{SEARCH_PATH}?keyword={requests.utils.quote(keyword)}&branch={requests.utils.quote(b)}"


def fetch_by_product_id(session: requests.Session, product_id: str, branch: Optional[Union[str, int]] = None) -> Optional[Dict[str, Any]]:
    """Fetch product directly by product ID (fallback when search fails)."""
    # Try direct product page URL
    url = f"{BASE_URL}/product.php?id={product_id}"
    if branch:
        url += f"&branch={branch}"
    
    try:
        html = fetch_html(session, url)
        detail = parse_detail_page(html)
        detail["detail_url"] = url
        return detail
    except Exception as e:  # noqa: BLE001
        return None


def fetch_by_keyword(session: requests.Session, keyword: str, branch: Union[str, int]) -> List[Dict[str, Any]]:
    url = build_search_url(keyword, branch)
    try:
        html = fetch_html(session, url)
        page_results, links = parse_search_page(html)

        out: List[Dict[str, Any]] = []
        # Follow discovered links for authoritative detail info
        for href in links[:20]:  # cap to avoid surprises
            try:
                detail_html = fetch_html(session, href)
                detail = parse_detail_page(detail_html)
                # inherit obvious name if missing
                if not detail.get("name"):
                    detail["name"] = next((r.get("name") for r in page_results if r.get("detail_url") == href), None)
                detail["detail_url"] = href
                out.append(detail)
            except Exception as e:  # noqa: BLE001
                # fall back to whatever minimal info we had on the search page
                out.append({"detail_url": href, "_error": str(e)})

        # If no detail links found, return whatever we parsed from the search page
        if not out and page_results:
            out = page_results

        return out
    except Exception as e:  # noqa: BLE001
        # If search fails, try direct product ID lookup as fallback
        # Only if keyword looks like a numeric product ID
        if keyword.isdigit() or (keyword.replace('A', '').replace('B', '').isdigit()):
            direct_result = fetch_by_product_id(session, keyword, branch)
            if direct_result:
                return [direct_result]
        # Re-raise the original error if fallback also fails
        raise


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Wismettac eCatalog fetch → normalized JSON")
    ap.add_argument("keywords", nargs="+", help="Search keywords (or item numbers)")
    ap.add_argument("--branch", default="CHI", help="Branch code or id (e.g., CHI or 3). Default: CHI")
    ap.add_argument("--cookie", default=None, help="Browser cookie string (if login is required)")
    ap.add_argument("--user-agent", default=None, help="Custom User-Agent")
    ap.add_argument("--insecure", action="store_true", help="Disable TLS verification (not recommended)")
    ap.add_argument("--json-fields", action="store_true", help="Output only the 7 normalized fields per product")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = ap.parse_args()

    session = get_session(args.cookie, args.user_agent, args.insecure)

    aggregated: List[Dict[str, Any]] = []
    for kw in args.keywords:
        try:
            detail_dicts = fetch_by_keyword(session, kw, args.branch)
            # If search failed or returned no results, try direct product ID lookup
            if not detail_dicts or (len(detail_dicts) == 1 and '_error' in detail_dicts[0]):
                # Try direct product ID lookup if keyword looks like a product ID
                if kw.isdigit() or (kw.replace('A', '').replace('B', '').isdigit()):
                    direct_result = fetch_by_product_id(session, kw, args.branch)
                    if direct_result:
                        detail_dicts = [direct_result]
            
            if detail_dicts:
                if args.json_fields:
                    aggregated.extend([to_public_json(d) for d in detail_dicts])
                else:
                    # enrich with normalized view side-by-side
                    for d in detail_dicts:
                        e = dict(d)
                        e["_normalized"] = to_public_json(d)
                        aggregated.append(e)
            else:
                aggregated.append({"keyword": kw, "_error": "Product not found"})
        except Exception as e:  # noqa: BLE001
            # Try direct product ID lookup as fallback
            if kw.isdigit() or (kw.replace('A', '').replace('B', '').isdigit()):
                try:
                    direct_result = fetch_by_product_id(session, kw, args.branch)
                    if direct_result:
                        if args.json_fields:
                            aggregated.append(to_public_json(direct_result))
                        else:
                            e = dict(direct_result)
                            e["_normalized"] = to_public_json(direct_result)
                            aggregated.append(e)
                        continue
                except Exception:
                    pass
            aggregated.append({"keyword": kw, "_error": str(e)})

    print(json.dumps(aggregated, indent=2 if args.pretty else None, ensure_ascii=False))


if __name__ == "__main__":
    main()
