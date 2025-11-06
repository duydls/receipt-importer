#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
import argparse
from pathlib import Path
from typing import Dict, Any, Iterable, List

import requests
from bs4 import BeautifulSoup  # type: ignore


STORE_URL = "https://www.instacart.com/store/restaurant-depot/storefront"


def search_instacart_rd(query: str, actid: str, zipcode: str | None = None, timeout: int = 15, headers: Dict[str, str] | None = None) -> List[Dict[str, Any]]:
    """Search Instacart RD storefront by query (UPC or keyword) and extract product cards."""
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        hdrs.update(headers)

    # Common Instacart search pattern uses path /search/<query>
    extra = f"&zipcode={zipcode}" if zipcode else ""
    url = f"{STORE_URL}/search/{requests.utils.quote(query)}?actid={actid}{extra}"
    resp = requests.get(url, headers=hdrs, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    products: List[Dict[str, Any]] = []
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

        # department text may be in breadcrumbs or aria-labels; try a broad scan
        if not dept:
            m = re.search(r"Department\s*:\s*([^\n]+)", text, re.I)
            if m:
                dept = m.group(1).strip()

        if name:
            products.append({
                "name": name,
                "brand": brand or "",
                "size": size or "",
                "department": dept or "",
                "query": query,
                "url": url,
            })

    return products


def load_rd_identifiers(extracted_path: Path) -> List[str]:
    data = {}
    if extracted_path.exists():
        with extracted_path.open('r', encoding='utf-8') as f:
            data = json.load(f)
    ids: List[str] = []
    for oid, rec in data.items():
        vendor = (rec.get('vendor') or rec.get('vendor_name') or rec.get('detected_vendor_code') or '').upper()
        if vendor not in ('RD', 'RESTAURANT DEPOT', 'RESTAURANT_DEPOT', 'RESTAURANT'):
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
    # de-duplicate, keep short
    seen = set()
    out: List[str] = []
    for v in ids:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def merge_into_kb(kb_path: Path, entries: List[Dict[str, Any]]) -> int:
    kb = {}
    if kb_path.exists():
        with kb_path.open('r', encoding='utf-8') as f:
            try:
                kb = json.load(f)
            except Exception:
                kb = {}
    items: List[Dict[str, Any]] = kb.get('items') or []

    def kb_key(row: Dict[str, Any]) -> str:
        vendor = (row.get('vendor') or '').upper()
        key = row.get('upc') or row.get('sku') or row.get('item_number') or row.get('name')
        return f"{vendor}:{key}" if vendor and key else ''

    index: Dict[str, Dict[str, Any]] = {}
    for r in items:
        k = kb_key(r)
        if k:
            index[k] = r

    merged = 0
    for e in entries:
        row = {
            'vendor': 'RD',
            'upc': e.get('upc', ''),
            'item_number': e.get('item_number', ''),
            'canonical_name': e.get('name', ''),
            'vendor_brand': e.get('brand', ''),
            'raw_uom_text': e.get('size', ''),
            'rd_department': e.get('department', ''),
            'source_url': e.get('url', ''),
        }
        k = kb_key(row)
        if not k:
            continue
        if k in index:
            index[k].update({kk: vv for kk, vv in row.items() if vv})
        else:
            items.append(row)
            index[k] = row
        merged += 1

    kb['items'] = items
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    with kb_path.open('w', encoding='utf-8') as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description='Fetch Instacart RD data and merge to KB')
    ap.add_argument('--actid', required=True, help='Instacart actid from storefront URL')
    ap.add_argument('--max', type=int, default=80, help='Max queries to attempt')
    ap.add_argument('--zip', dest='zipcode', help='ZIP code for storefront localization (e.g., 60640)')
    ap.add_argument('--delay', type=float, default=0.8, help='Delay between queries (s)')
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    extracted_path = root / 'data/step1_output/localgrocery_based/extracted_data.json'
    kb_path = root / 'data/step1_input/knowledge_base.json'

    ids = load_rd_identifiers(extracted_path)
    if not ids:
        print('No RD identifiers found')
        return
    ids = ids[: args.max]
    all_entries: List[Dict[str, Any]] = []
    for q in ids:
        try:
            results = search_instacart_rd(q, args.actid, zipcode=args.zipcode)
            # Try to attach the query as upc if numeric length
            for r in results:
                if re.fullmatch(r"\d{8,14}", q):
                    r['upc'] = q
                else:
                    r['item_number'] = q
            if results:
                all_entries.extend(results[:3])  # keep top few
        except Exception as e:
            # continue on errors
            pass
        time.sleep(args.delay)

    merged = merge_into_kb(kb_path, all_entries)
    print(f"Merged {merged} RD entries into {kb_path}")


if __name__ == '__main__':
    main()


