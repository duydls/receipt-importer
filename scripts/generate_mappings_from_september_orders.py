#!/usr/bin/env python3
"""
Generate Product Mappings from September Purchase Orders

Extracts products from September receipts in data/Arc/Sep/ and matches them
with September purchase orders in Odoo database to create additional mapping rules.
"""

import json
import sys
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def extract_english_text(value: Any) -> str:
    """Extract English text from JSON field"""
    if not value:
        return ''
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed.get('en_US') or parsed.get('en') or (list(parsed.values())[0] if parsed else '')
            return str(parsed)
        except (json.JSONDecodeError, ValueError):
            return value
    return str(value)


def get_september_odoo_orders() -> Dict[int, Dict[str, Any]]:
    """Get all purchase orders from September 2025 with their lines"""
    conn = connect_to_database()
    if not conn:
        logger.error("Could not connect to Odoo database")
        return {}
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get purchase orders from September 2025
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
                    pc.complete_name::text as category_name,
                    pol.display_type,
                    pt.type as product_type
                FROM purchase_order po
                LEFT JOIN res_partner rp ON po.partner_id = rp.id
                LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
                LEFT JOIN product_product pp ON pol.product_id = pp.id
                LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pol.product_uom = uom.id
                LEFT JOIN product_category pc ON pt.categ_id = pc.id
                WHERE po.date_order >= '2025-09-01' 
                  AND po.date_order < '2025-10-01'
                  AND (pol.display_type IS NULL OR pol.display_type IN ('line_section', 'line_note'))
                  AND (pt.type IN ('product', 'consu', 'service') OR pt.type IS NULL OR pol.display_type IS NOT NULL)
                ORDER BY po.date_order, po.id, pol.sequence
            """)
            
            lines = cur.fetchall()
            
            # Group by purchase order
            orders = {}
            for line in lines:
                po_id = line['po_id']
                
                if po_id not in orders:
                    orders[po_id] = {
                        'po_id': po_id,
                        'po_name': line['po_name'],
                        'partner_ref': line['partner_ref'],
                        'date_order': line['date_order'],
                        'vendor_name': extract_english_text(line['vendor_name']),
                        'lines': []
                    }
                
                product_name = extract_english_text(line['product_name'])
                uom_name = extract_english_text(line['uom_name'])
                
                orders[po_id]['lines'].append({
                    'product_id': line['product_id'],
                    'product_name': product_name,
                    'line_name': line['line_name'] or product_name,
                    'product_qty': float(line['product_qty']) if line['product_qty'] else 0.0,
                    'price_unit': float(line['price_unit']) if line['price_unit'] else 0.0,
                    'price_subtotal': float(line['price_subtotal']) if line['price_subtotal'] else 0.0,
                    'uom_name': uom_name,
                    'uom_id': line['product_uom'],
                    'category_name': extract_english_text(line['category_name']) if line['category_name'] else '',
                    'is_fee': line.get('display_type') in ('line_section', 'line_note'),
                })
            
            logger.info(f"Loaded {len(orders)} September purchase orders with {sum(len(o['lines']) for o in orders.values())} lines")
            return orders
    except Exception as e:
        logger.error(f"Error querying Odoo: {e}", exc_info=True)
        return {}
    finally:
        if conn:
            conn.close()


def extract_products_from_odoo_orders(odoo_orders: Dict[int, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract product names from Odoo purchase orders
    Use line_name as receipt product name and product_name as Odoo standard name
    
    Returns:
        Dictionary mapping vendor to list of product mappings
    """
    vendor_products = defaultdict(list)
    
    for po_id, po_data in odoo_orders.items():
        vendor_name = po_data['vendor_name']
        
        for line in po_data['lines']:
            if line.get('is_fee'):
                continue
            
            product_id = line['product_id']
            product_name = line['product_name']  # Odoo standard name
            line_name = line['line_name']  # May be different from product_name (receipt name)
            
            # If line_name is different from product_name, create a mapping
            if line_name and line_name != product_name:
                vendor_products[vendor_name].append({
                    'receipt_product_name': line_name,  # Name as it appears on receipt/PO
                    'odoo_product_id': product_id,
                    'odoo_product_name': product_name,  # Standard Odoo name
                    'odoo_uom_name': line.get('uom_name', ''),
                    'po_name': po_data['po_name'],
                    'vendor': vendor_name,
                })
    
    return dict(vendor_products)


