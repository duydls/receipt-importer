#!/usr/bin/env python3
"""
Rule Executor - Execute Step 2 rule stages
Transforms items through each stage in processing order
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from difflib import SequenceMatcher

from .query_database import connect_to_database

logger = logging.getLogger(__name__)


def execute_inputs_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 01_inputs.yaml stage - normalize fields and add metadata"""
    logger.info("Executing inputs stage...")
    
    stage_config = config.get('inputs', {})
    normalize_fields = stage_config.get('normalize_fields', {})
    add_metadata = stage_config.get('add_metadata', {})
    
    transformed_items = []
    
    for item in items:
        new_item = item.copy()
        
        # Normalize field names
        for old_field, new_field in normalize_fields.items():
            if old_field in new_item:
                new_item[new_field] = new_item.pop(old_field)
        
        # Add metadata
        for key, value in add_metadata.items():
            if key not in new_item:
                new_item[key] = value
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in inputs stage")
    return transformed_items


def execute_vendor_match_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 02_vendor_match.yaml stage - normalize vendors"""
    logger.info("Executing vendor_match stage...")
    
    stage_config = config.get('vendor_match', {})
    rules = stage_config.get('rules', [])
    
    transformed_items = []
    
    for item in items:
        new_item = item.copy()
        receipt_data = new_item.get('receipt_data', {})
        source_type = new_item.get('source_type', receipt_data.get('source_type', ''))
        
        # Build searchable text
        receipt_text = ' '.join([
            receipt_data.get('vendor', ''),
            receipt_data.get('filename', ''),
            new_item.get('source_file', ''),
            str(receipt_data.get('receipt_text', ''))
        ]).lower()
        
        detected_vendor_name = receipt_data.get('vendor', '').lower()
        source_file = new_item.get('source_file', '').lower()
        
        # Try rules in order
        matched = False
        for rule in rules:
            rule_name = rule.get('name', '')
            when_any = rule.get('when_any', [])
            when = rule.get('when')
            and_also = rule.get('and_also', [])
            set_fields = rule.get('set', {})
            
            # Check conditions
            matches = False
            
            if when_any:
                # Match if ANY condition is true
                for condition in when_any:
                    if check_condition(condition, source_type, receipt_text, detected_vendor_name, source_file):
                        matches = True
                        break
            elif when:
                # Single condition
                matches = check_condition(when, source_type, receipt_text, detected_vendor_name, source_file)
            
            # Check 'and_also' conditions
            if matches and and_also:
                for condition in and_also:
                    if not check_condition(condition, source_type, receipt_text, detected_vendor_name, source_file):
                        matches = False
                        break
            
            if matches:
                # Apply set fields
                for key, value in set_fields.items():
                    if key == 'review_reasons' and isinstance(value, list):
                        if 'review_reasons' not in new_item:
                            new_item['review_reasons'] = []
                        new_item['review_reasons'].extend(value)
                    else:
                        new_item[key] = value
                matched = True
                logger.debug(f"Vendor match: {rule_name} → {set_fields.get('vendor_code', 'N/A')}")
                break
        
        if not matched:
            logger.warning(f"No vendor match for item: {new_item.get('product_name', 'unknown')}")
        
        # IC-OTHER vendor inference: try to infer actual vendor after initial matching
        if new_item.get('vendor_code') == 'IC-OTHER':
            # Check PDF header text for vendor names
            receipt_text_lower = receipt_text.lower()
            inferred_vendor = None
            
            # Check header text for vendor names
            if 'jewel' in receipt_text_lower:
                inferred_vendor = 'JEWEL'
            elif 'aldi' in receipt_text_lower:
                inferred_vendor = 'IC-ALDI'
            elif 'mariano' in receipt_text_lower:
                inferred_vendor = 'IC-MARIANOS'
            elif 'costco' in receipt_text_lower:
                inferred_vendor = 'IC-COSTCO'
            
            # Check item names for store-exclusive SKUs (Costco pack sizes, Aldi house brands, Jewel dairy)
            if not inferred_vendor:
                product_name_lower = new_item.get('product_name', '').lower()
                canonical_key_lower = new_item.get('canonical_product_key', '').lower()
                
                # Costco indicators: pack sizes (e.g., "6-pack", large quantities)
                if any(indicator in product_name_lower or indicator in canonical_key_lower 
                       for indicator in ['6-pack', '12-pack', 'bulk', 'kirkland']):
                    inferred_vendor = 'IC-COSTCO'
                # Aldi indicators: house brands (e.g., "friendly farms", "specially selected", "simply nature")
                elif any(brand in product_name_lower or brand in canonical_key_lower 
                         for brand in ['friendly farms', 'specially selected', 'simply nature']):
                    inferred_vendor = 'IC-ALDI'
                # Jewel indicators: dairy section patterns
                elif any(pattern in product_name_lower or pattern in canonical_key_lower 
                         for pattern in ['jewel', 'mariano']):
                    inferred_vendor = 'JEWEL'
            
            if inferred_vendor:
                logger.info(f"Inferred vendor for IC-OTHER: {inferred_vendor} (from receipt: {receipt_data.get('filename', 'unknown')})")
                new_item['vendor_code'] = inferred_vendor
                # Update vendor_name based on inferred code
                vendor_names = {
                    'JEWEL': 'Jewel-Osco',
                    'IC-ALDI': 'IC-Aldi',
                    'IC-MARIANOS': 'IC-Mariano\'s',
                    'IC-COSTCO': 'IC-Costco'
                }
                if inferred_vendor in vendor_names:
                    new_item['vendor_name'] = vendor_names[inferred_vendor]
                
                # Clear review reasons if we successfully inferred
                if 'review_reasons' in new_item:
                    new_item['review_reasons'] = [
                        r for r in new_item['review_reasons'] 
                        if r != 'Instacart order without clear underlying store'
                    ]
                    if not new_item['review_reasons']:
                        new_item.pop('review_reasons', None)
                        new_item['needs_review'] = False
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in vendor_match stage")
    return transformed_items


def check_condition(condition: str, source_type: str, receipt_text: str, detected_vendor_name: str, source_file: str) -> bool:
    """Check if a condition string matches"""
    if ' == ' in condition:
        left, right = condition.split(' == ', 1)
        left = left.strip().strip('"\'')
        right = right.strip().strip('"\'')
        
        if left == 'source_type':
            return source_type.lower() == right.lower()
    
    if ' ILIKE ' in condition:
        left, pattern = condition.split(' ILIKE ', 1)
        left = left.strip()
        pattern = pattern.strip().strip('"\'%')
        
        if left == 'receipt_text':
            return pattern.lower() in receipt_text
        elif left == 'source_file':
            return pattern.lower() in source_file
        elif left == 'detected_vendor_name':
            return pattern.lower() in detected_vendor_name
    
    if ' ILIKE "%' in condition:
        # Handle ILIKE patterns with wildcards
        parts = condition.split(' ILIKE ', 1)
        if len(parts) == 2:
            field = parts[0].strip()
            pattern = parts[1].strip().strip('"\'%')
            
            if field == 'receipt_text':
                return pattern.lower() in receipt_text
            elif field == 'source_file':
                return pattern.lower() in source_file
            elif field == 'detected_vendor_name':
                return pattern.lower() in detected_vendor_name
    
    return False


def execute_product_canonicalization_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 03_product_canonicalization.yaml stage - canonicalize product names"""
    logger.info("Executing product_canonicalization stage...")
    
    stage_config = config.get('product_canonicalization', {})
    normalize_config = stage_config.get('normalize', {})
    category_rules = stage_config.get('category_rules', [])
    size_rules = stage_config.get('size_rules', [])
    compose_config = stage_config.get('compose', {})
    
    transformed_items = []
    
    for item in items:
        new_item = item.copy()
        product_name = new_item.get('product_name', '')
        
        # Normalize
        normalized_name = product_name
        if normalize_config.get('lowercase'):
            normalized_name = normalized_name.lower()
        
        if normalize_config.get('strip_punctuation'):
            normalized_name = re.sub(r'[^\w\s]', ' ', normalized_name)
        
        # Remove store words
        for word in normalize_config.get('remove_store_words', []):
            normalized_name = re.sub(r'\b' + re.escape(word.lower()) + r'\b', '', normalized_name, flags=re.IGNORECASE)
        
        # Remove brand words
        for word in normalize_config.get('remove_brand_words', []):
            normalized_name = re.sub(r'\b' + re.escape(word.lower()) + r'\b', '', normalized_name, flags=re.IGNORECASE)
        
        if normalize_config.get('collapse_spaces'):
            normalized_name = re.sub(r'\s+', ' ', normalized_name).strip()
        
        # Apply category rules
        canonical_name = None
        for rule in category_rules:
            keywords = rule.get('keywords', [])
            for keyword in keywords:
                if keyword.lower() in normalized_name:
                    canonical_name = rule.get('canonical_name')
                    break
            if canonical_name:
                break
        
        # Apply size rules
        canonical_size = None
        canonical_uom = None
        for rule in size_rules:
            matches = rule.get('match', [])
            for match_pattern in matches:
                if match_pattern.lower() in normalized_name:
                    canonical_size = rule.get('canonical_size')
                    canonical_uom = rule.get('canonical_uom')
                    break
            if canonical_size:
                break
        
        # Check vendor-specific canonical mapping (e.g., RD short codes)
        vendor_code = new_item.get('vendor_code', '')
        vendor_specific_maps = stage_config.get('vendor_specific_canonical_map', {})
        canonical_key = None
        
        if vendor_code and vendor_code in vendor_specific_maps:
            vendor_map = vendor_specific_maps[vendor_code]
            # Check if normalized_name matches any key in vendor map
            for pattern, mapped_value in vendor_map.items():
                # Match pattern (handle variations like "1/2" vs "1 2")
                pattern_normalized = re.sub(r'[^\w\s]', ' ', pattern.lower()).strip()
                pattern_normalized = re.sub(r'\s+', ' ', pattern_normalized)
                if pattern_normalized == normalized_name or pattern.lower() in normalized_name:
                    canonical_key = mapped_value
                    logger.debug(f"Matched RD code: {pattern} → {canonical_key}")
                    break
        
        # Compose canonical key if not set by vendor-specific mapping
        if not canonical_key:
            if compose_config and canonical_name:
                pattern = compose_config.get('pattern', '{{ canonical_name }}')
                if canonical_size and '{{ canonical_size }}' in pattern:
                    canonical_key = pattern.replace('{{ canonical_name }}', canonical_name).replace('{{ canonical_size }}', canonical_size)
                else:
                    canonical_key = compose_config.get('fallback_pattern', '{{ canonical_name }}').replace('{{ canonical_name }}', canonical_name)
            else:
                canonical_key = canonical_name if canonical_name else normalized_name
        
        new_item['canonical_product_key'] = canonical_key
        # Store raw name for Costco organic handling
        if not new_item.get('raw_product_name'):
            new_item['raw_product_name'] = product_name
        if canonical_name:
            new_item['canonical_name'] = canonical_name
        if canonical_size:
            new_item['canonical_size'] = canonical_size
        if canonical_uom:
            new_item['canonical_uom'] = canonical_uom
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in product_canonicalization stage")
    return transformed_items


