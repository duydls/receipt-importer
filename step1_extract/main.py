#!/usr/bin/env python3
"""
Step 1 Main Entry Point - Rule-Driven Receipt Extraction

Detects receipt type (vendor-based vs instacart-based) and routes to appropriate processor.
Uses rule-driven architecture with vendor detection, layout application, and UoM extraction.

EXPLICIT RULE EXECUTION ORDER (enforced in code, not by filename):

1. ALWAYS FIRST (applied in order):
   a. 10_vendor_detection.yaml - Detects vendor and source type from file path/content
   b. 15_vendor_aliases.yaml - Normalizes vendor names (applied inside VendorMatcher)
   c. 40_vendor_normalization.yaml - Additional vendor normalization rules

2. CONDITIONAL BRANCH (based on detected_source_type from step 1):

   IF detected_source_type == "instacart-based":
     a. 25_instacart_csv.yaml - Instacart CSV matching configuration
     b. Try modern layouts (if any exist for Instacart)
     c. group2_pdf.yaml - Legacy fallback for Instacart PDFs (marks as needs_review)
   
   ELSE (detected_source_type == "vendor-based"):
     a. Try vendor layouts in order:
        - 20_costco_layout.yaml
        - 21_rd_layout.yaml
        - 22_jewel_layout.yaml
        - (future: 23_hmart_layout.yaml, 24_parktoshop_layout.yaml, etc.)
     b. 30_uom_extraction.yaml - Extract raw UoM/size text (no normalization)
     c. group1_excel.yaml - Legacy fallback if no modern layout matched (marks as needs_review)

3. ALWAYS AFTER PROCESSING:
   a. shared.yaml - Common flags, fee keywords, multiline rules, AI fallback config
   b. vendor_profiles.yaml - Costco/RD extra info, item_number/upc hints (if available)

See step1_rules/README.md for detailed rule documentation.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from .logger import setup_logger
from .rule_loader import RuleLoader

logger = logging.getLogger(__name__)


def detect_group(file_path: Path, input_dir: Path) -> str:
    """
    Detect which receipt type a file belongs to based on folder structure
    
    Args:
        file_path: Path to the file being processed
        input_dir: Base input directory
        
    Returns:
        'vendor_based' or 'instacart_based'
    """
    try:
        rel_path = file_path.relative_to(input_dir)
        folder_name = str(rel_path.parent) if rel_path.parent != Path('.') else ''
        
        # Instacart-based = Instacart only
        if 'instacart' in folder_name.lower() or 'instarcart' in folder_name.lower():
            return 'instacart_based'
        
        # Vendor-based = Costco, Jewel-Osco, RD, others
        return 'vendor_based'
    except ValueError:
        # If can't determine relative path, check filename
        filename_lower = file_path.name.lower()
        if 'instacart' in filename_lower or 'uni_uni_uptown' in filename_lower:
            return 'instacart_based'
        return 'vendor_based'


def process_files(
    input_dir: Path,
    output_base_dir: Path,
    rules_dir: Path,
    use_threads: bool = True,
    max_workers: int = 4
) -> Dict[str, Dict[str, Any]]:
    """
    Main processing function
    
    Args:
        input_dir: Input directory containing receipts
        output_base_dir: Base output directory (will create vendor_based/ and instacart_based/ subdirs)
        rules_dir: Directory containing rule YAML files
        use_threads: If True, process files in parallel using ThreadPoolExecutor (default: True)
        max_workers: Maximum number of parallel workers (default: 4, safe for most systems)
        
    Returns:
        Dictionary with 'vendor_based' and 'instacart_based' keys containing extracted data
    
    Note:
        ThreadPoolExecutor is used for file-level parallelism only.
        Each file is processed independently — no shared state or database writes occur.
        Set use_threads=False for debugging or if you encounter issues.
    """
    # Setup logger
    log_dir = output_base_dir / 'logs'
    setup_logger(log_level='INFO', log_dir=log_dir)
    
    # Initialize rule loader
    rule_loader = RuleLoader(rules_dir)
    
    # Initialize vendor detector (load vendor detection rule first)
    from .vendor_detector import VendorDetector
    vendor_detector = VendorDetector(rule_loader)
    
    # Initialize processors (pass input_dir for knowledge base location)
    from .excel_processor import ExcelProcessor
    from .pdf_processor import PDFProcessor
    
    excel_processor = ExcelProcessor(rule_loader, input_dir=input_dir)
    pdf_processor = PDFProcessor(rule_loader, input_dir=input_dir)
    
    # Find all files
    pdf_files = list(input_dir.glob('**/*.pdf'))
    excel_files = list(input_dir.glob('**/*.xlsx')) + list(input_dir.glob('**/*.xls'))
    csv_files = list(input_dir.glob('**/*.csv'))
    
    logger.info(f"Found {len(pdf_files)} PDF files, {len(excel_files)} Excel files, {len(csv_files)} CSV files")
    
    # Group files by receipt type
    # Note: CSV files are only for instacart-based (Instacart baseline files)
    vendor_based_files: List[Path] = []
    instacart_based_files: List[Path] = []
    
    # Group PDF and Excel files
    for file_list in [pdf_files, excel_files]:
        for file_path in file_list:
            receipt_type = detect_group(file_path, input_dir)
            if receipt_type == 'vendor_based':
                vendor_based_files.append(file_path)
            else:
                instacart_based_files.append(file_path)
    
    # CSV files are only for instacart-based (Instacart baseline files)
    # They should only be in Instacart folders
    for file_path in csv_files:
        receipt_type = detect_group(file_path, input_dir)
        if receipt_type == 'instacart_based':
            instacart_based_files.append(file_path)
        else:
            logger.warning(f"CSV file found in vendor-based location (ignoring): {file_path.relative_to(input_dir)}")
    
    logger.info(f"Vendor-based files: {len(vendor_based_files)}, Instacart-based files: {len(instacart_based_files)}")
    
    ### Process vendor-based files
    vendor_based_output_dir = output_base_dir / 'vendor_based'
    vendor_based_data: Dict[str, Any] = {}
    
    if vendor_based_files:
        logger.info("Processing vendor-based receipts...")
        
        def process_vendor_based_file(file_path: Path) -> Tuple[str, Optional[Dict[str, Any]]]:
            """Process a single vendor-based file and return (receipt_id, receipt_data)"""
            try:
                logger.info(f"Processing [Vendor-based]: {file_path.name}")
                
                # Apply vendor detection FIRST (before processing)
                # This adds detected_vendor_code which is needed for layout matching
                initial_receipt_data = {'filename': file_path.name}
                initial_receipt_data = vendor_detector.apply_detection_to_receipt(file_path, initial_receipt_data)
                detected_vendor_code = initial_receipt_data.get('detected_vendor_code')
                
                if file_path.suffix.lower() in ['.xlsx', '.xls']:
                    receipt_data = excel_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                elif file_path.suffix.lower() == '.pdf':
                    receipt_data = excel_processor.process_pdf(file_path)
                else:
                    logger.warning(f"Unsupported file type: {file_path.suffix}")
                    return file_path.stem, None
                
                if receipt_data:
                    receipt_id = receipt_data.get('order_id') or file_path.stem
                    # Preserve fields from vendor detection (don't overwrite if already set by processor)
                    preserve_fields = ['detected_vendor_code', 'detected_source_type', 'source_file']
                    for field in preserve_fields:
                        if field in initial_receipt_data and field not in receipt_data:
                            receipt_data[field] = initial_receipt_data[field]
                        # If already set, preserve it (don't overwrite)
                    
                    # Merge vendor detection fields if not already present
                    if 'detected_vendor_code' not in receipt_data:
                        receipt_data['detected_vendor_code'] = detected_vendor_code
                    if 'detected_source_type' not in receipt_data:
                        receipt_data['detected_source_type'] = initial_receipt_data.get('detected_source_type', 'vendor_based')
                    # Add source_group and source_file if not already present
                    if 'source_group' not in receipt_data:
                        receipt_data['source_group'] = 'vendor_based'
                    if 'source_file' not in receipt_data:
                        receipt_data['source_file'] = str(file_path.relative_to(input_dir))
                    item_count = len(receipt_data.get('items', []))
                    if item_count > 0:
                        logger.info(f"  ✓ Extracted {item_count} items")
                    else:
                        logger.warning(f"  ⚠ No items extracted from {file_path.name}")
                    return receipt_id, receipt_data
                else:
                    logger.warning(f"  ✗ Failed to process {file_path.name}")
                    return file_path.stem, None
                    
            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}", exc_info=True)
                # Include failed receipt for review
                receipt_id = file_path.stem
                error_data: Dict[str, Any] = {
                    'filename': file_path.name,
                    'vendor': None,
                    'items': [],
                    'total': 0.0,
                    'source_group': 'vendor_based',
                    'source_file': str(file_path.relative_to(input_dir)),
                    'needs_review': True,
                    'review_reasons': [f'Error processing: {str(e)}']
                }
                return receipt_id, error_data
        
        # Process files (sequential or parallel based on use_threads flag)
        # Note: ThreadPoolExecutor is used for file-level parallelism only.
        # Each file is processed independently — no shared state or database writes occur.
        if use_threads and len(vendor_based_files) > 1:
            logger.info(f"Using parallel processing with {max_workers} workers for {len(vendor_based_files)} files")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_vendor_based_file, file_path): file_path 
                          for file_path in vendor_based_files}
                for future in as_completed(futures):
                    receipt_id, receipt_data = future.result()
                    if receipt_data:
                        vendor_based_data[receipt_id] = receipt_data
        else:
            if use_threads and len(vendor_based_files) <= 1:
                logger.debug("Only 1 file to process, using sequential processing")
            for file_path in vendor_based_files:
                receipt_id, receipt_data = process_vendor_based_file(file_path)
                if receipt_data:
                    vendor_based_data[receipt_id] = receipt_data
    
    ### Process instacart-based files
    instacart_based_output_dir = output_base_dir / 'instacart_based'
    instacart_based_data: Dict[str, Any] = {}
    
    if instacart_based_files:
        logger.info("Processing instacart-based receipts...")
        
        def process_instacart_based_file(file_path: Path) -> Tuple[str, Optional[Dict[str, Any]]]:
            """Process a single instacart-based file and return (receipt_id, receipt_data)"""
            try:
                logger.info(f"Processing [Instacart-based]: {file_path.name}")
                
                if file_path.suffix.lower() == '.pdf':
                    receipt_data = pdf_processor.process_file(file_path)
                elif file_path.suffix.lower() == '.csv':
                    # CSV files are handled by PDF processor as baseline files
                    return file_path.stem, None
                else:
                    logger.warning(f"Unsupported file type for instacart-based: {file_path.suffix}")
                    return file_path.stem, None
                
                if receipt_data:
                    receipt_id = receipt_data.get('order_id') or file_path.stem
                    # Apply vendor detection (adds detected_vendor_code and detected_source_type)
                    receipt_data = vendor_detector.apply_detection_to_receipt(file_path, receipt_data)
                    # Add source_group and source_file if not already present
                    if 'source_group' not in receipt_data:
                        receipt_data['source_group'] = 'instacart_based'
                    if 'source_file' not in receipt_data:
                        receipt_data['source_file'] = str(file_path.relative_to(input_dir))
                    item_count = len(receipt_data.get('items', []))
                    if item_count > 0:
                        logger.info(f"  ✓ Extracted {item_count} items")
                    else:
                        logger.warning(f"  ⚠ No items extracted from {file_path.name}")
                    return receipt_id, receipt_data
                else:
                    logger.warning(f"  ✗ Failed to process {file_path.name}")
                    return file_path.stem, None
                    
            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}", exc_info=True)
                # Include failed receipt for review
                receipt_id = file_path.stem
                error_data: Dict[str, Any] = {
                    'filename': file_path.name,
                    'vendor': None,
                    'items': [],
                    'total': 0.0,
                    'source_group': 'instacart_based',
                    'source_file': str(file_path.relative_to(input_dir)),
                    'needs_review': True,
                    'review_reasons': [f'Error processing: {str(e)}']
                }
                return receipt_id, error_data
        
        # Process files (sequential or parallel based on use_threads flag)
        # Note: ThreadPoolExecutor is used for file-level parallelism only.
        # Each file is processed independently — no shared state or database writes occur.
        if use_threads and len(instacart_based_files) > 1:
            logger.info(f"Using parallel processing with {max_workers} workers for {len(instacart_based_files)} files")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_instacart_based_file, file_path): file_path 
                          for file_path in instacart_based_files}
                for future in as_completed(futures):
                    receipt_id, receipt_data = future.result()
                    if receipt_data:
                        instacart_based_data[receipt_id] = receipt_data
        else:
            if use_threads and len(instacart_based_files) <= 1:
                logger.debug("Only 1 file to process, using sequential processing")
            for file_path in instacart_based_files:
                receipt_id, receipt_data = process_instacart_based_file(file_path)
                if receipt_data:
                    instacart_based_data[receipt_id] = receipt_data
    
    ### Save output files and generate reports
    results: Dict[str, Dict[str, Any]] = {
        'vendor_based': vendor_based_data,
        'instacart_based': instacart_based_data
    }
    
    # Save vendor-based output and generate report
    if vendor_based_data:
        vendor_based_output_dir.mkdir(parents=True, exist_ok=True)
        output_file = vendor_based_output_dir / 'extracted_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(vendor_based_data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved vendor-based data to: {output_file}")
        
        # Generate vendor-based report (preserves existing report intelligence)
        try:
            from .generate_report import generate_html_report
            report_file = vendor_based_output_dir / 'report.html'
            generate_html_report(vendor_based_data, report_file)
            logger.info(f"Generated vendor-based report: {report_file}")
        except Exception as e:
            logger.warning(f"Could not generate vendor-based report: {e}")
    
    # Save instacart-based output and generate report
    if instacart_based_data:
        instacart_based_output_dir.mkdir(parents=True, exist_ok=True)
        output_file = instacart_based_output_dir / 'extracted_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(instacart_based_data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved instacart-based data to: {output_file}")
        
        # Generate instacart-based report (preserves ALL existing report intelligence including UoM match, validation summary, etc.)
        try:
            from .generate_report import generate_html_report
            report_file = instacart_based_output_dir / 'report.html'
            generate_html_report(instacart_based_data, report_file)
            logger.info(f"Generated instacart-based report: {report_file}")
        except Exception as e:
            logger.warning(f"Could not generate instacart-based report: {e}")
    
    # Generate combined final report at root output directory
    all_receipts: Dict[str, Any] = {}
    all_receipts.update(vendor_based_data)
    all_receipts.update(instacart_based_data)
    
    if all_receipts:
        try:
            from .generate_report import generate_html_report
            final_report_file = output_base_dir / 'report.html'
            generate_html_report(all_receipts, final_report_file)
            logger.info(f"Generated combined final report: {final_report_file}")
        except Exception as e:
            logger.warning(f"Could not generate combined final report: {e}")
    
    logger.info(f"\nStep 1 Complete: Extracted {len(vendor_based_data)} vendor-based receipts, {len(instacart_based_data)} instacart-based receipts")
    
    return results


def main() -> None:
    """Main entry point for step1_extract"""
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser(
        description='Step 1: Extract receipt data from PDF and Excel files',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        'input_dir',
        type=str,
        help='Input directory containing receipts'
    )
    parser.add_argument(
        'output_dir',
        type=str,
        nargs='?',
        default='output',
        help='Output directory (default: output)'
    )
    parser.add_argument(
        '--rules-dir',
        type=str,
        default=None,
        help='Directory containing rule YAML files (default: step1_rules in parent directory)'
    )
    parser.add_argument(
        '--use-threads',
        action='store_true',
        help='Process files in parallel using ThreadPoolExecutor (default: False)'
    )
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    rules_dir = Path(args.rules_dir) if args.rules_dir else Path(__file__).parent.parent / 'step1_rules'
    
    logger.info(f"Input directory: {input_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Rules directory: {rules_dir}")
    logger.info(f"Use threads: {args.use_threads}")
    
    process_files(input_dir, output_dir, rules_dir, use_threads=args.use_threads)


if __name__ == "__main__":
    main()

