#!/usr/bin/env python3
"""
Fix receipt totals and missing fees
- Fix UNI_UT_1025_Mousse total (should be subtotal + tax + shipping)
- Add missing fees (Cold Pack Fee, Shipping) to foodservicedirect_1015
"""

import json
import re
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def extract_english_text(value):
    """Extract English text from JSON field"""
    if not value:
        return ''
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed.get('en_US') or parsed.get('en') or (list(parsed.values())[0] if parsed else '')
            return str(parsed)
        except:
            return value
    return str(value)


def fix_uni_ut_1025_mousse():
    """Fix total for UNI_UT_1025_Mousse"""
    data_file = Path('data/step1_output/bbi_based/extracted_data.json')
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    receipt_id = 'UNI_UT_1025_Mousse'
    if receipt_id in data:
        receipt = data[receipt_id]
        subtotal = receipt.get('subtotal', 0)
        tax = receipt.get('tax', 0)
        shipping = receipt.get('shipping', 0)
        
        # Calculate correct total
        calculated_total = subtotal + tax + shipping
        
        if receipt.get('total', 0) != calculated_total:
            print(f"Fixing {receipt_id}: total was {receipt.get('total')}, setting to {calculated_total}")
            receipt['total'] = calculated_total
            
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            print(f"✓ Fixed {receipt_id} total")
            return True
    return False


def fix_foodservicedirect_fees():
    """Add missing fees to foodservicedirect_1015 from Odoo"""
    # Get fees from Odoo
    conn = connect_to_database()
    if not conn:
        print("Could not connect to database")
        return False
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get purchase order lines for foodservicedirect_1015
            cur.execute("""
                SELECT pol.name, pol.product_qty, pol.price_unit, pol.price_subtotal,
                       pt.name::text as product_name
                FROM purchase_order_line pol
                JOIN purchase_order po ON pol.order_id = po.id
                LEFT JOIN product_product pp ON pol.product_id = pp.id
                LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE po.partner_ref = 'foodservicedirect_1015'
                   OR po.name = 'P00162'
                ORDER BY pol.sequence
            """)
            
            lines = cur.fetchall()
            
            # Find fee items
            fees = []
            for line in lines:
                product_name = extract_english_text(line['product_name'])
                line_name = line['name']
                
                # Check if it's a fee
                if 'Cold Pack' in product_name or 'Cold Pack' in line_name:
                    fees.append({
                        'product_name': 'Cold Pack Fee',
                        'quantity': float(line['product_qty']),
                        'unit_price': float(line['price_unit']),
                        'total_price': float(line['price_subtotal']),
                        'is_fee': True,
                        'fee_type': 'cold_pack_fee'
                    })
                elif 'Shipping' in product_name or 'Shipping' in line_name:
                    fees.append({
                        'product_name': 'Shipping & Handling',
                        'quantity': float(line['product_qty']),
                        'unit_price': float(line['price_unit']),
                        'total_price': float(line['price_subtotal']),
                        'is_fee': True,
                        'fee_type': 'shipping'
                    })
    finally:
        conn.close()
    
    if not fees:
        print("No fees found in Odoo for foodservicedirect_1015")
        return False
    
    # Add fees to receipt
    data_file = Path('data/step1_output/localgrocery_based/extracted_data.json')
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    receipt_id = 'foodservicedirect_1015'
    if receipt_id in data:
        receipt = data[receipt_id]
        items = receipt.get('items', [])
        
        # Check if fees already exist
        existing_fee_names = {item.get('product_name', '') for item in items if item.get('is_fee', False)}
        
        added_count = 0
        for fee in fees:
            fee_name = fee['product_name']
            if fee_name not in existing_fee_names:
                # Add fee as new item
                items.append(fee)
                added_count += 1
                print(f"  Added fee: {fee_name} = ${fee['total_price']}")
        
        if added_count > 0:
            receipt['items'] = items
            
            # Recalculate subtotal (should exclude fees)
            product_items = [item for item in items if not item.get('is_fee', False)]
            receipt['subtotal'] = sum(item.get('total_price', 0) for item in product_items)
            
            # Recalculate total (subtotal + tax + fees)
            fee_total = sum(item.get('total_price', 0) for item in items if item.get('is_fee', False))
            receipt['total'] = receipt.get('subtotal', 0) + receipt.get('tax', 0) + fee_total
            
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            print(f"✓ Added {added_count} fees to {receipt_id}")
            print(f"  Updated subtotal: ${receipt['subtotal']}")
            print(f"  Updated total: ${receipt['total']}")
            return True
        else:
            print(f"All fees already exist in {receipt_id}")
            return False
    else:
        print(f"Receipt {receipt_id} not found")
        return False


