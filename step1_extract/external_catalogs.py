import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import hashlib

import requests


class ExternalCatalogs:
    def __init__(self, cache_dir: Path, fdc_api_key: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fdc_api_key = fdc_api_key

    def _cache_path(self, prefix: str, key: str) -> Path:
        h = hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]
        return self.cache_dir / f"{prefix}_{h}.json"

    def _read_cache(self, path: Path) -> Optional[Dict[str, Any]]:
        if path.exists():
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _write_cache(self, path: Path, data: Dict[str, Any]):
        try:
            with open(path, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def search_fdc(self, query: str, page_size: int = 5) -> Optional[Dict[str, Any]]:
        if not self.fdc_api_key:
            return None
        url = "https://api.nal.usda.gov/fdc/v1/foods/search"
        params = {"query": query, "pageSize": page_size, "api_key": self.fdc_api_key}
        cache_key = f"fdc:{query}:{page_size}"
        cache_file = self._cache_path('fdc', cache_key)
        cached = self._read_cache(cache_file)
        if cached:
            return cached
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self._write_cache(cache_file, data)
                return data
        except Exception:
            return None
        return None

    def search_off(self, query: str, page_size: int = 5) -> Optional[Dict[str, Any]]:
        url = "https://world.openfoodfacts.org/cgi/search.pl"
        params = {
            "search_terms": query,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": page_size,
            "fields": "product_name,brands,categories_tags",
        }
        cache_key = f"off:{query}:{page_size}"
        cache_file = self._cache_path('off', cache_key)
        cached = self._read_cache(cache_file)
        if cached:
            return cached
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self._write_cache(cache_file, data)
                return data
        except Exception:
            return None
        return None


