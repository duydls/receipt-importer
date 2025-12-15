#!/usr/bin/env python3
"""
Generate Excel template for Product to Odoo Product Name Mapping

Creates an Excel file that can be used to map receipt product names to Odoo standard product names.
The Excel can be edited manually and then converted back to JSON format.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database


def get_odoo_products(conn) -> List[Dict[str, Any]]:
    """Get all products from Odoo database"""
    try:
        from psycopg2.extras import RealDictCursor
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    pp.id as product_id,
                    pt.id as template_id,
                    pt.name::text as product_name,
                    uom.id as uom_id,
                    uom.name::text as uom_name,
                    pc.complete_name::text as category_name,
                    pt.type as product_type
                FROM product_product pp
                LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                LEFT JOIN product_category pc ON pt.categ_id = pc.id
                WHERE pt.active = TRUE
                  AND (pt.type IN ('product', 'consu', 'service') OR pt.type IS NULL)
                ORDER BY pt.name
            """)
            
            products = []
            for row in cur.fetchall():
                products.append({
                    'product_id': row['product_id'],
                    'template_id': row['template_id'],
                    'product_name': extract_english_text(row['product_name']),
                    'uom_id': row['uom_id'],
                    'uom_name': extract_english_text(row['uom_name']) if row['uom_name'] else '',
                    'category_name': extract_english_text(row['category_name']) if row['category_name'] else '',
                    'product_type': row['product_type'] or 'consu'
                })
            
            return products
    except Exception as e:
        print(f"Error querying Odoo products: {e}")
        return []


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


