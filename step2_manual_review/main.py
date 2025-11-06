#!/usr/bin/env python3
"""
Step 2: Manual Review Export
Exports Step 1 extracted data to Excel for manual review and corrections.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)


def export_to_excel(
    input_dir: Path,
    output_dir: Path,
    filename: str = "manual_review_export.xlsx"
) -> Path:
    """
    Export Step 1 extracted data to Excel for manual review.
    
    Args:
        input_dir: Step 1 output directory (contains extracted_data.json files)
        output_dir: Output directory for Excel file
        filename: Output Excel filename
        
    Returns:
        Path to generated Excel file
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / filename
    
    # Load all Step 1 output files
    all_items = []
    
    # Source types to process
    source_types = [
        'localgrocery_based',
        'instacart_based',
        'bbi_based',
        'amazon_based',
        'webstaurantstore_based'
    ]
    
    for source_type in source_types:
        json_file = input_dir / source_type / 'extracted_data.json'
        if not json_file.exists():
            continue
            
        logger.info(f"Loading {source_type} data from {json_file}")
        with open(json_file, 'r', encoding='utf-8') as f:
            receipts_data = json.load(f)
        
        # Flatten receipts into items with receipt metadata
        for receipt_id, receipt_data in receipts_data.items():
            items = receipt_data.get('items', [])
            receipt_needs_review = receipt_data.get('needs_review', False)
            receipt_review_reasons = receipt_data.get('review_reasons', [])
            
            for item in items:
                item_needs_review = item.get('needs_review', False) or item.get('needs_category_review', False)
                
                # Include items that need review OR items from receipts that need review
                if item_needs_review or receipt_needs_review:
                    row = {
                        # Receipt metadata
                        'receipt_id': receipt_id,
                        'receipt_filename': receipt_data.get('filename', ''),
                        'receipt_vendor': receipt_data.get('vendor', ''),
                        'receipt_date': receipt_data.get('order_date') or receipt_data.get('transaction_date', ''),
                        'receipt_total': receipt_data.get('total', 0.0),
                        'receipt_needs_review': receipt_needs_review,
                        'receipt_review_reasons': '; '.join(receipt_review_reasons),
                        
                        # Item fields
                        'item_index': items.index(item),
                        'upc': item.get('upc', ''),
                        'item_number': item.get('item_number', ''),
                        'product_name': item.get('product_name', ''),
                        'display_name': item.get('display_name') or item.get('clean_name') or item.get('product_name', ''),
                        'quantity': item.get('quantity', 0),
                        'unit_price': item.get('unit_price', 0),
                        'total_price': item.get('total_price', 0),
                        'purchase_uom': item.get('purchase_uom', ''),
                        'raw_uom_text': item.get('raw_uom_text', ''),
                        
                        # Category fields
                        'l1_category': item.get('l1_category', ''),
                        'l1_category_name': item.get('l1_category_name', ''),
                        'l2_category': item.get('l2_category', ''),
                        'l2_category_name': item.get('l2_category_name', ''),
                        'category_source': item.get('category_source', ''),
                        'category_confidence': item.get('category_confidence', 0),
                        'needs_category_review': item.get('needs_category_review', False),
                        
                        # Review flags
                        'item_needs_review': item_needs_review,
                        'is_fee': item.get('is_fee', False),
                        'is_summary': item.get('is_summary', False),
                        
                        # Manual review columns (editable)
                        'reviewed_product_name': '',  # User can edit
                        'reviewed_quantity': '',  # User can edit
                        'reviewed_unit_price': '',  # User can edit
                        'reviewed_total_price': '',  # User can edit
                        'reviewed_l1_category': '',  # User can edit
                        'reviewed_l2_category': '',  # User can edit
                        'reviewed_purchase_uom': '',  # User can edit
                        'review_notes': '',  # User can add notes
                        'review_status': '',  # User can mark: 'approved', 'needs_fix', 'skip'
                        
                        # Source metadata
                        'source_type': receipt_data.get('detected_source_type', source_type),
                        'source_group': receipt_data.get('source_group', source_type),
                        'parsed_by': receipt_data.get('parsed_by', ''),
                    }
                    all_items.append(row)
    
    if not all_items:
        logger.info("No items found that need review")
        return output_file
    
    # Create DataFrame
    df = pd.DataFrame(all_items)
    
    # Sort by: receipt_needs_review (True first), then item_needs_review (True first), then receipt_id
    df = df.sort_values(
        by=['receipt_needs_review', 'item_needs_review', 'receipt_id'],
        ascending=[False, False, True]
    )
    
    # Reset index
    df = df.reset_index(drop=True)
    
    # Write to Excel with formatting
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Manual Review', index=False)
        
        # Get worksheet for formatting
        worksheet = writer.sheets['Manual Review']
        
        # Auto-adjust column widths
        for idx, col in enumerate(df.columns):
            max_length = max(
                df[col].astype(str).map(len).max(),
                len(str(col))
            )
            # Cap at 50 characters for readability
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[chr(65 + idx)].width = adjusted_width
    
    logger.info(f"Exported {len(all_items)} items to {output_file}")
    return output_file


