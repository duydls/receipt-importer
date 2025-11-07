#!/usr/bin/env python3
"""
Generate a comprehensive product list CSV from all extracted receipt data.
Includes all product details: name, quantity, size/uom, price, vendor, classifications, etc.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_category_names(rules_dir: Path) -> Dict[str, Dict[str, str]]:
    """Load L1 and L2 category names for display"""
    categories = {'L1': {}, 'L2': {}}
    
    try:
        import sys
        current_file = Path(__file__)
        project_root = current_file.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from step1_extract.rule_loader import RuleLoader
        
        if not rules_dir.exists():
            rules_dir = project_root / 'step1_rules'
        
        if not rules_dir.exists():
            logger.warning(f"Rules directory not found: {rules_dir}")
            return categories
        
        rule_loader = RuleLoader(rules_dir)
        
        # Load L1 categories
        l1_rules = rule_loader.load_rule_file_by_name('55_categories_l1.yaml')
        if l1_rules:
            l1_categories = l1_rules.get('categories_l1', {}).get('l1_categories', [])
            for cat in l1_categories:
                cat_id = cat.get('id', '')
                cat_name = cat.get('name', '')
                if cat_id:
                    categories['L1'][cat_id] = cat_name
        
        # Load L2 categories
        l2_rules = rule_loader.load_rule_file_by_name('56_categories_l2.yaml')
        if l2_rules:
            l2_categories = l2_rules.get('categories_l2', {}).get('l2_categories', [])
            for cat in l2_categories:
                cat_id = cat.get('id', '')
                cat_name = cat.get('name', '')
                if cat_id:
                    categories['L2'][cat_id] = cat_name
        
        logger.info(f"Loaded {len(categories['L1'])} L1 and {len(categories['L2'])} L2 categories")
        
    except Exception as e:
        logger.warning(f"Could not load category names: {e}")
    
    return categories


def extract_product_fields(item: Dict[str, Any], receipt_data: Dict[str, Any], 
                          categories: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """Extract all product fields from an item"""
    
    # Product names
    product_name = item.get('product_name', '') or item.get('display_name', '') or item.get('clean_name', '')
    canonical_name = item.get('canonical_name', '') or item.get('clean_name', '')
    raw_name = item.get('raw_name_original', '') or product_name
    
    # Quantities and prices
    quantity = item.get('quantity', 0.0)
    unit_price = item.get('unit_price', 0.0)
    total_price = item.get('total_price', 0.0) or item.get('extended_amount', 0.0)
    
    # Size and UoM
    purchase_uom = item.get('purchase_uom', '') or item.get('raw_uom_text', '')
    size_spec = item.get('size_spec', '') or item.get('raw_size_text', '')
    pack_count = item.get('pack_count', '')
    unit_size = item.get('unit_size', '')
    unit_uom = item.get('unit_uom', '')
    
    # Knowledge base info
    kb_name = item.get('kb_name', '')
    kb_size = item.get('kb_size', '')
    kb_spec = item.get('kb_spec', '')
    kb_source = item.get('kb_source', '')
    kb_name_mismatch = item.get('kb_name_mismatch', False)
    
    # Identifiers
    upc = str(item.get('upc', '')).strip() or ''
    item_number = str(item.get('item_number', '')).strip() or ''
    
    # Vendor info
    vendor = receipt_data.get('vendor', '') or receipt_data.get('vendor_name', '')
    vendor_code = receipt_data.get('vendor_code', '') or receipt_data.get('detected_vendor_code', '')
    
    # Receipt info
    receipt_number = receipt_data.get('receipt_number', '') or receipt_data.get('order_number', '')
    transaction_date = receipt_data.get('transaction_date', '') or receipt_data.get('order_date', '') or receipt_data.get('receipt_date', '')
    source_file = receipt_data.get('filename', '') or receipt_data.get('source_file', '')
    
    # Classifications
    l1_code = item.get('l1_category', '')
    l2_code = item.get('l2_category', '')
    l1_name = categories['L1'].get(l1_code, '') if l1_code else ''
    l2_name = categories['L2'].get(l2_code, '') if l2_code else ''
    category_source = item.get('category_source', '')
    category_confidence = item.get('category_confidence', 0.0)
    category_rule_id = item.get('category_rule_id', '')
    
    # Review flags
    needs_review = item.get('needs_review', False) or item.get('needs_category_review', False)
    review_reasons = item.get('review_reasons', [])
    if item.get('needs_category_review', False):
        review_reasons.append('category_review')
    if item.get('needs_quantity_review', False):
        review_reasons.append('quantity_review')
    review_reason = '; '.join(review_reasons) if review_reasons else ''
    
    # Other fields
    brand = item.get('brand', '')
    is_fee = item.get('is_fee', False)
    is_summary = item.get('is_summary', False)
    cogs_include = not is_fee and not is_summary
    
    # Build product record
    product = {
        # Identifiers
        'receipt_number': receipt_number,
        'source_file': source_file,
        'line_id': item.get('line_id', ''),
        
        # Vendor
        'vendor': vendor,
        'vendor_code': vendor_code,
        
        # Dates
        'transaction_date': transaction_date,
        
        # Product names
        'product_name': product_name,
        'canonical_name': canonical_name,
        'raw_name': raw_name,
        'brand': brand,
        
        # Identifiers
        'upc': upc,
        'item_number': item_number,
        
        # Quantities
        'quantity': quantity,
        'purchase_uom': purchase_uom,
        
        # Size information
        'size_spec': size_spec,
        'pack_count': pack_count if pack_count else '',
        'unit_size': unit_size if unit_size else '',
        'unit_uom': unit_uom if unit_uom else '',
        
        # Knowledge base
        'kb_name': kb_name,
        'kb_size': kb_size,
        'kb_spec': kb_spec,
        'kb_source': kb_source,
        'kb_name_mismatch': 'Yes' if kb_name_mismatch else 'No',
        
        # Pricing
        'unit_price': unit_price,
        'total_price': total_price,
        'unit_price_uom': item.get('unit_price_uom', ''),
        
        # Classifications
        'L1_code': l1_code,
        'L1_name': l1_name,
        'L2_code': l2_code,
        'L2_name': l2_name,
        'category_source': category_source,
        'category_confidence': category_confidence,
        'category_rule_id': category_rule_id,
        
        # Review flags
        'needs_review': 'Yes' if needs_review else 'No',
        'review_reason': review_reason,
        'cogs_include': 'Yes' if cogs_include else 'No',
        'is_fee': 'Yes' if is_fee else 'No',
        'is_summary': 'Yes' if is_summary else 'No',
    }
    
    return product


def load_all_extracted_data(output_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load all extracted data from all vendor groups"""
    all_receipts = {}
    
    vendor_groups = [
        'localgrocery_based',
        'instacart_based',
        'bbi_based',
        'amazon_based',
        'webstaurantstore_based',
        'wismettac_based',
        'odoo_based',
    ]
    
    for group in vendor_groups:
        json_file = output_dir / group / 'extracted_data.json'
        if json_file.exists():
            try:
                with json_file.open() as f:
                    data = json.load(f)
                    all_receipts.update(data)
                    logger.info(f"Loaded {len(data)} receipts from {group}")
            except Exception as e:
                logger.warning(f"Could not load {json_file}: {e}")
    
    return all_receipts


