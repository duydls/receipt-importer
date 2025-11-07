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
    brand: Optional[str]
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

    def __init__(self, cache_dir: Path | str = "data/cache/wismettac"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

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

    def search_by_item_number(self, item_number: str, branch: str | int | None = None, timeout: int = 10, verify: bool = False) -> Optional[Dict[str, Any]]:
        """Search by item number. Branch is optional."""
        branch_key = str(branch) if branch is not None else "default"
        key = f"search:{branch_key}:{item_number}"
        cached = self._read_cache(key)
        if cached:
            return cached
        url = f"{self.BASE}/products.php"
        params = {"keyword": item_number}
        if branch is not None:
            params["branch"] = str(branch)
        try:
            resp = requests.get(url, params=params, timeout=timeout, verify=verify)
            resp.raise_for_status()
            data = self._parse_search(resp.text)
            if data:
                self._write_cache(key, data)
            return data
        except requests.exceptions.SSLError:
            # Retry without SSL verification
            resp = requests.get(url, params=params, timeout=timeout, verify=False)
            resp.raise_for_status()
            data = self._parse_search(resp.text)
            if data:
                self._write_cache(key, data)
            return data
    
    def search_by_product_name(self, product_name: str, branch: str | int | None = None, timeout: int = 10, verify: bool = False) -> Optional[Dict[str, Any]]:
        """Search by product name (fallback if item number search fails). Branch is optional."""
        # Extract key words from product name (remove common words, keep main terms)
        # For example: "CAN 6/A10 SWEET KERNEL CORN" -> "SWEET KERNEL CORN" or "CORN"
        keywords = product_name.strip()
        # Remove common prefixes like "CAN", "OIL", etc. if they're at the start
        keywords = re.sub(r'^(CAN|OIL|SOUP BASE)\s+', '', keywords, flags=re.I)
        # Use first 2-3 significant words
        words = [w for w in keywords.split() if len(w) > 2][:3]
        if not words:
            words = [keywords[:20]]  # Fallback to first 20 chars
        
        search_term = ' '.join(words)
        branch_key = str(branch) if branch is not None else "default"
        key = f"search_name:{branch_key}:{search_term}"
        cached = self._read_cache(key)
        if cached:
            return cached
        
        url = f"{self.BASE}/products.php"
        params = {"keyword": search_term}
        if branch is not None:
            params["branch"] = str(branch)
        try:
            resp = requests.get(url, params=params, timeout=timeout, verify=verify)
            resp.raise_for_status()
            data = self._parse_search(resp.text)
            if data:
                self._write_cache(key, data)
            return data
        except requests.exceptions.SSLError:
            # Retry without SSL verification
            resp = requests.get(url, params=params, timeout=timeout, verify=False)
            resp.raise_for_status()
            data = self._parse_search(resp.text)
            if data:
                self._write_cache(key, data)
            return data

    def fetch_detail(self, relative_url: str, timeout: int = 10, verify: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch product detail page. URL can be relative or absolute."""
        detail_url = relative_url if relative_url.startswith("http") else f"{self.BASE}/{relative_url.lstrip('/')}"
        key = f"detail:{detail_url}"
        cached = self._read_cache(key)
        if cached:
            return cached
        try:
            resp = requests.get(detail_url, timeout=timeout, verify=verify)
            resp.raise_for_status()
            data = self._parse_detail(resp.text)
            if data is not None:
                data["detail_url"] = detail_url
                self._write_cache(key, data)
            return data
        except requests.exceptions.SSLError:
            # Retry without SSL verification
            resp = requests.get(detail_url, timeout=timeout, verify=False)
            resp.raise_for_status()
            data = self._parse_detail(resp.text)
            if data is not None:
                data["detail_url"] = detail_url
                self._write_cache(key, data)
            return data
    
    def fetch_product_by_id(self, product_id: str | int, branch: str | int | None = None, timeout: int = 10, verify: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch product directly by product ID using URL format: product.php?id={id} (branch is optional)"""
        product_id_str = str(product_id)
        # Use branch in cache key if provided, otherwise use "default"
        branch_key = str(branch) if branch is not None else "default"
        key = f"product_id:{branch_key}:{product_id_str}"
        cached = self._read_cache(key)
        if cached:
            return cached
        
        url = f"{self.BASE}/product.php"
        params = {"id": product_id_str}
        # Only add branch parameter if provided
        if branch is not None:
            params["branch"] = str(branch)
        
        # Add browser-like headers to avoid blocking
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout, verify=verify)
            # Don't raise on 404 - check if response contains product data anyway
            if resp.status_code == 404:
                # Check if response is actually a 404 page or contains product data
                if 'Error 404' in resp.text or 'Not Found' in resp.text:
                    return None
            resp.raise_for_status()
            data = self._parse_detail(resp.text)
            if data is not None:
                # Build detail_url with or without branch
                if branch is not None:
                    data["detail_url"] = f"{url}?id={product_id_str}&branch={str(branch)}"
                else:
                    data["detail_url"] = f"{url}?id={product_id_str}"
                self._write_cache(key, data)
            return data
        except requests.exceptions.SSLError:
            # Retry without SSL verification
            resp = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
            # Don't raise on 404 - check if response contains product data anyway
            if resp.status_code == 404:
                # Check if response is actually a 404 page or contains product data
                if 'Error 404' in resp.text or 'Not Found' in resp.text:
                    return None
            resp.raise_for_status()
            data = self._parse_detail(resp.text)
            if data is not None:
                # Build detail_url with or without branch
                if branch is not None:
                    data["detail_url"] = f"{url}?id={product_id_str}&branch={str(branch)}"
                else:
                    data["detail_url"] = f"{url}?id={product_id_str}"
                self._write_cache(key, data)
            return data
        except requests.exceptions.HTTPError as e:
            # If it's a 404, return None instead of raising
            if e.response.status_code == 404:
                return None
            raise

    def lookup_product(self, item_number: str, branch: str | int | None = None) -> Optional[WismettacProduct]:
        """Lookup product by item number. Branch is optional."""
        search = self.search_by_item_number(item_number, branch=branch)
        if not search:
            return None
        
        # Try to fetch by product ID first (more reliable) - without branch parameter
        product_id = search.get("product_id")
        detail = None
        if product_id:
            detail = self.fetch_product_by_id(product_id, branch=None)
        
        # Fallback to detail URL if product ID lookup failed
        if not detail:
            detail_rel = search.get("detail_url")
            detail = self.fetch_detail(detail_rel) if detail_rel else None
        
        name = search.get("name") or (detail or {}).get("name")
        brand = (detail or {}).get("Brand")
        category = (detail or {}).get("Category")
        pack_size_raw = (detail or {}).get("Pack Size") or search.get("pack_size")
        barcode = (detail or {}).get("Barcode (UPC)") or search.get("barcode")
        min_order_qty = (detail or {}).get("Minimum Order Qty")
        # Extract item number from detail if not provided
        if not item_number:
            item_number = (detail or {}).get("Item Number") or search.get("item_number") or ""
        pack, each_qty, each_uom = parse_pack_size(pack_size_raw)
        return WismettacProduct(
            item_number=item_number,
            name=name,
            brand=brand,
            category=category,
            pack_size_raw=pack_size_raw,
            pack=pack,
            each_qty=each_qty,
            each_uom=each_uom,
            barcode=barcode,
            min_order_qty=min_order_qty,
            detail_url=(detail or {}).get("detail_url") or search.get("detail_url")
        )
    
    def lookup_product_by_name(self, product_name: str, branch: str | int | None = None) -> Optional[WismettacProduct]:
        """Lookup product by product name (fallback when item number not available). Branch is optional."""
        search = self.search_by_product_name(product_name, branch=branch)
        if not search:
            return None
        
        # Try to fetch by product ID first (more reliable) - without branch parameter
        product_id = search.get("product_id")
        detail = None
        if product_id:
            detail = self.fetch_product_by_id(product_id, branch=None)
        
        # Fallback to detail URL if product ID lookup failed
        if not detail:
            detail_rel = search.get("detail_url")
            detail = self.fetch_detail(detail_rel) if detail_rel else None
        
        name = search.get("name") or (detail or {}).get("name")
        brand = (detail or {}).get("Brand")
        category = (detail or {}).get("Category")
        pack_size_raw = (detail or {}).get("Pack Size") or search.get("pack_size")
        barcode = (detail or {}).get("Barcode (UPC)") or search.get("barcode")
        min_order_qty = (detail or {}).get("Minimum Order Qty")
        item_number = (detail or {}).get("Item Number") or search.get("item_number") or ""
        pack, each_qty, each_uom = parse_pack_size(pack_size_raw)
        return WismettacProduct(
            item_number=item_number,
            name=name,
            brand=brand,
            category=category,
            pack_size_raw=pack_size_raw,
            pack=pack,
            each_qty=each_qty,
            each_uom=each_uom,
            barcode=barcode,
            min_order_qty=min_order_qty,
            detail_url=(detail or {}).get("detail_url") or search.get("detail_url")
        )

    def _parse_search(self, html: str) -> Optional[Dict[str, Any]]:
        """Parse search results - returns first matching product"""
        soup = BeautifulSoup(html, "html.parser")
        
        # Try multiple selectors for product cards
        cards = (soup.select(".product_list .box") or 
                 soup.select(".box") or 
                 soup.select(".product-card") or
                 soup.select("[class*='product']") or
                 [])
        
        # Also try to find product links directly
        product_links = soup.select("a[href*='product.php']")
        if not cards and product_links:
            # Create a virtual card from the first product link
            first_link = product_links[0]
            parent = first_link.find_parent()
            if parent:
                cards = [parent]
        
        if not cards:
            # Try to extract product info from any product links
            if product_links:
                first_link = product_links[0]
                detail_url = first_link.get("href")
                if detail_url:
                    # Extract product ID
                    product_id = None
                    id_match = re.search(r'[?&]id=(\d+)', detail_url)
                    if id_match:
                        product_id = id_match.group(1)
                    
                    # Try to get name from link text or nearby elements
                    name = first_link.get_text(strip=True)
                    if not name or len(name) < 5:
                        # Look for name in parent or siblings
                        parent = first_link.find_parent()
                        if parent:
                            name_el = parent.select_one("h1, h2, h3, .title, .name")
                            if name_el:
                                name = name_el.get_text(strip=True)
                    
                    return {
                        "name": name if name and len(name) > 5 else None,
                        "detail_url": detail_url,
                        "product_id": product_id,
                        "item_number": None,
                        "pack_size": None,
                        "barcode": None,
                    }
            return None
        
        # Use first card (best match)
        card = cards[0]
        
        # Title/name - try multiple selectors
        name_el = (card.select_one(".product_name") or 
                  card.select_one(".ttl") or 
                  card.select_one(".title") or
                  card.select_one("h1, h2, h3") or
                  card.select_one("a"))
        name = name_el.get_text(strip=True) if name_el else None
        
        # Detail link - try multiple patterns
        link_el = (card.select_one("a[href*='product.php']") or 
                  card.select_one("a[href*='product']") or
                  card.find("a", href=re.compile(r'product')))
        detail_url = link_el["href"] if link_el and link_el.has_attr("href") else None
        
        # Extract product ID from URL if available
        product_id = None
        if detail_url:
            # Try to extract ID from URL like: product.php?id=132965&branch=SDG
            id_match = re.search(r'[?&]id=(\d+)', detail_url)
            if id_match:
                product_id = id_match.group(1)
        
        # Meta info (item number, pack size, barcode) - attempt common patterns
        meta_text = card.get_text("\n", strip=True)
        item_match = re.search(r"Item\s*#?:\s*(\S+)", meta_text, re.I)
        pack_match = re.search(r"Pack\s*Size\s*:?\s*([\w\s./#]+)", meta_text, re.I)
        barcode_match = re.search(r"(UPC|Barcode)\s*:?\s*([0-9\-]+)", meta_text, re.I)
        return {
            "name": name,
            "detail_url": detail_url,
            "product_id": product_id,
            "item_number": item_match.group(1) if item_match else None,
            "pack_size": pack_match.group(1).strip() if pack_match else None,
            "barcode": barcode_match.group(2) if barcode_match else None,
        }

    def _parse_detail(self, html: str) -> Optional[Dict[str, Any]]:
        """Parse product detail page to extract all available fields"""
        soup = BeautifulSoup(html, "html.parser")
        data: Dict[str, Any] = {}
        
        # Extract product name - look in main content area, not sidebar
        # The product name is typically in an h1 with ID "product-name" or in a div with class "col-lg-6"
        # First try the specific ID selector (most reliable)
        name_el = (soup.select_one("#product-name") or
                  soup.select_one("h1#product-name") or
                  soup.select_one(".col-lg-6 h1") or
                  soup.select_one("#product-item h1") or
                  soup.select_one(".product-item h1"))
        
        if name_el:
            name_text = name_el.get_text(strip=True)
            # Skip common sidebar/header text
            if name_text and name_text not in ["EXPLORE MORE", "BUSINESS CHANNEL", "CATEGORY LIST", "Recent Views"]:
                data["name"] = name_text
        
        # Fallback: try to find main content area
        if not data.get("name"):
            main_content = (soup.select_one(".main-content") or 
                           soup.select_one("#main-content") or 
                           soup.select_one("main") or 
                           soup.select_one(".content") or
                           soup.select_one("#content"))
            
            if main_content:
                # Look for product name in main content area
                name_el = (main_content.select_one(".product_name") or 
                          main_content.select_one("h1") or 
                          main_content.select_one("h2") or
                          main_content.select_one(".title") or
                          main_content.select_one(".product-title"))
                if name_el:
                    name_text = name_el.get_text(strip=True)
                    # Skip common sidebar/header text
                    if name_text and name_text not in ["EXPLORE MORE", "BUSINESS CHANNEL", "CATEGORY LIST"]:
                        data["name"] = name_text
        
        # Final fallback: try all h1/h2 but filter out sidebar text
        if not data.get("name"):
            for h in soup.select("h1, h2"):
                text = h.get_text(strip=True)
                # Skip sidebar/header text
                if text and text not in ["EXPLORE MORE", "BUSINESS CHANNEL", "CATEGORY LIST", "Recent Views"]:
                    # Check if it's in main content (not sidebar)
                    parent = h.find_parent(["nav", "aside", "#sidebar", ".sidebar"])
                    if not parent and len(text) > 5:  # Reasonable product name length
                        data["name"] = text
                        break
        
        # Try to find product info table (multiple possible selectors)
        table = (soup.select_one(".right .table") or 
                 soup.select_one(".tbl") or
                 soup.select_one("table") or
                 soup.select_one(".product-info") or
                 soup.select_one(".product-details"))
        
        if table:
            rows = table.select("tr")
            for tr in rows:
                th = tr.select_one("th")
                td = tr.select_one("td")
                if not th or not td:
                    continue
                key = th.get_text(strip=True).lower()
                val = td.get_text(" ", strip=True)
                
                # Normalize key names to match expected fields
                if "brand" in key:
                    data["Brand"] = val
                elif "category" in key:
                    data["Category"] = val
                elif "item" in key and ("number" in key or "#" in key or "no" in key):
                    data["Item Number"] = val
                elif "pack" in key and "size" in key:
                    data["Pack Size"] = val
                elif "minimum" in key and "order" in key:
                    data["Minimum Order Qty"] = val
                elif "barcode" in key or "upc" in key:
                    data["Barcode (UPC)"] = val
                else:
                    # Store with original key for other fields
                    data[key] = val
        
        # Fallback: try to extract from text patterns if table parsing didn't work
        if not data.get("Brand") and not data.get("Category"):
            page_text = soup.get_text("\n", strip=True)
            
            # Try to extract Brand
            brand_match = re.search(r'(?i)Brand\s*:?\s*([^\n]+)', page_text)
            if brand_match:
                data["Brand"] = brand_match.group(1).strip()
            
            # Try to extract Category
            category_match = re.search(r'(?i)Category\s*:?\s*([^\n]+)', page_text)
            if category_match:
                data["Category"] = category_match.group(1).strip()
            
            # Try to extract Item Number
            item_match = re.search(r'(?i)Item\s*(?:#|Number|No\.?)\s*:?\s*([^\n]+)', page_text)
            if item_match:
                data["Item Number"] = item_match.group(1).strip()
            
            # Try to extract Pack Size
            pack_match = re.search(r'(?i)Pack\s*Size\s*:?\s*([^\n]+)', page_text)
            if pack_match:
                data["Pack Size"] = pack_match.group(1).strip()
            
            # Try to extract Minimum Order Qty
            min_order_match = re.search(r'(?i)Minimum\s*Order\s*(?:Qty|Quantity)\s*:?\s*([^\n]+)', page_text)
            if min_order_match:
                data["Minimum Order Qty"] = min_order_match.group(1).strip()
            
            # Try to extract Barcode/UPC
            barcode_match = re.search(r'(?i)(?:Barcode|UPC)\s*:?\s*([0-9\-]+)', page_text)
            if barcode_match:
                data["Barcode (UPC)"] = barcode_match.group(1).strip()
        
        return data if data else None


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


