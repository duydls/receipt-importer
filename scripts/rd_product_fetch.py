#!/usr/bin/env python3
"""
Restaurant Depot Product Fetcher
Fetches product information from Restaurant Depot website using UPC.

Uses Chrome cookies for authentication.
"""

import logging
import re
import sqlite3
import json
from pathlib import Path
from typing import Dict, Optional, Any
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def get_chrome_cookies(domain: str = 'member.restaurantdepot.com') -> Dict[str, str]:
    """
    Extract cookies from Chrome's cookie database.
    
    Args:
        domain: Domain to extract cookies for
        
    Returns:
        Dictionary of cookie name -> value
    """
    cookies = {}
    
    # Chrome cookie database locations (macOS)
    chrome_paths = [
        Path.home() / 'Library/Application Support/Google/Chrome/Default/Cookies',
        Path.home() / 'Library/Application Support/Google/Chrome/Profile 1/Cookies',
    ]
    
    for cookie_db in chrome_paths:
        if not cookie_db.exists():
            continue
        
        try:
            # Copy database to temp location (Chrome locks the original)
            import tempfile
            import shutil
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp_db:
                shutil.copy2(cookie_db, tmp_db.name)
                tmp_path = Path(tmp_db.name)
            
            try:
                conn = sqlite3.connect(str(tmp_path))
                cursor = conn.cursor()
                
                # Query cookies for the domain
                cursor.execute("""
                    SELECT name, value, host_key, path, expires_utc, is_secure, is_httponly
                    FROM cookies
                    WHERE host_key LIKE ? OR host_key LIKE ?
                """, (f'%{domain}%', f'%.{domain}%'))
                
                for row in cursor.fetchall():
                    name, value, host_key, path, expires_utc, is_secure, is_httponly = row
                    cookies[name] = value
                    logger.debug(f"Extracted cookie: {name} from {host_key}")
                
                conn.close()
            finally:
                # Clean up temp file
                tmp_path.unlink()
            
            if cookies:
                logger.info(f"Extracted {len(cookies)} cookies from Chrome for {domain}")
                return cookies
                
        except Exception as e:
            logger.debug(f"Could not extract cookies from {cookie_db}: {e}")
            continue
    
    logger.warning(f"No cookies found for {domain}")
    return cookies