def load_existing_mapping(mapping_file: Path) -> Dict[str, Dict[str, Any]]:
    """Load existing mapping file if it exists"""
    if not mapping_file.exists():
        return {}
    
    try:
        with open(mapping_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Remove metadata fields
            return {k: v for k, v in data.items() if not k.startswith('_')}
    except Exception as e:
        print(f"Warning: Could not load existing mapping: {e}")
        return {}


def generate_mapping_excel(
    output_file: Path,
    odoo_products: List[Dict[str, Any]],
    existing_mapping: Optional[Dict[str, Dict[str, Any]]] = None
):
    """
    Generate Excel file for product mapping
    
    Args:
        output_file: Path to output Excel file
        odoo_products: List of Odoo products
        existing_mapping: Existing mapping dictionary (optional)
    """
    # Create DataFrame with columns
    columns = [
        'Receipt Product Name',      # Key: Product name as it appears on receipt
        'Odoo Product ID',          # Odoo product_product.id
        'Odoo Product Name',          # Standard name in Odoo
        'Odoo Template ID',           # product_template.id (for reference)
        'Receipt UoM',                # UoM as it appears on receipt (optional)
        'Odoo UoM ID',                # Odoo UoM ID (optional)
        'Odoo UoM Name',              # Odoo UoM name (optional)
        'UoM Conversion Ratio',       # Conversion ratio if UoM differs (e.g., 4.0 for banana: 1 lb = 4 units)
        'Vendors',                    # Comma-separated list of vendors this mapping applies to
        'Category',                   # Product category (for reference)
        'Product Type',               # product, consu, or service (for reference)
        'Notes',                      # Any notes about this mapping
        'Active'                      # TRUE/FALSE - whether this mapping is active
    ]
    
    # Start with existing mappings if provided
    rows = []
    if existing_mapping:
        for receipt_name, mapping_data in existing_mapping.items():
            product_id = mapping_data.get('database_product_id') or mapping_data.get('product_id')
            product_name = mapping_data.get('database_product_name') or mapping_data.get('product_name', '')
            receipt_uom = mapping_data.get('receipt_uom', '')
            odoo_uom_id = mapping_data.get('odoo_uom_id', '')
            odoo_uom_name = mapping_data.get('odoo_uom_name', '')
            conversion_ratio = mapping_data.get('uom_conversion_ratio', '')
            vendors = ', '.join(mapping_data.get('vendors', [])) if isinstance(mapping_data.get('vendors'), list) else mapping_data.get('vendors', '')
            
            # Find product details from Odoo products list
            product_details = next((p for p in odoo_products if p['product_id'] == product_id), None)
            
            rows.append({
                'Receipt Product Name': receipt_name,
                'Odoo Product ID': product_id or '',
                'Odoo Product Name': product_name or (product_details['product_name'] if product_details else ''),
                'Odoo Template ID': product_details['template_id'] if product_details else '',
                'Receipt UoM': receipt_uom,
                'Odoo UoM ID': odoo_uom_id or (product_details['uom_id'] if product_details else ''),
                'Odoo UoM Name': odoo_uom_name or (product_details['uom_name'] if product_details else ''),
                'UoM Conversion Ratio': conversion_ratio,
                'Vendors': vendors,
                'Category': product_details['category_name'] if product_details else '',
                'Product Type': product_details['product_type'] if product_details else '',
                'Notes': mapping_data.get('notes', ''),
                'Active': mapping_data.get('active', True)
            })
    
    # Create DataFrame
    df = pd.DataFrame(rows, columns=columns)
    
    # If no existing mappings, create empty template with example row
    if df.empty:
        df = pd.DataFrame([{
            'Receipt Product Name': 'EXAMPLE: Chicken Breast',
            'Odoo Product ID': '',
            'Odoo Product Name': '',
            'Odoo Template ID': '',
            'Receipt UoM': '',
            'Odoo UoM ID': '',
            'Odoo UoM Name': '',
            'UoM Conversion Ratio': '',
            'Vendors': 'Costco, RD',
            'Category': '',
            'Product Type': '',
            'Notes': 'Example row - delete this and add your mappings',
            'Active': True
        }], columns=columns)
    
    # Create Excel writer with formatting
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Write main mapping sheet
        df.to_excel(writer, sheet_name='Product Mappings', index=False)
        
        # Get worksheet for formatting
        worksheet = writer.sheets['Product Mappings']
        
        # Set column widths
        column_widths = {
            'A': 30,  # Receipt Product Name
            'B': 15,  # Odoo Product ID
            'C': 40,  # Odoo Product Name
            'D': 15,  # Odoo Template ID
            'E': 15,  # Receipt UoM
            'F': 15,  # Odoo UoM ID
            'G': 20,  # Odoo UoM Name
            'H': 20,  # UoM Conversion Ratio
            'I': 30,  # Vendors
            'J': 30,  # Category
            'K': 15,  # Product Type
            'L': 40,  # Notes
            'M': 10,  # Active
        }
        
        for col, width in column_widths.items():
            worksheet.column_dimensions[col].width = width
        
        # Freeze first row
        worksheet.freeze_panes = 'A2'
        
        # Format header row
        from openpyxl.styles import Font, PatternFill, Alignment
        
        header_fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
        header_font = Font(bold=True, color='FFFFFF')
        
        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
        # Create Odoo Products reference sheet
        if odoo_products:
            products_df = pd.DataFrame(odoo_products)
            products_df = products_df[['product_id', 'product_name', 'uom_name', 'category_name', 'product_type']]
            products_df.columns = ['Product ID', 'Product Name', 'UoM Name', 'Category', 'Product Type']
            products_df.to_excel(writer, sheet_name='Odoo Products Reference', index=False)
            
            # Format products sheet
            products_worksheet = writer.sheets['Odoo Products Reference']
            products_worksheet.column_dimensions['A'].width = 15
            products_worksheet.column_dimensions['B'].width = 50
            products_worksheet.column_dimensions['C'].width = 20
            products_worksheet.column_dimensions['D'].width = 40
            products_worksheet.column_dimensions['E'].width = 15
            
            # Freeze first row
            products_worksheet.freeze_panes = 'A2'
            
            # Format header
            for cell in products_worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
        
        # Create Instructions sheet
        instructions = [
            ['Product to Odoo Product Name Mapping - Instructions', ''],
            ['', ''],
            ['Purpose', 'This Excel file maps receipt product names to Odoo standard product names.'],
            ['', ''],
            ['How to Use', ''],
            ['1.', 'Fill in the "Product Mappings" sheet with your mappings'],
            ['2.', 'Receipt Product Name: Product name as it appears on receipts'],
            ['3.', 'Odoo Product ID: The product_product.id from Odoo database'],
            ['4.', 'Odoo Product Name: Standard product name in Odoo (for reference)'],
            ['5.', 'Vendors: Comma-separated list of vendors (e.g., "Costco, RD, Instacart")'],
            ['6.', 'UoM Conversion Ratio: Only needed if receipt UoM differs from Odoo UoM'],
            ['', ''],
            ['Example', ''],
            ['Receipt Product Name', 'Chicken Breast'],
            ['Odoo Product ID', '12345'],
            ['Odoo Product Name', 'Chicken Breast'],
            ['Vendors', 'Costco, RD'],
            ['UoM Conversion Ratio', '1.0'],
            ['', ''],
            ['UoM Conversion Example', ''],
            ['Receipt Product Name', 'Banana'],
            ['Receipt UoM', 'lb'],
            ['Odoo UoM Name', 'Units'],
            ['UoM Conversion Ratio', '4.0'],
            ['Note', '1 lb of bananas = 4 units'],
            ['', ''],
            ['After Editing', ''],
            ['1.', 'Save the Excel file'],
            ['2.', 'Run: python scripts/convert_mapping_excel_to_json.py <excel_file>'],
            ['3.', 'This will generate/update the JSON mapping file'],
            ['', ''],
            ['Reference Sheets', ''],
            ['- Odoo Products Reference', 'List of all products in Odoo database for lookup'],
            ['', ''],
        ]
        
        instructions_df = pd.DataFrame(instructions, columns=['Column A', 'Column B'])
        instructions_df.to_excel(writer, sheet_name='Instructions', index=False)
        
        # Format instructions sheet
        instructions_worksheet = writer.sheets['Instructions']
        instructions_worksheet.column_dimensions['A'].width = 40
        instructions_worksheet.column_dimensions['B'].width = 60
        
        # Format title
        instructions_worksheet['A1'].font = Font(bold=True, size=14)
        instructions_worksheet['A1'].fill = header_fill
        instructions_worksheet['A1'].font = Font(bold=True, size=14, color='FFFFFF')
    
    print(f"✅ Generated Excel mapping template: {output_file}")
    print(f"   - Product Mappings sheet: {len(df)} rows")
    if odoo_products:
        print(f"   - Odoo Products Reference sheet: {len(odoo_products)} products")
    print(f"   - Instructions sheet included")


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate Excel template for Product to Odoo Product Name Mapping'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='data/product_mapping_template.xlsx',
        help='Output Excel file path (default: data/product_mapping_template.xlsx)'
    )
    parser.add_argument(
        '-m', '--mapping-file',
        type=str,
        default='data/product_standard_name_mapping.json',
        help='Existing mapping JSON file to load (default: data/product_standard_name_mapping.json)'
    )
    parser.add_argument(
        '--no-odoo-products',
        action='store_true',
        help='Skip loading Odoo products (faster, but no reference sheet)'
    )
    
    args = parser.parse_args()
    
    output_file = Path(args.output)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing mapping if it exists
    existing_mapping = None
    mapping_file = Path(args.mapping_file)
    if mapping_file.exists():
        print(f"Loading existing mapping from: {mapping_file}")
        existing_mapping = load_existing_mapping(mapping_file)
        print(f"   Loaded {len(existing_mapping)} existing mappings")
    
    # Load Odoo products
    odoo_products = []
    if not args.no_odoo_products:
        print("Connecting to Odoo database...")
        conn = connect_to_database()
        if conn:
            print("Loading Odoo products...")
            odoo_products = get_odoo_products(conn)
            print(f"   Loaded {len(odoo_products)} products from Odoo")
        else:
            print("   ⚠️  Could not connect to database. Generating template without Odoo products.")
    
    # Generate Excel
    print(f"\nGenerating Excel template...")
    generate_mapping_excel(output_file, odoo_products, existing_mapping)
    
    print(f"\n✅ Done! Edit the Excel file and then convert to JSON using:")
    print(f"   python scripts/convert_mapping_excel_to_json.py {output_file}")


if __name__ == '__main__':
    main()

