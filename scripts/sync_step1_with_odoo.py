#!/usr/bin/env python3
"""
Sync Step 1 extracted data with Odoo purchase order information
Updates quantities, UoMs, and standard names from Odoo database
"""

import sys
import json
from pathlib import Path
from datetime import datetime
import pandas as pd
import re

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def extract_english_text(value):
    """Extract English text from JSON field"""
    if not value or pd.isna(value):
        return ''
    if isinstance(value, str):
        try:
            import json as json_lib
            parsed = json_lib.loads(value)
            if isinstance(parsed, dict):
                return parsed.get('en_US') or parsed.get('en') or (list(parsed.values())[0] if parsed else '')
            return str(parsed)
        except (json_lib.JSONDecodeError, ValueError):
            return value
    return str(value)


def normalize_receipt_id(receipt_id):
    """Normalize receipt ID for matching"""
    if not receipt_id:
        return None
    # Remove common prefixes/suffixes
    receipt_id = str(receipt_id).strip()
    # Remove "PO" prefix if present
    if receipt_id.upper().startswith('PO'):
        receipt_id = receipt_id[2:].strip()
    return receipt_id




def get_odoo_purchase_orders():
    """Get all purchase orders from October 2025 with their lines"""
    conn = connect_to_database()
    if not conn:
        raise Exception("Could not connect to database")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get purchase orders with lines, including category information
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
                    pc_parent.complete_name::text as l1_category_name
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
                  AND pol.display_type IS NULL
                  AND (pt.type IN ('product', 'consu') OR pt.type IS NULL)
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

                orders[po_id]['lines'].append({
                    'product_id': line['product_id'],
                    'product_name': product_name,
                    'line_name': line['line_name'],
                    'product_qty': float(line['product_qty']) if line['product_qty'] else 0.0,
                    'price_unit': float(line['price_unit']) if line['price_unit'] else 0.0,
                    'price_subtotal': float(line['price_subtotal']) if line['price_subtotal'] else 0.0,
                    'uom_name': uom_name,
                    'uom_id': line['product_uom'],
                    'category_id': line['category_id'],
                    'category_name': category_name,
                    'l1_category_id': line['l1_category_id'],
                    'l1_category_name': l1_category_name,
                    'l1_category_code': l1_category_name,  # Use L1 name directly as code
                    'l2_category_code': category_name  # Use L2 name directly as code
                })
            
            return orders
    finally:
        conn.close()


def load_step1_data():
    """Load all Step 1 extracted data"""
    step1_output_dir = Path('data/step1_output')
    all_receipts = {}
    
    # Load from all source groups
    source_groups = ['localgrocery_based', 'instacart_based', 'amazon_based', 
                     'bbi_based', 'wismettac_based', 'webstaurantstore_based']
    
    for group in source_groups:
        data_file = step1_output_dir / group / 'extracted_data.json'
        if data_file.exists():
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Add source_group to each receipt if not present
                for receipt_id, receipt in data.items():
                    if 'source_group' not in receipt:
                        receipt['source_group'] = group
                all_receipts.update(data)
                print(f"  Loaded {len(data)} receipts from {group}")
    
    return all_receipts


def match_po_to_receipt(po, receipts):
    """Match a purchase order to a receipt"""
    po_name = po['po_name']
    partner_ref = po['partner_ref']
    vendor_name = po['vendor_name']
    
    # Try multiple matching strategies
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
            # Check if dates are close (within 1 day)
            try:
                if receipt_date:
                    if isinstance(receipt_date, str):
                        # Try to parse date
                        for fmt in ['%Y-%m-%d', '%m/%d/%y', '%m/%d/%Y', '%Y-%m-%dT%H:%M:%S']:
                            try:
                                receipt_date_parsed = datetime.strptime(receipt_date.split()[0], fmt).date()
                                if abs((receipt_date_parsed - po_date).days) <= 1:
                                    candidates.append((receipt_id, receipt, 0.7, 'vendor_date'))
                                    break
                            except:
                                continue
            except:
                pass
    
    if candidates:
        # Sort by confidence and return best match
        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates[0]
    
    return None