def fetch_rd_product_by_upc(upc: str, cookies: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch product information from Restaurant Depot website by UPC.
    
    Args:
        upc: UPC code (12-14 digits)
        cookies: Optional cookies dictionary (if None, will try to extract from Chrome)
        
    Returns:
        Dictionary with product information or None if not found
    """
    if not upc or not upc.isdigit():
        logger.warning(f"Invalid UPC: {upc}")
        return None
    
    # Get cookies if not provided
    if cookies is None:
        cookies = get_chrome_cookies('member.restaurantdepot.com')
        if not cookies:
            logger.warning("No cookies available for Restaurant Depot")
            return None
    
    # Try multiple URL patterns for RD product pages
    # RD website uses search functionality - try search by UPC first
    base_urls = [
        f"https://member.restaurantdepot.com/store/jetro-restaurant-depot/storefront/search?q={upc}",
        f"https://member.restaurantdepot.com/storefront/search?q={upc}",
        f"https://member.restaurantdepot.com/store/jetro-restaurant-depot/storefront/products/{upc}",
        f"https://member.restaurantdepot.com/store/jetro-restaurant-depot/storefront/product/{upc}",
        f"https://member.restaurantdepot.com/storefront/products/{upc}",
        f"https://member.restaurantdepot.com/storefront/product/{upc}",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    session = requests.Session()
    session.cookies.update(cookies)
    
    for url in base_urls:
        try:
            logger.debug(f"Trying URL: {url}")
            response = session.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                # Parse HTML response
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Try to extract product information
                # This will depend on RD's actual HTML structure
                product_info = _parse_rd_product_page(soup, upc)
                if product_info:
                    logger.info(f"Found product for UPC {upc}: {product_info.get('name', 'Unknown')}")
                    return product_info
            elif response.status_code == 403:
                logger.warning(f"403 Forbidden for {url} - authentication may be required")
            else:
                logger.debug(f"Status {response.status_code} for {url}")
                
        except Exception as e:
            logger.debug(f"Error fetching {url}: {e}")
            continue
    
    logger.warning(f"Could not find product for UPC {upc}")
    return None


def _parse_rd_product_page(soup: BeautifulSoup, upc: str) -> Optional[Dict[str, Any]]:
    """
    Parse product information from RD product page HTML.
    
    Args:
        soup: BeautifulSoup object of the product page
        upc: UPC code (for validation)
        
    Returns:
        Dictionary with product information or None
    """
    product_info = {
        'upc': upc,
        'name': None,
        'description': None,
        'size': None,
        'unit_price': None,
        'item_number': None,
    }
    
    # Try to find product name (common selectors)
    name_selectors = [
        'h1.product-title',
        'h1.product-name',
        '.product-title',
        '.product-name',
        'h1',
        '[data-testid="product-title"]',
    ]
    
    for selector in name_selectors:
        name_elem = soup.select_one(selector)
        if name_elem:
            product_info['name'] = name_elem.get_text(strip=True)
            break
    
    # Try to find product description
    desc_selectors = [
        '.product-description',
        '.product-details',
        '[data-testid="product-description"]',
    ]
    
    for selector in desc_selectors:
        desc_elem = soup.select_one(selector)
        if desc_elem:
            product_info['description'] = desc_elem.get_text(strip=True)
            break
    
    # Try to find size/UoM information
    # Look for patterns like "10 lb", "6/5 lb", "35 lbs", etc.
    text = soup.get_text()
    size_patterns = [
        r'(\d+(?:/\d+)?)\s*(lb|lbs|oz|ct|each|ea|pack|pk)',
        r'Size[:\s]+(\d+(?:/\d+)?)\s*(lb|lbs|oz|ct|each|ea)',
        r'Weight[:\s]+(\d+(?:/\d+)?)\s*(lb|lbs|oz)',
    ]
    
    for pattern in size_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            size = match.group(1)
            unit = match.group(2).lower()
            product_info['size'] = f"{size} {unit}"
            break
    
    # Try to find price
    price_selectors = [
        '.price',
        '.product-price',
        '[data-testid="price"]',
        '.current-price',
    ]
    
    for selector in price_selectors:
        price_elem = soup.select_one(selector)
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            # Extract numeric price
            price_match = re.search(r'\$?([\d,]+\.?\d*)', price_text)
            if price_match:
                try:
                    product_info['unit_price'] = float(price_match.group(1).replace(',', ''))
                except ValueError:
                    pass
            break
    
    # Try to find item number
    item_num_patterns = [
        r'Item[#:\s]+(\d+)',
        r'Item\s+Number[:\s]+(\d+)',
        r'SKU[:\s]+(\d+)',
    ]
    
    for pattern in item_num_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            product_info['item_number'] = match.group(1)
            break
    
    # Return product info if we found at least a name
    if product_info['name']:
        return product_info
    
    return None


def _parse_rd_search_results(soup: BeautifulSoup, upc: str) -> Optional[Dict[str, Any]]:
    """
    Parse product information from RD search results page.
    
    Args:
        soup: BeautifulSoup object of the search results page
        upc: UPC code (for validation)
        
    Returns:
        Dictionary with product information or None
    """
    product_info = {
        'upc': upc,
        'name': None,
        'description': None,
        'size': None,
        'unit_price': None,
        'item_number': None,
    }
    
    # Try to find product cards/items in search results
    # Common selectors for product listings
    product_selectors = [
        '.product-card',
        '.product-item',
        '.product',
        '[data-testid="product-card"]',
        '.search-result-item',
    ]
    
    for selector in product_selectors:
        products = soup.select(selector)
        if products:
            # Try to find product matching the UPC
            for product_elem in products:
                product_text = product_elem.get_text()
                
                # Check if UPC is mentioned in this product
                if upc in product_text:
                    # Extract product name
                    name_elem = product_elem.select_one('h2, h3, .product-name, .product-title, [data-testid="product-name"]')
                    if name_elem:
                        product_info['name'] = name_elem.get_text(strip=True)
                    
                    # Extract price
                    price_elem = product_elem.select_one('.price, .product-price, [data-testid="price"]')
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        price_match = re.search(r'\$?([\d,]+\.?\d*)', price_text)
                        if price_match:
                            try:
                                product_info['unit_price'] = float(price_match.group(1).replace(',', ''))
                            except ValueError:
                                pass
                    
                    # Extract size/UoM from product text
                    size_match = re.search(r'(\d+(?:/\d+)?)\s*(lb|lbs|oz|ct|each|ea|pack|pk)', product_text, re.IGNORECASE)
                    if size_match:
                        size = size_match.group(1)
                        unit = size_match.group(2).lower()
                        product_info['size'] = f"{size} {unit}"
                    
                    # If we found a name, return this product
                    if product_info['name']:
                        return product_info
    
    # If no product cards found, try to extract from page text directly
    page_text = soup.get_text()
    if upc in page_text:
        # Try to find product name near UPC
        upc_index = page_text.find(upc)
        if upc_index > 0:
            # Look for product name before or after UPC
            context = page_text[max(0, upc_index-200):min(len(page_text), upc_index+200)]
            # Try to extract a product name (look for capitalized words)
            name_match = re.search(r'([A-Z][A-Za-z\s&-]+(?:[A-Z][A-Za-z\s&-]+)*)', context)
            if name_match:
                product_info['name'] = name_match.group(1).strip()
                return product_info
    
    return None


def update_knowledge_base_with_rd_products(upc_list: list, kb_file: Path) -> None:
    """
    Update knowledge base with RD product information fetched from website.
    
    Args:
        upc_list: List of UPC codes to fetch
        kb_file: Path to knowledge base JSON file
    """
    # Load existing knowledge base
    kb = {}
    if kb_file.exists():
        try:
            with open(kb_file, 'r', encoding='utf-8') as f:
                kb = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load knowledge base: {e}")
    
    # Get cookies once
    cookies = get_chrome_cookies('member.restaurantdepot.com')
    if not cookies:
        logger.error("No cookies available - cannot fetch RD products")
        return
    
    # Fetch products
    updated_count = 0
    for upc in upc_list:
        if not upc or not upc.isdigit():
            continue
        
        # Check if already in KB
        if upc in kb:
            logger.debug(f"UPC {upc} already in knowledge base, skipping")
            continue
        
        # Fetch product info
        product_info = fetch_rd_product_by_upc(upc, cookies)
        if product_info:
            # Add to knowledge base
            kb[upc] = {
                'name': product_info.get('name'),
                'size': product_info.get('size'),
                'unit_price': product_info.get('unit_price'),
                'item_number': product_info.get('item_number'),
                'source': 'rd_website',
            }
            updated_count += 1
            logger.info(f"Added UPC {upc} to knowledge base: {product_info.get('name')}")
    
    # Save updated knowledge base
    if updated_count > 0:
        try:
            with open(kb_file, 'w', encoding='utf-8') as f:
                json.dump(kb, f, indent=2, ensure_ascii=False)
            logger.info(f"Updated knowledge base with {updated_count} new products")
        except Exception as e:
            logger.error(f"Could not save knowledge base: {e}")


if __name__ == '__main__':
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python rd_product_fetch.py <UPC> [UPC2] [UPC3] ...")
        print("Or: python rd_product_fetch.py --update-kb <kb_file> <UPC1> [UPC2] ...")
        sys.exit(1)
    
    if sys.argv[1] == '--update-kb':
        if len(sys.argv) < 4:
            print("Usage: python rd_product_fetch.py --update-kb <kb_file> <UPC1> [UPC2] ...")
            sys.exit(1)
        kb_file = Path(sys.argv[2])
        upc_list = sys.argv[3:]
        update_knowledge_base_with_rd_products(upc_list, kb_file)
    else:
        # Fetch single UPC
        upc = sys.argv[1]
        product_info = fetch_rd_product_by_upc(upc)
        if product_info:
            print(json.dumps(product_info, indent=2))
        else:
            print(f"Could not find product for UPC {upc}")

