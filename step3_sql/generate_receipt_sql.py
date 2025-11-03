#!/usr/bin/env python3
"""
Generate SQL INSERT commands for all receipts
Creates one SQL file per receipt with purchase_order and purchase_order_line INSERT statements
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from step1_extract.receipt_processor import ReceiptProcessor
from step2_mapping.product_matcher import ProductMatcher
from config import *

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ReceiptSQLGenerator:
    """Generate SQL INSERT statements for receipts"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.receipt_processor = ReceiptProcessor(config)
        
        # Load product matcher with mapping files
        db_dump_json = config.get('DB_DUMP_JSON', DB_DUMP_JSON)
        mapping_file = config.get('PRODUCT_MAPPING_FILE', PRODUCT_MAPPING_FILE)
        fruit_conversion_file = config.get('FRUIT_CONVERSION_FILE', FRUIT_CONVERSION_FILE)
        
        if Path(db_dump_json).exists():
            self.product_matcher = ProductMatcher(
                db_dump_json,
                mapping_file=mapping_file,
                fruit_conversion_file=fruit_conversion_file
            )
        else:
            logger.error(f"Database dump JSON not found: {db_dump_json}")
            self.product_matcher = None
    
    def format_sql_value(self, value) -> str:
        """Format a value for SQL INSERT"""
        if value is None or value == '' or value == '\\N':
            return 'NULL'
        elif isinstance(value, bool):
            return 'TRUE' if value else 'FALSE'
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Escape single quotes
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        else:
            # Convert to string and escape
            escaped = str(value).replace("'", "''")
            return f"'{escaped}'"
    
    def generate_purchase_order_sql(self, receipt_data: Dict, po_id: int) -> str:
        """Generate SQL INSERT statement for purchase_order"""
        
        # Get vendor/partner ID from receipt data
        # For Instacart receipts: IC-{store_name}
        # For other receipts: use vendor name as-is
        vendor_name = receipt_data.get('vendor') or receipt_data.get('store_name')
        
        # Check if this is an Instacart order (has store_name but vendor might be different)
        is_instacart = False
        if receipt_data.get('store_name'):
            # If we have a store_name from CSV, it's likely Instacart
            is_instacart = True
            store_name = receipt_data.get('store_name', '')
            # Format as IC-{store_name}
            vendor_name = f"IC-{store_name}"
        
        # Look up vendor in database (we'll use a subquery in SQL to get partner_id)
        # For now, we'll generate SQL that looks up the partner_id by name
        partner_id_sql = f"(SELECT id FROM res_partner WHERE name = {self.format_sql_value(vendor_name)} LIMIT 1)"
        partner_id = None  # Will be determined at SQL execution time
        
        # Get order date
        order_date = receipt_data.get('order_date') or receipt_data.get('delivery_date')
        if isinstance(order_date, str):
            try:
                # Parse ISO format
                order_date = datetime.fromisoformat(order_date.replace('Z', '+00:00'))
            except:
                try:
                    order_date = datetime.strptime(order_date[:19], '%Y-%m-%d %H:%M:%S')
                except:
                    order_date = datetime.now()
        elif order_date is None:
            order_date = datetime.now()
        
        date_order = order_date.strftime('%Y-%m-%d %H:%M:%S')
        date_planned = date_order  # Use same as order date
        create_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        write_date = create_date
        
        # Calculate totals
        total = receipt_data.get('total', 0.0)
        amount_untaxed = receipt_data.get('subtotal', total)
        amount_tax = 0.00
        amount_total = total
        
        # Get order name/sequence
        order_name = receipt_data.get('order_id') or f"P{po_id:05d}"
        partner_ref = receipt_data.get('order_id') or receipt_data.get('vendor_ref')
        
        # Look up vendor/partner ID using SQL subquery
        # This ensures the vendor exists in the database before insertion
        partner_id_subquery = f"(SELECT id FROM res_partner WHERE name = {self.format_sql_value(vendor_name)} LIMIT 1)"
        
        # Purchase Order columns (from actual Odoo structure)
        sql = f"""-- Look up vendor/partner ID by name
-- Vendor Name: {vendor_name}
INSERT INTO purchase_order (id, partner_id, dest_address_id, currency_id, invoice_count, fiscal_position_id, payment_term_id, incoterm_id, user_id, company_id, create_uid, write_uid, access_token, name, priority, origin, partner_ref, state, invoice_status, notes, amount_untaxed, amount_tax, amount_total, amount_total_cc, currency_rate, mail_reminder_confirmed, mail_reception_confirmed, mail_reception_declined, date_order, date_approve, date_planned, date_calendar_start, create_date, write_date, picking_type_id, group_id, incoterm_location, receipt_status, effective_date)
SELECT {po_id}, id, NULL, 1, 0, NULL, NULL, NULL, 2, 1, 2, 2, NULL, {self.format_sql_value(order_name)}, 0, NULL, {self.format_sql_value(partner_ref)}, 'draft', 'no', NULL, {amount_untaxed}, {amount_tax}, {amount_total}, {amount_total}, 1.0, FALSE, FALSE, NULL, {self.format_sql_value(date_order)}, NULL, {self.format_sql_value(date_planned)}, {self.format_sql_value(date_planned)}, {self.format_sql_value(create_date)}, {self.format_sql_value(write_date)}, 1, NULL, NULL, NULL, NULL
FROM res_partner WHERE name = {self.format_sql_value(vendor_name)} LIMIT 1;"""
        
        return sql, vendor_name
    
    def generate_purchase_order_line_sql(self, line_item: Dict, po_line_id: int, po_id: int, sequence: int, vendor_name: str) -> str:
        """Generate SQL INSERT statement for purchase_order_line"""
        
        # Get matched product and UoM
        product_id = None
        product_uom_id = None
        db_product_name = None
        db_uom_name = None
        
        if 'product_match' in line_item and line_item['product_match']:
            product_id = line_item['product_match']['product_id']
            db_product_name = line_item['product_match'].get('name', '')
        
        if 'uom_match' in line_item and line_item['uom_match']:
            product_uom_id = line_item['uom_match']['id']
            db_uom_name = line_item['uom_match'].get('name', '')
            logger.debug(f"Using matched UoM ID {product_uom_id} ({db_uom_name})")
        else:
            # Default to Units (UoM ID 1)
            product_uom_id = 1
            db_uom_name = 'Units'
            logger.warning(f"No UoM match found, using default Units (ID 1)")
        
        if not product_id:
            logger.warning(f"No product match for: {line_item.get('product_name', 'Unknown')}")
            # Use a placeholder or skip
            return None
        
        # Get item data
        receipt_item = line_item.get('receipt_item', {})
        original_product_name = receipt_item.get('product_name', '')
        product_qty = receipt_item.get('quantity', 1.0)
        price_unit = receipt_item.get('unit_price', 0.0)
        price_subtotal = receipt_item.get('total_price', 0.0)
        price_total = price_subtotal
        product_uom_qty = product_qty  # Default to same as product_qty
        
        # Get original receipt values (before conversion)
        original_qty = receipt_item.get('original_weight_lb')
        original_uom = receipt_item.get('original_uom', receipt_item.get('receipt_uom', receipt_item.get('purchase_uom', 'each')))
        original_unit_price = receipt_item.get('original_unit_price_per_lb')
        is_converted = receipt_item.get('converted', False)
        
        # Get database product name if not from match
        if not db_product_name:
            db_product_name = receipt_item.get('database_product_name', '')
        
        # Build detailed comment showing original receipt info and Odoo mapping
        comment_lines = []
        comment_lines.append(f"-- Receipt Line {sequence // 10}: {original_product_name}")
        comment_lines.append(f"-- =================================================")
        comment_lines.append(f"-- ORIGINAL RECEIPT INFORMATION:")
        comment_lines.append(f"--   Product Name (from receipt): {original_product_name}")
        comment_lines.append(f"--   Quantity: {receipt_item.get('quantity', product_qty) if not is_converted else original_qty} {original_uom}")
        comment_lines.append(f"--   Unit Price: ${receipt_item.get('unit_price', price_unit) if not is_converted else original_unit_price:.4f} per {original_uom}")
        
        original_total = 0.0
        if is_converted and original_qty is not None and original_unit_price is not None:
            original_total = original_qty * original_unit_price
        else:
            original_total = receipt_item.get('total_price', price_subtotal)
        
        comment_lines.append(f"--   Total Price: ${original_total:.2f}")
        comment_lines.append(f"--")
        comment_lines.append(f"-- ODOO MAPPING:")
        comment_lines.append(f"--   Database Product ID: {product_id}")
        comment_lines.append(f"--   Database Product Name: {db_product_name or 'N/A'}")
        comment_lines.append(f"--   Database UoM ID: {product_uom_id}")
        comment_lines.append(f"--   Database UoM Name: {db_uom_name or 'N/A'}")
        comment_lines.append(f"--")
        comment_lines.append(f"-- UPDATED VALUES FOR SQL:")
        
        # Check if UoM conversion ratio was applied
        uom_conversion_applied = receipt_item.get('uom_conversion_applied', False)
        uom_conversion_ratio = receipt_item.get('uom_conversion_ratio', 1.0)
        original_receipt_qty = receipt_item.get('original_receipt_qty')
        original_receipt_unit_price = receipt_item.get('original_receipt_unit_price')
        
        if is_converted and original_qty is not None and original_unit_price is not None:
            # Show conversion details for fruits purchased by weight
            comment_lines.append(f"--   Original: {original_qty} {original_uom} @ ${original_unit_price:.4f}/{original_uom} = ${original_total:.2f}")
            comment_lines.append(f"--   Converted Quantity: {product_qty} {db_uom_name or 'units'}")
            comment_lines.append(f"--   Converted Unit Price: ${price_unit:.4f} per {db_uom_name or 'unit'}")
            comment_lines.append(f"--   Converted Total: ${price_subtotal:.2f}")
            
            # Show conversion calculation
            items_per_lb = None
            if hasattr(self.product_matcher, 'fruit_conversions') and db_product_name:
                fruit_conv = self.product_matcher.fruit_conversions.get(db_product_name)
                if fruit_conv:
                    items_per_lb = fruit_conv.get('items_per_lb')
            
            if items_per_lb:
                comment_lines.append(f"--   Conversion Logic: {original_qty} {original_uom} × {items_per_lb} items/{original_uom} = {product_qty} {db_uom_name or 'units'}")
        elif uom_conversion_applied and original_receipt_qty is not None and original_receipt_unit_price is not None:
            # Show UoM conversion ratio details
            original_receipt_total = original_receipt_qty * original_receipt_unit_price
            comment_lines.append(f"--   Original (receipt): {original_receipt_qty} {original_uom} @ ${original_receipt_unit_price:.4f}/{original_uom} = ${original_receipt_total:.2f}")
            comment_lines.append(f"--   Converted Quantity: {product_qty} {db_uom_name or original_uom}")
            comment_lines.append(f"--   Converted Unit Price: ${price_unit:.4f} per {db_uom_name or original_uom}")
            comment_lines.append(f"--   Converted Total: ${price_subtotal:.2f}")
            comment_lines.append(f"--   Conversion Ratio: {original_receipt_qty} {original_uom} × {uom_conversion_ratio} = {product_qty} {db_uom_name or original_uom}")
            comment_lines.append(f"--   Unit Price: ${original_receipt_unit_price:.4f}/{original_uom} ÷ {uom_conversion_ratio} = ${price_unit:.4f}/{db_uom_name or original_uom}")
        else:
            # No conversion - show receipt values
            comment_lines.append(f"--   Quantity: {product_qty} {db_uom_name or original_uom}")
            comment_lines.append(f"--   Unit Price: ${price_unit:.4f} per {db_uom_name or original_uom}")
            comment_lines.append(f"--   Total: ${price_subtotal:.2f}")
        
        comment = '\n'.join(comment_lines)
        
        # Get dates
        order_date = receipt_item.get('order_date')
        if isinstance(order_date, str):
            try:
                order_date = datetime.fromisoformat(order_date.replace('Z', '+00:00'))
            except:
                order_date = datetime.now()
        elif order_date is None:
            order_date = datetime.now()
        
        date_planned = order_date.strftime('%Y-%m-%d %H:%M:%S')
        create_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        write_date = create_date
        
        # Purchase Order Line columns (from actual Odoo structure)
        # Look up partner_id from vendor_name (same as in PO insert)
        sql = f"""{comment}
INSERT INTO purchase_order_line (id, sequence, product_uom, product_id, order_id, company_id, partner_id, currency_id, product_packaging_id, create_uid, write_uid, state, qty_received_method, display_type, analytic_distribution, name, product_qty, discount, price_unit, price_subtotal, price_total, qty_invoiced, qty_received, qty_received_manual, qty_to_invoice, is_downpayment, date_planned, create_date, write_date, product_uom_qty, price_tax, product_packaging_qty, orderpoint_id, location_final_id, group_id, product_description_variants, propagate_cancel)
SELECT {po_line_id}, {sequence}, {product_uom_id}, {product_id}, {po_id}, 1, rp.id, 1, NULL, 2, 2, 'draft', 'stock_moves', NULL, NULL, {self.format_sql_value(original_product_name)}, {product_qty}, 0.00, {price_unit}, {price_subtotal}, {price_total}, 0.00, 0.00, 0.00, 0.00, NULL, {self.format_sql_value(date_planned)}, {self.format_sql_value(create_date)}, {self.format_sql_value(write_date)}, {product_uom_qty}, 0, 0, NULL, NULL, NULL, NULL, TRUE
FROM res_partner rp 
WHERE rp.name = {self.format_sql_value(vendor_name)} 
LIMIT 1;"""
        
        return sql
    
    def process_receipt(self, receipt_path: Path, output_dir: Path) -> Optional[str]:
        """Process a single receipt and generate SQL"""
        
        logger.info(f"Processing receipt: {receipt_path.name}")
        
        try:
            # Process receipt
            receipt_data = self.receipt_processor.process_pdf(str(receipt_path))
            
            if not receipt_data or not receipt_data.get('items'):
                logger.warning(f"No items found in receipt: {receipt_path.name}")
                return None
            
            # Match products and UoMs
            if not self.product_matcher:
                logger.error("Product matcher not available")
                return None
            
            receipt_items = receipt_data.get('items', [])
            matched_items = self.product_matcher.match_receipt_items(receipt_items, config=self.config)
            
            # Filter out unmatched items
            matched_items = [item for item in matched_items if item.get('matched', False)]
            
            if not matched_items:
                logger.warning(f"No matched items for receipt: {receipt_path.name}")
                return None
            
            # Generate SQL
            # Use receipt order_id or filename to determine PO ID
            receipt_order_id = receipt_data.get('order_id')
            if receipt_order_id:
                # Extract numeric part for ID
                try:
                    po_id = int(receipt_order_id[-6:]) % 1000000  # Use last 6 digits
                except:
                    po_id = hash(receipt_path.name) % 1000000
            else:
                po_id = hash(receipt_path.name) % 1000000
            
            # Get original receipt total
            original_receipt_total = receipt_data.get('total', 0.0)
            original_subtotal = receipt_data.get('subtotal', 0.0)
            
            # Generate SQL statements
            sql_lines = []
            sql_lines.append("-- ============================================================================")
            sql_lines.append("-- SQL INSERT Statements for Purchase Order")
            sql_lines.append("-- ============================================================================")
            sql_lines.append(f"-- Receipt File: {receipt_path.name}")
            sql_lines.append(f"-- Order ID: {receipt_order_id or 'N/A'}")
            sql_lines.append(f"-- Receipt Date: {receipt_data.get('order_date') or receipt_data.get('delivery_date') or 'N/A'}")
            sql_lines.append(f"-- Vendor: {receipt_data.get('vendor') or receipt_data.get('store_name') or 'N/A'}")
            sql_lines.append(f"-- Original Receipt Total: ${original_receipt_total:.2f}")
            sql_lines.append(f"-- Generated: {datetime.now().isoformat()}")
            sql_lines.append("")
            sql_lines.append("-- Wrap in transaction to view all output")
            sql_lines.append("BEGIN;")
            sql_lines.append("")
            
            # Get vendor name for this receipt
            vendor_name = receipt_data.get('vendor') or receipt_data.get('store_name')
            if receipt_data.get('store_name'):
                # Instacart order: use IC-{store_name} format
                vendor_name = f"IC-{receipt_data.get('store_name', '')}"
            
            # Purchase Order
            sql_lines.append("-- Purchase Order")
            sql_lines.append("-- ===============")
            sql_lines.append(f"-- Vendor Name: {vendor_name}")
            po_sql, vendor_name_returned = self.generate_purchase_order_sql(receipt_data, po_id)
            if vendor_name_returned:
                vendor_name = vendor_name_returned
            sql_lines.append(po_sql)
            sql_lines.append("")
            
            # Purchase Order Lines
            sql_lines.append("-- Purchase Order Lines")
            sql_lines.append("-- ====================")
            sql_lines.append("")
            
            po_line_id = po_id * 100  # Start line IDs from PO ID * 100
            sequence = 10  # Start sequence at 10
            sql_line_totals = []
            
            for item in matched_items:
                line_sql = self.generate_purchase_order_line_sql(item, po_line_id, po_id, sequence, vendor_name)
                if line_sql:
                    sql_lines.append(line_sql)
                    sql_lines.append("")
                    
                    # Get line total for validation
                    receipt_item = item.get('receipt_item', {})
                    line_total = receipt_item.get('total_price', 0.0)
                    sql_line_totals.append(line_total)
                    
                    po_line_id += 1
                    sequence += 1
            
            # Calculate SQL total
            sql_total = sum(sql_line_totals)
            
            # Add SELECT queries to view inserted data with product/UoM names
            sql_lines.append("-- View inserted Purchase Order with Product and UoM Names")
            sql_lines.append("-- ===========================================================")
            sql_lines.append(f"SELECT po.id, po.name, po.partner_id, rp.name as partner_name,")
            sql_lines.append(f"       po.amount_total, po.state, po.date_order")
            sql_lines.append(f"FROM purchase_order po")
            sql_lines.append(f"LEFT JOIN res_partner rp ON po.partner_id = rp.id")
            sql_lines.append(f"WHERE po.id = {po_id};")
            sql_lines.append("")
            sql_lines.append("-- View inserted Purchase Order Lines with Product and UoM Names")
            sql_lines.append("-- ==================================================================")
            sql_lines.append(f"SELECT pol.id, pol.sequence, pol.name as receipt_product_name,")
            sql_lines.append(f"       pol.product_id, pt.name->>'en_US' as odoo_product_name,")
            sql_lines.append(f"       pol.product_qty, pol.product_uom_qty,")
            sql_lines.append(f"       pol.product_uom, uom.name->>'en_US' as odoo_uom_name,")
            sql_lines.append(f"       pol.price_unit, pol.price_subtotal, pol.price_total")
            sql_lines.append(f"FROM purchase_order_line pol")
            sql_lines.append(f"LEFT JOIN product_product pp ON pol.product_id = pp.id")
            sql_lines.append(f"LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id")
            sql_lines.append(f"LEFT JOIN uom_uom uom ON pol.product_uom = uom.id")
            sql_lines.append(f"WHERE pol.order_id = {po_id}")
            sql_lines.append(f"ORDER BY pol.sequence;")
            sql_lines.append("")
            
            # Add total validation query
            sql_lines.append("-- Validate Total: Compare SQL Total with Original Receipt Total")
            sql_lines.append("-- ==================================================================")
            sql_lines.append(f"SELECT ")
            sql_lines.append(f"    po.amount_total as sql_total,")
            sql_lines.append(f"    {self.format_sql_value(original_receipt_total)} as original_receipt_total,")
            sql_lines.append(f"    po.amount_total - {original_receipt_total} as difference,")
            sql_lines.append(f"    CASE ")
            sql_lines.append(f"        WHEN ABS(po.amount_total - {original_receipt_total}) < 0.01 THEN 'MATCH'")
            sql_lines.append(f"        ELSE 'MISMATCH'")
            sql_lines.append(f"    END as validation_status")
            sql_lines.append(f"FROM purchase_order po")
            sql_lines.append(f"WHERE po.id = {po_id};")
            sql_lines.append("")
            
            # Add summary with line-by-line totals
            sql_lines.append("-- Summary: Line-by-Line Totals")
            sql_lines.append("-- ===========================================================")
            sql_lines.append(f"SELECT ")
            sql_lines.append(f"    pol.sequence,")
            sql_lines.append(f"    pol.name as receipt_product_name,")
            sql_lines.append(f"    pt.name->>'en_US' as odoo_product_name,")
            sql_lines.append(f"    pol.product_qty || ' ' || COALESCE(uom.name->>'en_US', 'N/A') as quantity_uom,")
            sql_lines.append(f"    pol.price_unit as unit_price,")
            sql_lines.append(f"    pol.price_subtotal as line_total")
            sql_lines.append(f"FROM purchase_order_line pol")
            sql_lines.append(f"LEFT JOIN product_product pp ON pol.product_id = pp.id")
            sql_lines.append(f"LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id")
            sql_lines.append(f"LEFT JOIN uom_uom uom ON pol.product_uom = uom.id")
            sql_lines.append(f"WHERE pol.order_id = {po_id}")
            sql_lines.append(f"ORDER BY pol.sequence;")
            sql_lines.append("")
            sql_lines.append(f"-- Calculate sum of all line totals")
            sql_lines.append(f"SELECT ")
            sql_lines.append(f"    SUM(pol.price_subtotal) as calculated_total,")
            sql_lines.append(f"    po.amount_total as po_total,")
            sql_lines.append(f"    {self.format_sql_value(original_receipt_total)} as original_receipt_total")
            sql_lines.append(f"FROM purchase_order_line pol")
            sql_lines.append(f"JOIN purchase_order po ON pol.order_id = po.id")
            sql_lines.append(f"WHERE pol.order_id = {po_id};")
            sql_lines.append("")
            sql_lines.append("-- Commit transaction (or ROLLBACK to undo)")
            sql_lines.append("COMMIT;")
            sql_lines.append("-- ROLLBACK;  -- Uncomment to undo all changes")
            
            # Generate output filename
            receipt_stem = receipt_path.stem
            if receipt_order_id:
                sql_filename = f"purchase_order_{receipt_order_id}.sql"
            else:
                sql_filename = f"purchase_order_{receipt_stem}.sql"
            
            output_path = output_dir / sql_filename
            
            # Save SQL file
            with open(output_path, 'w') as f:
                f.write('\n'.join(sql_lines))
            
            logger.info(f"✓ Generated SQL file: {output_path.name} ({len(matched_items)} lines)")
            return str(output_path)
        
        except Exception as e:
            logger.error(f"Error processing receipt {receipt_path.name}: {e}", exc_info=True)
            return None
    
    def process_all_receipts(self, receipts_dir: Path, output_dir: Path):
        """Process all receipts in a directory"""
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Find all PDF receipts
        receipt_folders = [d for d in receipts_dir.iterdir() if d.is_dir()]
        
        # Also find individual PDF files in the receipts directory (non-Instacart receipts)
        individual_pdfs = list(receipts_dir.glob('*.pdf'))
        
        if not receipt_folders and not individual_pdfs:
            logger.warning(f"No receipt folders or PDF files found in: {receipts_dir}")
            return
        
        total_receipts = len(receipt_folders) + len(individual_pdfs)
        logger.info(f"Found {len(receipt_folders)} receipt folder(s) and {len(individual_pdfs)} individual PDF file(s)")
        logger.info("="*60)
        
        success_count = 0
        failed_count = 0
        
        # Process PDFs in folders (Instacart receipts)
        for folder in receipt_folders:
            # Find PDF files in folder
            pdf_files = list(folder.glob('*.pdf'))
            
            if not pdf_files:
                logger.warning(f"No PDF files found in: {folder.name}")
                continue
            
            # Process each PDF (usually one per folder)
            for pdf_file in pdf_files:
                result = self.process_receipt(pdf_file, output_dir)
                if result:
                    success_count += 1
                else:
                    failed_count += 1
        
        # Process individual PDF files in receipts directory (non-Instacart receipts)
        for pdf_file in individual_pdfs:
            result = self.process_receipt(pdf_file, output_dir)
            if result:
                success_count += 1
            else:
                failed_count += 1
        
        logger.info("="*60)
        logger.info(f"Processing complete!")
        logger.info(f"  Success: {success_count}")
        logger.info(f"  Failed: {failed_count}")
        logger.info(f"  Output directory: {output_dir}")
        
        return {
            'success': success_count,
            'failed': failed_count,
            'output_dir': str(output_dir),
        }


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate SQL INSERT statements for all receipts')
    parser.add_argument('--receipts-dir', type=str, 
                       default='../odoo_data/receipts',
                       help='Directory containing receipt folders')
    parser.add_argument('--output-dir', type=str,
                       default='../odoo_data/analysis/receipt_sql',
                       help='Output directory for SQL files')
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run mode (show what would be processed)')
    
    args = parser.parse_args()
    
    receipts_dir = Path(args.receipts_dir)
    output_dir = Path(args.output_dir)
    
    if not receipts_dir.exists():
        logger.error(f"Receipts directory not found: {receipts_dir}")
        sys.exit(1)
    
    # Setup config
    config = {
        'DB_DUMP_JSON': DB_DUMP_JSON,
        'FEE_PRODUCTS': FEE_PRODUCTS,
        'FRUIT_WEIGHT_CONVERSION': FRUIT_WEIGHT_CONVERSION,
        'BANANA_CONVERSION': BANANA_CONVERSION,
        'PRODUCT_MAPPING_FILE': PRODUCT_MAPPING_FILE,
        'FRUIT_CONVERSION_FILE': FRUIT_CONVERSION_FILE,
    }
    
    # Create generator
    generator = ReceiptSQLGenerator(config)
    
    if args.dry_run:
        logger.info("DRY RUN MODE - No files will be created")
        logger.info(f"Would process receipts from: {receipts_dir}")
        logger.info(f"Would output SQL files to: {output_dir}")
        
        # List receipt folders
        receipt_folders = [d for d in receipts_dir.iterdir() if d.is_dir()]
        logger.info(f"Found {len(receipt_folders)} receipt folder(s):")
        for folder in receipt_folders:
            pdf_files = list(folder.glob('*.pdf'))
            logger.info(f"  {folder.name}: {len(pdf_files)} PDF file(s)")
    else:
        # Process all receipts
        generator.process_all_receipts(receipts_dir, output_dir)


if __name__ == '__main__':
    main()