def execute_db_match_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 04_db_match.yaml stage - match products to database"""
    logger.info("Executing db_match stage...")
    
    stage_config = config.get('db_match', {})
    product_matcher = context.get('product_matcher')
    
    if not product_matcher:
        logger.error("ProductMatcher not found in context")
        return items
    
    # Connect to database if needed
    db_conn = context.get('db_conn')
    if not db_conn and stage_config.get('connection') == 'use_config':
        logger.info("Connecting to database...")
        db_conn = connect_to_database()
        if db_conn:
            context['db_conn'] = db_conn
            logger.info("✓ Connected to database")
        else:
            logger.warning("Failed to connect to database, continuing with ProductMatcher only")
    
    # Load database products if we have a connection
    db_products = {}
    if db_conn:
        try:
            from psycopg2.extras import RealDictCursor
            queries = stage_config.get('queries', {})
            
            with db_conn.cursor(cursor_factory=RealDictCursor) as cur:
                if 'products' in queries:
                    cur.execute(queries['products'])
                    for row in cur.fetchall():
                        product_id = row['product_id']
                        # Handle JSON field for product_name
                        product_name = row.get('product_name', '')
                        if isinstance(product_name, dict):
                            product_name = product_name.get('en_US', '') or product_name.get(list(product_name.keys())[0] if product_name else '', '')
                        
                        db_products[product_id] = {
                            'product_id': product_id,
                            'product_name': product_name,
                            'default_code': row.get('default_code'),
                            'barcode': row.get('barcode'),
                            'default_uom_id': row.get('product_uom_id'),
                            'purchase_ok': row.get('purchase_ok', False),
                            'sale_ok': row.get('sale_ok', False),
                            'product_type': row.get('product_type', ''),
                            'product_categ_id': row.get('product_categ_id')
                        }
            logger.info(f"Loaded {len(db_products)} products from database")
        except Exception as e:
            logger.error(f"Error querying database products: {e}", exc_info=True)
    
    # Get matching order from config
    match_order = stage_config.get('product_match_order', [
        'by_canonical_key',
        'by_name_similarity'
    ])
    similarity_threshold = stage_config.get('name_similarity_threshold', 0.80)
    
    transformed_items = []
    
    for item in items:
        new_item = item.copy()
        product_name = new_item.get('product_name', '')
        canonical_key = new_item.get('canonical_product_key', product_name)
        vendor_code = new_item.get('vendor_code', '')
        raw_product_name = new_item.get('raw_product_name', product_name)
        
        # Store original matched product_id if exists
        if 'product_id' in new_item and new_item['product_id']:
            new_item['original_matched_product_id'] = new_item['product_id']
        
        # Costco organic abbreviation handling: strip "org" or "organic" prefix and re-run matching
        # Pattern: ORG ..., ORGANIC ... from folder Costco/
        stripped_name = None
        stripped_canonical = None
        if vendor_code == 'COSTCO' and not new_item.get('product_id'):
            # Check if product_name or canonical_key starts with "org" or "organic"
            if product_name.upper().startswith('ORG '):
                stripped_name = product_name[4:].strip()
            elif product_name.upper().startswith('ORGANIC '):
                stripped_name = product_name[8:].strip()
            
            if canonical_key.lower().startswith('org '):
                stripped_canonical = canonical_key[4:].strip()
            elif canonical_key.lower().startswith('organic '):
                stripped_canonical = canonical_key[8:].strip()
            
            if stripped_name:
                logger.debug(f"Costco organic detected: {product_name} → {stripped_name}")
        
        # Try matching using ProductMatcher according to match_order
        product_match = None
        
        for match_method in match_order:
            if match_method == 'if_has_odoo_product_id_from_local':
                # Check if item already has product_id from local data
                if 'odoo_product_id' in new_item and new_item['odoo_product_id']:
                    product_id = new_item['odoo_product_id']
                    # Verify it exists in database
                    if product_id in db_products:
                        product_match = {'product_id': product_id}
                        break
            
            elif match_method == 'by_canonical_key':
                # First try stripped canonical key for Costco organic items
                if stripped_canonical:
                    product_match = product_matcher.match_product(stripped_canonical, min_similarity=similarity_threshold)
                    if product_match:
                        logger.info(f"Matched Costco organic (stripped): {product_name} → {stripped_canonical} → product_id {product_match.get('product_id')}")
                        break
                # Then try original canonical key
                if canonical_key and not product_match:
                    product_match = product_matcher.match_product(canonical_key, min_similarity=similarity_threshold)
                    if product_match:
                        break
            
            elif match_method == 'by_barcode':
                barcode = new_item.get('barcode')
                if barcode:
                    # Search in db_products by barcode
                    for pid, db_prod in db_products.items():
                        if db_prod.get('barcode') == barcode:
                            product_match = {'product_id': pid}
                            break
                    if product_match:
                        break
            
            elif match_method == 'by_default_code':
                default_code = new_item.get('default_code')
                if default_code:
                    # Search in db_products by default_code
                    for pid, db_prod in db_products.items():
                        if db_prod.get('default_code') == default_code:
                            product_match = {'product_id': pid}
                            break
                    if product_match:
                        break
            
            elif match_method == 'by_name_similarity':
                # First try stripped name for Costco organic items
                if stripped_name:
                    product_match = product_matcher.match_product(stripped_name, min_similarity=similarity_threshold)
                    if product_match:
                        logger.info(f"Matched Costco organic (stripped name): {product_name} → {stripped_name} → product_id {product_match.get('product_id')}")
                        break
                # Then try original product_name
                if product_name and product_name != canonical_key and not product_match:
                    product_match = product_matcher.match_product(product_name, min_similarity=similarity_threshold)
                    if product_match:
                        break
                elif product_name and not product_match:
                    product_match = product_matcher.match_product(product_name, min_similarity=similarity_threshold)
                    if product_match:
                        break
        
        if product_match:
            product_id = product_match.get('product_id')
            new_item['product_id'] = product_id
            matched_name = product_match.get('full_name', product_match.get('name', product_name))
            new_item['product_name'] = matched_name
            
            # For Costco organic items, if we matched after stripping, clear review reasons
            if stripped_name or stripped_canonical:
                # Remove "No product match found" review reason if it exists
                if 'review_reasons' in new_item:
                    new_item['review_reasons'] = [
                        r for r in new_item['review_reasons'] 
                        if not r.startswith('No product match found')
                    ]
                    if not new_item['review_reasons']:
                        new_item['needs_review'] = False
                        new_item.pop('review_reasons', None)
                # Keep original text in raw_name field
                if not new_item.get('raw_product_name'):
                    new_item['raw_product_name'] = raw_product_name
            
            # Enrich with database product info if available
            if product_id and product_id in db_products:
                db_product = db_products[product_id]
                new_item['product_categ_id'] = db_product.get('product_categ_id')
                new_item['purchase_ok'] = db_product.get('purchase_ok')
                new_item['sale_ok'] = db_product.get('sale_ok')
                new_item['product_type'] = db_product.get('product_type')
                if db_product.get('default_uom_id'):
                    new_item['product_uom_id'] = db_product.get('default_uom_id')
            
            # Add UoM info from ProductMatcher
            if 'product_uom_info' in product_match:
                uom_info = product_match['product_uom_info']
                if not new_item.get('product_uom_id'):
                    new_item['product_uom_id'] = uom_info.get('id')
                new_item['product_uom_name'] = uom_info.get('name')
            
            # Check purchase priority rules
            purchase_priority = stage_config.get('purchase_priority', {})
            if purchase_priority.get('enabled'):
                purchase_ok = new_item.get('purchase_ok')
                sale_ok = new_item.get('sale_ok')
                
                rules = purchase_priority.get('rules', [])
                for rule in rules:
                    if rule.get('prefer_if') == 'purchase_ok = true':
                        if purchase_ok:
                            break  # OK, no review needed
                    elif rule.get('else_if') == 'sale_ok = true':
                        if sale_ok:
                            if rule.get('set_flag'):
                                new_item['needs_review'] = True
                                if 'review_reasons' not in new_item:
                                    new_item['review_reasons'] = []
                                if rule.get('review_reason'):
                                    new_item['review_reasons'].append(rule['review_reason'])
                            break
                    elif rule.get('else'):
                        # Final fallback
                        if rule.get('set_flag'):
                            new_item['needs_review'] = True
                            if 'review_reasons' not in new_item:
                                new_item['review_reasons'] = []
                            if rule.get('review_reason'):
                                new_item['review_reasons'].append(rule['review_reason'])
            
            # Post-match category check
            category_check = stage_config.get('post_match_category_check', {})
            if category_check.get('enabled'):
                # Category checks would go here if we loaded category data
                # For now, just log that we'd check categories
                pass
        else:
            logger.warning(f"No product match for: {product_name} (canonical: {canonical_key})")
            new_item['needs_review'] = True
            if 'review_reasons' not in new_item:
                new_item['review_reasons'] = []
            new_item['review_reasons'].append(f"No product match found for: {product_name}")
            
            # For RD items, if vendor-specific mapping was used but still not found, add specific reason
            if vendor_code == 'RD' and new_item.get('canonical_product_key', '').startswith('rd_'):
                # Check if RD code was mapped but still not found in database
                if not any(r.startswith('RD code not in') for r in new_item.get('review_reasons', [])):
                    new_item['review_reasons'].append("RD code not in rd_item_map.csv")
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in db_match stage")
    return transformed_items


def execute_usage_probe_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 05_usage_probe.yaml stage - probe product usage in system"""
    logger.info("Executing usage_probe stage...")
    
    stage_config = config.get('usage_probe', {})
    db_conn = context.get('db_conn')
    
    if not db_conn:
        logger.warning("No database connection for usage_probe stage, skipping")
        return items
    
    # Query usage data
    usage_data = {}
    queries = stage_config.get('queries', {})
    time_window = stage_config.get('time_window', {}).get('days_back', 180)
    
    try:
        from psycopg2.extras import RealDictCursor
        with db_conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Sales usage
            if 'sales_usage' in queries:
                query = queries['sales_usage'].replace('180', str(time_window))
                cur.execute(query)
                for row in cur.fetchall():
                    product_id = row['product_id']
                    if product_id not in usage_data:
                        usage_data[product_id] = {}
                    usage_data[product_id]['so_line_count'] = row['so_line_count']
                    usage_data[product_id]['so_qty'] = float(row['so_qty']) if row['so_qty'] else 0
            
            # Inventory usage
            if 'inventory_usage' in queries:
                query = queries['inventory_usage'].replace('180', str(time_window))
                cur.execute(query)
                for row in cur.fetchall():
                    product_id = row['product_id']
                    if product_id not in usage_data:
                        usage_data[product_id] = {}
                    usage_data[product_id]['move_count'] = row['move_count']
                    usage_data[product_id]['move_qty'] = float(row['move_qty']) if row['move_qty'] else 0
            
            # Manufacturing usage
            if 'manufacturing_usage' in queries:
                cur.execute(queries['manufacturing_usage'])
                for row in cur.fetchall():
                    product_id = row['product_id']
                    if product_id not in usage_data:
                        usage_data[product_id] = {}
                    usage_data[product_id]['bom_line_count'] = row['bom_line_count']
    except Exception as e:
        logger.error(f"Error querying usage data: {e}")
    
    # Apply inference rules
    infer_rules = stage_config.get('infer_role', [])
    transformed_items = []
    
    for item in items:
        new_item = item.copy()
        product_id = new_item.get('product_id')
        
        if product_id and product_id in usage_data:
            usage = usage_data[product_id]
            
            # Apply inference rules
            for rule in infer_rules:
                rule_name = rule.get('name', '')
                when = rule.get('when', {})
                set_fields = rule.get('set', {})
                
                matches = True
                for key, condition in when.items():
                    if key in usage:
                        value = usage[key]
                        if '>' in condition:
                            threshold = float(condition.split('>')[1].strip())
                            if not (value > threshold):
                                matches = False
                                break
                
                if matches:
                    for key, value in set_fields.items():
                        new_item[key] = value
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in usage_probe stage")
    return transformed_items