def match_items_by_product(odoo_lines, receipt_items):
    """Match Odoo purchase order lines to receipt items by product"""
    matches = []
    
    # First pass: exact product ID matches
    for odoo_line in odoo_lines:
        odoo_product_id = odoo_line['product_id']
        odoo_product_name = odoo_line['product_name'].lower().strip()
        odoo_line_name = odoo_line['line_name'].lower().strip() if odoo_line.get('line_name') else ''
        
        best_match = None
        best_score = 0
        
        for receipt_item in receipt_items:
            # Check if already matched
            if receipt_item.get('_matched'):
                continue
            
            receipt_product_id = receipt_item.get('odoo_product_id')
            receipt_product_name = (receipt_item.get('product_name') or receipt_item.get('standard_name') or '').lower().strip()
            receipt_display_name = (receipt_item.get('display_name') or receipt_item.get('canonical_name') or '').lower().strip()
            
            # Strategy 1: Exact product ID match (highest priority)
            if receipt_product_id and receipt_product_id == odoo_product_id:
                best_match = receipt_item
                best_score = 1.0
                break
            
            # Strategy 2: Match by standard_name or product_name
            if receipt_product_name and odoo_product_name:
                # Exact match
                if receipt_product_name == odoo_product_name:
                    if best_score < 0.95:
                        best_match = receipt_item
                        best_score = 0.95
                # Contains match
                elif odoo_product_name in receipt_product_name or receipt_product_name in odoo_product_name:
                    score = min(len(odoo_product_name), len(receipt_product_name)) / max(len(odoo_product_name), len(receipt_product_name))
                    if score > best_score:
                        best_match = receipt_item
                        best_score = score
            
            # Strategy 3: Match by line_name (Odoo product name in purchase order)
            if odoo_line_name and receipt_product_name:
                if odoo_line_name in receipt_product_name or receipt_product_name in odoo_line_name:
                    score = 0.8
                    if score > best_score:
                        best_match = receipt_item
                        best_score = score
        
        if best_match and best_score > 0.5:
            matches.append((odoo_line, best_match, best_score))
            best_match['_matched'] = True
    
    return matches


def extract_l1_code_from_odoo_path(category_path):
    """Extract L1 code (A01, A02, etc.) from Odoo category path"""
    if not category_path:
        return 'A99', 'Unknown'

    # Only accept categories with proper Axx codes
    # Match pattern: A## - Name (may contain slashes, stop before next /C## or end of string)
    import re
    match = re.search(r'A(\d{2})\s*-\s*([^/]+(?:/[^/]+)*?)(?:\s*/\s*C\d|$)', category_path)
    if match:
        code = f"A{match.group(1)}"
        name = match.group(2).strip()
        return code, name

    # For any other categories (batch, saleable, etc.), mark as ignored
    return 'A99', 'Non-A Series (Ignored)'

def extract_l2_code_from_odoo_path(category_path):
    """Extract L2 code (C01, C02, etc.) from Odoo category path"""
    if not category_path:
        return 'C99', 'Unknown'

    # Only accept categories with proper Cxx codes
    # Match pattern: C## - Name (capture everything after C## - until end)
    import re
    match = re.search(r'C(\d{2,3})\s*-\s*(.+)$', category_path)
    if match:
        code = f"C{match.group(1)}"
        name = match.group(2).strip()
        return code, name

    # For categories without Cxx codes, mark as ignored
    return 'C99', 'Non-C Series (Ignored)'

