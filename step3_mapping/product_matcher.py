#!/usr/bin/env python3
"""
Product Matcher - Match receipt items to existing products and UoMs in database
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class ProductMatcher:
    """Match receipt items to existing products and UoMs"""
    
    def __init__(self, db_analysis_path: str, mapping_file: str = None, fruit_conversion_file: str = None):
        """
        Initialize product matcher with database analysis
        
        Args:
            db_analysis_path: Path to products_uom_analysis.json
            mapping_file: Path to product_name_mapping.json (optional)
            fruit_conversion_file: Path to fruit_weight_conversion.json (optional)
        """
        self.db_analysis_path = Path(db_analysis_path)
        self.mapping_file = mapping_file
        self.fruit_conversion_file = fruit_conversion_file
        
        # Initialize mapping data
        self.product_mappings = {}
        self.fruit_conversions = {}
        self._load_mappings()
        
        # Load database data
        self.db_data = self._load_db_analysis()
        self.products_index = self._build_products_index()
        self.uoms_index = self._build_uoms_index()
    
    def _load_mappings(self):
        """Load product name mappings and fruit weight conversions"""
        # Load product name mappings
        if self.mapping_file and Path(self.mapping_file).exists():
            try:
                with open(self.mapping_file, 'r', encoding='utf-8') as f:
                    all_mappings = json.load(f)
                    # Remove metadata fields (starting with _)
                    self.product_mappings = {
                        k: v for k, v in all_mappings.items() 
                        if not k.startswith('_')
                    }
                logger.debug(f"Loaded {len(self.product_mappings)} product mappings")
            except Exception as e:
                logger.warning(f"Could not load product mappings: {e}")
        
        # Load fruit weight conversions
        if self.fruit_conversion_file and Path(self.fruit_conversion_file).exists():
            try:
                with open(self.fruit_conversion_file, 'r', encoding='utf-8') as f:
                    all_conversions = json.load(f)
                    # Remove metadata fields (starting with _)
                    self.fruit_conversions = {
                        k: v for k, v in all_conversions.items() 
                        if not k.startswith('_')
                    }
                logger.debug(f"Loaded {len(self.fruit_conversions)} fruit conversions")
            except Exception as e:
                logger.warning(f"Could not load fruit conversions: {e}")
        
    
    def _load_db_analysis(self) -> Dict:
        """Load database analysis JSON file"""
        if not self.db_analysis_path.exists():
            raise FileNotFoundError(f"Database analysis file not found: {self.db_analysis_path}")
        
        with open(self.db_analysis_path, 'r') as f:
            data = json.load(f)
        
        logger.info(f"Loaded {len(data.get('products', {}))} products and {len(data.get('uoms', {}))} UoMs")
        return data
    
    def _build_products_index(self) -> Dict:
        """Build searchable index of products"""
        products_index = {}
        
        for prod_id, product in self.db_data.get('products', {}).items():
            template_id = product.get('product_tmpl_id')
            if template_id and template_id in self.db_data.get('product_templates', {}):
                template = self.db_data['product_templates'][template_id]
                name = template.get('name', '').lower()
                
                # Index by exact name
                products_index[name] = {
                    'product_id': int(prod_id),
                    'template_id': int(template_id),
                    'full_name': template.get('name'),
                    'exact_match': True,
                }
                
                # Index by words for partial matching
                words = name.split()
                for word in words:
                    if len(word) > 2:  # Ignore very short words
                        if word not in products_index:
                            products_index[word] = {
                                'product_id': int(prod_id),
                                'template_id': int(template_id),
                                'full_name': template.get('name'),
                                'exact_match': False,
                            }
        
        return products_index
    
    def _build_uoms_index(self) -> Dict:
        """Build searchable index of UoMs"""
        uoms_index = {}
        
        for uom_id, uom in self.db_data.get('uoms', {}).items():
            name = uom.get('name', '').lower()
            if name:
                uoms_index[name] = {
                    'id': int(uom_id),
                    'name': uom.get('name'),
                }
        
        return uoms_index
    
    def match_fee_product(self, product_name: str, fee_config: Dict) -> Optional[Dict]:
        """
        Match fee product name to existing products
        
        Args:
            product_name: Fee product name (e.g., "Checkout Bag Fee", "Grocery Tip")
            fee_config: Fee configuration with search_names
            
        Returns:
            Matched product dict or None
        """
        search_names = fee_config.get('search_names', [])
        product_name_lower = product_name.lower()
        
        # Try exact match with search names
        for search_name in search_names:
            if search_name.lower() in product_name_lower or product_name_lower in search_name.lower():
                # Try to match to product in database
                match = self.match_product(search_name, min_similarity=0.8)
                if match:
                    logger.debug(f"Fee product match: {product_name} → {match['full_name']}")
                    return match
        
        # Try fuzzy match
        match = self.match_product(product_name, min_similarity=0.7)
        return match
    
    def match_product_from_mapping(self, receipt_name: str) -> Optional[Dict]:
        """
        Match product using name mapping file
        Returns both product match and mapping info (which may include UoM)
        
        Args:
            receipt_name: Product name from receipt
            
        Returns:
            Product match dict with mapping_info (for UoM lookup) or None
        """
        if not self.product_mappings:
            return None
        
        mapping_info = None
        
        # Try exact match first
        if receipt_name in self.product_mappings:
            mapping_info = self.product_mappings[receipt_name]
            product_id = mapping_info.get('database_product_id')
            if product_id:
                # Find product in database
                product_match = self._get_product_by_id(product_id)
                if product_match and mapping_info:
                    product_match['mapping_info'] = mapping_info
                return product_match
        
        # Try case-insensitive match
        receipt_lower = receipt_name.lower()
        for receipt_key, mapping in self.product_mappings.items():
            if receipt_key.lower() == receipt_lower:
                mapping_info = mapping
                product_id = mapping.get('database_product_id')
                if product_id:
                    product_match = self._get_product_by_id(product_id)
                    if product_match:
                        product_match['mapping_info'] = mapping_info
                    return product_match
        
        # Try partial match
        for receipt_key, mapping in self.product_mappings.items():
            receipt_key_lower = receipt_key.lower()
            if receipt_lower in receipt_key_lower or receipt_key_lower in receipt_lower:
                mapping_info = mapping
                product_id = mapping.get('database_product_id')
                if product_id:
                    product_match = self._get_product_by_id(product_id)
                    if product_match:
                        product_match['mapping_info'] = mapping_info
                    return product_match
        
        return None
    
    def match_uom_from_mapping(self, mapping_info: Dict, receipt_uom: str) -> Optional[Dict]:
        """
        Match UoM from mapping file if specified
        
        Args:
            mapping_info: Mapping info from product_name_mapping.json
            receipt_uom: Original UoM from receipt
            
        Returns:
            UoM match dict or None
        """
        if not mapping_info:
            return None
        
        # Priority 1: Check odoo_uom (exact UoM name from database)
        odoo_uom = mapping_info.get('odoo_uom')
        if odoo_uom:
            odoo_uom_lower = odoo_uom.lower()
            # Try to find UoM by exact name match
            for name, uom_info in self.uoms_index.items():
                if name.lower() == odoo_uom_lower:
                    logger.debug(f"UoM from mapping (odoo_uom): {receipt_uom} → {uom_info['name']} (ID: {uom_info.get('id')})")
                    return uom_info
        
        # Priority 2: Check if mapping specifies UoM ID
        uom_id = mapping_info.get('database_uom_id')
        if uom_id:
            # Find UoM by ID
            for uom_info in self.uoms_index.values():
                if uom_info.get('id') == uom_id:
                    logger.debug(f"UoM from mapping (ID): {receipt_uom} → {uom_info['name']} (ID: {uom_id})")
                    return uom_info
        
        # Priority 3: Check if mapping specifies UoM name
        uom_name = mapping_info.get('database_uom_name')
        if uom_name:
            uom_name_lower = uom_name.lower()
            # Try to find UoM by name
            for name, uom_info in self.uoms_index.items():
                if name.lower() == uom_name_lower or name.startswith(uom_name_lower):
                    logger.debug(f"UoM from mapping (name): {receipt_uom} → {uom_info['name']}")
                    return uom_info
        
        # Priority 4: Check if mapping specifies receipt UoM override
        uom_override = mapping_info.get('receipt_uom_override')
        if uom_override:
            # Override the receipt UoM before matching
            logger.debug(f"UoM override from mapping: {receipt_uom} → {uom_override}")
            return self.match_uom(uom_override)
        
        return None
    
    def _get_product_by_id(self, product_id: int) -> Optional[Dict]:
        """Get product by ID from loaded data, including UoM information"""
        if not hasattr(self, 'products_index'):
            return None
        
        # Check products_index first
        for name, product in self.products_index.items():
            if product.get('product_id') == product_id:
                # Also get UoM info from db_data
                return self._enrich_product_with_uom(product)
        
        # Also check db_data for product templates
        if hasattr(self, 'db_data'):
            for prod_id, product in self.db_data.get('products', {}).items():
                if int(prod_id) == product_id:
                    template_id = product.get('product_tmpl_id')
                    if template_id and template_id in self.db_data.get('product_templates', {}):
                        template = self.db_data['product_templates'][template_id]
                        product_info = {
                            'product_id': int(prod_id),
                            'template_id': int(template_id),
                            'full_name': template.get('name'),
                        }
                        # Get UoM info from product and template
                        uom_id = product.get('uom_id')
                        uom_po_id = template.get('uom_po_id')  # Purchase UoM (preferred for PO)
                        
                        # Use purchase UoM if available, otherwise default UoM
                        final_uom_id = uom_po_id if uom_po_id else uom_id
                        
                        if final_uom_id:
                            # Find UoM in index
                            uom_info = None
                            for uom_name, uom_data in self.uoms_index.items():
                                if uom_data.get('id') == final_uom_id:
                                    uom_info = uom_data
                                    break
                            
                            if uom_info:
                                product_info['product_uom_id'] = final_uom_id
                                product_info['product_uom_name'] = uom_info.get('name', '')
                                product_info['product_uom_info'] = uom_info
                        
                        return product_info
        
        return None
    
    def _enrich_product_with_uom(self, product_info: Dict) -> Dict:
        """Enrich product info with UoM from database"""
        if not hasattr(self, 'db_data'):
            return product_info
        
        product_id = product_info.get('product_id')
        if not product_id:
            return product_info
        
        # Get product from db_data
        prod_data = self.db_data.get('products', {}).get(str(product_id))
        if not prod_data:
            return product_info
        
        template_id = prod_data.get('product_tmpl_id')
        if not template_id:
            return product_info
        
        template = self.db_data.get('product_templates', {}).get(str(template_id))
        if not template:
            return product_info
        
        # Get UoM info
        uom_id = prod_data.get('uom_id')
        uom_po_id = template.get('uom_po_id')  # Purchase UoM (preferred for PO)
        
        # Use purchase UoM if available, otherwise default UoM
        final_uom_id = uom_po_id if uom_po_id else uom_id
        
        if final_uom_id:
            # Find UoM in index
            uom_info = None
            for uom_name, uom_data in self.uoms_index.items():
                if uom_data.get('id') == final_uom_id:
                    uom_info = uom_data
                    break
            
            if uom_info:
                product_info['product_uom_id'] = final_uom_id
                product_info['product_uom_name'] = uom_info.get('name', '')
                product_info['product_uom_info'] = uom_info
        
        return product_info
    
    def match_product(self, product_name: str, min_similarity: float = 0.7) -> Optional[Dict]:
        """
        Match receipt product name to existing product
        
        Args:
            product_name: Product name from receipt
            min_similarity: Minimum similarity score (0-1)
            
        Returns:
            Matched product dict or None
        """
        product_name_lower = product_name.lower()
        
        # Try exact match first
        if product_name_lower in self.products_index:
            match = self.products_index[product_name_lower]
            if match.get('exact_match'):
                logger.debug(f"Exact match found: {product_name} → {match['full_name']}")
                return match
        
        # Try partial match (product name contains database product name or vice versa)
        best_match = None
        best_score = 0.0
        
        for db_name, product_info in self.products_index.items():
            if product_info.get('exact_match'):  # Only check full product names
                # Calculate similarity
                score = SequenceMatcher(None, product_name_lower, db_name).ratio()
                
                # Check if one contains the other
                if product_name_lower in db_name or db_name in product_name_lower:
                    score = max(score, 0.8)  # Boost for substring match
                
                if score > best_score:
                    best_score = score
                    best_match = product_info
        
        # Check if best match meets threshold
        if best_match and best_score >= min_similarity:
            logger.debug(f"Similarity match found: {product_name} → {best_match['full_name']} (score: {best_score:.2f})")
            return best_match
        
        # Try word-based matching
        receipt_words = set(word for word in product_name_lower.split() if len(word) > 2)
        for word in receipt_words:
            if word in self.products_index:
                match = self.products_index[word]
                logger.debug(f"Word-based match found: {product_name} → {match['full_name']}")
                return match
        
        logger.warning(f"No product match found for: {product_name}")
        return None
    
    def match_uom(self, purchase_uom: str) -> Optional[Dict]:
        """
        Match receipt UoM to existing UoM
        
        Args:
            purchase_uom: UoM from receipt (e.g., 'each', 'lb', 'kg')
            
        Returns:
            Matched UoM dict or None
        """
        purchase_uom_lower = purchase_uom.lower()
        
        # UoM mapping variations
        uom_variations = {
            'each': ['units', 'unit', 'each', 'piece', 'pieces'],
            'lb': ['lb', 'lbs', 'pound', 'pounds', 'pound(s)'],
            'kg': ['kg', 'kilogram', 'kilograms'],
            'oz': ['oz', 'ounce', 'ounces'],
            'g': ['g', 'gram', 'grams'],
        }
        
        # Find matching variation
        for base, variations in uom_variations.items():
            if purchase_uom_lower in variations:
                # Try to match to database UoM
                for name, uom_info in self.uoms_index.items():
                    if any(v in name for v in variations) or name in variations:
                        logger.debug(f"UoM match found: {purchase_uom} → {uom_info['name']}")
                        return uom_info
                break
        
        # Fallback: Direct match
        if purchase_uom_lower in self.uoms_index:
            return self.uoms_index[purchase_uom_lower]
        
        # Try partial match
        for name, uom_info in self.uoms_index.items():
            if purchase_uom_lower in name or name in purchase_uom_lower:
                logger.debug(f"UoM partial match: {purchase_uom} → {uom_info['name']}")
                return uom_info
        
        # Special case: Match "4-pc" variations
        if '4-pc' in purchase_uom_lower or '4pc' in purchase_uom_lower:
            for name, uom_info in self.uoms_index.items():
                if '4-pc' in name.lower() or '4pc' in name.lower() or '4-pc' in name:
                    logger.debug(f"UoM 4-pc match: {purchase_uom} → {uom_info['name']}")
                    return uom_info
        
        logger.warning(f"No UoM match found for: {purchase_uom}")
        return None
    
    def convert_fruit_weight_to_units(self, item: Dict, config: Dict = None) -> Dict:
        """
        Convert fruit weight (lb) to units (each) using 4-pc UoM
        Applies to all fruits purchased by weight, not just bananas
        Uses fruit_weight_conversion.json for conversion rates
        
        Args:
            item: Receipt item with quantity in lb
            config: Conversion configuration
            
        Returns:
            Updated item with quantity in units
        """
        if not config:
            config = {
                'convert_to_units': True,
                'use_4pc_uom': True,
            }
        
        product_name = item.get('product_name', '').lower()
        
        # Check if purchased by weight
        purchase_uom = item.get('purchase_uom', '').lower()
        weight_uoms = config.get('weight_uoms', ['lb', 'lbs', 'pound', 'pounds'])
        is_weight_based = purchase_uom in weight_uoms
        
        # Get database product name from the item (after product matching)
        # If product was already matched, use the database product name
        database_product_name = item.get('database_product_name') or item.get('product_name', '')
        
        # Check if this is a fruit (using fruit_conversions file with database product name)
        fruit_conversions = config.get('fruit_conversions', self.fruit_conversions) if config else self.fruit_conversions
        fruit_conversion = None
        
        if fruit_conversions and database_product_name:
            # Match by exact database product name (not receipt name)
            if database_product_name in fruit_conversions:
                fruit_conversion = fruit_conversions[database_product_name]
            else:
                # Try case-insensitive match
                db_name_lower = database_product_name.lower()
                for db_name, conversion in fruit_conversions.items():
                    if db_name.lower() == db_name_lower:
                        fruit_conversion = conversion
                        break
        
        is_fruit = fruit_conversion is not None
        
        if is_fruit and is_weight_based and config.get('convert_to_units', True):
            weight_lb = item.get('quantity', 0)
            items_per_lb = fruit_conversion.get('items_per_lb', 4.0)
            
            # Store original receipt values BEFORE conversion
            original_weight_lb = weight_lb
            original_unit_price_per_lb = item.get('unit_price', 0)
            original_uom = item.get('purchase_uom', 'lb')
            original_total = item.get('total_price', weight_lb * original_unit_price_per_lb)
            
            # Convert weight to units: quantity from receipt is updated
            qty_units = round(weight_lb * items_per_lb)
            
            # Recalculate unit price: unit price from receipt is updated
            # Total price remains the same, but unit price changes from per-lb to per-unit
            unit_price = original_total / qty_units if qty_units > 0 else original_unit_price_per_lb
            
            # Update BOTH quantity and unit price from receipt
            item['quantity'] = qty_units  # Updated from receipt (lb → units)
            item['unit_price'] = unit_price  # Updated from receipt (per lb → per unit)
            
            # Always use "Units" UoM (simpler approach)
            # The conversion is done by calculating qty_units from items_per_lb
            # We don't need fruit-specific UoMs like "4-pc", "8-pc", etc.
            item['purchase_uom'] = 'each'  # Use "Units" (each)
            
            # Store original receipt values for reference (for SQL comments)
            item['original_weight_lb'] = original_weight_lb
            item['original_unit_price_per_lb'] = original_unit_price_per_lb
            item['original_uom'] = original_uom
            item['converted'] = True
            
            logger.debug(f"Converted {original_weight_lb} lb to {qty_units} units using {items_per_lb} items/lb (using Units UoM)")
            logger.debug(f"Unit price updated: ${original_unit_price_per_lb:.2f}/lb → ${unit_price:.4f}/unit (total: ${original_total:.2f})")
            
            fruit_name = fruit_conversion.get('description', 'fruit')
            logger.info(f"Converted fruit ({fruit_name}): {weight_lb} lb → {qty_units} {item['purchase_uom']} @ ${unit_price:.3f} each (using {items_per_lb} items/lb)")
        
        return item
    
    # Legacy: Keep convert_banana_weight_to_units for backward compatibility
    def convert_banana_weight_to_units(self, item: Dict, config: Dict = None) -> Dict:
        """Legacy method - use convert_fruit_weight_to_units instead"""
        return self.convert_fruit_weight_to_units(item, config)
    
    def match_receipt_items(self, receipt_items: List[Dict], min_similarity: float = 0.7, config: Dict = None) -> List[Dict]:
        """
        Match all receipt items to products and UoMs
        
        Args:
            receipt_items: List of receipt items with product_name, purchase_uom, etc.
            min_similarity: Minimum similarity score for product matching
            
        Returns:
            List of matched items with product_id, uom_id, etc.
        """
        matched_items = []
        
        for item in receipt_items:
            product_name = item.get('product_name', '')
            purchase_uom = item.get('purchase_uom', 'each')
            is_fee = item.get('is_fee', False)
            
            # Match product FIRST (use mapping file first, then fuzzy match)
            # Try mapping file first
            product_match = self.match_product_from_mapping(product_name)
            
            # If not found in mapping, try fuzzy match
            if not product_match:
                if is_fee and config:
                    fee_config = config.get('FEE_PRODUCTS', {})
                    fee_type = item.get('fee_type', '')
                    
                    if fee_type in fee_config:
                        product_match = self.match_fee_product(product_name, fee_config[fee_type])
                    else:
                        product_match = self.match_product(product_name, min_similarity)
                else:
                    product_match = self.match_product(product_name, min_similarity)
            
            # Add database product name to item for fruit conversion matching
            if product_match:
                item['database_product_name'] = product_match.get('full_name', product_match.get('name', ''))
            
            # Get mapping info (includes uom_conversion_ratio)
            mapping_info = product_match.get('mapping_info', {}) if product_match else {}
            uom_conversion_ratio = mapping_info.get('uom_conversion_ratio', 1.0)
            
            # For fruits purchased by weight (lb), use uom_conversion_ratio from mapping file
            # The mapping file now has the correct ratio (e.g., 4.0 for banana = 1 lb = 4 units)
            # Only apply convert_fruit_weight_to_units if no mapping exists or ratio is 1.0
            purchase_uom_lower = purchase_uom.lower()
            is_weight_based = purchase_uom_lower in ['lb', 'lbs', 'pound', 'pounds']
            
            # Check if this product has a mapping with conversion ratio != 1.0
            has_conversion_ratio = uom_conversion_ratio != 1.0
            
            # Apply fruit conversion ONLY if:
            # 1. No mapping exists (uom_conversion_ratio == 1.0), OR
            # 2. Product is not in mapping file but is a fruit
            # If mapping exists with ratio != 1.0, use the mapping ratio instead
            if config and is_weight_based and not has_conversion_ratio:
                # Use FRUIT_WEIGHT_CONVERSION if available, otherwise use BANANA_CONVERSION
                fruit_config = config.get('FRUIT_WEIGHT_CONVERSION', config.get('BANANA_CONVERSION', {}))
                # Pass fruit_conversions from loaded mapping file
                if hasattr(self, 'fruit_conversions') and self.fruit_conversions:
                    fruit_config = fruit_config.copy()
                    fruit_config['fruit_conversions'] = self.fruit_conversions
                item = self.convert_fruit_weight_to_units(item.copy(), fruit_config)
            
            # Match UoM (fruit conversions now use "Units" / "each")
            purchase_uom_converted = item.get('purchase_uom', purchase_uom)
            
            # Apply UoM conversion ratio from mapping if specified
            # For fruits with mapping, uom_conversion_ratio is already set (e.g., 4.0 for banana)
            # Skip if already converted by convert_fruit_weight_to_units
            if uom_conversion_ratio != 1.0 and not item.get('converted', False):
                original_qty = item.get('quantity', 1.0)
                original_unit_price = item.get('unit_price', 0.0)
                original_total = item.get('total_price', original_qty * original_unit_price)
                
                # Convert quantity: receipt_qty * ratio = odoo_qty
                # Convert unit price: receipt_unit_price / ratio = odoo_unit_price
                # Total price remains the same
                converted_qty = original_qty * uom_conversion_ratio
                converted_unit_price = original_unit_price / uom_conversion_ratio if uom_conversion_ratio != 0 else original_unit_price
                
                item['quantity'] = converted_qty
                item['unit_price'] = converted_unit_price
                item['total_price'] = original_total  # Keep original total
                
                # Store original values for SQL comments
                item['original_receipt_qty'] = original_qty
                item['original_receipt_unit_price'] = original_unit_price
                item['original_receipt_uom'] = purchase_uom_converted
                item['uom_conversion_applied'] = True
                item['uom_conversion_ratio'] = uom_conversion_ratio
                
                logger.debug(f"Applied UoM conversion ratio {uom_conversion_ratio}: {original_qty} {purchase_uom_converted} @ ${original_unit_price:.2f} → {converted_qty} units @ ${converted_unit_price:.2f}")
            
            # Check if mapping file specifies UoM
            uom_match = None
            if product_match and 'mapping_info' in product_match:
                uom_match = self.match_uom_from_mapping(product_match['mapping_info'], purchase_uom_converted)
            
            # If no UoM from mapping, match from receipt
            if not uom_match:
                uom_match = self.match_uom(purchase_uom_converted)
            
            matched_item = {
                'receipt_item': item,
                'product_match': product_match,
                'uom_match': uom_match,
                'matched': product_match is not None and uom_match is not None,
            }
            
            matched_items.append(matched_item)
            
            if matched_item['matched']:
                logger.info(f"✓ Matched: {product_name} → Product ID {product_match['product_id']}, UoM ID {uom_match['id']}")
            else:
                logger.warning(f"✗ Not matched: {product_name}")
        
        return matched_items


if __name__ == '__main__':
    # Test the matcher
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    matcher = ProductMatcher('products_uom_analysis.json')
    
    # Test items
    test_items = [
        {'product_name': 'Lime 42', 'purchase_uom': 'each', 'quantity': 10.0, 'unit_price': 0.39},
        {'product_name': 'SELECT Napkins', 'purchase_uom': 'each', 'quantity': 1.0, 'unit_price': 5.99},
        {'product_name': 'Chiquita Bananas', 'purchase_uom': 'lb', 'quantity': 3.61, 'unit_price': 0.96},
    ]
    
    matches = matcher.match_receipt_items(test_items)
    for match in matches:
        print(f"\n{match['receipt_item']['product_name']}:")
        if match['product_match']:
            print(f"  Product: ID {match['product_match']['product_id']} - {match['product_match']['full_name']}")
        if match['uom_match']:
            print(f"  UoM: ID {match['uom_match']['id']} - {match['uom_match']['name']}")

