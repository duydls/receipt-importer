from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any
import hashlib

import requests
from bs4 import BeautifulSoup  # type: ignore


@dataclass
class WismettacProduct:
    item_number: str
    name: Optional[str]
    category: Optional[str]
    pack_size_raw: Optional[str]
    pack: Optional[int]
    each_qty: Optional[float]
    each_uom: Optional[str]
    barcode: Optional[str]
    min_order_qty: Optional[str]
    detail_url: Optional[str]


class WismettacClient:
    BASE = "https://ecatalog.wismettacusa.com"

    def __init__(self, cache_dir: Path | str = "data/cache/wismettac", verify_ssl: bool = True):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.verify_ssl = verify_ssl

    def _cache_path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{h}.json"

    def _read_cache(self, key: str) -> Optional[Dict[str, Any]]:
        p = self._cache_path(key)
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                return None
        return None

    def _write_cache(self, key: str, data: Dict[str, Any]) -> None:
        p = self._cache_path(key)
        try:
            p.write_text(json.dumps(data))
        except Exception:
            pass

    def search_by_item_number(self, item_number: str, branch: int = 3, timeout: int = 10) -> Optional[Dict[str, Any]]:
        key = f"search:{branch}:{item_number}"
        cached = self._read_cache(key)
        if cached:
            return cached
        url = f"{self.BASE}/products.php"
        params = {"keyword": item_number, "branch": branch}
        resp = requests.get(url, params=params, timeout=timeout, verify=self.verify_ssl)
        resp.raise_for_status()
        data = self._parse_search(resp.text)
        if data:
            self._write_cache(key, data)
        return data

    def fetch_detail(self, relative_url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
        detail_url = relative_url if relative_url.startswith("http") else f"{self.BASE}/{relative_url.lstrip('/')}"
        key = f"detail:{detail_url}"
        cached = self._read_cache(key)
        if cached:
            return cached
        resp = requests.get(detail_url, timeout=timeout, verify=self.verify_ssl)
        resp.raise_for_status()
        data = self._parse_detail(resp.text)
        if data is not None:
            data["detail_url"] = detail_url
            self._write_cache(key, data)
        return data

    def lookup_product(self, item_number: str, branch: int = 3) -> Optional[WismettacProduct]:
        search = self.search_by_item_number(item_number, branch=branch)
        if not search:
            return None
        detail_rel = search.get("detail_url")
        detail = self.fetch_detail(detail_rel) if detail_rel else None
        name = search.get("name") or (detail or {}).get("name")
        category = (detail or {}).get("Category")
        pack_size_raw = (detail or {}).get("Pack Size") or search.get("pack_size")
        barcode = (detail or {}).get("Barcode (UPC)") or search.get("barcode")
        min_order_qty = (detail or {}).get("Minimum Order Qty")
        pack, each_qty, each_uom = parse_pack_size(pack_size_raw)
        return WismettacProduct(
            item_number=item_number,
            name=name,
            category=category,
            pack_size_raw=pack_size_raw,
            pack=pack,
            each_qty=each_qty,
            each_uom=each_uom,
            barcode=barcode,
            min_order_qty=min_order_qty,
            detail_url=(detail or {}).get("detail_url")
        )

    def _parse_search(self, html: str) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        card = soup.select_one(".product_list .box") or soup.select_one(".box")
        if not card:
            return None
        # Title/name
        name_el = card.select_one(".product_name") or card.select_one(".ttl") or card.select_one("a")
        name = name_el.get_text(strip=True) if name_el else None
        # Detail link
        link_el = card.select_one("a[href*='product.php']") or card.select_one("a[href*='product']")
        detail_url = link_el["href"] if link_el and link_el.has_attr("href") else None
        # Meta info (item number, pack size, barcode) - attempt common patterns
        meta_text = card.get_text("\n", strip=True)
        item_match = re.search(r"Item\s*#?:\s*(\S+)", meta_text, re.I)
        pack_match = re.search(r"Pack\s*Size\s*:?\s*([\w\s./#]+)", meta_text, re.I)
        barcode_match = re.search(r"(UPC|Barcode)\s*:?\s*([0-9\-]+)", meta_text, re.I)
        return {
            "name": name,
            "detail_url": detail_url,
            "item_number": item_match.group(1) if item_match else None,
            "pack_size": pack_match.group(1).strip() if pack_match else None,
            "barcode": barcode_match.group(2) if barcode_match else None,
        }

    def _parse_detail(self, html: str) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        right_table = soup.select_one(".right .table") or soup.select_one(".tbl")
        data: Dict[str, Any] = {}
        name_el = soup.select_one(".product_name") or soup.select_one("h1")
        if name_el:
            data["name"] = name_el.get_text(strip=True)
        if right_table:
            rows = right_table.select("tr")
            for tr in rows:
                th = tr.select_one("th")
                td = tr.select_one("td")
                if not th or not td:
                    continue
                key = th.get_text(strip=True)
                val = td.get_text(" ", strip=True)
                data[key] = val
        return data or None


_A10_RX = re.compile(r"(?i)\bA\s*10\b|#?10\s*can")
_PACK_RX = re.compile(r"(?i)^(\d+)\s*/\s*([\w#.]+(?:\s*[\w#.]+)*)$")
_QTY_UOM_RX = re.compile(r"(?i)^(\d+(?:\.\d+)?)\s*([a-z#0-9]+)$")


def parse_pack_size(text: Optional[str]) -> tuple[Optional[int], Optional[float], Optional[str]]:
    if not text:
        return None, None, None
    t = re.sub(r"\s+", " ", text.strip())
    # Handle A10 / #10 can as a special UOM
    if _A10_RX.search(t):
        m = re.search(r"(\d+)\s*/\s*(?:A\s*10|#?10\s*can)", t, re.I)
        if m:
            return int(m.group(1)), None, "#10_can"
        # fallback: treat as case count only
        m2 = re.search(r"(\d+)", t)
        return (int(m2.group(1)) if m2 else None), None, "#10_can"
    # Generic pattern: N / QTY UOM
    m = _PACK_RX.match(t)
    if m:
        pack = int(m.group(1))
        rest = m.group(2).strip()
        m2 = _QTY_UOM_RX.match(rest)
        if m2:
            qty = float(m2.group(1))
            uom = m2.group(2).upper()
            return pack, qty, uom
        # If only a UOM given
        return pack, None, rest.upper()
    # If only a number present, assume pack count
    m3 = re.search(r"^(\d+)$", t)
    if m3:
        return int(m3.group(1)), None, None
    return None, None, None