def fix_pike_global_foods_fees():
    """Add missing shipping fee to Pike Global Foods receipt from Odoo"""
    # Get fees from Odoo
    conn = connect_to_database()
    if not conn:
        print("Could not connect to database")
        return False
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get purchase order lines for Pike Global Foods
            cur.execute("""
                SELECT pol.name, pol.product_qty, pol.price_unit, pol.price_subtotal,
                       pt.name::text as product_name
                FROM purchase_order_line pol
                JOIN purchase_order po ON pol.order_id = po.id
                LEFT JOIN product_product pp ON pol.product_id = pp.id
                LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE po.partner_ref = 'Pike Global Foods - 20251001'
                   OR po.name = 'P00171'
                ORDER BY pol.sequence
            """)
            
            lines = cur.fetchall()
            
            # Find fee items
            fees = []
            for line in lines:
                product_name = extract_english_text(line['product_name'])
                line_name = line['name']
                
                # Check if it's a fee (shipping, handling, etc.)
                if 'Shipping' in product_name or 'Shipping' in line_name:
                    fees.append({
                        'product_name': 'Shipping',
                        'quantity': float(line['product_qty']),
                        'unit_price': float(line['price_unit']),
                        'total_price': float(line['price_subtotal']),
                        'is_fee': True,
                        'fee_type': 'shipping'
                    })
    finally:
        conn.close()
    
    if not fees:
        print("No fees found in Odoo for Pike Global Foods - 20251001")
        return False
    
    # Add fees to receipt
    data_file = Path('data/step1_output/localgrocery_based/extracted_data.json')
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    receipt_id = 'Pike Global Foods - 20251001'
    if receipt_id in data:
        receipt = data[receipt_id]
        items = receipt.get('items', [])
        
        # Check if fees already exist
        existing_fee_names = {item.get('product_name', '') for item in items if item.get('is_fee', False)}
        
        added_count = 0
        for fee in fees:
            fee_name = fee['product_name']
            if fee_name not in existing_fee_names:
                # Add fee as new item
                items.append(fee)
                added_count += 1
                print(f"  Added fee: {fee_name} = ${fee['total_price']}")
        
        if added_count > 0:
            receipt['items'] = items
            
            # Recalculate subtotal (should exclude fees)
            product_items = [item for item in items if not item.get('is_fee', False)]
            receipt['subtotal'] = sum(item.get('total_price', 0) for item in product_items)
            
            # Recalculate total (subtotal + tax + fees)
            fee_total = sum(item.get('total_price', 0) for item in items if item.get('is_fee', False))
            receipt['total'] = receipt.get('subtotal', 0) + receipt.get('tax', 0) + fee_total
            
            # Also set shipping field
            receipt['shipping'] = fee_total
            
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            print(f"✓ Added {added_count} fees to {receipt_id}")
            print(f"  Updated subtotal: ${receipt['subtotal']}")
            print(f"  Updated shipping: ${receipt['shipping']}")
            print(f"  Updated total: ${receipt['total']}")
            return True
        else:
            print(f"All fees already exist in {receipt_id}")
            return False
    else:
        print(f"Receipt {receipt_id} not found")
        return False