def generate_product_list(output_dir: Path, output_file: Optional[Path] = None) -> Path:
    """Generate comprehensive product list CSV"""
    
    # Load category names
    current_file = Path(__file__)
    project_root = current_file.parent.parent
    rules_dir = project_root / 'step1_rules'
    categories = load_category_names(rules_dir)
    
    # Load all extracted data
    extracted_data_dir = output_dir.parent if output_dir.name == 'artifacts' else output_dir
    all_receipts = load_all_extracted_data(extracted_data_dir)
    
    if not all_receipts:
        logger.error("No extracted data found")
        return None
    
    # Extract all products
    all_products = []
    for receipt_id, receipt_data in all_receipts.items():
        items = receipt_data.get('items', [])
        for item in items:
            # Skip fees and summary items if user wants only products
            # But include them for completeness
            product = extract_product_fields(item, receipt_data, categories)
            all_products.append(product)
    
    if not all_products:
        logger.warning("No products found")
        return None
    
    # Create DataFrame
    df = pd.DataFrame(all_products)
    
    # Define column order
    column_order = [
        # Identifiers
        'receipt_number',
        'source_file',
        'line_id',
        
        # Vendor
        'vendor',
        'vendor_code',
        
        # Dates
        'transaction_date',
        
        # Product names
        'product_name',
        'canonical_name',
        'raw_name',
        'brand',
        
        # Identifiers
        'upc',
        'item_number',
        
        # Quantities
        'quantity',
        'purchase_uom',
        
        # Size information
        'size_spec',
        'pack_count',
        'unit_size',
        'unit_uom',
        
        # Knowledge base
        'kb_name',
        'kb_size',
        'kb_spec',
        'kb_source',
        'kb_name_mismatch',
        
        # Pricing
        'unit_price',
        'total_price',
        'unit_price_uom',
        
        # Classifications
        'L1_code',
        'L1_name',
        'L2_code',
        'L2_name',
        'category_source',
        'category_confidence',
        'category_rule_id',
        
        # Review flags
        'needs_review',
        'review_reason',
        'cogs_include',
        'is_fee',
        'is_summary',
    ]
    
    # Reorder columns (only include columns that exist)
    existing_columns = [col for col in column_order if col in df.columns]
    df = df[existing_columns]
    
    # Determine output file
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'product_list_{timestamp}.csv'
    
    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write CSV
    df.to_csv(output_file, index=False)
    logger.info(f"Generated product list with {len(df)} products: {output_file}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Product List Summary")
    print(f"{'='*60}")
    print(f"Total products: {len(df)}")
    print(f"Unique products (by canonical_name): {df['canonical_name'].nunique() if 'canonical_name' in df.columns else 'N/A'}")
    print(f"Vendors: {df['vendor'].nunique() if 'vendor' in df.columns else 'N/A'}")
    print(f"Receipts: {df['receipt_number'].nunique() if 'receipt_number' in df.columns else 'N/A'}")
    print(f"With UPC: {len(df[df['upc'] != '']) if 'upc' in df.columns else 'N/A'}")
    print(f"With L2 classification: {len(df[df['L2_code'] != '']) if 'L2_code' in df.columns else 'N/A'}")
    print(f"Needs review: {len(df[df['needs_review'] == 'Yes']) if 'needs_review' in df.columns else 'N/A'}")
    print(f"Output file: {output_file}")
    print(f"{'='*60}\n")
    
    return output_file


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate comprehensive product list CSV')
    parser.add_argument('--output-dir', type=Path, 
                       default=Path('data/step1_output'),
                       help='Output directory (default: data/step1_output)')
    parser.add_argument('--output-file', type=Path, default=None,
                       help='Output file path (default: auto-generated with timestamp)')
    
    args = parser.parse_args()
    
    output_file = generate_product_list(args.output_dir, args.output_file)
    
    if output_file:
        print(f"✅ Product list generated: {output_file}")
    else:
        print("❌ Failed to generate product list")
        return 1
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())

