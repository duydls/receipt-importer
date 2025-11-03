#!/usr/bin/env python3
"""
Vendor Profiles - Support for Costco & Restaurant Depot item number patterns
Uses a knowledge base (JSON file) for product lookups - no web scraping
Knowledge base can be manually updated as new items are encountered
"""

import csv
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from functools import lru_cache

logger = logging.getLogger(__name__)

# Module-level knowledge base singleton cache
_KB_SINGLETON = None

# ---------- Lightweight module-level KB helpers (for cached lookups) ----------
def _ensure_kb_loaded() -> Dict:
    global _KB_SINGLETON
    if _KB_SINGLETON is not None:
        return _KB_SINGLETON
    # Try input location first, then data fallback
    kb_candidates = [
        Path('data/step1_input/knowledge_base.json'),
        Path('data/knowledge_base.json'),
    ]
    for p in kb_candidates:
        if p.exists():
            try:
                with p.open('r', encoding='utf-8') as f:
                    kb_raw = json.load(f)
                # Normalize into dict[str, dict]
                kb = {}
                for item_no, item_data in kb_raw.items():
                    if isinstance(item_data, list) and len(item_data) >= 4:
                        kb[str(item_no).strip()] = {
                            'name': item_data[0],
                            'store': item_data[1],
                            'spec': item_data[2],
                            'price': item_data[3],
                        }
                _KB_SINGLETON = kb
                logger.debug("KB loaded (module-level) with %d items from %s", len(kb), p)
                return _KB_SINGLETON
            except Exception as e:
                logger.warning("Failed to load KB from %s: %s", p, e)
    _KB_SINGLETON = {}
    return _KB_SINGLETON

def _kb_lookup_price_by_signature(vendor_key: str, item_signature: Dict) -> Optional[float]:
    kb = _ensure_kb_loaded()
    if not kb:
        return None
    # Prefer item_number, then upc
    item_number = (item_signature.get('item_number') or '').strip() if isinstance(item_signature, dict) else ''
    upc = (item_signature.get('upc') or '').strip() if isinstance(item_signature, dict) else ''
    for key in (item_number, upc):
        if key and key in kb:
            price = kb[key].get('price')
            try:
                return float(price)
            except Exception:
                # Try to parse from "$12.34"
                try:
                    import re as _re
                    m = _re.search(r"\$?(\d+\.?\d*)", str(price))
                    return float(m.group(1)) if m else None
                except Exception:
                    return None
    return None

def _freeze_signature(item_signature: Dict) -> tuple:
    # Convert dict into a hashable tuple of sorted items (key, value)
    try:
        return tuple(sorted((k, str(v)) for k, v in (item_signature or {}).items()))
    except Exception:
        return tuple()

@lru_cache(maxsize=4096)
def lookup_cached(vendor_key: str, frozen_signature: tuple) -> Optional[Dict]:
    """LRU-cached KB lookup. Callers should pass a frozen signature (use _freeze_signature)."""
    # Unfreeze back into dict
    sig = {k: v for (k, v) in frozen_signature}
    price = _kb_lookup_price_by_signature(vendor_key, sig)
    if price is None:
        return None
    return {'unit_price': price}

def lookup_cached_dict(vendor_key: str, item_signature: Dict) -> Optional[Dict]:
    """Convenience wrapper that accepts a dict signature."""
    return lookup_cached(vendor_key, _freeze_signature(item_signature))


