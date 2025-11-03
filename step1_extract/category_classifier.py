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
        
        # Load all category rules
        self.l1_rules = rule_loader.load_rule_file_by_name('55_categories_l1.yaml')
        self.l2_rules = rule_loader.load_rule_file_by_name('56_categories_l2.yaml')
        self.instacart_rules = rule_loader.load_rule_file_by_name('57_category_maps_instacart.yaml')
        self.amazon_rules = rule_loader.load_rule_file_by_name('58_category_maps_amazon.yaml')
        self.keyword_rules = rule_loader.load_rule_file_by_name('59_category_keywords.yaml')
        
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
        product_name = item.get('product_name', '')
        is_fee = item.get('is_fee', False)
        
        # Try each stage in pipeline order
        for stage in self.pipeline_order:
            if stage == 'source_map':
                result = self._apply_source_map(item, source_type)
                if result:
                    return result
            
            elif stage == 'vendor_overrides':
                result = self._apply_vendor_overrides(item, vendor_code)
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
    
    def _apply_vendor_overrides(self, item: Dict[str, Any], vendor_code: str) -> Optional[Dict[str, Any]]:
        """Apply vendor-specific hints from L2 catalog"""
        # TODO: Could implement vendor-specific biasing here
        return None
    
    def _apply_keywords(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply global keyword rules"""
        keyword_config = self.keyword_rules.get('category_keywords', {})
        rules = keyword_config.get('keyword_rules', [])
        
        # Sort by priority
        sorted_rules = sorted(rules, key=lambda r: r.get('priority', 0), reverse=True)
        
        product_name = item.get('product_name', '')
        
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
        
        product_name = item.get('product_name', '').lower()
        
        # Try fruit heuristic
        fruit_config = heuristics.get('fruit', {})
        if self._contains_any_token(product_name, fruit_config.get('tokens', [])):
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

