#!/usr/bin/env python3
"""
Generate a transaction summary Excel file from all extracted receipt data.
Lists all transactions with date, vendor, receipt number, and total amount.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


def extract_transaction_fields(receipt_id: str, receipt_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract transaction-level fields from receipt data"""
    
    # Vendor info
    vendor = receipt_data.get('vendor', '') or receipt_data.get('vendor_name', '')
    vendor_code = receipt_data.get('vendor_code', '') or receipt_data.get('detected_vendor_code', '')
    
    # Receipt/Order number
    receipt_number = receipt_data.get('receipt_number', '') or receipt_data.get('order_number', '') or receipt_id
    
    # Dates - prioritize transaction_date, then order_date, then delivery_date
    transaction_date = receipt_data.get('transaction_date', '')
    order_date = receipt_data.get('order_date', '')
    delivery_date = receipt_data.get('delivery_date', '')
    invoice_date = receipt_data.get('invoice_date', '')
    
    # Use the first available date
    date_used = transaction_date or order_date or delivery_date or invoice_date
    date_field_used = 'transaction_date' if transaction_date else ('order_date' if order_date else ('delivery_date' if delivery_date else 'invoice_date'))
    
    # Totals
    total = receipt_data.get('total', 0.0)
    subtotal = receipt_data.get('subtotal', 0.0)
    tax = receipt_data.get('tax', 0.0)
    
    # If total is 0 but subtotal and tax exist, calculate total
    if total == 0.0 and subtotal > 0:
        total = subtotal + tax
    
    # Source file
    source_file = receipt_data.get('filename', '') or receipt_data.get('source_file', '')
    
    # Item count
    items = receipt_data.get('items', [])
    item_count = len([item for item in items if not item.get('is_fee', False) and not item.get('is_summary', False)])
    
    # Currency
    currency = receipt_data.get('currency', 'USD')
    
    # Build transaction record
    transaction = {
        'transaction_date': transaction_date,
        'order_date': order_date,
        'delivery_date': delivery_date,
        'invoice_date': invoice_date,
        'date_used': date_used,
        'date_field_used': date_field_used,
        'vendor': vendor,
        'vendor_code': vendor_code,
        'receipt_number': receipt_number,
        'order_number': receipt_data.get('order_number', ''),
        'subtotal': subtotal,
        'tax': tax,
        'total': total,
        'currency': currency,
        'item_count': item_count,
        'source_file': source_file,
        'receipt_id': receipt_id,
    }
    
    return transaction