def load_reviewed_excel(excel_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load reviewed Excel file and return updated items grouped by receipt.
    
    Args:
        excel_path: Path to reviewed Excel file
        
    Returns:
        Dictionary mapping receipt_id to list of reviewed items
    """
    if not excel_path.exists():
        logger.warning(f"Reviewed Excel file not found: {excel_path}")
        return {}
    
    df = pd.read_excel(excel_path, sheet_name='Manual Review')
    
    # Group by receipt_id
    reviewed_data = {}
    
    for _, row in df.iterrows():
        receipt_id = str(row.get('receipt_id', ''))
        if not receipt_id:
            continue
        
        if receipt_id not in reviewed_data:
            reviewed_data[receipt_id] = []
        
        # Build reviewed item (only include fields that were edited)
        reviewed_item = {
            'item_index': int(row.get('item_index', -1)),
        }
        
        # Use reviewed values if provided, otherwise keep original
        for field in ['product_name', 'quantity', 'unit_price', 'total_price', 
                     'l1_category', 'l2_category', 'purchase_uom']:
            reviewed_field = f'reviewed_{field}'
            if pd.notna(row.get(reviewed_field)) and str(row[reviewed_field]).strip():
                # Convert to appropriate type
                value = row[reviewed_field]
                if field in ['quantity', 'unit_price', 'total_price']:
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        continue
                reviewed_item[field] = value
        
        # Add review notes and status
        if pd.notna(row.get('review_notes')):
            reviewed_item['review_notes'] = str(row['review_notes'])
        if pd.notna(row.get('review_status')):
            reviewed_item['review_status'] = str(row['review_status'])
        
        reviewed_data[receipt_id].append(reviewed_item)
    
    logger.info(f"Loaded reviewed data for {len(reviewed_data)} receipts from {excel_path}")
    return reviewed_data


def apply_reviewed_data(
    extracted_data: Dict[str, Dict[str, Any]],
    reviewed_data: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Dict[str, Any]]:
    """
    Apply reviewed data from Excel back to extracted data.
    
    Args:
        extracted_data: Original Step 1 extracted data
        reviewed_data: Reviewed items from Excel
        
    Returns:
        Updated extracted data with reviewed values applied
    """
    updated_data = extracted_data.copy()
    
    for receipt_id, reviewed_items in reviewed_data.items():
        if receipt_id not in updated_data:
            logger.warning(f"Receipt {receipt_id} not found in extracted data")
            continue
        
        receipt = updated_data[receipt_id]
        items = receipt.get('items', [])
        
        # Create lookup by item_index
        reviewed_lookup = {item['item_index']: item for item in reviewed_items}
        
        # Apply reviewed values to items
        for idx, item in enumerate(items):
            if idx in reviewed_lookup:
                reviewed = reviewed_lookup[idx]
                
                # Update fields that were reviewed
                for field in ['product_name', 'quantity', 'unit_price', 'total_price',
                            'l1_category', 'l2_category', 'purchase_uom']:
                    if field in reviewed:
                        item[field] = reviewed[field]
                        item[f'_reviewed_{field}'] = True  # Mark as reviewed
                
                # Add review metadata
                if 'review_notes' in reviewed:
                    item['review_notes'] = reviewed['review_notes']
                if 'review_status' in reviewed:
                    item['review_status'] = reviewed['review_status']
                
                # Mark item as reviewed
                item['_manually_reviewed'] = True
        
        # Update receipt metadata
        receipt['_manually_reviewed'] = True
        receipt['_reviewed_at'] = datetime.now().isoformat()
    
    return updated_data


def generate_reports_from_artifacts(
    step1_output_dir: Path,
    output_dir: Optional[Path] = None
) -> Dict[str, Path]:
    """
    Generate HTML and PDF reports from Step 1 artifacts folder.
    
    Args:
        step1_output_dir: Step 1 output directory (contains artifacts folder)
        output_dir: Output directory for reports (defaults to step1_output_dir)
        
    Returns:
        Dictionary mapping report names to file paths
    """
    output_dir = output_dir or step1_output_dir
    
    # Find the latest artifacts folder
    artifacts_base = step1_output_dir / 'artifacts' / 'step1'
    if not artifacts_base.exists():
        logger.warning(f"Artifacts folder not found: {artifacts_base}")
        return {}
    
    # Find the latest STEP1 folder
    step1_folders = sorted(artifacts_base.glob('STEP1_*'), reverse=True)
    if not step1_folders:
        logger.warning(f"No STEP1 folders found in {artifacts_base}")
        return {}
    
    latest_artifacts_dir = step1_folders[0]
    logger.info(f"Using artifacts folder: {latest_artifacts_dir}")
    
    # Load data from artifacts
    try:
        from step1_extract.standardized_output import load_data_from_artifacts
        artifacts_data = load_data_from_artifacts(latest_artifacts_dir)
        
        if not artifacts_data.get('receipts_data'):
            logger.warning("No receipts data found in artifacts")
            return {}
        
        reports = {}
        
        # Generate combined final report
        try:
            from step1_extract.generate_report import generate_html_report
            final_report_file = output_dir / 'report.html'
            generate_html_report(artifacts_data['receipts_data'], final_report_file)
            reports['combined_report'] = final_report_file
            logger.info(f"Generated combined final report: {final_report_file}")
        except Exception as e:
            logger.warning(f"Could not generate combined final report: {e}", exc_info=True)
        
        # Generate classification report
        try:
            from step1_extract.generate_classification_report import generate_classification_report
            html_path, csv_path = generate_classification_report(
                artifacts_data['receipts_data'], 
                output_dir
            )
            reports['classification_report_html'] = html_path
            reports['classification_report_csv'] = csv_path
            logger.info(f"Generated classification report: {html_path}")
            logger.info(f"Generated classification CSV: {csv_path}")
        except Exception as e:
            logger.warning(f"Could not generate classification report: {e}", exc_info=True)
        
        # Generate PDF versions of all reports
        try:
            from step1_extract.pdf_generator import generate_pdfs_for_all_reports
            pdfs = generate_pdfs_for_all_reports(output_dir)
            pdf_count = sum(1 for path in pdfs.values() if path.suffix == '.pdf')
            if pdf_count > 0:
                logger.info(f"✅ Generated {pdf_count} PDF reports")
                reports.update(pdfs)
            else:
                logger.info("ℹ️  PDF generation skipped (Chrome not available)")
                logger.info("   You can print HTML reports to PDF manually from your browser")
        except Exception as e:
            logger.warning(f"Could not generate PDF reports: {e}", exc_info=True)
        
        return reports
        
    except Exception as e:
        logger.error(f"Error generating reports from artifacts: {e}", exc_info=True)
        return {}


def main():
    """Main entry point for Step 2"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Step 2: Export data for manual review and generate reports')
    parser.add_argument('input_dir', type=Path, help='Step 1 output directory')
    parser.add_argument('output_dir', type=Path, help='Step 2 output directory')
    parser.add_argument('--filename', default='manual_review_export.xlsx', help='Output Excel filename')
    parser.add_argument('--load-reviewed', type=Path, help='Load reviewed Excel and apply changes')
    parser.add_argument('--generate-reports', action='store_true', help='Generate HTML and PDF reports from artifacts')
    parser.add_argument('--reports-output', type=Path, help='Output directory for reports (defaults to input_dir)')
    
    args = parser.parse_args()
    
    if args.load_reviewed:
        # Load reviewed Excel and apply to extracted data
        reviewed_data = load_reviewed_excel(args.load_reviewed)
        
        # Load original extracted data
        all_extracted = {}
        for source_type in ['localgrocery_based', 'instacart_based', 'bbi_based', 'amazon_based', 'webstaurantstore_based']:
            json_file = args.input_dir / source_type / 'extracted_data.json'
            if json_file.exists():
                with open(json_file, 'r', encoding='utf-8') as f:
                    extracted = json.load(f)
                    all_extracted.update(extracted)
        
        # Apply reviewed data
        updated_data = apply_reviewed_data(all_extracted, reviewed_data)
        
        # Save updated data back
        output_file = args.output_dir / 'reviewed_extracted_data.json'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Applied reviewed data to {len(updated_data)} receipts")
        logger.info(f"Saved to {output_file}")
    elif args.generate_reports:
        # Generate reports from artifacts
        reports = generate_reports_from_artifacts(args.input_dir, args.reports_output)
        if reports:
            logger.info(f"✅ Generated {len(reports)} reports")
            for name, path in reports.items():
                logger.info(f"  - {name}: {path}")
        else:
            logger.warning("No reports generated")
    else:
        # Export to Excel
        output_file = export_to_excel(args.input_dir, args.output_dir, args.filename)
        logger.info(f"Export complete: {output_file}")
        
        # Also generate reports if artifacts are available
        reports_output = args.reports_output or args.input_dir
        reports = generate_reports_from_artifacts(args.input_dir, reports_output)
        if reports:
            logger.info(f"✅ Also generated {len(reports)} reports from artifacts")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    main()