def update_receipt_with_odoo_data(receipt, odoo_po):
    """Update receipt items with Odoo purchase order data"""
    updated_count = 0

    receipt_items = receipt.get('items', [])
    odoo_lines = odoo_po['lines']

    # Match items
    matches = match_items_by_product(odoo_lines, receipt_items)

    # Track which Odoo lines have been matched
    matched_odoo_lines = set()

    for odoo_line, receipt_item, score in matches:
        matched_odoo_lines.add(odoo_line['product_id'])

        # Keep original values for reference (BEFORE updating)
        if 'quantity_original' not in receipt_item:
            receipt_item['quantity_original'] = receipt_item.get('quantity', 0)
        if 'purchase_uom_original' not in receipt_item:
            receipt_item['purchase_uom_original'] = receipt_item.get('purchase_uom', '')
        if 'unit_price_original' not in receipt_item:
            receipt_item['unit_price_original'] = receipt_item.get('unit_price', 0)
        if 'total_price_original' not in receipt_item:
            receipt_item['total_price_original'] = receipt_item.get('total_price', 0)

        # Update with Odoo data (use Odoo as source of truth)
        receipt_item['standard_name'] = odoo_line['product_name']
        receipt_item['odoo_product_id'] = odoo_line['product_id']

        # Update quantities and UoM from Odoo
        receipt_item['quantity'] = float(odoo_line['product_qty'])
        receipt_item['purchase_uom'] = odoo_line['uom_name']
        receipt_item['unit_price'] = float(odoo_line['price_unit'])
        receipt_item['total_price'] = float(odoo_line['price_subtotal'])

        # Extract L1 and L2 codes from Odoo category paths
        l1_path = odoo_line.get('l1_category_name', '')
        l2_path = odoo_line.get('category_name', '')

        l1_code, l1_name = extract_l1_code_from_odoo_path(l1_path)
        l2_code, l2_name = extract_l2_code_from_odoo_path(l2_path)

        receipt_item['l1_category'] = l1_code
        receipt_item['l1_category_name'] = l1_name
        receipt_item['l2_category'] = l2_code
        receipt_item['l2_category_name'] = l2_name

        # Store Odoo category info for reference
        if odoo_line.get('l1_category_name'):
            receipt_item['odoo_l1_name'] = odoo_line['l1_category_name']
        if odoo_line.get('category_name'):
            receipt_item['odoo_l2_name'] = odoo_line['category_name']

        # Store Odoo values for reference
        receipt_item['product_qty_odoo'] = odoo_line['product_qty']
        receipt_item['purchase_uom_odoo'] = odoo_line['uom_name']
        receipt_item['price_unit_odoo'] = odoo_line['price_unit']
        receipt_item['price_subtotal_odoo'] = odoo_line['price_subtotal']

        updated_count += 1

    # Add any missing fee lines from Odoo that weren't matched
    for odoo_line in odoo_lines:
        if odoo_line['product_id'] not in matched_odoo_lines:
            # This is a fee or additional item not in our extracted data
            # Check if it's a fee by looking at the product name
            product_name = odoo_line['product_name'].lower()
            is_fee = any(keyword in product_name for keyword in [
                'shipping', 'delivery', 'fee', 'tax', 'difference', 'discount',
                'bag fee', 'service fee', 'tip', 'charge'
            ])

            if is_fee or not odoo_line['product_id']:  # No product_id usually means it's a fee line
                print(f"     Adding missing fee line: {odoo_line['product_name']} (${odoo_line['price_subtotal']:.2f})")

                # Extract categories for the fee line
                l1_path = odoo_line.get('l1_category_name', '')
                l2_path = odoo_line.get('category_name', '')
                l1_code, l1_name = extract_l1_code_from_odoo_path(l1_path)
                l2_code, l2_name = extract_l2_code_from_odoo_path(l2_path)

                # Add this fee line to the receipt items
                fee_item = {
                    'product_name': odoo_line['product_name'],
                    'standard_name': odoo_line['product_name'],
                    'odoo_product_id': odoo_line['product_id'],
                    'quantity': float(odoo_line['product_qty']),
                    'purchase_uom': odoo_line['uom_name'],
                    'unit_price': float(odoo_line['price_unit']),
                    'total_price': float(odoo_line['price_subtotal']),
                    'is_fee': True,
                    'from_odoo': True,
                    'l1_category': l1_code,
                    'l1_category_name': l1_name,
                    'l2_category': l2_code,
                    'l2_category_name': l2_name
                }

                receipt_items.append(fee_item)
                updated_count += 1

    # Update receipt totals based on all items (including added fees)
    if receipt_items:
        total_amount = sum(float(item.get('total_price', 0)) for item in receipt_items)
        receipt['total'] = total_amount
        receipt['subtotal'] = total_amount  # Assume no tax for now
        receipt['tax'] = 0.0

    # Clean up temporary _matched flags
    for item in receipt_items:
        item.pop('_matched', None)

    return updated_count