def execute_uom_mapping_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 06_uom.yaml stage - map UoMs and validate category consistency"""
    logger.info("Executing uom_mapping stage...")
    
    stage_config = config.get('uom_mapping', {})
    product_matcher = context.get('product_matcher')
    db_conn = context.get('db_conn')
    
    receipt_uom_field = stage_config.get('receipt_uom_field', 'receipt_uom_raw')
    normalize_config = stage_config.get('normalize', {})
    alias_config = normalize_config.get('alias', {})
    
    # Load UoM categories from database if available
    uom_categories = {}  # {uom_id: {'category_id': ..., 'category_name': ...}}
    if db_conn:
        try:
            from psycopg2.extras import RealDictCursor
            from .query_database import get_uom_categories
            uom_categories = get_uom_categories(db_conn)
            logger.info(f"Loaded {len(uom_categories)} UoM category mappings from database")
        except Exception as e:
            logger.warning(f"Could not load UoM categories from database: {e}")
    
    transformed_items = []
    
    for item in items:
        new_item = item.copy()
        
        # Get receipt UoM from various possible fields
        receipt_uom = ''
        if receipt_uom_field in new_item:
            receipt_uom = str(new_item.get(receipt_uom_field, ''))
        else:
            # Try common field names
            receipt_uom = str(new_item.get('purchase_uom', new_item.get('uom', new_item.get('unit', ''))))
        
        receipt_uom = receipt_uom.lower().strip() if receipt_uom else ''
        
        # Normalize receipt UoM
        normalized_uom = receipt_uom
        if normalize_config.get('lowercase'):
            normalized_uom = normalized_uom.lower()
        if normalize_config.get('strip_spaces'):
            normalized_uom = normalized_uom.strip()
        
        # Apply aliases
        for canonical, aliases in alias_config.items():
            if normalized_uom in aliases:
                normalized_uom = canonical
                break
        
        # Get product UoM from product_match
        product_uom_id = new_item.get('product_uom_id')
        
        # Store original receipt UoM (what we parsed from receipt)
        receipt_uom_id = None
        receipt_uom_category_id = None
        receipt_uom_category_name = None
        
        # Try to match UoM using ProductMatcher
        uom_match = None
        if product_matcher:
            uom_match = product_matcher.match_uom(normalized_uom)
        
        if uom_match:
            receipt_uom_id = uom_match.get('id')
            new_item['final_uom_id'] = receipt_uom_id
            new_item['final_uom_name'] = uom_match.get('name')
            # Get receipt UoM category from database
            if receipt_uom_id and receipt_uom_id in uom_categories:
                receipt_uom_category_id = uom_categories[receipt_uom_id].get('category_id')
                receipt_uom_category_name = uom_categories[receipt_uom_id].get('category_name')
        elif product_uom_id:
            # Fallback to product default UoM
            new_item['final_uom_id'] = product_uom_id
            new_item['uom_conflict'] = True
            new_item['needs_review'] = True
            if 'review_reasons' not in new_item:
                new_item['review_reasons'] = []
            new_item['review_reasons'].append(stage_config.get('if_category_mismatch', {}).get('add_review_reason', 'UoM category mismatch'))
        else:
            new_item['needs_review'] = True
            if 'review_reasons' not in new_item:
                new_item['review_reasons'] = []
            new_item['review_reasons'].append("No UoM could be mapped")
        
        # Get product UoM category
        product_uom_category_id = None
        product_uom_category_name = None
        if product_uom_id and product_uom_id in uom_categories:
            product_uom_category_id = uom_categories[product_uom_id].get('category_id')
            product_uom_category_name = uom_categories[product_uom_id].get('category_name')
        
        # Add UoM category info to item
        new_item['receipt_uom_id'] = receipt_uom_id
        new_item['receipt_uom_category_id'] = receipt_uom_category_id
        new_item['receipt_uom_category_name'] = receipt_uom_category_name
        new_item['product_uom_category_id'] = product_uom_category_id
        new_item['product_uom_category_name'] = product_uom_category_name
        
        # Check for UoM category mismatch
        uom_category_mismatch = False
        if receipt_uom_category_id and product_uom_category_id:
            if receipt_uom_category_id != product_uom_category_id:
                uom_category_mismatch = True
                new_item['uom_category_mismatch'] = True
                new_item['needs_review'] = True
                if 'review_reasons' not in new_item:
                    new_item['review_reasons'] = []
                if not any('UoM category mismatch' in r for r in new_item['review_reasons']):
                    new_item['review_reasons'].append("UoM category mismatch: receipt UoM category != product default UoM category")
            else:
                new_item['uom_category_mismatch'] = False
        else:
            new_item['uom_category_mismatch'] = None  # Unknown
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in uom_mapping stage")
    return transformed_items


def execute_enrichment_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 07_enrichment.yaml stage - enrich items with additional data"""
    logger.info("Executing enrichment stage...")
    
    stage_config = config.get('enrichment', {})
    defaults = stage_config.get('defaults', {})
    unit_price_prefer = stage_config.get('unit_price', {}).get('prefer_order', ['unit_price'])
    quantity_prefer = stage_config.get('quantity', {}).get('prefer_order', ['quantity'])
    line_total_config = stage_config.get('line_total', {})
    preserve_original = stage_config.get('preserve_original_fields', True)
    
    transformed_items = []
    
    for item in items:
        new_item = item.copy() if preserve_original else {}
        if preserve_original:
            # Already copied
            pass
        else:
            # Copy only needed fields
            new_item.update(item)
        
        # Set unit_price from preferred field
        for field in unit_price_prefer:
            if field in item and item[field] is not None:
                new_item['unit_price'] = item[field]
                break
        
        # Set quantity from preferred field
        for field in quantity_prefer:
            if field in item and item[field] is not None:
                new_item['quantity'] = item[field]
                break
        
        # Recompute line_total if missing
        if line_total_config.get('recompute_if_missing') and not new_item.get('line_total'):
            unit_price = new_item.get('unit_price', 0)
            quantity = new_item.get('quantity', 0)
            if unit_price and quantity:
                new_item['line_total'] = float(unit_price) * float(quantity)
        
        # Apply defaults
        for key, value in defaults.items():
            if key not in new_item or new_item[key] is None:
                new_item[key] = value
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in enrichment stage")
    return transformed_items


