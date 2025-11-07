"""
Category Classifier
Classifies receipt line items into L1 (accounting) and L2 (operational) categories
using rule-based matching from YAML files.
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class CategoryClassifier:
    """
    Rule-based category classifier for receipt items.
    Loads rules from YAML files and applies them in a deterministic pipeline.
    """
    
    def __init__(self, rule_loader):
        """
        Initialize classifier with rule loader.
        
        Args:
            rule_loader: RuleLoader instance
        """
        self.rule_loader = rule_loader
        
        # Load all category rules (in priority order: 57 → 58 → 59 → 99)
        self.l1_rules = rule_loader.load_rule_file_by_name('55_categories_l1.yaml')
        self.l2_rules = rule_loader.load_rule_file_by_name('56_categories_l2.yaml')
        self.instacart_rules = rule_loader.load_rule_file_by_name('57_category_maps_instacart.yaml')
        self.amazon_rules = rule_loader.load_rule_file_by_name('58_category_maps_amazon.yaml')
        self.keyword_rules = rule_loader.load_rule_file_by_name('59_category_keywords.yaml')
        self.classification_overrides = rule_loader.load_rule_file_by_name('99_classification_overrides.yaml')
        # Optional: Wismettac online category mapping
        try:
            self.wismettac_map = rule_loader.load_rule_file_by_name('wismettac_category_map.yaml')
        except Exception:
            self.wismettac_map = {"maps": []}
        
        # Extract relevant sections
        self.l1_categories = self.l1_rules.get('categories_l1', {}).get('l1_categories', [])
        self.l2_to_l1_map = self.l1_rules.get('categories_l1', {}).get('l2_to_l1_map', {})
        self.l2_categories = self.l2_rules.get('categories_l2', {}).get('l2_categories', [])
        
        # Build lookup dicts
        self.l1_lookup = {cat['id']: cat for cat in self.l1_categories}
        self.l2_lookup = {cat['id']: cat for cat in self.l2_categories}
        
        # Pipeline settings
        pipeline_config = self.keyword_rules.get('category_keywords', {})
        self.pipeline_order = pipeline_config.get('pipeline_order', [])
        self.default_confidence = pipeline_config.get('default_confidence', {})
        self.review_threshold = pipeline_config.get('review_threshold', 0.60)
        self.fallback_l2 = pipeline_config.get('fallback_l2', 'C99')
        
        
        logger.info(f"CategoryClassifier initialized with {len(self.l1_categories)} L1 and {len(self.l2_categories)} L2 categories")
    
    def classify_items(self, items: List[Dict[str, Any]], source_type: str = None, vendor_code: str = None) -> List[Dict[str, Any]]:
        """
        Classify a list of items from a receipt.
        
        Args:
            items: List of item dicts from Step 1 extraction
            source_type: e.g., 'localgrocery_based', 'instacart_based', 'amazon_based'
            vendor_code: e.g., 'COSTCO', 'RD', 'INSTACART', 'AMAZON'
            
        Returns:
            List of items with added category fields
        """
        classified_items = []
        
        for item in items:
            classified_item = item.copy()
            
            # Run classification pipeline
            result = self._classify_single_item(item, source_type, vendor_code)
            
            # Add category fields
            classified_item['l2_category'] = result['l2_category']
            classified_item['l1_category'] = result['l1_category']
            classified_item['category_source'] = result['category_source']
            classified_item['category_rule_id'] = result['category_rule_id']
            classified_item['category_confidence'] = result['category_confidence']
            classified_item['needs_category_review'] = result['needs_category_review']
            
            # Add human-readable names
            l2_info = self.l2_lookup.get(result['l2_category'], {})
            l1_info = self.l1_lookup.get(result['l1_category'], {})
            classified_item['l2_category_name'] = l2_info.get('name', 'Unknown')
            classified_item['l1_category_name'] = l1_info.get('name', 'Unknown')
            
            classified_items.append(classified_item)
        
        return classified_items
    
    def _classify_single_item(self, item: Dict[str, Any], source_type: str, vendor_code: str) -> Dict[str, Any]:
        """
        Classify a single item through the pipeline.
        
        Returns:
            Dict with l2_category, l1_category, category_source, category_rule_id, category_confidence, needs_category_review
        """
        # Use clean_name if available (from name hygiene), otherwise fall back to product_name
        product_name = item.get('clean_name') or item.get('canonical_name') or item.get('product_name', '')
        is_fee = item.get('is_fee', False)
        
        # Try each stage in pipeline order
        for stage in self.pipeline_order:
            if stage == 'source_map':
                result = self._apply_source_map(item, source_type)
                if result:
                    return result

            # Vendor-scoped online lookup (Wismettac) before vendor_overrides
            if ((vendor_code or '').upper() == 'WISMETTAC') and stage == 'vendor_overrides':
                # 1) Map using vendor_category if present (offline enrichment support)
                vc = (item.get('vendor_category') or '').strip()
                if vc:
                    mapped = self._map_wismettac_category_string(vc)
                    if mapped:
                        return mapped
                # 2) Try live/name-based lookup
                online = self._apply_wismettac_lookup(item)
                if online:
                    return online
            
            
            
            elif stage == 'vendor_overrides':
                result = self._apply_vendor_overrides(item, vendor_code, source_type)
                if result:
                    return result
            
            elif stage == 'keywords':
                result = self._apply_keywords(item)
                if result:
                    return result
            
            elif stage == 'heuristics':
                result = self._apply_heuristics(item)
                if result:
                    return result
            
            elif stage == 'overrides':
                result = self._apply_overrides(item)
                if result:
                    return result
            
            elif stage == 'fallback':
                return self._apply_fallback(item)
        
        # Should never reach here, but safety fallback
        return self._apply_fallback(item)

    def _map_wismettac_category_string(self, category_text: str) -> Optional[Dict[str, Any]]:
        if not category_text:
            return None
        # Handle both direct 'maps' key and nested 'wismettac_category_map.maps' structure
        maps = self.wismettac_map.get('maps', [])
        if not maps:
            # Try nested structure
            nested = self.wismettac_map.get('wismettac_category_map', {})
            maps = nested.get('maps', [])
        
        for rule in maps:
            pat = rule.get('match')
            if pat and re.search(pat, category_text, re.IGNORECASE):
                l2 = rule.get('l2')
                if l2:
                    return self._build_result(
                        l2_category=l2,
                        source='wismettac_vendor_category',
                        rule_id='wismettac_vendor_category_map',
                        confidence=0.92
                    )
        return None

    def _apply_wismettac_lookup(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Use Wismettac online catalog by item number or product name to get category and pack size → map to L2."""
        try:
            from .wismettac_client import WismettacClient
        except Exception:
            return None
        
        item_no = (item.get('item_number') or '').strip()
        product_name = (item.get('product_name') or item.get('canonical_name') or '').strip()
        
        if not item_no and not product_name:
            return None
        
        try:
            client = WismettacClient()
            prod = None
            
            # Try item number first (more reliable)
            if item_no:
                prod = client.lookup_product(item_no)
            
            # If item number lookup failed, try product name
            if not prod and product_name:
                prod = client.lookup_product_by_name(product_name)
            
            if not prod:
                return None
            
            # Enrich item fields when available
            if prod.name and not item.get('product_name'):
                item['product_name'] = prod.name
            if prod.brand:
                item['brand'] = prod.brand
            if prod.pack_size_raw:
                item['pack_size_raw'] = prod.pack_size_raw
                # Also set size_spec for consistency
                if not item.get('size_spec'):
                    item['size_spec'] = prod.pack_size_raw
            if prod.pack is not None:
                item['pack_case_qty'] = prod.pack
                item['pack_count'] = prod.pack
            if prod.each_qty is not None:
                item['each_qty'] = prod.each_qty
                item['unit_size'] = prod.each_qty
            if prod.each_uom:
                item['each_uom'] = prod.each_uom
                item['unit_uom'] = prod.each_uom
                # Also set purchase_uom if not already set
                if not item.get('purchase_uom'):
                    item['purchase_uom'] = prod.each_uom
            if prod.barcode:
                item['upc'] = prod.barcode
            if prod.min_order_qty:
                item['min_order_qty'] = prod.min_order_qty
            if prod.detail_url:
                item['vendor_detail_url'] = prod.detail_url
            if prod.item_number and not item.get('item_number'):
                item['item_number'] = prod.item_number
            
            # Store category for mapping
            if prod.category:
                item['vendor_category'] = prod.category
            
            # Add to knowledge base if not already present
            try:
                self._add_wismettac_to_kb(prod, item.get('unit_price'))
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Failed to add Wismettac product to KB: {e}")
            
            # If no pack info from site, try to parse from product name string
            if not item.get('pack_size_raw'):
                try:
                    from .wismettac_client import parse_pack_size
                    p, q, u = parse_pack_size(item.get('product_name') or '')
                    if p is not None or q is not None or u:
                        item['pack_size_raw'] = item.get('product_name')
                        if p is not None:
                            item['pack_case_qty'] = p
                            item['pack_count'] = p
                        if q is not None:
                            item['each_qty'] = q
                            item['unit_size'] = q
                        if u:
                            item['each_uom'] = u
                            item['unit_uom'] = u
                except Exception:
                    pass

            # Map by site Category first (only if available)
            if prod.category:
                category = prod.category
                for rule in self.wismettac_map.get('maps', []):
                    pat = rule.get('match')
                    if pat and re.search(pat, category, re.IGNORECASE):
                        l2 = rule.get('l2')
                        if l2:
                            return self._build_result(
                                l2_category=l2,
                                source='wismettac_online',
                                rule_id='wismettac_online_map',
                                confidence=0.90
                            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Wismettac lookup failed: {e}")
            pass
        
        # Name-based fallback mapping regardless of online success
        text = (item.get('canonical_name') or item.get('product_name') or '')
        for rule in self.wismettac_map.get('name_maps', []):
            pat = rule.get('match')
            if pat and re.search(pat, text, re.IGNORECASE):
                l2 = rule.get('l2')
                if l2:
                    return self._build_result(
                        l2_category=l2,
                        source='wismettac_name_fallback',
                        rule_id='wismettac_name_map',
                        confidence=0.85
                    )
        return None
    
    def _add_wismettac_to_kb(self, product: Any, unit_price: Optional[float] = None) -> None:
        """Add Wismettac product to knowledge base if not already present."""
        try:
            from .vendor_profiles import _ensure_kb_loaded
            from pathlib import Path
            import json
            
            # Get KB path
            kb_path = Path('data/step1_input/knowledge_base.json')
            if not kb_path.exists():
                kb_path = Path('data/knowledge_base.json')
            
            if not kb_path.exists():
                return  # KB doesn't exist, skip
            
            # Load KB
            try:
                with kb_path.open('r', encoding='utf-8') as f:
                    kb = json.load(f)
            except Exception:
                return  # Can't load KB, skip
            
            # Get item number
            item_no = product.item_number
            if not item_no:
                return
            
            # Normalize item number (remove # prefix)
            item_no_clean = str(item_no).strip().lstrip('#')
            
            # Check if already in KB
            if item_no_clean in kb:
                return  # Already in KB, skip
            
            # Build size_spec
            size_spec = product.pack_size_raw or ''
            if not size_spec and product.pack and product.each_qty and product.each_uom:
                size_spec = f"{product.pack}/{product.each_qty} {product.each_uom}"
            elif not size_spec and product.pack:
                size_spec = f"{product.pack} pack"
            
            # Get product name
            product_name = product.name or ''
            
            # Use provided unit_price or default to 0.0
            price = float(unit_price) if unit_price is not None else 0.0
            
            # Add to KB in old format: [product_name, store, size_spec, unit_price]
            kb[item_no_clean] = [
                product_name,
                'Wismettac',
                size_spec,
                price
            ]
            
            # Save KB
            try:
                with kb_path.open('w', encoding='utf-8') as f:
                    json.dump(kb, f, indent=2, ensure_ascii=False)
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Added Wismettac product {item_no_clean} to KB: {product_name}")
            except Exception:
                pass  # Can't save, skip silently
        except Exception:
            pass  # Fail silently to not interrupt processing

    
    
    def _apply_source_map(self, item: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """Apply source-specific rules (Instacart/Amazon)"""
        if source_type == 'instacart_based':
            return self._apply_instacart_rules(item)
        elif source_type == 'amazon_based':
            return self._apply_amazon_rules(item)
        return None
    
    def _apply_instacart_rules(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply Instacart-specific category rules"""
        rules = self.instacart_rules.get('category_maps_instacart', {}).get('rules', [])
        
        # Sort by priority (highest first)
        sorted_rules = sorted(rules, key=lambda r: r.get('priority', 0), reverse=True)
        
        for idx, rule in enumerate(sorted_rules):
            if self._match_instacart_rule(item, rule):
                l2_category = rule.get('map_to_l2', self.fallback_l2)
                return self._build_result(
                    l2_category=l2_category,
                    source='instacart_map',
                    rule_id=f"instacart_rule_{idx}",
                    confidence=self.default_confidence.get('source_map', 0.95)
                )
        
        return None
    
    def _match_instacart_rule(self, item: Dict[str, Any], rule: Dict[str, Any]) -> bool:
        """Check if item matches an Instacart rule"""
        match = rule.get('match', {})
        
        # Default rule (always matches)
        if match.get('default'):
            return True
        
        # Check is_fee
        if 'is_fee' in match and match['is_fee'] != item.get('is_fee', False):
            return False
        
        # Check department
        if 'department' in match:
            item_dept = item.get('department', '').lower()
            if match['department'].lower() not in item_dept and item_dept not in match['department'].lower():
                return False
        
        # Check category_path
        if 'category_path' in match:
            item_cat = item.get('category_path', '').lower()
            if match['category_path'].lower() not in item_cat:
                return False
        
        # Check aisle
        if 'aisle' in match:
            item_aisle = item.get('aisle', '').lower()
            if match['aisle'].lower() not in item_aisle:
                return False
        
        # Check l3_category_name (direct mapping from Instacart CSV)
        if 'l3_category_name' in match:
            item_l3 = item.get('l3_category_name', '').lower()
            if match['l3_category_name'].lower() != item_l3:
                return False
        
        # Check text_contains (against product_name)
        if 'text_contains' in match:
            product_name = item.get('product_name', '').lower()
            patterns = match['text_contains']
            if not isinstance(patterns, list):
                patterns = [patterns]
            
            if not any(pattern.lower() in product_name for pattern in patterns):
                return False
        
        # Check and_contains (all must be present)
        if 'and_contains' in match:
            product_name = item.get('product_name', '').lower()
            patterns = match['and_contains']
            if not isinstance(patterns, list):
                patterns = [patterns]
            
            if not all(pattern.lower() in product_name for pattern in patterns):
                return False
        
        return True
    
    def _apply_amazon_rules(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply Amazon-specific category rules"""
        rules = self.amazon_rules.get('category_maps_amazon', {}).get('rules', [])
        
        # Sort by priority (highest first)
        sorted_rules = sorted(rules, key=lambda r: r.get('priority', 0), reverse=True)
        
        for idx, rule in enumerate(sorted_rules):
            if self._match_amazon_rule(item, rule):
                l2_category = rule.get('map_to_l2', self.fallback_l2)
                return self._build_result(
                    l2_category=l2_category,
                    source='amazon_map',
                    rule_id=f"amazon_rule_{idx}",
                    confidence=self.default_confidence.get('source_map', 0.95)
                )
        
        return None
    
    def _match_amazon_rule(self, item: Dict[str, Any], rule: Dict[str, Any]) -> bool:
        """Check if item matches an Amazon rule"""
        match = rule.get('match', {})
        
        # Default rule (always matches)
        if match.get('default'):
            return True
        
        # Check is_fee
        if 'is_fee' in match and match['is_fee'] != item.get('is_fee', False):
            return False
        
        product_name = item.get('product_name', '')
        
        # Check item_title_regex
        if 'item_title_regex' in match:
            pattern = match['item_title_regex']
            if not re.search(pattern, product_name, re.IGNORECASE):
                return False
        
        # Check text_contains (for fees)
        if 'text_contains' in match:
            patterns = match['text_contains']
            if not isinstance(patterns, list):
                patterns = [patterns]
            
            if not any(pattern.lower() in product_name.lower() for pattern in patterns):
                return False
        
        # Check category
        if 'category' in match:
            item_cat = item.get('category', '')
            if match['category'].lower() not in item_cat.lower():
                return False
        
        # Check UNSPSC segment
        if 'unspsc_segment' in match:
            item_segment = item.get('unspsc_segment', '')
            if match['unspsc_segment'].lower() not in item_segment.lower():
                return False
        
        # Check UNSPSC family
        if 'unspsc_family' in match:
            item_family = item.get('unspsc_family', '')
            if match['unspsc_family'].lower() != item_family.lower():
                return False
        
        # Check UNSPSC commodity
        if 'unspsc_commodity' in match:
            item_commodity = item.get('unspsc_commodity', '')
            if match['unspsc_commodity'].lower() not in item_commodity.lower():
                return False
        
        # Check seller
        if 'seller' in match:
            item_seller = item.get('seller', '')
            if match['seller'].lower() not in item_seller.lower():
                return False
        
        return True
    
    def _apply_vendor_overrides(self, item: Dict[str, Any], vendor_code: str, source_type: str = None) -> Optional[Dict[str, Any]]:
        """Apply vendor-specific hints from L2 catalog"""
        # Check for WebstaurantStore online lookup hints
        if vendor_code == 'WEBSTAURANTSTORE' and item.get('_webstaurantstore_l2_hint'):
            l2_category = item['_webstaurantstore_l2_hint']
            confidence = item.get('_webstaurantstore_confidence', 0.80)
            keywords = item.get('_webstaurantstore_keywords', [])
            
            return self._build_result(
                l2_category=l2_category,
                source='webstaurantstore_lookup',
                rule_id=f"wss_lookup_{item.get('item_number', 'unknown')}",
                confidence=confidence
            )
        
        # Apply classification overrides from YAML file (highest priority)
        override_rules = self.classification_overrides.get('overrides', [])
        if override_rules:
            # Build text for matching (canonical_name or display_name or product_name)
            text = (item.get('canonical_name') or 
                    item.get('display_name') or 
                    item.get('product_name') or '')
            vendor = (vendor_code or item.get('vendor') or '').strip()
            
            # Sort by weight (highest first) - stop after first match
            sorted_rules = sorted(override_rules, key=lambda r: r.get('weight', 0), reverse=True)
            
            for rule in sorted_rules:
                # Check vendor match
                if 'when_vendor_in' in rule:
                    vendor_list = rule.get('when_vendor_in', [])
                    if not vendor or vendor.upper() not in [v.upper() for v in vendor_list]:
                        continue
                
                # Check source_type match
                if 'when_source_type_in' in rule:
                    source_list = rule.get('when_source_type_in', [])
                    if not source_type or source_type.lower() not in [s.lower() for s in source_list]:
                        continue
                
                # Check name patterns (match canonical_name/display_name/product_name)
                name_patterns = rule.get('when_name_matches', [])
                if name_patterns:
                    name_matched = any(re.search(pattern, text) for pattern in name_patterns)
                    if not name_matched:
                        continue
                
                # Apply override using codes (L1_code/L2_code)
                set_config = rule.get('set', {})
                l1_code = set_config.get('L1_code')
                l2_code = set_config.get('L2_code')
                
                # Map codes to names using taxonomy
                l1_category = l1_code
                l2_category = l2_code
                
                if l2_code and not l1_code:
                    # Derive L1 from L2 mapping if not provided
                    l1_category = self.l2_to_l1_map.get(l2_code, 'A99')
                
                # Get category names from taxonomy
                l1_name = "UNKNOWN_L1"
                l2_name = "UNKNOWN_L2"
                needs_review = False
                
                if l1_category:
                    l1_cat_data = self.l1_lookup.get(l1_category)
                    if l1_cat_data:
                        l1_name = l1_cat_data.get('name', 'UNKNOWN_L1')
                    else:
                        needs_review = True
                        logger.warning(f"L1 code {l1_category} not found in taxonomy")
                
                if l2_category:
                    l2_cat_data = self.l2_lookup.get(l2_category)
                    if l2_cat_data:
                        l2_name = l2_cat_data.get('name', 'UNKNOWN_L2')
                    else:
                        needs_review = True
                        logger.warning(f"L2 code {l2_category} not found in taxonomy")
                
                # Use weight as confidence (normalized to 0-1 range)
                weight = rule.get('weight', 98)
                confidence = min(weight / 100.0, 1.0)
                
                # Store l2_subtype if provided
                l2_subtype = set_config.get('l2_subtype')
                
                if l2_category:
                    rule_id = rule.get('id', f"override_{vendor.lower()}")
                    # Build result with L1 and L2 codes
                    result = self._build_result(
                        l2_category=l2_category,
                        source='classification_override',
                        rule_id=rule_id,
                        confidence=confidence
                    )
                    # Override L1 if explicitly set (otherwise _build_result derives it from L2)
                    if l1_category:
                        result['l1_category'] = l1_category
                    # Add category names from taxonomy
                    result['l1_category_name'] = l1_name
                    result['l2_category_name'] = l2_name
                    # Add subtype if provided
                    if l2_subtype:
                        result['l2_subtype'] = l2_subtype
                    # Mark for review if code not found in taxonomy
                    if needs_review:
                        result['needs_category_review'] = True
                    # Stop after first match (highest weight)
                    return result
        
        # RD-specific vendor heuristics (run early, before general keywords)
        # These use clean_name and size_spec from name hygiene
        if vendor_code in ['RD', 'RESTAURANT_DEPOT', 'RESTAURANT']:
            result = self._apply_rd_vendor_heuristics(item)
            if result:
                return result
        
        return None
    
    def _apply_keywords(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply global keyword rules"""
        keyword_config = self.keyword_rules.get('category_keywords', {})
        rules = keyword_config.get('keyword_rules', [])
        
        # Sort by priority
        sorted_rules = sorted(rules, key=lambda r: r.get('priority', 0), reverse=True)
        
        # Use clean_name if available (from name hygiene), otherwise fall back to product_name
        product_name = item.get('clean_name') or item.get('canonical_name') or item.get('product_name', '')
        
        for idx, rule in enumerate(sorted_rules):
            include_pattern = rule.get('include_regex', '')
            exclude_pattern = rule.get('exclude_regex', '')
            
            # Check include
            if not re.search(include_pattern, product_name, re.IGNORECASE):
                continue
            
            # Check exclude (if present)
            if exclude_pattern and re.search(exclude_pattern, product_name, re.IGNORECASE):
                continue
            
            # Match found
            l2_category = rule.get('map_to_l2', self.fallback_l2)
            return self._build_result(
                l2_category=l2_category,
                source='keyword',
                rule_id=f"keyword_rule_{idx}",
                confidence=self.default_confidence.get('keywords', 0.80)
            )
        
        return None
    
    def _apply_heuristics(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply heuristic classifiers - all mappings from YAML"""
        keyword_config = self.keyword_rules.get('category_keywords', {})
        heuristics = keyword_config.get('heuristics', {})
        
        # Use clean_name if available (from name hygiene), otherwise fall back to product_name
        product_name = (item.get('clean_name') or item.get('canonical_name') or item.get('product_name', '')).lower()
        
        # Try fruit heuristic
        fruit_config = heuristics.get('fruit', {})
        if self._contains_any_token(product_name, fruit_config.get('tokens', [])):
            # Check unless_name_matches to exclude powder, jelly, jam, purée, topping
            unless_patterns = fruit_config.get('unless_name_matches', [])
            if unless_patterns:
                for pattern in unless_patterns:
                    if re.search(pattern, product_name, re.IGNORECASE):
                        # Skip fruit classification if it matches exclusion pattern
                        break
                else:
                    # No exclusion pattern matched, continue with fruit classification
                    # Check if frozen - mapping from YAML
                    freezer_markers = fruit_config.get('freezer_markers', [])
                    if self._contains_any_token(product_name, freezer_markers):
                        l2_category = fruit_config.get('map_to_l2_frozen')  # From YAML, no default
                    else:
                        l2_category = fruit_config.get('map_to_l2_fresh')  # From YAML, no default
                    
                    if l2_category:  # Only return if YAML provides mapping
                        return self._build_result(
                            l2_category=l2_category,
                            source='heuristic',
                            rule_id='fruit_heuristic',
                            confidence=fruit_config.get('confidence', 0.85)
                        )
            else:
                # No exclusion patterns defined, proceed normally
                # Check if frozen - mapping from YAML
                freezer_markers = fruit_config.get('freezer_markers', [])
                if self._contains_any_token(product_name, freezer_markers):
                    l2_category = fruit_config.get('map_to_l2_frozen')  # From YAML, no default
                else:
                    l2_category = fruit_config.get('map_to_l2_fresh')  # From YAML, no default
                
                if l2_category:  # Only return if YAML provides mapping
                    return self._build_result(
                        l2_category=l2_category,
                        source='heuristic',
                        rule_id='fruit_heuristic',
                        confidence=fruit_config.get('confidence', 0.85)
                    )
        
        # Try topping heuristic
        topping_config = heuristics.get('topping', {})
        if self._contains_any_token(product_name, topping_config.get('tokens', [])):
            l2_category = topping_config.get('map_to_l2')  # From YAML
            if l2_category:
                return self._build_result(
                    l2_category=l2_category,
                    source='heuristic',
                    rule_id='topping_heuristic',
                    confidence=topping_config.get('confidence', 0.90)
                )
        
        # Try dairy heuristic
        dairy_config = heuristics.get('dairy', {})
        if self._contains_any_token(product_name, dairy_config.get('tokens', [])):
            l2_category = dairy_config.get('map_to_l2')  # From YAML
            if l2_category:
                return self._build_result(
                    l2_category=l2_category,
                    source='heuristic',
                    rule_id='dairy_heuristic',
                    confidence=dairy_config.get('confidence', 0.85)
                )
        
        # Try cleaning heuristic
        cleaning_config = heuristics.get('cleaning', {})
        if self._contains_any_token(product_name, cleaning_config.get('tokens', [])):
            l2_category = cleaning_config.get('map_to_l2')  # From YAML
            if l2_category:
                return self._build_result(
                    l2_category=l2_category,
                    source='heuristic',
                    rule_id='cleaning_heuristic',
                    confidence=cleaning_config.get('confidence', 0.80)
                )
        
        return None
    
    def _contains_any_token(self, text: str, tokens: List[str]) -> bool:
        """Check if text contains any of the tokens (case-insensitive)"""
        text_lower = text.lower()
        return any(token.lower() in text_lower for token in tokens)
    
    def _apply_rd_vendor_heuristics(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        RD-specific vendor heuristics that run early in the pipeline.
        Uses clean_name and size_spec from name hygiene.
        
        Heuristics:
        - Frozen: IQF, FZ markers → C08 (Frozen Fruit) or C10 (Frozen Vegetables)
        - Packaging: CT markers, multi-pack patterns → C20-C23 (Packaging)
        - Cleaning: detergent, sanitizer → C50 (Cleaning & Chemicals)
        - Gloves: gloves, food service supplies → C31 (Gloves & Food Service Supplies)
        - Syrups/Jams: syrups vs jams distinction → C02 (Syrups) or C03 (Jam/Purée)
        """
        # Use clean_name and size_spec from name hygiene
        clean_name = (item.get('clean_name') or item.get('canonical_name') or item.get('product_name', '')).lower()
        size_spec = (item.get('size_spec') or '').upper()
        product_name = clean_name  # Use clean name for matching
        
        # 1. Frozen detection (IQF, FZ markers)
        if 'iqf' in product_name or 'fz' in product_name or 'frozen' in product_name:
            # Check if it's fruit or vegetable
            fruit_tokens = ['strawberry', 'blueberry', 'mango', 'peach', 'berry', 'fruit']
            vegetable_tokens = ['vegetable', 'broccoli', 'corn', 'peas', 'carrot', 'spinach']
            
            if any(token in product_name for token in fruit_tokens):
                return self._build_result(
                    l2_category='C08',
                    source='rd_vendor_heuristic',
                    rule_id='rd_frozen_fruit',
                    confidence=0.90
                )
            elif any(token in product_name for token in vegetable_tokens):
                return self._build_result(
                    l2_category='C10',
                    source='rd_vendor_heuristic',
                    rule_id='rd_frozen_vegetable',
                    confidence=0.90
                )
            else:
                # Generic frozen (could be fruit or vegetable, default to fruit)
                return self._build_result(
                    l2_category='C08',
                    source='rd_vendor_heuristic',
                    rule_id='rd_frozen_generic',
                    confidence=0.75
                )
        
        # 2. Packaging detection (CT markers, multi-pack patterns from size_spec)
        if size_spec and ('CT' in size_spec or 'PK' in size_spec or 'CS' in size_spec):
            # Check product name for specific packaging types
            if any(word in product_name for word in ['napkin', 'towel', 'wipe', 'tissue']):
                return self._build_result(
                    l2_category='C21',
                    source='rd_vendor_heuristic',
                    rule_id='rd_packaging_napkin',
                    confidence=0.90
                )
            elif any(word in product_name for word in ['cup', 'lid', 'container']):
                return self._build_result(
                    l2_category='C20',
                    source='rd_vendor_heuristic',
                    rule_id='rd_packaging_cup',
                    confidence=0.90
                )
            elif any(word in product_name for word in ['bag', 'tray', 'wrap']):
                return self._build_result(
                    l2_category='C21',
                    source='rd_vendor_heuristic',
                    rule_id='rd_packaging_bag',
                    confidence=0.90
                )
            elif any(word in product_name for word in ['straw', 'utensil', 'fork', 'spoon', 'skewer']):
                return self._build_result(
                    l2_category='C22',
                    source='rd_vendor_heuristic',
                    rule_id='rd_packaging_utensil',
                    confidence=0.90
                )
            # Generic packaging (multi-pack pattern detected)
            return self._build_result(
                l2_category='C21',
                source='rd_vendor_heuristic',
                rule_id='rd_packaging_generic',
                confidence=0.80
            )
        
        # 3. Cleaning detection (detergent, sanitizer)
        cleaning_tokens = ['detergent', 'sanitizer', 'disinfectant', 'cleaner', 'chlorine', 'sani', 'dish']
        if any(token in product_name for token in cleaning_tokens):
            return self._build_result(
                l2_category='C50',
                source='rd_vendor_heuristic',
                rule_id='rd_cleaning',
                confidence=0.92
            )
        
        # 4. Gloves & Food Service Supplies
        if any(word in product_name for word in ['glove', 'spill kit', 'body fluid', 'apron']):
            return self._build_result(
                l2_category='C31',
                source='rd_vendor_heuristic',
                rule_id='rd_gloves_supplies',
                confidence=0.90
            )
        
        # 5. Syrups vs Jams distinction
        if 'syrup' in product_name or 'torani' in product_name or 'puremade' in product_name:
            # Exclude jams (they might have "syrup" in description)
            if 'jam' not in product_name and 'jelly' not in product_name and 'purée' not in product_name:
                return self._build_result(
                    l2_category='C02',
                    source='rd_vendor_heuristic',
                    rule_id='rd_syrup',
                    confidence=0.90
                )
        
        if 'jam' in product_name or 'jelly' in product_name or 'purée' in product_name or 'puree' in product_name:
            return self._build_result(
                l2_category='C03',
                source='rd_vendor_heuristic',
                rule_id='rd_jam',
                confidence=0.90
            )
        
        # No RD-specific match found
        return None
    
    def _apply_overrides(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply special overrides (tax, discount, shipping, tips) - all from YAML"""
        product_name = item.get('product_name', '')
        l1_config = self.l1_rules.get('categories_l1', {})
        
        # Tax override
        tax_config = l1_config.get('tax_overrides', {})
        tax_patterns = tax_config.get('patterns', [])
        for pattern in tax_patterns:
            if re.search(pattern, product_name):
                # Get L2 category from YAML (not hardcoded)
                l2_category = tax_config.get('map_to_l2', 'C70')
                return self._build_result(
                    l2_category=l2_category,
                    source='override_tax',
                    rule_id='tax_override',
                    confidence=1.00
                )
        
        # Discount override
        discount_config = l1_config.get('discount_overrides', {})
        discount_patterns = discount_config.get('patterns', [])
        for pattern in discount_patterns:
            if re.search(pattern, product_name):
                # Get L2 category from YAML (not hardcoded)
                l2_category = discount_config.get('map_to_l2', 'C95')
                return self._build_result(
                    l2_category=l2_category,
                    source='override_discount',
                    rule_id='discount_override',
                    confidence=1.00
                )
        
        # Shipping override
        shipping_config = l1_config.get('shipping_overrides', {})
        shipping_patterns = shipping_config.get('patterns', [])
        for pattern in shipping_patterns:
            if re.search(pattern, product_name):
                # Get L2 category from YAML (not hardcoded)
                l2_category = shipping_config.get('map_to_l2', 'C80')
                return self._build_result(
                    l2_category=l2_category,
                    source='override_shipping',
                    rule_id='shipping_override',
                    confidence=1.00
                )
        
        # Tip override
        tip_config = l1_config.get('tip_overrides', {})
        tip_patterns = tip_config.get('patterns', [])
        for pattern in tip_patterns:
            if re.search(pattern, product_name):
                # Get L2 category from YAML (not hardcoded)
                l2_category = tip_config.get('map_to_l2', 'C85')
                return self._build_result(
                    l2_category=l2_category,
                    source='override_tip',
                    rule_id='tip_override',
                    confidence=1.00
                )
        
        return None
    
    def _apply_fallback(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback to Unknown category"""
        return self._build_result(
            l2_category=self.fallback_l2,
            source='fallback',
            rule_id='fallback',
            confidence=self.default_confidence.get('fallback', 0.20)
        )
    
    def _build_result(self, l2_category: str, source: str, rule_id: str, confidence: float) -> Dict[str, Any]:
        """Build classification result dict"""
        # Map L2 to L1
        l1_category = self.l2_to_l1_map.get(l2_category, 'A99')
        
        # Determine if needs review
        needs_review = (l2_category == self.fallback_l2) or (confidence < self.review_threshold)
        
        return {
            'l2_category': l2_category,
            'l1_category': l1_category,
            'category_source': source,
            'category_rule_id': rule_id,
            'category_confidence': round(confidence, 2),
            'needs_category_review': needs_review
        }