def main():
    """Main function"""
    print("=" * 80)
    print("SYNC STEP 1 DATA WITH ODOO PURCHASE ORDERS")
    print("=" * 80)
    
    # Load Odoo purchase orders
    print("\n1. Loading purchase orders from Odoo database...")
    odoo_orders = get_odoo_purchase_orders()
    print(f"   Found {len(odoo_orders)} purchase orders")
    
    # Load Step 1 data
    print("\n2. Loading Step 1 extracted data...")
    step1_receipts = load_step1_data()
    print(f"   Found {len(step1_receipts)} receipts in Step 1 output")
    
    # Match and update
    print("\n3. Matching purchase orders to receipts and updating data...")
    matched_count = 0
    total_updated_items = 0
    
    for po_id, odoo_po in odoo_orders.items():
        match_result = match_po_to_receipt(odoo_po, step1_receipts)
        
        if match_result:
            receipt_id, receipt, confidence, method = match_result
            print(f"   ✓ Matched PO {odoo_po['po_name']} to receipt {receipt_id} (confidence: {confidence:.2f}, method: {method})")
            
            updated_items = update_receipt_with_odoo_data(receipt, odoo_po)
            total_updated_items += updated_items
            matched_count += 1
            print(f"     Updated {updated_items} items")
        else:
            print(f"   ✗ No match found for PO {odoo_po['po_name']} (vendor: {odoo_po['vendor_name']})")
    
    # Save updated data
    print(f"\n4. Saving updated Step 1 data...")
    step1_output_dir = Path('data/step1_output')
    
    # Group receipts back by source
    receipts_by_source = {}
    for receipt_id, receipt in step1_receipts.items():
        source_group = receipt.get('source_group', 'localgrocery_based')
        if source_group not in receipts_by_source:
            receipts_by_source[source_group] = {}
        receipts_by_source[source_group][receipt_id] = receipt
    
    # Save each source group
    for source_group, receipts in receipts_by_source.items():
        output_file = step1_output_dir / source_group / 'extracted_data.json'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(receipts, f, indent=2, ensure_ascii=False, default=str)
        print(f"   Saved {len(receipts)} receipts to {output_file}")
    
    # Summary
    print("\n" + "=" * 80)
    print("SYNC SUMMARY")
    print("=" * 80)
    print(f"Purchase Orders Matched: {matched_count}/{len(odoo_orders)}")
    print(f"Total Items Updated: {total_updated_items}")
    print(f"Receipts Updated: {matched_count}")
    print("=" * 80)
    
    # Regenerate reports
    print("\n5. Regenerating Step 1 reports...")
    try:
        from step1_extract.generate_report import generate_html_report
        
        for source_group, receipts in receipts_by_source.items():
            if receipts:
                report_file = step1_output_dir / source_group / 'report.html'
                generate_html_report(receipts, report_file)
                print(f"   ✓ Generated report: {report_file}")
    except Exception as e:
        print(f"   ⚠ Could not regenerate reports: {e}")


if __name__ == "__main__":
    main()