def execute_bom_protection_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 08_bom_protection.yaml stage - check BoM protection"""
    logger.info("Executing bom_protection stage...")
    
    stage_config = config.get('bom_protection', {})
    db_conn = context.get('db_conn')
    
    # Query BoM data
    products_in_bom = set()
    if db_conn and 'db_queries' in stage_config:
        try:
            from psycopg2.extras import RealDictCursor
            queries = stage_config.get('db_queries', {})
            
            with db_conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get products used in BoMs
                if 'bom_lines' in queries:
                    cur.execute(queries['bom_lines'])
                    for row in cur.fetchall():
                        product_id = row['component_product_id']
                        if product_id:
                            products_in_bom.add(product_id)
        except Exception as e:
            logger.error(f"Error querying BoM data: {e}")
    else:
        logger.warning("No database connection for bom_protection stage, skipping BoM checks")
    
    context['products_in_bom'] = products_in_bom
    
    # Apply BoM protection rules
    rules = stage_config.get('rules', [])
    transformed_items = []
    
    for item in items:
        new_item = item.copy()
        product_id = new_item.get('product_id')
        original_product_id = new_item.get('original_matched_product_id', product_id)
        
        # Check if product is in BoM
        if product_id and product_id in products_in_bom:
            new_item['bom_protected'] = True
        
        # Apply rules
        for rule in rules:
            rule_name = rule.get('name', '')
            when = rule.get('when', {})
            action = rule.get('action', {})
            
            matches = True
            if 'this.product_id IN (products_used_in_bom)' in str(when):
                if product_id not in products_in_bom:
                    matches = False
            elif 'this.original_matched_product_id IN (products_used_in_bom)' in str(when):
                if original_product_id not in products_in_bom:
                    matches = False
                if matches and product_id != original_product_id:
                    # Force original product ID
                    if 'force_product_id' in action:
                        new_item['product_id'] = original_product_id
                    if action.get('needs_review'):
                        new_item['needs_review'] = True
                        if 'review_reasons' not in new_item:
                            new_item['review_reasons'] = []
                        if action.get('add_reason'):
                            new_item['review_reasons'].append(action['add_reason'])
            
            if matches:
                for key, value in action.items():
                    if key not in ['force_product_id', 'needs_review', 'add_reason']:
                        new_item[key] = value
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in bom_protection stage")
    return transformed_items


def execute_validation_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 09_validation.yaml stage - final validation checks"""
    logger.info("Executing validation stage...")
    
    stage_config = config.get('validation', {})
    checks = stage_config.get('checks', [])
    
    transformed_items = []
    
    for item in items:
        new_item = item.copy()
        
        # Apply validation checks
        for check in checks:
            condition = check.get('if', '')
            mark_review = check.get('mark_review', False)
            add_reason = check.get('add_reason', '')
            
            # Parse condition
            if condition.endswith(' is null'):
                field = condition.replace(' is null', '').strip()
                if not new_item.get(field):
                    if mark_review:
                        new_item['needs_review'] = True
                        if 'review_reasons' not in new_item:
                            new_item['review_reasons'] = []
                        if add_reason:
                            new_item['review_reasons'].append(add_reason)
            
            elif ' <= 0' in condition:
                field = condition.replace(' <= 0', '').strip()
                if new_item.get(field, 0) <= 0:
                    if mark_review:
                        new_item['needs_review'] = True
                        if 'review_reasons' not in new_item:
                            new_item['review_reasons'] = []
                        if add_reason:
                            new_item['review_reasons'].append(add_reason)
            
            elif condition.endswith(' == true'):
                field = condition.replace(' == true', '').strip()
                if new_item.get(field) is True:
                    if mark_review:
                        new_item['needs_review'] = True
                        if 'review_reasons' not in new_item:
                            new_item['review_reasons'] = []
                        if add_reason:
                            new_item['review_reasons'].append(add_reason)
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in validation stage")
    return transformed_items