def fix_instacart_order_18179604832488932():
    """Fix missing Priority Fee and trash bag UoM/quantity for instacart order"""
    # Get fees from Odoo
    conn = connect_to_database()
    if not conn:
        print("Could not connect to database")
        return False
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get purchase order lines
            cur.execute("""
                SELECT pol.name, pol.product_qty, pol.price_unit, pol.price_subtotal,
                       pt.name::text as product_name, uom.name::text as uom_name
                FROM purchase_order_line pol
                JOIN purchase_order po ON pol.order_id = po.id
                LEFT JOIN product_product pp ON pol.product_id = pp.id
                LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pol.product_uom = uom.id
                WHERE po.name = '18179604832488932'
                ORDER BY pol.sequence
            """)
            
            lines = cur.fetchall()
            
            # Find fee items
            fees = []
            
            for line in lines:
                product_name = extract_english_text(line['product_name'])
                line_name = line['name']
                
                # Check if it's a fee
                if 'Priority Fee' in line_name or 'Priority Fee' in product_name:
                    fees.append({
                        'product_name': 'Priority Fee',
                        'quantity': float(line['product_qty']),
                        'unit_price': float(line['price_unit']),
                        'total_price': float(line['price_subtotal']),
                        'is_fee': True,
                        'fee_type': 'priority_fee'
                    })
            
            # Check if 90-pc UoM exists in Odoo
            # Try multiple patterns to match "90-pc"
            cur.execute("""
                SELECT uom.id, uom.name::text as uom_name
                FROM uom_uom uom
                WHERE uom.name::text ILIKE '%90%pc%' 
                   OR uom.name::text ILIKE '%90-pc%'
                   OR uom.name::text ILIKE '%90 pc%'
                   OR uom.name::text = '90-pc'
                LIMIT 1
            """)
            uom_result = cur.fetchone()
            uom_exists = uom_result is not None
            if uom_exists:
                uom_name = extract_english_text(uom_result['uom_name'])
                print(f"  Found 90-pc UoM in Odoo: {uom_name} (ID: {uom_result['id']})")
    finally:
        conn.close()
    
    # Update receipt
    data_file = Path('data/step1_output/instacart_based/extracted_data.json')
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    receipt_id = '18179604832488932'
    if receipt_id not in data:
        print(f"Receipt {receipt_id} not found")
        return False
    
    receipt = data[receipt_id]
    items = receipt.get('items', [])
    updated = False
    
    # Add missing Priority Fee
    if fees:
        existing_fee_names = {item.get('product_name', '') for item in items if item.get('is_fee', False)}
        for fee in fees:
            if fee['product_name'] not in existing_fee_names:
                items.append(fee)
                updated = True
                print(f"  Added fee: {fee['product_name']} = ${fee['total_price']}")
    
    # Fix trash bag UoM/quantity if needed
    # The product name suggests "90-count" bags, so if we have 180 units, it should be 2 bags of 90-count
    # Now that 90-pc UoM exists in Odoo, we should use it
    for item in items:
        name = item.get('product_name', '')
        if 'Trash' in name and '90-count' in name:
            # Check if we should use original UoM (90-pc) instead of Units
            current_qty = item.get('quantity', 0)
            current_uom = item.get('purchase_uom', '')
            
            # If current is 180 Units, and product name says 90-count, convert to 2 bags of 90-pc
            if current_qty == 180.0 and current_uom == 'Units':
                if uom_exists:
                    # 90-pc UoM exists, use it
                    # 180 pieces / 90 pieces per bag = 2 bags
                    # Calculate: 180 / 90 = 2
                    item['quantity'] = 2.0
                    item['purchase_uom'] = '90-pc'
                    item['unit_price'] = item.get('total_price', 0) / 2.0
                    # Update Odoo fields to reflect the change
                    item['purchase_uom_odoo'] = '90-pc'
                    item['product_qty_odoo'] = 2.0
                    item['price_unit_odoo'] = item['unit_price']
                    updated = True
                    print(f"  Fixed trash bag: Using qty=2.0, UoM=90-pc (was {current_qty} {current_uom})")
                    print(f"    Unit price: ${item['unit_price']:.2f} per 90-pc bag")
                    print(f"    Total: ${item.get('total_price', 0)} (2 × ${item['unit_price']:.2f})")
                else:
                    print(f"  Trash bag: 90-pc UoM not found in Odoo yet, keeping current: {current_qty} {current_uom}")
    
    if updated:
        receipt['items'] = items
        
        # Recalculate subtotal (should exclude fees)
        product_items = [item for item in items if not item.get('is_fee', False)]
        receipt['subtotal'] = sum(item.get('total_price', 0) for item in product_items)
        
        # Recalculate total (subtotal + tax + fees)
        fee_total = sum(item.get('total_price', 0) for item in items if item.get('is_fee', False))
        receipt['total'] = receipt.get('subtotal', 0) + receipt.get('tax', 0) + fee_total
        
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"✓ Updated {receipt_id}")
        print(f"  Updated subtotal: ${receipt['subtotal']}")
        print(f"  Updated total: ${receipt['total']}")
        return True
    else:
        print(f"No updates needed for {receipt_id}")
        return False


def main():
    """Main function"""
    print("=" * 80)
    print("FIX RECEIPT TOTALS AND FEES")
    print("=" * 80)
    
    print("\n1. Fixing UNI_UT_1025_Mousse total...")
    fix_uni_ut_1025_mousse()
    
    print("\n2. Adding missing fees to foodservicedirect_1015...")
    fix_foodservicedirect_fees()
    
    print("\n3. Adding missing fees to Pike Global Foods - 20251001...")
    fix_pike_global_foods_fees()
    
    print("\n4. Fixing instacart order 18179604832488932...")
    fix_instacart_order_18179604832488932()
    
    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()

