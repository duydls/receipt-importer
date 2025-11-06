#!/usr/bin/env python3
from __future__ import annotations

import re
import json
import time
import argparse
from typing import Optional, Dict, Any
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup  # type: ignore

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


def get_html(url: str, verify: bool, tries: int = 3, sleep: float = 1.5) -> str:
    last_exc: Optional[Exception] = None
    for _ in range(tries):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                timeout=15,
                verify=verify,
            )
            if r.status_code == 200 and r.text:
                return r.text
        except Exception as e:
            last_exc = e
        time.sleep(sleep)
    raise RuntimeError(f"fetch failed: {url} ({last_exc})")


def parse_pack_size(pack: Optional[str]) -> Optional[Dict[str, Any]]:
    if not pack:
        return None
    s = re.sub(r"\s+", " ", pack).strip()
    m = re.match(r"^(\d+)\s*/\s*([\d.]+)\s*(LB|OZ|KG|G)\b", s, re.I)
    if m:
        case_qty = int(m.group(1))
        each = float(m.group(2))
        uom = m.group(3).upper()
        each_oz = (
            each * 16
            if uom == "LB"
            else (each * 35.274 if uom == "KG" else (each * 0.035274 if uom == "G" else each))
        )
        return {"caseQty": case_qty, "each": each, "uom": uom, "eachOz": round(each_oz, 4)}
    m = re.match(r"^(\d+)\s*/\s*A?10\b", s, re.I)
    if m:
        return {"caseQty": int(m.group(1)), "each": None, "uom": "#10_can", "eachOz": None}
    return {"raw": s}


def fetch_wismettac_by_keyword(keyword: str, branch: str = "3", verify: bool = True) -> Dict[str, Any]:
    search_url = f"https://ecatalog.wismettacusa.com/products.php?keyword={quote(keyword)}&branch={quote(branch)}"
    html = get_html(search_url, verify=verify)
    soup = BeautifulSoup(html, "html.parser")

    data: Dict[str, Any] = {"keyword": keyword, "branch": branch}

    # Broad text scan on search page
    txt = soup.get_text(" \n", strip=True)
    m_item = re.search(r"#\s*(\w{4,})", txt)
    if m_item:
        data["itemNumber"] = m_item.group(1)
    m_pack = re.search(r"Pack\s*Size\s*:\s*([^\n]+)", txt)
    if m_pack:
        data["packSizeRaw"] = m_pack.group(1).strip()
    m_bar = re.search(r"Barcode\s*:\s*([0-9]{8,14})", txt)
    if m_bar:
        data["barcode"] = m_bar.group(1)

    # First detail link
    a = soup.select_one('a[href*="product.php"]')
    if a and a.get("href"):
        details_url = urljoin(search_url, a["href"])
        data["detailsUrl"] = details_url

        dhtml = get_html(details_url, verify=verify)
        dsoup = BeautifulSoup(dhtml, "html.parser")

        title = dsoup.select_one("h1, h2, .product-title, .title")
        if title:
            data["name"] = title.get_text(strip=True)

        # Robust key:value scan
        dtext = dsoup.get_text("\n", strip=True)
        for line in dtext.split("\n"):
            line = re.sub(r"\s+", " ", line).strip()
            if ":" not in line:
                continue
            key, val = [x.strip() for x in line.split(":", 1)]
            lk = key.lower()
            if "item" in lk and "number" in lk and "itemNumber" not in data:
                mm = re.search(r"(\w{4,})", val)
                data["itemNumber"] = mm.group(1) if mm else val
            elif lk.startswith("category") and "category" not in data:
                data["category"] = val
            elif lk.startswith("brand") and "brand" not in data:
                data["brand"] = val
            elif lk.startswith("pack size") and "packSizeRaw" not in data:
                data["packSizeRaw"] = val
            elif "minimum order" in lk and "minOrderQty" not in data:
                data["minOrderQty"] = val
            elif "barcode" in lk and "barcode" not in data:
                mm = re.search(r"([0-9]{8,14})", val)
                data["barcode"] = mm.group(1) if mm else val

    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch Wismettac item metadata by keyword (item number)")
    ap.add_argument("keywords", nargs="+", help="Item numbers or keywords to search")
    ap.add_argument("--branch", default="3", help="Branch code (default: 3)")
    ap.add_argument("--insecure", action="store_true", help="Disable SSL verification (not recommended)")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = ap.parse_args()

    out = []
    for kw in args.keywords:
        rec = fetch_wismettac_by_keyword(kw, branch=args.branch, verify=not args.insecure)
        parsed = parse_pack_size(rec.get("packSizeRaw"))
        if parsed:
            rec["packParsed"] = parsed
        out.append(rec)

    if args.pretty:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()