def execute_outputs_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 10_outputs.yaml stage - prepare final output"""
    logger.info("Executing outputs stage...")
    
    stage_config = config.get('outputs', {})
    mapped_items_config = stage_config.get('mapped_items', {})
    schema = mapped_items_config.get('schema', {})
    
    # Filter and format items according to schema
    required_fields = schema.get('required', [])
    optional_fields = schema.get('optional', [])
    all_fields = required_fields + optional_fields
    
    transformed_items = []
    
    for item in items:
        new_item = {}
        
        # Include required fields
        for field in required_fields:
            if field in item:
                new_item[field] = item[field]
            else:
                logger.warning(f"Required field {field} missing in item: {item.get('product_name', 'unknown')}")
        
        # Include optional fields if present
        for field in optional_fields:
            if field in item:
                new_item[field] = item[field]
        
        transformed_items.append(new_item)
    
    logger.info(f"Processed {len(transformed_items)} items in outputs stage")
    return transformed_items


def execute_quality_report_stage(items: List[Dict[str, Any]], config: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute 11_quality_report.yaml stage - generate quality report"""
    logger.info("Executing quality_report stage...")
    
    stage_config = config.get('quality_report', {})
    output_dir = context.get('output_dir')
    
    if not output_dir:
        logger.warning("No output directory in context for quality_report stage")
        return items
    
    # Generate HTML report
    html_config = stage_config.get('html', {})
    if html_config:
        html_path = html_config.get('path', 'output/step2_output/step2_quality_report.html')
        html_file = Path(html_path).name
        html_output = output_dir / html_file
        
        try:
            generate_html_quality_report(items, stage_config, html_output)
            logger.info(f"✓ Generated HTML quality report: {html_output}")
        except Exception as e:
            logger.error(f"Error generating HTML quality report: {e}", exc_info=True)
    
    # Generate CSV report
    csv_config = stage_config.get('csv', {})
    if csv_config:
        csv_path = csv_config.get('path', 'output/step2_output/step2_quality_report.csv')
        csv_file = Path(csv_path).name
        csv_output = output_dir / csv_file
        
        try:
            generate_csv_quality_report(items, csv_config, csv_output)
            logger.info(f"✓ Generated CSV quality report: {csv_output}")
        except Exception as e:
            logger.error(f"Error generating CSV quality report: {e}", exc_info=True)
    
    # This stage doesn't transform items, just generates reports
    return items