class VendorProfileHandler:
    """Handle vendor-specific profiles (Costco, Restaurant Depot)"""
    
    def __init__(self, vendor_profiles: Dict, rules_dir: Path, knowledge_base_file: Optional[str] = None):
        """Initialize with vendor profiles"""
        self.vendor_profiles = vendor_profiles
        self.rules_dir = rules_dir
        self.cache_dir = rules_dir  # Cache files are in rules directory (legacy)
        
        # Load knowledge base (default: look in input folder first, then data folder)
        if knowledge_base_file:
            kb_path = Path(knowledge_base_file)
        else:
            # Try input folder first (data/step1_input/knowledge_base.json)
            input_kb = Path('data/step1_input/knowledge_base.json')
            if input_kb.exists():
                kb_path = input_kb
            else:
                # Fallback to data folder (for backward compatibility)
                kb_path = Path('data/knowledge_base.json')
        
        self.knowledge_base = self._load_knowledge_base(kb_path)
        
        self.item_caches = {}  # vendor -> {item_number -> item_data}
        self._load_caches()
    
    def _load_knowledge_base(self, kb_path: Path) -> Dict:
        """Load knowledge base from JSON file with module-level singleton cache."""
        global _KB_SINGLETON
        if _KB_SINGLETON is not None:
            return _KB_SINGLETON
        if kb_path.exists():
            try:
                with open(kb_path, 'r', encoding='utf-8') as f:
                    kb_data = json.load(f)
                    knowledge_base = {}
                    for item_no, item_data in kb_data.items():
                        if isinstance(item_data, list) and len(item_data) >= 4:
                            knowledge_base[str(item_no).strip()] = {
                                'name': item_data[0],
                                'store': item_data[1],
                                'spec': item_data[2],
                                'price': float(item_data[3]) if isinstance(item_data[3], (int, float)) else item_data[3]
                            }
                    _KB_SINGLETON = knowledge_base
                    logger.info("Loaded knowledge base with %d items from %s", len(_KB_SINGLETON), kb_path)
                    return _KB_SINGLETON
            except Exception as e:
                logger.warning(f"Failed to load knowledge base from {kb_path}: {e}")
        else:
            logger.info(f"Knowledge base file not found: {kb_path}, using empty knowledge base")
        _KB_SINGLETON = {}
        return _KB_SINGLETON
    
    def should_process(self, vendor: str, filename: str) -> bool:
        """Check if vendor should be processed with profiles"""
        vendor_key = self._normalize_vendor_key(vendor)
        
        # Always enable for Costco and Restaurant Depot (vendor name-based, not just filename)
        if vendor_key in ['costco', 'restaurant_depot']:
            if vendor_key in self.vendor_profiles:
                return True
        
        # Legacy: Check filename patterns if vendor profile exists
        if vendor_key not in self.vendor_profiles:
            return False
        
        profile = self.vendor_profiles[vendor_key]
        detect_by_filename = profile.get('detect_by_filename', [])
        
        # Check if filename matches patterns (if configured)
        if detect_by_filename:
            filename_lower = filename.lower()
            for pattern in detect_by_filename:
                if pattern.lower() in filename_lower:
                    return True
        
        return False
    
    def process_items(self, vendor: str, items: List[Dict]) -> List[Dict]:
        """
        Process items with vendor profile (extract item numbers/UPCs, fetch specs)
        
        Args:
            vendor: Vendor name
            items: List of receipt items
            
        Returns:
            Updated items with vendor profile data
        """
        vendor_key = self._normalize_vendor_key(vendor)
        if vendor_key not in self.vendor_profiles:
            return items
        
        profile = self.vendor_profiles[vendor_key]
        item_number_pattern = profile.get('item_number_pattern', '')
        cache_file = profile.get('cache_file', '')
        output_mapping = profile.get('output_mapping', {})
        
        # Store vendor_key in profile for scraper selection
        profile['_vendor_key'] = vendor_key
        
        if not item_number_pattern:
            return items
        
        # Compile regex pattern
        try:
            pattern = re.compile(item_number_pattern)
        except Exception as e:
            logger.error(f"Invalid item number pattern for {vendor}: {e}")
            return items
        
        # Process each item
        updated_items = []
        for item in items:
            updated_item = self._process_item(item, vendor_key, profile, pattern, cache_file, output_mapping)
            updated_items.append(updated_item)
        
        return updated_items
    
    def _process_item(self, item: Dict, vendor_key: str, profile: Dict, 
                     pattern: re.Pattern, cache_file: str, output_mapping: Dict) -> Dict:
        """Process a single item with vendor profile"""
        product_name = item.get('product_name', '')
        line_text = item.get('line_text', product_name)
        
        # For RD items, try to extract size from line_text first (before database lookup)
        # RD receipts often have size in line_text like "CHX NUGGET BTRD TY 10LB" or "FF ZESTY TWISTER 20LB"
        if vendor_key == 'restaurant_depot' and line_text and not item.get('size'):
            size_from_line = self._extract_size_from_line_text(line_text)
            if size_from_line:
                item['size'] = size_from_line['size']
                if size_from_line.get('uom') and size_from_line['uom'] != 'EACH':
                    item['purchase_uom'] = size_from_line['uom'].lower()
                    logger.debug(f"Extracted size from line_text for RD item: {size_from_line['size']} ({size_from_line['uom']})")
        
        # First, check if item_number is already extracted (e.g., by Costco/RD parser)
        item_number = item.get('item_number')
        upc = item.get('upc')  # UPC for RD receipts
        
        # If not found, try to find item number in line text using pattern
        if not item_number:
            match = pattern.search(line_text)
            if not match:
                # Try UPC pattern if available (for RD receipts)
                if upc:
                    item_number = upc  # Use UPC as fallback identifier
                else:
                    upc_pattern = profile.get('upc_pattern', '')
                    if upc_pattern:
                        upc_match = re.search(upc_pattern, line_text)
                        if upc_match:
                            upc = upc_match.group(0).strip()
                            item_number = upc  # Use UPC as identifier
                
                if not item_number:
                    return item
            else:
                item_number = match.group(0).strip()
        
        # Get item data from cache or fetch (try item_number first, then UPC)
        item_data = self._get_item_data(vendor_key, item_number, profile, cache_file, upc=upc)
        
        if not item_data:
            # Log missing spec
            fallback_behavior = profile.get('fallback_behavior', [])
            for behavior in fallback_behavior:
                if 'log missing' in behavior.lower():
                    # Format with item_number and upc (if available)
                    try:
                        if '{upc}' in behavior and upc:
                            logger.warning(behavior.format(item_number=item_number, upc=upc))
                        else:
                            logger.warning(behavior.format(item_number=item_number))
                    except KeyError:
                        # Fallback if format string has issues - replace placeholders directly
                        formatted = behavior.replace('{item_number}', str(item_number))
                        if '{upc}' in formatted:
                            formatted = formatted.replace('{upc}', str(upc or 'N/A'))
                        logger.warning(formatted)
            return item
        
        # Map item data to output fields
        updated_item = item.copy()
        
        product_name_field = output_mapping.get('product_name_field', 'desc')
        unit_field = output_mapping.get('unit_field', 'purchase_uom')
        size_field = output_mapping.get('size_field', 'size')
        source_field = output_mapping.get('source_field', f'{vendor_key}_spec')
        
        if product_name_field in item_data and item_data[product_name_field]:
            updated_item['product_name'] = item_data[product_name_field]
        
        # Always set UoM if it exists in item_data (from Costco database)
        # This ensures verified items always get UoM from the database
        if unit_field in item_data:
            uom_value = str(item_data[unit_field]).strip() if item_data[unit_field] else ''
            if uom_value:
                updated_item['purchase_uom'] = uom_value.lower()
                logger.debug(f"Set UoM from verification for item {item.get('item_number', 'N/A')}: {uom_value.lower()}")
            else:
                logger.warning(f"Item data for {item.get('item_number', 'N/A')} has empty UoM in database")
        
        if size_field in item_data and item_data[size_field]:
            updated_item['size'] = item_data[size_field]
            
            # For Costco items, try to extract quantity from size field (e.g., "2 lb", "8 lb")
            # This helps us get accurate unit_price and quantity when Excel doesn't provide it
            size_text = str(item_data[size_field]).strip()
            if size_text:
                # Try to extract quantity from size patterns like "2 lb", "8 lb", "1 gal", etc.
                # Also handle "Case of 12" format
                qty_patterns = [
                    (r'(\d+(?:\.\d+)?)\s*(?:lb|lbs|pound|pounds|oz|ounce|ounces|gal|gallon|gallons|qt|quart|quarts|pt|pint|pints)', re.IGNORECASE),  # e.g., "2 lb", "8 lb"
                    (r'(\d+(?:\.\d+)?)\s*×\s*\d+', re.IGNORECASE),  # e.g., "1 gal × 3 ct"
                    (r'case\s+of\s+(\d+)', re.IGNORECASE),  # e.g., "Case of 12"
                ]
                
                extracted_qty = None
                for pattern, flags in qty_patterns:
                    match = re.search(pattern, size_text, flags)
                    if match:
                        try:
                            extracted_qty = float(match.group(1))
                            # Only update quantity if we haven't extracted it from Excel 
                            # (quantity == 1.0 and unit_price == total_price means it wasn't in Excel)
                            current_qty = updated_item.get('quantity', 1.0)
                            current_unit_price = updated_item.get('unit_price', 0)
                            total_price = updated_item.get('total_price', 0)
                            
                            # If quantity is 1.0 and unit_price equals total_price, it likely wasn't extracted from Excel
                            # In this case, use the quantity from size field
                            if current_qty == 1.0 and total_price > 0 and abs(current_unit_price - total_price) < 0.01:
                                updated_item['quantity'] = extracted_qty
                                # Recalculate unit_price
                                if extracted_qty > 0:
                                    updated_item['unit_price'] = total_price / extracted_qty
                                logger.debug(f"Extracted quantity {extracted_qty} from size field '{size_text}' for item {item.get('item_number', 'N/A')} (was: qty={current_qty}, unit_price=${current_unit_price:.2f}, now: qty={extracted_qty}, unit_price=${total_price/extracted_qty:.2f})")
                            break
                        except (ValueError, IndexError, ZeroDivisionError):
                            continue
        
        # For Costco: Use knowledge base unit_price to estimate quantity if we only have total_price
        # Costco receipts typically only show total_price, not quantity or unit_price
        if vendor_key == 'costco' and 'unit_price' in item_data:
            db_unit_price = item_data.get('unit_price')
            if db_unit_price is not None:
                current_total_price = updated_item.get('total_price', 0)
                current_quantity = updated_item.get('quantity', 1.0)
                current_unit_price = updated_item.get('unit_price')
                
                # If we have total_price and knowledge base unit_price, estimate quantity
                if current_total_price > 0 and db_unit_price > 0:
                    # Calculate estimated quantity
                    estimated_qty = current_total_price / db_unit_price
                    
                    # Round to reasonable precision (usually whole numbers for Costco, sometimes 0.5)
                    # Round to nearest 0.5 if it's close, otherwise nearest integer
                    if abs(estimated_qty - round(estimated_qty)) < 0.1:
                        estimated_qty = round(estimated_qty)
                    elif abs(estimated_qty - round(estimated_qty * 2) / 2) < 0.1:
                        estimated_qty = round(estimated_qty * 2) / 2
                    else:
                        estimated_qty = round(estimated_qty * 2) / 2  # Round to 0.5 precision
                    
                    # Only update if quantity seems reasonable (between 0.5 and 100, and makes sense)
                    if 0.5 <= estimated_qty <= 100:
                        # If quantity was not set or seems incorrect (e.g., equals 1.0 when total_price doesn't match)
                        if current_quantity == 1.0 or abs(current_total_price - (current_quantity * db_unit_price)) > 0.5:
                            updated_item['quantity'] = estimated_qty
                            updated_item['unit_price'] = float(db_unit_price)
                            updated_item['price_source'] = 'knowledge_base'
                            logger.info(f"Estimated quantity for Costco item {item.get('item_number', 'N/A')}: {estimated_qty} units (total: ${current_total_price:.2f}, unit: ${db_unit_price:.2f})")
                        elif current_unit_price is None or abs(current_unit_price - db_unit_price) > 0.1:
                            # Update unit_price if missing or significantly different
                            updated_item['unit_price'] = float(db_unit_price)
                            updated_item['price_source'] = 'knowledge_base'
                            logger.debug(f"Updated unit_price from knowledge base for item {item.get('item_number', 'N/A')}: ${db_unit_price:.2f}")
        
        updated_item[source_field] = True
        
        return updated_item
    
    def _get_item_data(self, vendor_key: str, item_number: str, 
                      profile: Dict, cache_file: str, upc: Optional[str] = None) -> Optional[Dict]:
        """Get item data from cache, knowledge base, or fetch from web"""
        # Check in-memory cache first
        if vendor_key in self.item_caches:
            if item_number in self.item_caches[vendor_key]:
                return self.item_caches[vendor_key][item_number]
        
        # Check knowledge base (for Costco and RD)
        if vendor_key in ['costco', 'restaurant_depot']:
            kb_result = self._lookup_by_item_number_or_upc(vendor_key, item_number, upc, force_update=False)
            if kb_result:
                # Convert knowledge base result to item_data format
                item_data = {
                    'desc': kb_result.get('name', ''),
                    'product_name': kb_result.get('name', ''),
                    'size': kb_result.get('unit_size', ''),
                    'purchase_uom': '',  # Will be derived from size if needed
                    'url': kb_result.get('url', ''),
                }
                
                # Extract unit_price from price string (e.g., "$15.99" -> 15.99)
                # For Costco: use knowledge base unit_price
                # For RD: store as vendor_price for reference only (unit_price will be calculated from receipt)
                if 'unit_price' in kb_result and kb_result['unit_price']:
                    if vendor_key == 'costco':
                        item_data['unit_price'] = float(kb_result['unit_price'])
                    elif vendor_key == 'restaurant_depot':
                        # For RD, store as vendor_price only (unit_price will be calculated from total_price / quantity)
                        item_data['vendor_price'] = float(kb_result['unit_price'])
                else:
                    price_str = kb_result.get('price', '')
                    if price_str:
                        import re
                        price_match = re.search(r'\$?(\d+\.?\d*)', str(price_str))
                        if price_match:
                            try:
                                price_val = float(price_match.group(1))
                                if vendor_key == 'costco':
                                    item_data['unit_price'] = price_val
                                elif vendor_key == 'restaurant_depot':
                                    # For RD, store as vendor_price only
                                    item_data['vendor_price'] = price_val
                            except (ValueError, TypeError):
                                pass
                
                # Cache the result
                if vendor_key not in self.item_caches:
                    self.item_caches[vendor_key] = {}
                self.item_caches[vendor_key][item_number] = item_data
                return item_data
        
        # Check file cache
        if cache_file:
            cache_path = self.cache_dir / cache_file
            if cache_path.exists():
                item_data = self._load_from_cache(cache_path, item_number)
                if item_data:
                    # Update in-memory cache
                    if vendor_key not in self.item_caches:
                        self.item_caches[vendor_key] = {}
                    self.item_caches[vendor_key][item_number] = item_data
                    return item_data
        
        # Web scraping is disabled - use knowledge base only
        # All product lookups are done via knowledge base in _lookup_by_item_number_or_upc
        return None
    
    def _load_from_cache(self, cache_path: Path, item_number: str) -> Optional[Dict]:
        """Load item data from CSV cache file"""
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('item_number', '').strip() == item_number:
                        # Return data with correct field names (support both 'product_name' and 'desc')
                        product_name = row.get('product_name', '') or row.get('desc', '')
                        item_data = {
                            'desc': product_name,  # Main field name used by output_mapping
                            'product_name': product_name,  # Also provide as product_name
                            'size': row.get('size', ''),
                            'purchase_uom': row.get('uom', '') or row.get('purchase_uom', ''),
                            'url': row.get('url', ''),
                        }
                        # Add price if available in cache
                        if 'unit_price' in row and row.get('unit_price'):
                            try:
                                item_data['unit_price'] = float(row.get('unit_price'))
                            except (ValueError, TypeError):
                                pass
                        return item_data
        except Exception as e:
            logger.error(f"Error loading from cache {cache_path}: {e}")
        
        return None
    
    
    def _save_to_cache(self, vendor_key: str, item_number: str, item_data: Dict, cache_file: str):
        """Save item data to cache file"""
        if not cache_file:
            return
        
        cache_path = self.cache_dir / cache_file
        
        # Read existing cache
        existing_rows = []
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    existing_rows = list(reader)
            except:
                existing_rows = []
        
        # Check if item already exists
        item_exists = any(row.get('item_number', '') == item_number for row in existing_rows)
        
        if not item_exists:
            # Append new item
            row_data = {
                'item_number': item_number,
                'product_name': item_data.get('product_name', ''),
                'size': item_data.get('size', ''),
                'uom': item_data.get('purchase_uom', ''),
                'url': item_data.get('url', ''),
            }
            # Add price if available
            if 'unit_price' in item_data:
                row_data['unit_price'] = str(item_data.get('unit_price', ''))
            existing_rows.append(row_data)
            
            # Write back to cache
            try:
                with open(cache_path, 'w', encoding='utf-8', newline='') as f:
                    if existing_rows:
                        writer = csv.DictWriter(f, fieldnames=existing_rows[0].keys())
                        writer.writeheader()
                        writer.writerows(existing_rows)
            except Exception as e:
                logger.error(f"Error saving to cache {cache_path}: {e}")
    
    def _load_caches(self):
        """Load all vendor caches into memory"""
        for vendor_key, profile in self.vendor_profiles.items():
            cache_file = profile.get('cache_file', '')
            if cache_file:
                cache_path = self.cache_dir / cache_file
                if cache_path.exists():
                    self._load_cache_file(vendor_key, cache_path)
    
    def _load_cache_file(self, vendor_key: str, cache_path: Path):
        """Load a cache file into memory"""
        if vendor_key not in self.item_caches:
            self.item_caches[vendor_key] = {}
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    item_number = row.get('item_number', '').strip()
                    if item_number:
                        item_data = {
                            'product_name': row.get('product_name', ''),
                            'size': row.get('size', ''),
                            'purchase_uom': row.get('uom', ''),
                            'url': row.get('url', ''),
                        }
                        # Add price if available in cache
                        if 'unit_price' in row and row.get('unit_price'):
                            try:
                                item_data['unit_price'] = float(row.get('unit_price'))
                            except (ValueError, TypeError):
                                pass
                        self.item_caches[vendor_key][item_number] = item_data
            logger.info(f"Loaded {len(self.item_caches[vendor_key])} items from {cache_path.name} cache")
        except Exception as e:
            logger.error(f"Error loading cache {cache_path}: {e}")
    
    def _extract_size_from_line_text(self, line_text: str) -> Optional[Dict]:
        """Extract size and UoM from line text for RD receipts
        
        Examples:
        - "CHX NUGGET BTRD TY 10LB" -> size: "10 LB", uom: "LB"
        - "FF ZESTY TWISTER 20LB" -> size: "20 LB", uom: "LB"
        - "CREAM JF 36% UHT 32Z" -> size: "32 OZ", uom: "OZ"
        - "FF BIGC 1/2 CRINKL 6/5LB" -> size: "5 LB", uom: "LB"
        """
        if not line_text:
            return None
        
        # Pattern 1: Size and UoM together (e.g., "10LB", "20LB", "32Z", "5LB")
        size_patterns = [
            (r'(\d+(?:\.\d+)?)\s*(?:FL\s+)?(LB|LBS|OZ|OZS|QT|QTS|GAL|GALS|CT|COUNT|PK|PACK)', re.IGNORECASE),
            (r'(\d+(?:\.\d+)?)\s*([Z])\s*$', re.IGNORECASE),  # Handle "32Z" -> "32 OZ"
        ]
        
        for pattern, flags in size_patterns:
            match = re.search(pattern, line_text, flags)
            if match:
                size_qty = match.group(1)
                uom_raw = match.group(2).upper()
                
                # Handle "Z" as "OZ"
                if uom_raw == 'Z':
                    uom_raw = 'OZ'
                
                # Normalize UoM
                uom_map = {
                    'LB': 'LB', 'LBS': 'LB',
                    'OZ': 'OZ', 'OZS': 'OZ', 'Z': 'OZ',
                    'QT': 'QT', 'QTS': 'QT',
                    'GAL': 'GAL', 'GALS': 'GAL',
                    'CT': 'CT', 'COUNT': 'CT',
                    'PK': 'CT', 'PACK': 'CT',
                }
                uom = uom_map.get(uom_raw, uom_raw)
                
                size_str = f"{size_qty} {uom}"
                return {
                    'size': size_str,
                    'uom': uom
                }
        
        return None
    
    def _normalize_vendor_key(self, vendor: str) -> str:
        """Normalize vendor name to profile key"""
        vendor_lower = vendor.lower().replace('-', '_').replace(' ', '_')
        
        # Map to known profile keys
        vendor_map = {
            'costco': 'costco',
            'restaurant_depot': 'restaurant_depot',
            'rd': 'restaurant_depot',
            'restaurantdepot': 'restaurant_depot',
        }
        
        return vendor_map.get(vendor_lower, vendor_lower)
    
    def get_vendor_product_info(self, vendor: str, query: str, force_update: bool = False, 
                                item_number: Optional[str] = None, upc: Optional[str] = None) -> Optional[Dict]:
        """
        Unified function to get product information from vendor website or cache.
        
        Priority order:
        1. If item_number or UPC is provided, look up directly by item_number/UPC (most accurate)
        2. Otherwise, search by product name
        
        For Costco: Always fetches fresh price, caches non-price fields.
        For Restaurant Depot: Caches everything including prices (monthly updates).
        
        Args:
            vendor: Vendor name ("Costco", "Restaurant Depot", "RD", etc.)
            query: Product name or search query (used if item_number/UPC not available)
            force_update: If True, force fresh fetch (default: False, uses cache when available)
            item_number: Item number from receipt (if available, used for direct lookup)
            upc: UPC from receipt (if available, used for direct lookup)
            
        Returns:
            Dictionary with product info: {
                "vendor": str,
                "search_name": str,
                "name": str,
                "price": str (formatted),
                "unit_size": str,
                "url": str,
                "fetched_at": str (ISO timestamp)
            }
            Or None if not found
        """
        vendor_key = self._normalize_vendor_key(vendor)
        
        # Priority 1: If we have item_number or UPC, look up directly (most accurate)
        if item_number or upc:
            lookup_result = self._lookup_by_item_number_or_upc(vendor_key, item_number, upc, force_update)
            if lookup_result:
                return lookup_result
        
        # Priority 2: Fall back to product name search
        if vendor_key == 'costco':
            return self._get_costco_product_info(query, force_update)
        elif vendor_key == 'restaurant_depot':
            return self._get_rd_product_info(query, force_update)
        else:
            logger.warning(f"Unified product enrichment not supported for vendor: {vendor}")
            return None
    
    def _lookup_by_item_number_or_upc(self, vendor_key: str, item_number: Optional[str], 
                                       upc: Optional[str], force_update: bool = False) -> Optional[Dict]:
        """
        Look up product directly by item number or UPC on vendor website.
        This is more accurate than searching by product name.
        
        Args:
            vendor_key: Normalized vendor key ('costco' or 'restaurant_depot')
            item_number: Item number from receipt
            upc: UPC from receipt
            force_update: Force fresh fetch
            
        Returns:
            Product info dictionary or None
        """
        if vendor_key == 'costco':
            return self._lookup_costco_by_item_number(item_number, upc, force_update)
        elif vendor_key == 'restaurant_depot':
            return self._lookup_rd_by_item_number(item_number, upc, force_update)
        return None
    
    def _lookup_costco_by_item_number(self, item_number: Optional[str], upc: Optional[str], 
                                     force_update: bool = False) -> Optional[Dict]:
        """Look up Costco product by item number from knowledge base"""
        # Try item number first, then UPC
        identifier = item_number or upc
        if not identifier:
            logger.debug("No item_number or UPC provided for Costco lookup")
            return None
        
        logger.info(f"Looking up Costco product by item_number/UPC: {identifier} in knowledge base")
        
        # Look up in knowledge base
        item_no = str(identifier).strip()
        if item_no in self.knowledge_base:
            kb_item = self.knowledge_base[item_no]
            
            # Only return if it's a Costco item
            if kb_item.get('store', '').lower() in ['costco', 'costco.com']:
                # Get price as float for unit_price
                unit_price_float = None
                if isinstance(kb_item['price'], (int, float)):
                    unit_price_float = float(kb_item['price'])
                elif isinstance(kb_item['price'], str):
                    # Try to extract from string
                    import re
                    price_match = re.search(r'\$?(\d+\.?\d*)', kb_item['price'])
                    if price_match:
                        try:
                            unit_price_float = float(price_match.group(1))
                        except (ValueError, TypeError):
                            pass
                
                result = {
                    "vendor": "Costco",
                    "search_name": f"Item #{item_number}",
                    "name": kb_item['name'],
                    "price": f"${kb_item['price']:.2f}" if isinstance(kb_item['price'], (int, float)) else kb_item['price'],
                    "unit_price": unit_price_float,  # Add unit_price for quantity estimation
                    "unit_size": kb_item['spec'],
                    "url": f"https://www.costco.com/.product.{item_number}.html",
                    "fetched_at": datetime.now().isoformat()
                }
                logger.info(f"Found Costco product in knowledge base: {kb_item['name']} (item_number: {item_number}, unit_price: ${unit_price_float})")
                return result
        
        logger.debug(f"Costco product not found in knowledge base for item_number: {item_number}")
        return None
    
    def _lookup_rd_by_item_number(self, item_number: Optional[str], upc: Optional[str], 
                                  force_update: bool = False) -> Optional[Dict]:
        """Look up Restaurant Depot product by item number from knowledge base"""
        # Try item number first, then UPC
        identifier = item_number or upc
        if not identifier:
            logger.debug("No item_number or UPC provided for RD lookup")
            return None
        
        logger.info(f"Looking up RD product by item_number/UPC: {identifier} in knowledge base")
        
        # Look up in knowledge base
        item_no = str(identifier).strip()
        if item_no in self.knowledge_base:
            kb_item = self.knowledge_base[item_no]
            
            # Only return if it's an RD item
            if kb_item.get('store', '').upper() in ['RD', 'RESTAURANT DEPOT', 'RESTAURANTDEPOT']:
                result = {
                    "vendor": "Restaurant Depot",
                    "location": "Chicago, IL",
                    "item_name": kb_item['name'],
                    "unit_size": kb_item['spec'],
                    "price_total": f"${kb_item['price']:.2f}" if isinstance(kb_item['price'], (int, float)) else kb_item['price'],
                    "url": "",
                    "fetched_at": datetime.now().strftime('%Y-%m-%d')
                }
                logger.info(f"Found RD product in knowledge base: {kb_item['name']} (item_number: {item_number})")
                return result
        
        logger.debug(f"RD product not found in knowledge base for item_number: {item_number}")
        return None
    
    def _get_costco_product_info(self, query: str, force_update: bool = False) -> Optional[Dict]:
        """Get Costco product info from knowledge base (web scraping disabled)"""
        # Web scraping disabled - search knowledge base by product name would require
        # matching product name to item number, which is not straightforward.
        # For now, return None and suggest using item_number lookup instead.
        logger.debug(f"Product name search disabled - use item_number lookup with knowledge base for '{query}'")
        return None
    
    def _get_rd_product_info(self, query: str, force_update: bool = False) -> Optional[Dict]:
        """Get Restaurant Depot product info from knowledge base (web scraping disabled)"""
        # Web scraping disabled - search knowledge base by product name would require
        # matching product name to item number, which is not straightforward.
        # For now, return None and suggest using item_number lookup instead.
        logger.debug(f"Product name search disabled - use item_number lookup with knowledge base for '{query}'")
        return None
    