def generate_transaction_list(output_dir: Path, output_file: Optional[Path] = None) -> Path:
    """Generate transaction summary Excel file"""
    
    # Load all extracted data
    extracted_data_dir = output_dir.parent if output_dir.name == 'artifacts' else output_dir
    all_receipts = load_all_extracted_data(extracted_data_dir)
    
    if not all_receipts:
        logger.error("No extracted data found")
        return None
    
    # Extract all transactions
    all_transactions = []
    for receipt_id, receipt_data in all_receipts.items():
        transaction = extract_transaction_fields(receipt_id, receipt_data)
        all_transactions.append(transaction)
    
    if not all_transactions:
        logger.warning("No transactions found")
        return None
    
    # Create DataFrame
    df = pd.DataFrame(all_transactions)
    
    # Sort by date (most recent first)
    if 'date_used' in df.columns:
        # Convert dates to datetime for sorting, handling various formats
        df['date_sort'] = pd.to_datetime(df['date_used'], errors='coerce', format='%m/%d/%Y')
        df = df.sort_values('date_sort', ascending=False, na_position='last')
        df = df.drop('date_sort', axis=1)
    
    # Define column order for main sheet
    column_order = [
        'transaction_date',
        'order_date',
        'delivery_date',
        'date_used',
        'vendor',
        'vendor_code',
        'receipt_number',
        'order_number',
        'subtotal',
        'tax',
        'total',
        'currency',
        'item_count',
        'source_file',
        'receipt_id',
    ]
    
    # Reorder columns (only include columns that exist)
    existing_columns = [col for col in column_order if col in df.columns]
    df_main = df[existing_columns]
    
    # Create summary statistics
    summary_data = {
        'Metric': [
            'Total Transactions',
            'Total Amount',
            'Average Transaction',
            'Largest Transaction',
            'Smallest Transaction',
            'Total Items',
            'Average Items per Transaction',
            'Unique Vendors',
        ],
        'Value': [
            len(df),
            f"${df['total'].sum():.2f}",
            f"${df['total'].mean():.2f}",
            f"${df['total'].max():.2f}",
            f"${df['total'].min():.2f}",
            df['item_count'].sum(),
            f"{df['item_count'].mean():.2f}",
            df['vendor'].nunique(),
        ]
    }
    df_summary = pd.DataFrame(summary_data)
    
    # Group by vendor
    vendor_summary = df.groupby('vendor').agg({
        'total': ['count', 'sum', 'mean'],
        'item_count': 'sum',
    }).round(2)
    vendor_summary.columns = ['Transaction Count', 'Total Amount', 'Average Amount', 'Total Items']
    vendor_summary = vendor_summary.sort_values('Total Amount', ascending=False)
    vendor_summary = vendor_summary.reset_index()
    
    # Determine output file
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'transaction_list_{timestamp}.xlsx'
    else:
        # Ensure .xlsx extension
        if output_file.suffix.lower() != '.xlsx':
            output_file = output_file.with_suffix('.xlsx')
    
    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write Excel file with multiple sheets
    try:
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            # Sheet 1: All Transactions
            df_main.to_excel(writer, sheet_name='All Transactions', index=False)
            
            # Sheet 2: Summary Statistics
            df_summary.to_excel(writer, sheet_name='Summary', index=False)
            
            # Sheet 3: Vendor Summary
            vendor_summary.to_excel(writer, sheet_name='Vendor Summary', index=False)
            
            # Sheet 4: Transactions by Date (if date available)
            if 'date_used' in df.columns:
                df_by_date = df_main.copy()
                df_by_date = df_by_date[df_by_date['date_used'] != '']
                if len(df_by_date) > 0:
                    df_by_date = df_by_date.sort_values('date_used', ascending=False)
                    df_by_date.to_excel(writer, sheet_name='By Date', index=False)
        
        logger.info(f"Generated transaction list with {len(df)} transactions: {output_file}")
        
    except ImportError:
        logger.error("openpyxl not available. Install with: pip install openpyxl")
        # Fallback to CSV
        csv_file = output_file.with_suffix('.csv')
        df_main.to_csv(csv_file, index=False)
        logger.info(f"Generated transaction list as CSV: {csv_file}")
        output_file = csv_file
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Transaction List Summary")
    print(f"{'='*60}")
    print(f"Total transactions: {len(df)}")
    print(f"Total amount: ${df['total'].sum():.2f}")
    print(f"Average transaction: ${df['total'].mean():.2f}")
    print(f"Unique vendors: {df['vendor'].nunique()}")
    print(f"Total items: {df['item_count'].sum()}")
    print(f"Output file: {output_file}")
    print(f"{'='*60}\n")
    
    return output_file


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate transaction summary Excel file')
    parser.add_argument('--output-dir', type=Path, 
                       default=Path('data/step1_output'),
                       help='Output directory (default: data/step1_output)')
    parser.add_argument('--output-file', type=Path, default=None,
                       help='Output file path (default: auto-generated with timestamp)')
    
    args = parser.parse_args()
    
    output_file = generate_transaction_list(args.output_dir, args.output_file)
    
    if output_file:
        print(f"✅ Transaction list generated: {output_file}")
    else:
        print("❌ Failed to generate transaction list")
        return 1
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())