def generate_html_quality_report(items: List[Dict[str, Any]], config: Dict[str, Any], output_file: Path) -> None:
    """Generate HTML quality report"""
    views = config.get('views', [])
    html_config = config.get('html', {})
    
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Step 2 Quality Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; margin: 20px 0; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #4CAF50; color: white; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .summary { background-color: #f9f9f9; padding: 15px; margin: 20px 0; border: 1px solid #ddd; }
        .needs-review { background-color: #fff3cd; }
        .ready { background-color: #d4edda; }
    </style>
</head>
<body>
    <h1>Step 2 Quality Report</h1>
"""
    
    # Add summary
    if html_config.get('show_summary'):
        html_content += '<div class="summary"><h2>Summary</h2>\n'
        total_lines = len(items)
        ready_lines = len([i for i in items if not i.get('needs_review', False)])
        review_lines = len([i for i in items if i.get('needs_review', False)])
        bom_lines = len([i for i in items if i.get('bom_protected', False)])
        
        html_content += f'<p><strong>Total lines:</strong> {total_lines}</p>\n'
        html_content += f'<p><strong>Lines OK:</strong> {ready_lines}</p>\n'
        html_content += f'<p><strong>Lines need review:</strong> {review_lines}</p>\n'
        html_content += f'<p><strong>BoM-protected lines:</strong> {bom_lines}</p>\n'
        html_content += '</div>\n'
    
    # Add views
    for view in views:
        view_name = view.get('name', '')
        view_title = view.get('title', view_name)
        filter_config = view.get('filter', {})
        columns = view.get('columns', [])
        
        # Filter items
        filtered_items = items
        if filter_config:
            for key, value in filter_config.items():
                filtered_items = [i for i in filtered_items if i.get(key) == value]
        
        if not filtered_items:
            continue
        
        html_content += f'<h2>{view_title}</h2>\n'
        html_content += '<table>\n<tr>'
        for col in columns:
            html_content += f'<th>{col}</th>'
        html_content += '</tr>\n'
        
        for item in filtered_items:
            html_content += '<tr>'
            for col in columns:
                value = item.get(col, '')
                if isinstance(value, list):
                    value = ', '.join(str(v) for v in value)
                html_content += f'<td>{value}</td>'
            html_content += '</tr>\n'
        
        html_content += '</table>\n'
    
    html_content += '</body>\n</html>'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)


def generate_csv_quality_report(items: List[Dict[str, Any]], config: Dict[str, Any], output_file: Path) -> None:
    """Generate CSV quality report"""
    import csv
    
    columns = config.get('columns', [])
    
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        
        for item in items:
            row = {}
            for col in columns:
                value = item.get(col, '')
                if isinstance(value, list):
                    value = '; '.join(str(v) for v in value)
                row[col] = value
            writer.writerow(row)


# Mapping of stage keys to execution functions
STAGE_EXECUTORS = {
    'inputs': execute_inputs_stage,
    'vendor_match': execute_vendor_match_stage,
    'product_canonicalization': execute_product_canonicalization_stage,
    'db_match': execute_db_match_stage,
    'usage_probe': execute_usage_probe_stage,
    'uom_mapping': execute_uom_mapping_stage,
    'enrichment': execute_enrichment_stage,
    'bom_protection': execute_bom_protection_stage,
    'validation': execute_validation_stage,
    'outputs': execute_outputs_stage,
    'quality_report': execute_quality_report_stage,
}


def execute_stage(items: List[Dict[str, Any]], rule_file: str, rule_loader, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Execute a single rule stage
    
    Args:
        items: List of items to process
        rule_file: Name of rule file (e.g., '01_inputs.yaml')
        rule_loader: RuleLoader instance
        context: Shared context dictionary
        
    Returns:
        Transformed list of items
    """
    rule_data = rule_loader.get_rule(rule_file)
    if not rule_data:
        logger.warning(f"Rule file {rule_file} not found")
        return items
    
    # Detect top-level key (skip meta and internal keys)
    top_level_key = None
    for key in rule_data.keys():
        if key != 'meta' and not key.startswith('_'):
            top_level_key = key
            break
    
    if not top_level_key:
        logger.warning(f"No top-level key found in {rule_file}, available keys: {list(rule_data.keys())}")
        return items
    
    # Get stage config
    stage_config = rule_data[top_level_key]
    
    logger.info(f"Detected stage key: {top_level_key}")
    
    # Get executor function
    executor = STAGE_EXECUTORS.get(top_level_key)
    if not executor:
        logger.warning(f"No executor found for stage: {top_level_key}")
        logger.warning(f"Available executors: {list(STAGE_EXECUTORS.keys())}")
        return items
    
    # Execute stage
    try:
        transformed_items = executor(items, {top_level_key: stage_config}, context)
        return transformed_items
    except Exception as e:
        logger.error(f"Error executing stage {top_level_key} from {rule_file}: {e}", exc_info=True)
        return items

