#!/usr/bin/env python3
"""
WebstaurantStore Product Lookup
Searches WebstaurantStore website by item number to get product details for category mapping.
"""

import re
import logging
import time
from typing import Dict, Optional, Any
from urllib.parse import quote

logger = logging.getLogger(__name__)


class WebstaurantStoreLookup:
    """Lookup product information from WebstaurantStore by item number"""
    
    def __init__(self, rule_loader=None, cache_file=None):
        """
        Initialize WebstaurantStore lookup
        
        Args:
            rule_loader: RuleLoader instance (optional, for category hints)
            cache_file: Path to cache file for storing lookup results
        """
        self.rule_loader = rule_loader
        self.cache_file = cache_file
        self.cache: Dict[str, Dict[str, Any]] = {}
        self._load_cache()
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 1.0  # 1 second between requests
    
    def _load_cache(self):
        """Load cached lookup results from file"""
        if not self.cache_file:
            return
        
        try:
            import json
            from pathlib import Path
            
            cache_path = Path(self.cache_file)
            if cache_path.exists():
                with open(cache_path, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                logger.debug(f"Loaded {len(self.cache)} cached WebstaurantStore lookups")
        except Exception as e:
            logger.debug(f"Could not load cache: {e}")
    
    def _save_cache(self):
        """Save lookup results to cache file"""
        if not self.cache_file:
            return
        
        try:
            import json
            from pathlib import Path
            
            cache_path = Path(self.cache_file)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Could not save cache: {e}")
    
    def lookup_item(self, item_number: str) -> Optional[Dict[str, Any]]:
        """
        Lookup product information by item number
        
        Args:
            item_number: WebstaurantStore item number (SKU)
            
        Returns:
            Dictionary with product info: name, category, description, etc.
        """
        if not item_number or item_number == 'UNKNOWN':
            return None
        
        # Check cache first
        if item_number in self.cache:
            cached_result = self.cache[item_number]
            logger.debug(f"Using cached lookup for {item_number}")
            return cached_result
        
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        
        try:
            # Search WebstaurantStore by item number
            product_info = self._search_webstaurantstore(item_number)
            
            if product_info:
                # Cache the result
                self.cache[item_number] = product_info
                self._save_cache()
                logger.info(f"Looked up {item_number}: {product_info.get('name', 'N/A')[:50]}...")
                return product_info
            else:
                # Cache negative result
                self.cache[item_number] = {'found': False}
                self._save_cache()
                logger.debug(f"No product found for item number {item_number}")
                return None
                
        except Exception as e:
            logger.warning(f"Error looking up item {item_number}: {e}")
            return None
    
    def _search_webstaurantstore(self, item_number: str) -> Optional[Dict[str, Any]]:
        """
        Search WebstaurantStore website for product by item number
        
        Args:
            item_number: Item number to search
            
        Returns:
            Product information dictionary
        """
        try:
            import requests
            from bs4 import BeautifulSoup
            
            # WebstaurantStore search URL
            # Try direct product page first: https://www.webstaurantstore.com/{item_number}.html
            search_url = f"https://www.webstaurantstore.com/{item_number}.html"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                product_info = {
                    'item_number': item_number,
                    'found': True,
                    'url': search_url
                }
                
                # Extract product name
                name_selectors = [
                    'h1.product-name',
                    'h1[itemprop="name"]',
                    '.product-name h1',
                    'h1'
                ]
                for selector in name_selectors:
                    name_elem = soup.select_one(selector)
                    if name_elem:
                        product_info['name'] = name_elem.get_text(strip=True)
                        break
                
                # Extract category/breadcrumb
                breadcrumb = soup.select_one('.breadcrumb, .breadcrumbs, nav[aria-label="breadcrumb"]')
                if breadcrumb:
                    breadcrumb_text = breadcrumb.get_text(' > ', strip=True)
                    product_info['category_path'] = breadcrumb_text
                    
                    # Extract category keywords
                    category_keywords = []
                    for link in breadcrumb.select('a'):
                        category_text = link.get_text(strip=True)
                        if category_text and category_text.lower() not in ['home', 'webstaurantstore']:
                            category_keywords.append(category_text)
                    product_info['category_keywords'] = category_keywords
                
                # Extract description
                desc_selectors = [
                    '[itemprop="description"]',
                    '.product-description',
                    '.description',
                    '#product-description'
                ]
                for selector in desc_selectors:
                    desc_elem = soup.select_one(selector)
                    if desc_elem:
                        product_info['description'] = desc_elem.get_text(strip=True)
                        break
                
                # Extract meta keywords/tags
                meta_keywords = soup.find('meta', {'name': 'keywords'})
                if meta_keywords and meta_keywords.get('content'):
                    product_info['meta_keywords'] = meta_keywords['content'].split(',')
                
                return product_info if product_info.get('name') else None
            
            # If direct URL doesn't work, try search
            elif response.status_code == 404:
                logger.debug(f"Direct URL not found for {item_number}, trying search...")
                return self._search_by_query(item_number)
            else:
                logger.debug(f"HTTP {response.status_code} for {item_number}")
                return None
                
        except requests.RequestException as e:
            logger.debug(f"Request error for {item_number}: {e}")
            return None
        except Exception as e:
            logger.debug(f"Parse error for {item_number}: {e}")
            return None
    
    def _search_by_query(self, item_number: str) -> Optional[Dict[str, Any]]:
        """
        Search WebstaurantStore by query string
        
        Args:
            item_number: Item number to search
            
        Returns:
            Product information dictionary
        """
        try:
            import requests
            from bs4 import BeautifulSoup
            
            search_url = f"https://www.webstaurantstore.com/search/{quote(item_number)}.html"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Find first product result
                product_link = soup.select_one('.product-box a, .product-tile a, a[href*="/product/"]')
                if product_link:
                    product_href = product_link.get('href')
                    if product_href:
                        # Extract product name
                        product_name = product_link.get_text(strip=True)
                        
                        return {
                            'item_number': item_number,
                            'found': True,
                            'name': product_name,
                            'url': product_href if product_href.startswith('http') else f"https://www.webstaurantstore.com{product_href}"
                        }
            
            return None
            
        except Exception as e:
            logger.debug(f"Search query error for {item_number}: {e}")
            return None
    
    def get_category_hints(self, product_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract category mapping hints from product information
        
        Args:
            product_info: Product information from lookup
            
        Returns:
            Dictionary with category hints: l2_category, keywords, confidence
        """
        hints = {
            'l2_category': None,
            'keywords': [],
            'confidence': 0.0
        }
        
        if not product_info or not product_info.get('found'):
            return hints
        
        # Extract keywords from category path
        category_path = product_info.get('category_path', '')
        category_keywords = product_info.get('category_keywords', [])
        name = product_info.get('name', '').lower()
        description = product_info.get('description', '').lower()
        meta_keywords = product_info.get('meta_keywords', [])
        
        # Combine all text for analysis
        all_text = ' '.join([name, description, category_path.lower()] + [k.lower() for k in category_keywords] + [k.lower() for k in meta_keywords])
        
        # Map category keywords to L2 categories
        category_mappings = {
            # Cleaning & Chemicals
            'cleaning': 'C50',
            'sanitizer': 'C50',
            'disinfectant': 'C50',
            'chemical': 'C50',
            'test strip': 'C50',
            'chlorine': 'C50',
            
            # Gloves & Food Service
            'glove': 'C31',
            'spill kit': 'C31',
            'body fluid': 'C31',
            'food service': 'C31',
            
            # Smallwares & Equipment
            'equipment': 'C40',
            'thermometer': 'C40',
            'container': 'C40',
            'tool': 'C40',
            'smallware': 'C40',
            
            # Packaging
            'cup': 'C20',
            'lid': 'C20',
            'bag': 'C21',
            'tray': 'C21',
            'straw': 'C22',
            'utensil': 'C22',
            
            # Paper Products
            'napkin': 'C30',
            'towel': 'C30',
            'paper': 'C30',
            
            # Filters & Disposables
            'filter': 'C32',
            'wrap': 'C32',
            'foil': 'C32',
        }
        
        # Check for category matches
        matched_category = None
        matched_keywords = []
        
        for keyword, l2_category in category_mappings.items():
            if keyword in all_text:
                if not matched_category:
                    matched_category = l2_category
                matched_keywords.append(keyword)
        
        if matched_category:
            hints['l2_category'] = matched_category
            hints['keywords'] = matched_keywords
            hints['confidence'] = min(0.9, 0.7 + len(matched_keywords) * 0.1)
        
        return hints
    
    def enrich_item_with_lookup(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich an item with product lookup information
        
        Args:
            item: Item dictionary with item_number
            
        Returns:
            Updated item dictionary with category hints
        """
        item_number = item.get('item_number')
        if not item_number:
            return item
        
        # Lookup product
        product_info = self.lookup_item(item_number)
        if not product_info:
            return item
        
        # Get category hints
        hints = self.get_category_hints(product_info)
        
        # Add hints to item (can be used by category classifier)
        if hints.get('l2_category'):
            item['_webstaurantstore_l2_hint'] = hints['l2_category']
            item['_webstaurantstore_keywords'] = hints['keywords']
            item['_webstaurantstore_confidence'] = hints['confidence']
            item['_webstaurantstore_name'] = product_info.get('name')
            item['_webstaurantstore_category'] = product_info.get('category_path')
        
        logger.debug(
            f"Enriched {item_number} with category hint: {hints.get('l2_category')} "
            f"(confidence: {hints.get('confidence', 0):.2f})"
        )
        
        return item

