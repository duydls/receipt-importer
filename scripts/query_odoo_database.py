#!/usr/bin/env python3
"""
Query Odoo database and export data to CSV
Supports querying products, purchase orders, vendors, and more
"""

import sys
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def query_products(conn, output_file: Path) -> int:
    """Query all products with details"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = """
        SELECT 
            pp.id as product_id,
            pt.name->>'en_US' as product_name,
            pt.default_code,
            pp.barcode,
            pt.list_price as sale_price,
            pp.standard_price as cost_price,
            pt.uom_id as default_uom_id,
            uom.name as default_uom_name,
            pt.uom_po_id as purchase_uom_id,
            uom_po.name as purchase_uom_name,
            pt.categ_id as category_id,
            pc.name as category_name,
            pt.purchase_ok,
            pt.sale_ok,
            pt.type as product_type,
            pt.active
        FROM product_product pp
        JOIN product_template pt ON pp.product_tmpl_id = pt.id
        LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
        LEFT JOIN uom_uom uom_po ON pt.uom_po_id = uom_po.id
        LEFT JOIN product_category pc ON pt.categ_id = pc.id
        WHERE pt.active = true
        ORDER BY pp.id
        """
        
        cur.execute(query)
        rows = cur.fetchall()
        
        if not rows:
            print("No products found")
            return 0
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'product_id', 'product_name', 'default_code', 'barcode',
                'sale_price', 'cost_price', 'default_uom_id', 'default_uom_name',
                'purchase_uom_id', 'purchase_uom_name', 'category_id', 'category_name',
                'purchase_ok', 'sale_ok', 'product_type', 'active'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in rows:
                writer.writerow({
                    'product_id': row['product_id'],
                    'product_name': row['product_name'] or '',
                    'default_code': row['default_code'] or '',
                    'barcode': row['barcode'] or '',
                    'sale_price': row['sale_price'] or 0,
                    'cost_price': row['cost_price'] or 0,
                    'default_uom_id': row['default_uom_id'],
                    'default_uom_name': row['default_uom_name'] or '',
                    'purchase_uom_id': row['purchase_uom_id'],
                    'purchase_uom_name': row['purchase_uom_name'] or '',
                    'category_id': row['category_id'],
                    'category_name': row['category_name'] or '',
                    'purchase_ok': row['purchase_ok'],
                    'sale_ok': row['sale_ok'],
                    'product_type': row['product_type'] or '',
                    'active': row['active']
                })
        
        return len(rows)


def query_purchase_orders(conn, output_file: Path) -> int:
    """Query purchase orders with lines"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = """
        SELECT 
            po.id as order_id,
            po.name as order_name,
            po.date_order,
            po.date_planned,
            po.partner_id,
            rp.name as vendor_name,
            po.state,
            po.amount_total,
            po.amount_untaxed,
            po.amount_tax,
            pol.id as line_id,
            pol.product_id,
            pt.name->>'en_US' as product_name,
            pol.product_qty as quantity,
            pol.price_unit,
            pol.price_subtotal,
            pol.price_total,
            uom.name as uom_name,
            pol.date_planned as line_date_planned
        FROM purchase_order po
        JOIN res_partner rp ON po.partner_id = rp.id
        LEFT JOIN purchase_order_line pol ON po.id = pol.order_id
        LEFT JOIN product_product pp ON pol.product_id = pp.id
        LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
        LEFT JOIN uom_uom uom ON pol.product_uom = uom.id
        ORDER BY po.date_order DESC, po.id, pol.id
        """
        
        cur.execute(query)
        rows = cur.fetchall()
        
        if not rows:
            print("No purchase orders found")
            return 0
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'order_id', 'order_name', 'date_order', 'date_planned',
                'partner_id', 'vendor_name', 'state', 'amount_total',
                'amount_untaxed', 'amount_tax', 'line_id', 'product_id',
                'product_name', 'quantity', 'price_unit', 'price_subtotal',
                'price_total', 'uom_name', 'line_date_planned'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in rows:
                writer.writerow({
                    'order_id': row['order_id'],
                    'order_name': row['order_name'] or '',
                    'date_order': row['date_order'],
                    'date_planned': row['date_planned'],
                    'partner_id': row['partner_id'],
                    'vendor_name': row['vendor_name'] or '',
                    'state': row['state'] or '',
                    'amount_total': row['amount_total'] or 0,
                    'amount_untaxed': row['amount_untaxed'] or 0,
                    'amount_tax': row['amount_tax'] or 0,
                    'line_id': row['line_id'],
                    'product_id': row['product_id'],
                    'product_name': row['product_name'] or '',
                    'quantity': row['quantity'] or 0,
                    'price_unit': row['price_unit'] or 0,
                    'price_subtotal': row['price_subtotal'] or 0,
                    'price_total': row['price_total'] or 0,
                    'uom_name': row['uom_name'] or '',
                    'line_date_planned': row['line_date_planned']
                })
        
        return len(rows)


def query_vendors(conn, output_file: Path) -> int:
    """Query vendors/suppliers"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = """
        SELECT 
            rp.id as vendor_id,
            rp.name as vendor_name,
            rp.is_company,
            rp.supplier_rank,
            rp.customer_rank,
            rp.active,
            rp.email,
            rp.phone,
            rp.street,
            rp.city,
            rp.state_id,
            rp.country_id,
            rp.zip
        FROM res_partner rp
        WHERE rp.supplier_rank > 0 OR rp.is_company = true
        ORDER BY rp.name
        """
        
        cur.execute(query)
        rows = cur.fetchall()
        
        if not rows:
            print("No vendors found")
            return 0
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'vendor_id', 'vendor_name', 'is_company',
                'supplier_rank', 'customer_rank', 'active', 'email',
                'phone', 'street', 'city', 'state_id', 'country_id', 'zip'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in rows:
                writer.writerow({
                    'vendor_id': row['vendor_id'],
                    'vendor_name': row['vendor_name'] or '',
                    'is_company': row['is_company'],
                    'supplier_rank': row['supplier_rank'] or 0,
                    'customer_rank': row['customer_rank'] or 0,
                    'active': row['active'],
                    'email': row['email'] or '',
                    'phone': row['phone'] or '',
                    'street': row['street'] or '',
                    'city': row['city'] or '',
                    'state_id': row['state_id'],
                    'country_id': row['country_id'],
                    'zip': row['zip'] or ''
                })
        
        return len(rows)


def query_stock_moves(conn, output_file: Path, limit: int = 1000) -> int:
    """Query recent stock moves"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = """
        SELECT 
            sm.id as move_id,
            sm.name as move_name,
            sm.date,
            sm.product_id,
            pt.name->>'en_US' as product_name,
            sm.product_uom_qty as quantity,
            sm.product_uom as uom_id,
            uom.name as uom_name,
            sm.location_id,
            sl.name as location_name,
            sm.location_dest_id,
            sl_dest.name as destination_name,
            sm.picking_id,
            sm.origin,
            sm.state,
            sm.picking_type_id
        FROM stock_move sm
        LEFT JOIN product_product pp ON sm.product_id = pp.id
        LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
        LEFT JOIN uom_uom uom ON sm.product_uom = uom.id
        LEFT JOIN stock_location sl ON sm.location_id = sl.id
        LEFT JOIN stock_location sl_dest ON sm.location_dest_id = sl_dest.id
        ORDER BY sm.date DESC
        LIMIT %s
        """
        
        cur.execute(query, (limit,))
        rows = cur.fetchall()
        
        if not rows:
            print("No stock moves found")
            return 0
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'move_id', 'move_name', 'date', 'product_id', 'product_name',
                'quantity', 'uom_id', 'uom_name', 'location_id', 'location_name',
                'location_dest_id', 'destination_name', 'picking_id', 'origin',
                'state', 'picking_type_id'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in rows:
                writer.writerow({
                    'move_id': row['move_id'],
                    'move_name': row['move_name'] or '',
                    'date': row['date'],
                    'product_id': row['product_id'],
                    'product_name': row['product_name'] or '',
                    'quantity': row['quantity'] or 0,
                    'uom_id': row['uom_id'],
                    'uom_name': row['uom_name'] or '',
                    'location_id': row['location_id'],
                    'location_name': row['location_name'] or '',
                    'location_dest_id': row['location_dest_id'],
                    'destination_name': row['destination_name'] or '',
                    'picking_id': row['picking_id'],
                    'origin': row['origin'] or '',
                    'state': row['state'] or '',
                    'picking_type_id': row['picking_type_id']
                })
        
        return len(rows)


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Query Odoo database and export to CSV')
    parser.add_argument('--type', choices=['products', 'purchase_orders', 'vendors', 'stock_moves', 'all'],
                       default='all', help='Type of data to query')
    parser.add_argument('--output-dir', type=Path, default=Path('data/odoo_export'),
                       help='Output directory for CSV files')
    parser.add_argument('--limit', type=int, default=1000,
                       help='Limit for stock_moves query (default: 1000)')
    
    args = parser.parse_args()
    
    print("Connecting to Odoo database...")
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to database")
        return
    
    print("✓ Connected to database")
    print()
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    results = {}
    
    # Query based on type
    if args.type in ('products', 'all'):
        print("Querying products...")
        output_file = args.output_dir / 'products.csv'
        count = query_products(conn, output_file)
        results['products'] = count
        print(f"✓ Exported {count} products to: {output_file}")
        print()
    
    if args.type in ('purchase_orders', 'all'):
        print("Querying purchase orders...")
        output_file = args.output_dir / 'purchase_orders.csv'
        count = query_purchase_orders(conn, output_file)
        results['purchase_orders'] = count
        print(f"✓ Exported {count} purchase order lines to: {output_file}")
        print()
    
    if args.type in ('vendors', 'all'):
        print("Querying vendors...")
        output_file = args.output_dir / 'vendors.csv'
        count = query_vendors(conn, output_file)
        results['vendors'] = count
        print(f"✓ Exported {count} vendors to: {output_file}")
        print()
    
    if args.type in ('stock_moves', 'all'):
        print("Querying stock moves...")
        output_file = args.output_dir / 'stock_moves.csv'
        count = query_stock_moves(conn, output_file, limit=args.limit)
        results['stock_moves'] = count
        print(f"✓ Exported {count} stock moves to: {output_file}")
        print()
    
    conn.close()
    print("✓ Database connection closed")
    print()
    print("=" * 80)
    print("Export Summary:")
    for data_type, count in results.items():
        print(f"  {data_type}: {count} records")
    print("=" * 80)


if __name__ == '__main__':
    main()