def create_mappings_from_odoo_products(vendor_products: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Create mappings from Odoo purchase order products
    
    Returns:
        List of mappings
    """
    mappings = []
    seen_receipt_names = set()
    
    for vendor, products in vendor_products.items():
        for product in products:
            receipt_name = product['receipt_product_name']
            
            # Skip if we've seen this exact mapping
            key = f"{receipt_name}|{product['odoo_product_id']}"
            if key in seen_receipt_names:
                continue
            seen_receipt_names.add(key)
            
            mappings.append({
                'receipt_product_name': receipt_name,
                'odoo_product_id': product['odoo_product_id'],
                'odoo_product_name': product['odoo_product_name'],
                'odoo_uom_name': product.get('odoo_uom_name', ''),
                'vendor': vendor,
                'odoo_vendor': vendor,
                'po_name': product.get('po_name', ''),
                'similarity': 1.0,  # Direct match from Odoo
            })
    
    return mappings


def generate_mapping_excel_updates(
    mappings: List[Dict[str, Any]],
    existing_mapping_file: Path,
    output_excel: Path
):
    """Generate Excel updates with new mappings"""
    
    # Load existing mappings
    existing_mappings = {}
    if existing_mapping_file.exists():
        try:
            with open(existing_mapping_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                existing_mappings = {k: v for k, v in data.items() if not k.startswith('_')}
        except Exception as e:
            logger.warning(f"Could not load existing mappings: {e}")
    
    # Create DataFrame for new mappings
    new_mappings = []
    seen_receipt_names = set()
    
    for mapping in mappings:
        receipt_name = mapping['receipt_product_name']
        
        # Skip if already in existing mappings
        if receipt_name in existing_mappings:
            continue
        
        # Skip duplicates
        if receipt_name in seen_receipt_names:
            continue
        seen_receipt_names.add(receipt_name)
        
        # Get vendor list
        vendors = [mapping['vendor']]
        if mapping.get('odoo_vendor') and mapping['odoo_vendor'] not in vendors:
            vendors.append(mapping['odoo_vendor'])
        
        new_mappings.append({
            'Receipt Product Name': receipt_name,
            'Odoo Product ID': mapping['odoo_product_id'],
            'Odoo Product Name': mapping['odoo_product_name'],
            'Odoo Template ID': '',  # Will be filled when converting
            'Receipt UoM': '',
            'Odoo UoM ID': '',
            'Odoo UoM Name': mapping.get('odoo_uom_name', ''),
            'UoM Conversion Ratio': '',
            'Vendors': ', '.join(vendors),
            'Category': '',
            'Product Type': '',
            'Notes': f"Auto-generated from September orders (PO: {mapping.get('po_name', 'N/A')}, similarity: {mapping['similarity']:.2f})",
            'Active': True
        })
    
    if not new_mappings:
        logger.info("No new mappings found")
        return
    
    # Create DataFrame
    df = pd.DataFrame(new_mappings)
    
    # Append to existing Excel or create new
    if output_excel.exists():
        try:
            existing_df = pd.read_excel(output_excel, sheet_name='Product Mappings')
            # Remove example rows
            existing_df = existing_df[~existing_df['Receipt Product Name'].astype(str).str.contains('EXAMPLE', case=False, na=False)]
            # Combine
            df = pd.concat([existing_df, df], ignore_index=True)
        except Exception as e:
            logger.warning(f"Could not read existing Excel: {e}")
    
    # Save to Excel
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Product Mappings', index=False)
        
        # Format
        worksheet = writer.sheets['Product Mappings']
        worksheet.column_dimensions['A'].width = 30
        worksheet.column_dimensions['B'].width = 15
        worksheet.column_dimensions['C'].width = 40
        worksheet.column_dimensions['I'].width = 30
        worksheet.column_dimensions['L'].width = 50
        worksheet.freeze_panes = 'A2'
    
    logger.info(f"✅ Added {len(new_mappings)} new mappings to Excel: {output_excel}")


def main():
    """Main function"""
    arc_dir = Path('data/Arc')
    existing_mapping_file = Path('data/product_standard_name_mapping.json')
    output_excel = Path('data/product_mapping_template.xlsx')
    
    logger.info("="*80)
    logger.info("Generate Product Mappings from September Purchase Orders")
    logger.info("="*80)
    
    # Step 1: Get September Odoo orders
    logger.info("\n1. Loading September purchase orders from Odoo...")
    odoo_orders = get_september_odoo_orders()
    if not odoo_orders:
        logger.error("No September purchase orders found in Odoo")
        return
    
    # Step 2: Extract products from Odoo purchase orders
    logger.info("\n2. Extracting products from September Odoo purchase orders...")
    vendor_products = extract_products_from_odoo_orders(odoo_orders)
    
    total_products = sum(len(products) for products in vendor_products.values())
    logger.info(f"   Found {total_products} products with different line names from {len(vendor_products)} vendors")
    
    for vendor, products in vendor_products.items():
        logger.info(f"   {vendor}: {len(products)} products")
    
    # Step 3: Create mappings from Odoo products
    logger.info("\n3. Creating mappings from Odoo purchase order products...")
    all_mappings = create_mappings_from_odoo_products(vendor_products)
    
    logger.info(f"   Total mappings created: {len(all_mappings)}")
    
    # Step 4: Generate Excel updates
    logger.info("\n4. Generating Excel updates...")
    generate_mapping_excel_updates(all_mappings, existing_mapping_file, output_excel)
    
    logger.info("\n" + "="*80)
    logger.info("✅ Complete!")
    logger.info("="*80)
    logger.info(f"\nNext steps:")
    logger.info(f"1. Review the Excel file: {output_excel}")
    logger.info(f"2. Edit/verify the new mappings")
    logger.info(f"3. Convert to JSON: python scripts/convert_mapping_excel_to_json.py {output_excel}")


if __name__ == '__main__':
    main()

