#!/usr/bin/env python3
"""
Odoo Purchase Order Matcher
Matches receipt items to Odoo purchase orders from October and updates with standard product names
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def normalize_receipt_id(receipt_id: Any) -> Optional[str]:
    """Normalize receipt ID for matching"""
    if not receipt_id:
        return None
    receipt_id = str(receipt_id).strip()
    # Remove "PO" prefix if present
    if receipt_id.upper().startswith('PO'):
        receipt_id = receipt_id[2:].strip()
    return receipt_id


def extract_english_text(value: Any) -> str:
    """Extract English text from JSON field"""
    if not value:
        return ''
    if isinstance(value, str):
        try:
            import json
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed.get('en_US') or parsed.get('en') or (list(parsed.values())[0] if parsed else '')
            return str(parsed)
        except (json.JSONDecodeError, ValueError):
            return value
    return str(value)


def get_odoo_purchase_orders() -> Dict[int, Dict[str, Any]]:
    """Get all purchase orders from October 2025 with their lines"""
    try:
        from step3_mapping.query_database import connect_to_database
        from psycopg2.extras import RealDictCursor
        
        conn = connect_to_database()
        if not conn:
            logger.warning("Could not connect to Odoo database, skipping Odoo matching")
            return {}
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get purchase orders with lines, including category information and fees
                cur.execute("""
                    SELECT 
                        po.id as po_id,
                        po.name as po_name,
                        po.partner_ref,
                        po.date_order,
                        rp.name as vendor_name,
                        pol.id as line_id,
                        pol.sequence,
                        pol.product_id,
                        pt.name::text as product_name,
                        pol.name as line_name,
                        pol.product_qty,
                        pol.price_unit,
                        pol.price_subtotal,
                        pol.product_uom,
                        uom.name::text as uom_name,
                        pc.id as category_id,
                        pc.complete_name::text as category_name,
                        pc.parent_id as category_parent_id,
                        pc_parent.id as l1_category_id,
                        pc_parent.complete_name::text as l1_category_name,
                        pol.display_type,
                        pt.type as product_type
                    FROM purchase_order po
                    LEFT JOIN res_partner rp ON po.partner_id = rp.id
                    LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
                    LEFT JOIN product_product pp ON pol.product_id = pp.id
                    LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                    LEFT JOIN uom_uom uom ON pol.product_uom = uom.id
                    LEFT JOIN product_category pc ON pt.categ_id = pc.id
                    LEFT JOIN product_category pc_parent ON pc.parent_id = pc_parent.id
                    WHERE po.date_order >= '2025-10-01' 
                      AND po.date_order < '2025-11-01'
                      AND (pol.display_type IS NULL OR pol.display_type IN ('line_section', 'line_note'))
                      AND (pt.type IN ('product', 'consu', 'service') OR pt.type IS NULL OR pol.display_type IS NOT NULL)
                    ORDER BY po.date_order, po.id, pol.sequence
                """)
                
                lines = cur.fetchall()
                
                # Group by purchase order
                orders = {}
                for line in lines:
                    po_id = line['po_id']
                    po_name = line['po_name']
                    partner_ref = line['partner_ref']
                    
                    if po_id not in orders:
                        orders[po_id] = {
                            'po_id': po_id,
                            'po_name': po_name,
                            'partner_ref': partner_ref,
                            'date_order': line['date_order'],
                            'vendor_name': line['vendor_name'],
                            'lines': []
                        }
                    
                    # Extract English text
                    product_name = extract_english_text(line['product_name'])
                    uom_name = extract_english_text(line['uom_name'])
                    category_name = extract_english_text(line['category_name'])
                    l1_category_name = extract_english_text(line['l1_category_name'])
                    
                    # Determine if this is a fee item
                    display_type = line.get('display_type')
                    line_name = line.get('line_name') or ''
                    is_fee = False
                    fee_type = ''
                    
                    if display_type in ('line_section', 'line_note'):
                        is_fee = True
                        fee_type = 'other_fee'
                    elif product_name or line_name:
                        name_lower = (product_name or line_name).lower()
                        if 'fee' in name_lower or 'tip' in name_lower or 'tax' in name_lower or 'discount' in name_lower or 'shipping' in name_lower:
                            is_fee = True
                            if 'tip' in name_lower:
                                fee_type = 'tip'
                            elif 'tax' in name_lower:
                                fee_type = 'tax'
                            elif 'bag' in name_lower:
                                fee_type = 'bag_fee'
                            elif 'service' in name_lower or 'fee' in name_lower:
                                fee_type = 'service_fee'
                            elif 'discount' in name_lower:
                                fee_type = 'discount'
                            else:
                                fee_type = 'other_fee'
                    
                    orders[po_id]['lines'].append({
                        '_line_id': line['line_id'],  # For tracking matched lines
                        'product_id': line['product_id'],
                        'product_name': product_name,  # Standard Odoo product name
                        'line_name': line['line_name'] or product_name,
                        'product_qty': float(line['product_qty']) if line['product_qty'] else 0.0,
                        'price_unit': float(line['price_unit']) if line['price_unit'] else 0.0,
                        'price_subtotal': float(line['price_subtotal']) if line['price_subtotal'] else 0.0,
                        'uom_name': uom_name,
                        'uom_id': line['product_uom'],
                        'category_id': line['category_id'],
                        'category_name': category_name,  # L2 category path
                        'l1_category_id': line['l1_category_id'],
                        'l1_category_name': l1_category_name,  # L1 category path
                        'is_fee': is_fee,
                        'fee_type': fee_type,
                        'display_type': display_type,
                    })
                
                logger.info(f"Loaded {len(orders)} purchase orders from October 2025 with {sum(len(o['lines']) for o in orders.values())} lines")
                return orders
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Could not load Odoo purchase orders: {e}", exc_info=True)
        return {}


def match_po_to_receipt(po: Dict[str, Any], receipts: Dict[str, Dict[str, Any]]) -> Optional[tuple]:
    """Match a purchase order to a receipt"""
    po_name = po['po_name']
    partner_ref = po['partner_ref']
    vendor_name = po['vendor_name']
    
    candidates = []
    
    for receipt_id, receipt in receipts.items():
        # Strategy 1: Exact match on receipt_id
        if normalize_receipt_id(receipt_id) == normalize_receipt_id(po_name):
            candidates.append((receipt_id, receipt, 1.0, 'exact_id'))
        
        # Strategy 2: Match on partner_ref
        if partner_ref and normalize_receipt_id(partner_ref) == normalize_receipt_id(receipt_id):
            candidates.append((receipt_id, receipt, 0.9, 'partner_ref'))
        
        # Strategy 3: Match on order_id or receipt_number
        receipt_order_id = receipt.get('order_id') or receipt.get('receipt_number')
        if receipt_order_id:
            if normalize_receipt_id(str(receipt_order_id)) == normalize_receipt_id(po_name):
                candidates.append((receipt_id, receipt, 0.9, 'order_id'))
            if partner_ref and normalize_receipt_id(str(receipt_order_id)) == normalize_receipt_id(partner_ref):
                candidates.append((receipt_id, receipt, 0.85, 'order_id_partner_ref'))
        
        # Strategy 4: Match on vendor and date
        receipt_vendor = receipt.get('vendor') or receipt.get('vendor_name', '')
        receipt_date = receipt.get('transaction_date') or receipt.get('invoice_date') or receipt.get('order_date')
        po_date = po['date_order'].date() if hasattr(po['date_order'], 'date') else po['date_order']
        
        if receipt_vendor and vendor_name and receipt_vendor.upper() in vendor_name.upper():
            if receipt_date:
                try:
                    if isinstance(receipt_date, str):
                        receipt_date_obj = datetime.strptime(receipt_date[:10], '%Y-%m-%d').date()
                    else:
                        receipt_date_obj = receipt_date.date() if hasattr(receipt_date, 'date') else receipt_date
                    
                    if isinstance(po_date, str):
                        po_date_obj = datetime.strptime(po_date[:10], '%Y-%m-%d').date()
                    else:
                        po_date_obj = po_date.date() if hasattr(po_date, 'date') else po_date
                    
                    if receipt_date_obj == po_date_obj:
                        candidates.append((receipt_id, receipt, 0.8, 'vendor_date'))
                except (ValueError, AttributeError):
                    pass
    
    if candidates:
        # Sort by score (highest first)
        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates[0]
    
    return None


def extract_l1_code_from_odoo_path(category_path: str) -> tuple:
    """Extract L1 code (A01, A02, etc.) from Odoo category path"""
    if not category_path:
        return 'A99', ''
    
    import re
    # Match pattern: A## - Name (may contain slashes, stop before next /C## or end of string)
    # Try multiple patterns to handle different path formats
    patterns = [
        r'A(\d{2})\s*-\s*([^/]+(?:/[^/]+)*?)(?:\s*/\s*C\d|$)',  # Original pattern
        r'A(\d{2})\s*-\s*([^/]+)',  # Simpler pattern: A## - Name
        r'/A(\d{2})\s*-\s*([^/]+)',  # Pattern with leading slash
    ]
    
    for pattern in patterns:
        match = re.search(pattern, category_path)
        if match:
            code = f"A{match.group(1)}"
            name = match.group(2).strip()
            # Clean up name (remove trailing slashes or extra parts)
            name = re.sub(r'\s*/\s*.*$', '', name)
            return code, name
    
    # For any other categories (batch, saleable, etc.), mark as ignored
    return 'A99', ''


def extract_l2_code_from_odoo_path(category_path: str) -> tuple:
    """Extract L2 code (C01, C02, etc.) from Odoo category path"""
    if not category_path:
        return 'C99', ''
    
    import re
    # Match pattern: C## - Name (capture everything after C## - until end)
    match = re.search(r'C(\d{2,3})\s*-\s*(.+)$', category_path)
    if match:
        code = f"C{match.group(1)}"
        name = match.group(2).strip()
        return code, name
    
    # For categories without Cxx codes, mark as ignored
    return 'C99', ''


def normalize_name_for_matching(name: str) -> str:
    """Normalize product name for better matching"""
    if not name:
        return ''
    # Convert to lowercase
    name = name.lower().strip()
    # Remove common punctuation and special characters
    import re
    name = re.sub(r'[^\w\s]', ' ', name)
    # Remove extra whitespace
    name = re.sub(r'\s+', ' ', name)
    
    # Remove common quantity/size patterns that might differ
    # e.g., "2 lbs", "500ml", "13 oz", etc.
    name = re.sub(r'\d+\s*(?:lb|lbs|oz|fl\s*oz|ml|l|kg|g|ct|count|pcs?|pkgs?)\b', '', name)
    # Remove package/container words
    name = re.sub(r'\b(package|pack|pkg|container|bottle|can|box|bag|jar)\b', '', name)
    # Remove extra whitespace again
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def calculate_name_similarity(name1: str, name2: str) -> float:
    """Calculate similarity score between two product names"""
    if not name1 or not name2:
        return 0.0
    
    norm1 = normalize_name_for_matching(name1)
    norm2 = normalize_name_for_matching(name2)
    
    if not norm1 or not norm2:
        return 0.0
    
    # Exact match
    if norm1 == norm2:
        return 1.0
    
    # One contains the other (after normalization)
    if norm1 in norm2 or norm2 in norm1:
        return 0.9
    
    # Word-based matching
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    # Remove very short words (1-2 chars) as they're often noise
    words1 = {w for w in words1 if len(w) > 2}
    words2 = {w for w in words2 if len(w) > 2}
    
    if not words1 or not words2:
        return 0.0
    
    # Calculate Jaccard similarity (intersection over union)
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    if union == 0:
        return 0.0
    
    jaccard = intersection / union
    
    # Boost score if significant words match
    if intersection >= min(2, len(words1), len(words2)):
        jaccard = min(0.95, jaccard * 1.3)
    
    # Special case: if all significant words from shorter name are in longer name
    shorter_words = words1 if len(words1) <= len(words2) else words2
    longer_words = words2 if len(words1) <= len(words2) else words1
    if shorter_words and all(w in longer_words for w in shorter_words):
        jaccard = max(jaccard, 0.85)
    
    return jaccard


def match_items_by_product(odoo_lines: List[Dict[str, Any]], receipt_items: List[Dict[str, Any]]) -> List[tuple]:
    """
    Match receipt items to Odoo purchase order lines.
    Primary strategy: Match by total price (orders are identical, converted unit price should be the same).
    Secondary strategy: Match by unit price, then by product name similarity.
    
    Iterates through receipt items to ensure each gets matched to the best available Odoo line.
    """
    matches = []
    
    # Tolerance for price matching (5% difference allowed)
    PRICE_TOLERANCE = 0.05
    
    # Track which Odoo lines have been matched
    matched_odoo_lines = set()
    
    for receipt_item in receipt_items:
        # Skip summary items (but include fees)
        if receipt_item.get('is_summary', False):
            continue
        
        # Skip items with total_price = 0 (free or returned items) - but allow fees with 0 price
        receipt_total_price = float(receipt_item.get('total_price', 0) or receipt_item.get('extended_amount', 0) or 0)
        is_fee = receipt_item.get('is_fee', False)
        if receipt_total_price == 0 and not is_fee:
            continue
        
        # Check if already matched
        if receipt_item.get('_odoo_matched'):
            continue
        
        receipt_product_name = (receipt_item.get('product_name') or 
                              receipt_item.get('display_name') or 
                              receipt_item.get('canonical_name') or '')
        receipt_unit_price = float(receipt_item.get('unit_price', 0) or 0)
        receipt_qty = float(receipt_item.get('quantity', 0) or 0)
        receipt_product_id = receipt_item.get('odoo_product_id')
        
        best_odoo_line = None
        best_score = 0
        best_method = None
        
        for odoo_line in odoo_lines:
            odoo_line_id = odoo_line.get('_line_id') or id(odoo_line)
            
            # Skip if this Odoo line is already matched (unless it's a product ID match)
            if odoo_line_id in matched_odoo_lines:
                # Still allow product ID matches to override
                if receipt_product_id and receipt_product_id == odoo_line.get('product_id'):
                    pass  # Allow override
                else:
                    continue
            
            odoo_product_id = odoo_line['product_id']
            odoo_product_name = odoo_line['product_name']
            odoo_line_name = odoo_line.get('line_name') or ''
            odoo_price_unit = float(odoo_line.get('price_unit', 0) or 0)
            odoo_price_subtotal = float(odoo_line.get('price_subtotal', 0) or 0)
            odoo_qty = float(odoo_line.get('product_qty', 0) or 0)
            
            # Strategy 1: Exact product ID match (highest priority)
            if receipt_product_id and receipt_product_id == odoo_product_id:
                best_odoo_line = odoo_line
                best_score = 1.0
                best_method = 'product_id'
                break
            
            # Check if this is a fee match (both should be fees or both should not be fees)
            odoo_is_fee = odoo_line.get('is_fee', False)
            if is_fee != odoo_is_fee:
                # Don't match fees to non-fees or vice versa
                continue
            
            # Strategy 2: Match by total price (primary - orders are identical)
            # Only match if both have non-zero prices (receipt items with 0 are free/returned, skip those)
            # For fees, allow matching even with 0 price
            if (odoo_price_subtotal != 0 and receipt_total_price != 0) or (is_fee and odoo_is_fee):
                if odoo_price_subtotal != 0 and receipt_total_price != 0:
                    total_diff = abs(odoo_price_subtotal - receipt_total_price) / max(abs(odoo_price_subtotal), abs(receipt_total_price), 0.01)
                    if total_diff <= PRICE_TOLERANCE:
                        score = 0.98 - (total_diff * 10)  # Very high score for exact total match
                        if score > best_score:
                            best_odoo_line = odoo_line
                            best_score = score
                            best_method = 'total_price'
                elif is_fee and odoo_is_fee and odoo_price_subtotal == receipt_total_price:
                    # Exact match for fees (including 0)
                    score = 0.95
                    if score > best_score:
                        best_odoo_line = odoo_line
                        best_score = score
                        best_method = 'fee_exact'
            
            # Strategy 3: Match by unit price (when totals don't match or Odoo price is 0)
            # Odoo price = 0 means it's a new product, still try to match by name
            if odoo_price_unit > 0 and receipt_unit_price > 0:
                price_diff = abs(odoo_price_unit - receipt_unit_price) / max(odoo_price_unit, receipt_unit_price)
                if price_diff <= PRICE_TOLERANCE:
                    score = 0.95 - (price_diff * 10)
                    if score > best_score:
                        best_odoo_line = odoo_line
                        best_score = score
                        best_method = 'unit_price'
            
            # Strategy 3b: Match by name when Odoo price is 0 (new product, never purchased before)
            # This allows matching new products that haven't been purchased yet
            if odoo_price_subtotal == 0 and odoo_price_unit == 0 and receipt_total_price > 0:
                # Only match by name for zero-price Odoo items
                if receipt_product_name and odoo_product_name:
                    score = calculate_name_similarity(receipt_product_name, odoo_product_name)
                    if score > 0.7:  # Higher threshold for name-only matches on zero-price items
                        score = score * 0.85  # Slightly lower than price matches
                        if score > best_score:
                            best_odoo_line = odoo_line
                            best_score = score
                            best_method = 'name_zero_price'
            
            # Strategy 4: Match by product name using similarity (fallback)
            if receipt_product_name and odoo_product_name:
                score = calculate_name_similarity(receipt_product_name, odoo_product_name)
                score = score * 0.6  # Lower priority than price
                if score > best_score:
                    best_odoo_line = odoo_line
                    best_score = score
                    best_method = 'name_similarity'
            
            # Strategy 5: Match by line_name
            if odoo_line_name and receipt_product_name:
                score = calculate_name_similarity(receipt_product_name, odoo_line_name)
                score = score * 0.6
                if score > best_score:
                    best_odoo_line = odoo_line
                    best_score = score
                    best_method = 'line_name'
        
        if best_odoo_line and best_score > 0.3:
            matches.append((best_odoo_line, receipt_item, best_score))
            receipt_item['_odoo_matched'] = True
            receipt_item['_match_method'] = best_method
            # Mark Odoo line as matched
            odoo_line_id = best_odoo_line.get('_line_id') or id(best_odoo_line)
            matched_odoo_lines.add(odoo_line_id)
    
    return matches


def update_receipt_with_odoo_data(receipt: Dict[str, Any], odoo_po: Dict[str, Any]) -> int:
    """Update receipt items with Odoo purchase order data, including categories"""
    updated_count = 0
    
    receipt_items = receipt.get('items', [])
    odoo_lines = odoo_po['lines']
    
    # Match items
    matches = match_items_by_product(odoo_lines, receipt_items)
    
    for odoo_line, receipt_item, score in matches:
        # Update with Odoo standard product name
        receipt_item['standard_name'] = odoo_line['product_name']
        receipt_item['odoo_product_id'] = odoo_line['product_id']
        
        # For fees, update fee_type from Odoo
        if odoo_line.get('is_fee', False):
            receipt_item['is_fee'] = True
            if odoo_line.get('fee_type'):
                receipt_item['fee_type'] = odoo_line['fee_type']
        
        # Extract and set L1 and L2 categories from Odoo category paths
        l1_path = odoo_line.get('l1_category_name', '')
        l2_path = odoo_line.get('category_name', '')
        
        l1_code, l1_name = extract_l1_code_from_odoo_path(l1_path)
        l2_code, l2_name = extract_l2_code_from_odoo_path(l2_path)
        
        # If L1 extraction failed but L2 succeeded, try extracting L1 from L2 path
        # (L2 path contains full path: "All / Expenses / A02 - COGS / C21 - Name")
        if l1_code == 'A99' and l2_code != 'C99' and l2_path:
            l1_code_from_l2, l1_name_from_l2 = extract_l1_code_from_odoo_path(l2_path)
            if l1_code_from_l2 != 'A99':
                l1_code = l1_code_from_l2
                l1_name = l1_name_from_l2
        
        # If L1 is still A99 but L2 is valid, derive L1 from L2 using standard mapping
        if l1_code == 'A99' and l2_code != 'C99':
            # Standard L2 to L1 mappings
            l2_to_l1_map = {
                'C80': 'A08',  # Taxes & Fees
                'C82': 'A08',  # Tips/Gratuities -> Taxes & Fees
                'C85': 'A08',  # Tips -> Taxes & Fees
                'C90': 'A09',  # Shipping/Delivery
            }
            derived_l1 = l2_to_l1_map.get(l2_code)
            if derived_l1:
                l1_code = derived_l1
                # Try to get L1 name from taxonomy or use a default
                l1_name = 'Taxes & Fees' if derived_l1 == 'A08' else 'Shipping/Delivery' if derived_l1 == 'A09' else ''
        
        # Set categories directly from Odoo (don't reclassify)
        receipt_item['l1_category'] = l1_code
        receipt_item['l1_category_name'] = l1_name
        receipt_item['l2_category'] = l2_code
        receipt_item['l2_category_name'] = l2_name
        
        # Mark as matched to Odoo so category classifier will skip it
        receipt_item['odoo_category_matched'] = True
        receipt_item['category_source'] = 'odoo'
        
        updated_count += 1
    
    return updated_count


def add_missing_fees_from_odoo(receipt: Dict[str, Any], odoo_po: Dict[str, Any]) -> int:
    """
    Add fees from Odoo purchase order that are missing in the receipt
    
    Returns:
        Number of fees added
    """
    added_count = 0
    receipt_items = receipt.get('items', [])
    odoo_lines = odoo_po['lines']
    
    # Get existing fee names from receipt (for deduplication)
    existing_fee_names = set()
    existing_fee_totals = {}
    for item in receipt_items:
        if item.get('is_fee', False):
            fee_name = item.get('product_name') or item.get('standard_name') or ''
            fee_total = float(item.get('total_price', 0) or 0)
            existing_fee_names.add(fee_name.lower().strip())
            if fee_name.lower().strip() not in existing_fee_totals:
                existing_fee_totals[fee_name.lower().strip()] = []
            existing_fee_totals[fee_name.lower().strip()].append(fee_total)
    
    # Check each Odoo fee line
    for odoo_line in odoo_lines:
        if not odoo_line.get('is_fee', False):
            continue
        
        odoo_fee_name = odoo_line.get('product_name') or odoo_line.get('line_name') or ''
        odoo_fee_total = float(odoo_line.get('price_subtotal', 0) or 0)
        odoo_fee_type = odoo_line.get('fee_type', 'other_fee')
        
        # Check if this fee already exists in receipt
        fee_name_lower = odoo_fee_name.lower().strip()
        fee_exists = False
        
        if fee_name_lower in existing_fee_names:
            # Check if total matches (within tolerance)
            if fee_name_lower in existing_fee_totals:
                for existing_total in existing_fee_totals[fee_name_lower]:
                    if abs(existing_total - odoo_fee_total) < 0.01:
                        fee_exists = True
                        break
        
        if not fee_exists:
            # Add missing fee to receipt
            fee_item = {
                'product_name': odoo_fee_name,
                'standard_name': odoo_fee_name,
                'quantity': 1.0,
                'purchase_uom': 'each',
                'unit_price': odoo_fee_total,
                'total_price': odoo_fee_total,
                'is_fee': True,
                'fee_type': odoo_fee_type,
                'odoo_product_id': odoo_line.get('product_id'),
                'odoo_category_matched': True,
                'category_source': 'odoo',
                'l1_category': '',
                'l1_category_name': '',
                'l2_category': '',
                'l2_category_name': '',
            }
            receipt_items.append(fee_item)
            existing_fee_names.add(fee_name_lower)
            added_count += 1
            logger.debug(f"Added missing fee from Odoo: {odoo_fee_name} = ${odoo_fee_total:.2f}")
    
    return added_count


def match_receipts_to_odoo(receipts_data: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """
    Match all receipts to Odoo purchase orders and update with standard names.
    Matches items across ALL purchase orders, not just matched receipts.
    
    Args:
        receipts_data: Dictionary of receipt data
        
    Returns:
        Dictionary with matching statistics
    """
    stats = {
        'total_receipts': len(receipts_data),
        'matched_receipts': 0,
        'total_items': 0,
        'matched_items': 0
    }
    
    # Load Odoo purchase orders
    odoo_orders = get_odoo_purchase_orders()
    if not odoo_orders:
        logger.warning("No Odoo purchase orders found, skipping matching")
        return stats
    
    # Collect all items from all receipts
    all_receipt_items = []
    for receipt_id, receipt in receipts_data.items():
        for item in receipt.get('items', []):
            if not item.get('is_fee', False) and not item.get('is_summary', False):
                item['_receipt_id'] = receipt_id
                item['_receipt'] = receipt
                all_receipt_items.append(item)
                stats['total_items'] += 1
    
    # Collect all lines from all purchase orders
    all_odoo_lines = []
    for po_id, odoo_po in odoo_orders.items():
        for line in odoo_po.get('lines', []):
            line['_po_id'] = po_id
            line['_po'] = odoo_po
            all_odoo_lines.append(line)
    
    logger.info(f"Matching {len(all_receipt_items)} items against {len(all_odoo_lines)} Odoo purchase order lines")
    
    # Match items across all purchase orders
    matches = match_items_by_product(all_odoo_lines, all_receipt_items)
    
    # Update matched items
    for odoo_line, receipt_item, score in matches:
        # Update with Odoo standard product name
        receipt_item['standard_name'] = odoo_line['product_name']
        receipt_item['odoo_product_id'] = odoo_line['product_id']
        
        # For fees, update fee_type from Odoo
        if odoo_line.get('is_fee', False):
            receipt_item['is_fee'] = True
            if odoo_line.get('fee_type'):
                receipt_item['fee_type'] = odoo_line['fee_type']
        
        # Extract and set L1 and L2 categories from Odoo category paths
        l1_path = odoo_line.get('l1_category_name', '')
        l2_path = odoo_line.get('category_name', '')
        
        l1_code, l1_name = extract_l1_code_from_odoo_path(l1_path)
        l2_code, l2_name = extract_l2_code_from_odoo_path(l2_path)
        
        # If L1 extraction failed but L2 succeeded, try extracting L1 from L2 path
        # (L2 path contains full path: "All / Expenses / A02 - COGS / C21 - Name")
        if l1_code == 'A99' and l2_code != 'C99' and l2_path:
            l1_code_from_l2, l1_name_from_l2 = extract_l1_code_from_odoo_path(l2_path)
            if l1_code_from_l2 != 'A99':
                l1_code = l1_code_from_l2
                l1_name = l1_name_from_l2
        
        # If L1 is still A99 but L2 is valid, derive L1 from L2 using standard mapping
        if l1_code == 'A99' and l2_code != 'C99':
            # Standard L2 to L1 mappings
            l2_to_l1_map = {
                'C80': 'A08',  # Taxes & Fees
                'C82': 'A08',  # Tips/Gratuities -> Taxes & Fees
                'C85': 'A08',  # Tips -> Taxes & Fees
                'C90': 'A09',  # Shipping/Delivery
            }
            derived_l1 = l2_to_l1_map.get(l2_code)
            if derived_l1:
                l1_code = derived_l1
                # Try to get L1 name from taxonomy or use a default
                l1_name = 'Taxes & Fees' if derived_l1 == 'A08' else 'Shipping/Delivery' if derived_l1 == 'A09' else ''
        
        # Set categories directly from Odoo (don't reclassify)
        receipt_item['l1_category'] = l1_code
        receipt_item['l1_category_name'] = l1_name
        receipt_item['l2_category'] = l2_code
        receipt_item['l2_category_name'] = l2_name
        
        # Mark as matched to Odoo so category classifier will skip it
        receipt_item['odoo_category_matched'] = True
        receipt_item['category_source'] = 'odoo'
        
        stats['matched_items'] += 1
    
    # Add missing fees from Odoo purchase orders to matched receipts
    fees_added = 0
    for po_id, odoo_po in odoo_orders.items():
        match_result = match_po_to_receipt(odoo_po, receipts_data)
        if match_result:
            receipt_id, receipt, score, method = match_result
            added = add_missing_fees_from_odoo(receipt, odoo_po)
            fees_added += added
            if added > 0:
                logger.debug(f"Added {added} missing fees from Odoo PO {odoo_po['po_name']} to receipt {receipt_id}")
    
    stats['fees_added'] = fees_added
    
    # Also match receipts to purchase orders for reference
    for po_id, odoo_po in odoo_orders.items():
        match_result = match_po_to_receipt(odoo_po, receipts_data)
        if match_result:
            stats['matched_receipts'] += 1
    
    # Clean up temporary matching flags
    for receipt in receipts_data.values():
        for item in receipt.get('items', []):
            item.pop('_odoo_matched', None)
            item.pop('_receipt_id', None)
            item.pop('_receipt', None)
    
    logger.info(f"Odoo matching: {stats['matched_receipts']}/{stats['total_receipts']} receipts matched, {stats['matched_items']}/{stats['total_items']} items updated, {stats.get('fees_added', 0)} fees added")
    
    return stats

