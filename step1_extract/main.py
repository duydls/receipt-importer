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
        'localgrocery_based', 'instacart_based', 'bbi_based', 'amazon_based', or 'webstaurantstore_based'
    """
    try:
        rel_path = file_path.relative_to(input_dir)
        folder_name = str(rel_path.parent) if rel_path.parent != Path('.') else ''
        filename_lower = file_path.name.lower()
        
        # WebstaurantStore-based = WebstaurantStore folder
        if 'webstaurant' in folder_name.lower():
            return 'webstaurantstore_based'
        
        # BBI-based = BBI folder or BBI filename patterns
        if 'bbi' in folder_name.lower() or 'uni_il_ut' in filename_lower:
            return 'bbi_based'
        
        # Amazon-based = AMAZON folder or Amazon order ID pattern
        if 'amazon' in folder_name.lower() or 'orders_from_' in filename_lower:
            return 'amazon_based'
        
        # Instacart-based = Instacart folder
        if 'instacart' in folder_name.lower() or 'instarcart' in folder_name.lower():
            return 'instacart_based'
        
        # Local grocery-based = Costco, Jewel-Osco, RD, Aldi, Mariano's, Parktoshop, etc.
        return 'localgrocery_based'
    except ValueError:
        # If can't determine relative path, check filename
        filename_lower = file_path.name.lower()
        if 'webstaurant' in filename_lower:
            return 'webstaurantstore_based'
        if 'bbi' in filename_lower or 'uni_il_ut' in filename_lower:
            return 'bbi_based'
        if 'amazon' in filename_lower or 'orders_from_' in filename_lower:
            return 'amazon_based'
        if 'instacart' in filename_lower or 'uni_uni_uptown' in filename_lower:
            return 'instacart_based'
        return 'localgrocery_based'


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
        Dictionary with 'localgrocery_based' and 'instacart_based' keys containing extracted data
    
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
    from .rd_pdf_processor import RDPDFProcessor
    
    excel_processor = ExcelProcessor(rule_loader, input_dir=input_dir)
    pdf_processor = PDFProcessor(rule_loader, input_dir=input_dir)
    rd_pdf_processor = RDPDFProcessor(rule_loader, input_dir=input_dir)
    
    # Find all files
    pdf_files = list(input_dir.glob('**/*.pdf'))
    excel_files = list(input_dir.glob('**/*.xlsx')) + list(input_dir.glob('**/*.xls'))
    csv_files = list(input_dir.glob('**/*.csv'))
    
    logger.info(f"Found {len(pdf_files)} PDF files, {len(excel_files)} Excel files, {len(csv_files)} CSV files")
    
    # Group files by receipt type
    # Note: CSV files are for instacart-based and amazon-based (baseline files)
    localgrocery_based_files: List[Path] = []
    instacart_based_files: List[Path] = []
    bbi_based_files: List[Path] = []
    amazon_based_files: List[Path] = []
    webstaurantstore_based_files: List[Path] = []
    
    # Group PDF and Excel files
    for file_list in [pdf_files, excel_files]:
        for file_path in file_list:
            receipt_type = detect_group(file_path, input_dir)
            if receipt_type == 'localgrocery_based':
                localgrocery_based_files.append(file_path)
            elif receipt_type == 'instacart_based':
                instacart_based_files.append(file_path)
            elif receipt_type == 'bbi_based':
                bbi_based_files.append(file_path)
            elif receipt_type == 'amazon_based':
                amazon_based_files.append(file_path)
            elif receipt_type == 'webstaurantstore_based':
                webstaurantstore_based_files.append(file_path)
    
    # CSV files are only for instacart-based (Instacart baseline files)
    # They should only be in Instacart folders
    for file_path in csv_files:
        receipt_type = detect_group(file_path, input_dir)
        if receipt_type == 'instacart_based':
            instacart_based_files.append(file_path)
        else:
            logger.warning(f"CSV file found in localgrocery location (ignoring): {file_path.relative_to(input_dir)}")
    
    logger.info(f"LocalGrocery-based files: {len(localgrocery_based_files)}, Instacart-based files: {len(instacart_based_files)}, BBI-based files: {len(bbi_based_files)}, Amazon-based files: {len(amazon_based_files)}, WebstaurantStore-based files: {len(webstaurantstore_based_files)}")
    
    ### Process localgrocery-based files (Costco, RD, Aldi, Jewel-Osco, Mariano's, Parktoshop)
    localgrocery_based_output_dir = output_base_dir / 'localgrocery_based'
    localgrocery_based_data: Dict[str, Any] = {}
    
    if localgrocery_based_files:
        logger.info("Processing localgrocery-based receipts...")
        
        def process_localgrocery_file(file_path: Path) -> Tuple[str, Optional[Dict[str, Any]]]:
            """Process a single localgrocery file and return (receipt_id, receipt_data)"""
            try:
                logger.info(f"Processing [LocalGrocery]: {file_path.name}")
                
                # Apply vendor detection FIRST (before processing)
                # This adds detected_vendor_code which is needed for layout matching
                initial_receipt_data = {'filename': file_path.name}
                initial_receipt_data = vendor_detector.apply_detection_to_receipt(file_path, initial_receipt_data)
                detected_vendor_code = initial_receipt_data.get('detected_vendor_code')
                
                if file_path.suffix.lower() in ['.xlsx', '.xls']:
                    receipt_data = excel_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                elif file_path.suffix.lower() == '.pdf':
                    # Check if it's an RD PDF and use grid processor
                    if detected_vendor_code in ['RD', 'RESTAURANT_DEPOT']:
                        receipt_data = rd_pdf_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                    else:
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
                        receipt_data['detected_source_type'] = initial_receipt_data.get('detected_source_type', 'localgrocery_based')
                    # Add source_group and source_file if not already present
                    if 'source_group' not in receipt_data:
                        receipt_data['source_group'] = 'localgrocery_based'
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
                    'source_group': 'localgrocery_based',
                    'source_file': str(file_path.relative_to(input_dir)),
                    'needs_review': True,
                    'review_reasons': [f'Error processing: {str(e)}']
                }
                return receipt_id, error_data
        
        # Process files (sequential or parallel based on use_threads flag)
        # Note: ThreadPoolExecutor is used for file-level parallelism only.
        # Each file is processed independently — no shared state or database writes occur.
        if use_threads and len(localgrocery_based_files) > 1:
            logger.info(f"Using parallel processing with {max_workers} workers for {len(localgrocery_based_files)} files")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_localgrocery_file, file_path): file_path 
                          for file_path in localgrocery_based_files}
                for future in as_completed(futures):
                    receipt_id, receipt_data = future.result()
                    if receipt_data:
                        localgrocery_based_data[receipt_id] = receipt_data
        else:
            if use_threads and len(localgrocery_based_files) <= 1:
                logger.debug("Only 1 file to process, using sequential processing")
            for file_path in localgrocery_based_files:
                receipt_id, receipt_data = process_localgrocery_file(file_path)
                if receipt_data:
                    localgrocery_based_data[receipt_id] = receipt_data
    
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
    
    ### Process BBI-based files
    bbi_based_output_dir = output_base_dir / 'bbi_based'
    bbi_based_data: Dict[str, Any] = {}
    
    if bbi_based_files:
        logger.info("Processing BBI-based receipts...")
        for file_path in bbi_based_files:
            receipt_id, receipt_data = process_localgrocery_file(file_path)
            if receipt_data:
                receipt_data['source_group'] = 'bbi_based'
                bbi_based_data[receipt_id] = receipt_data
    
    ### Process Amazon-based files (CSV-first approach)
    amazon_based_output_dir = output_base_dir / 'amazon_based'
    amazon_based_data: Dict[str, Any] = {}
    
    if amazon_based_files:
        logger.info("Processing Amazon-based receipts (CSV-first)...")
        
        from .amazon_csv_processor import AmazonCSVProcessor
        amazon_processor = AmazonCSVProcessor(rule_loader)
        
        # Find Amazon CSV
        csv_path = amazon_processor.find_amazon_csv(input_dir)
        if not csv_path:
            logger.warning("No Amazon CSV found. PDFs will not be processed.")
        else:
            # Load and group CSV by Order ID
            orders_data = amazon_processor.load_and_parse_csv(csv_path)
            logger.info(f"Found {len(orders_data)} orders in Amazon CSV")
            
            # Build Order ID → PDF path mapping
            pdf_map = {}
            for file_path in amazon_based_files:
                if file_path.suffix.lower() == '.pdf':
                    order_id = amazon_processor.extract_order_id_from_pdf(file_path)
                    if order_id:
                        pdf_map[order_id] = file_path
            
            logger.info(f"Found {len(pdf_map)} Amazon PDFs with Order IDs")
            
            # Process each order from CSV
            for order_id, csv_rows in orders_data.items():
                try:
                    pdf_path = pdf_map.get(order_id)
                    receipt_data = amazon_processor.process_order(order_id, csv_rows, pdf_path)
                    
                    if receipt_data:
                        # Add source file
                        if pdf_path:
                            receipt_data['source_file'] = str(pdf_path.relative_to(input_dir))
                        else:
                            receipt_data['source_file'] = f"CSV: {csv_path.name}"
                            receipt_data['needs_review'] = True
                            if 'No PDF found for order' not in receipt_data['review_reasons']:
                                receipt_data['review_reasons'].append('No PDF found for order')
                        
                        # Apply UoM extraction
                        from .uom_extractor import UoMExtractor
                        uom_extractor = UoMExtractor(rule_loader)
                        receipt_data['items'] = uom_extractor.extract_uom_from_items(receipt_data['items'])
                        
                        amazon_based_data[order_id] = receipt_data
                        logger.info(f"  ✓ Processed Amazon order {order_id}: {len([i for i in receipt_data['items'] if not i.get('is_fee')])} items, ${receipt_data.get('total', 0):.2f}")
                    
                except Exception as e:
                    logger.error(f"Error processing Amazon order {order_id}: {e}", exc_info=True)
    
    ### Process WebstaurantStore-based files (PDF invoices)
    webstaurantstore_based_output_dir = output_base_dir / 'webstaurantstore_based'
    webstaurantstore_based_data: Dict[str, Any] = {}
    
    if webstaurantstore_based_files:
        logger.info("Processing WebstaurantStore-based receipts...")
        
        # Use dedicated WebstaurantStore PDF processor
        from .webstaurantstore_pdf_processor import WebstaurantStorePDFProcessor
        webstaurantstore_processor = WebstaurantStorePDFProcessor(rule_loader)
        
        for file_path in webstaurantstore_based_files:
            try:
                logger.info(f"Processing [WebstaurantStore]: {file_path.name}")
                
                if file_path.suffix.lower() == '.pdf':
                    receipt_data = webstaurantstore_processor.process_file(file_path)
                else:
                    logger.warning(f"Unsupported file type for WebstaurantStore: {file_path.suffix}")
                    continue
                
                if receipt_data:
                    receipt_id = receipt_data.get('receipt_number') or file_path.stem
                    
                    # Apply vendor detection
                    receipt_data = vendor_detector.apply_detection_to_receipt(file_path, receipt_data)
                    
                    # Add source info
                    receipt_data['source_group'] = 'webstaurantstore_based'
                    if 'source_file' not in receipt_data:
                        receipt_data['source_file'] = str(file_path.relative_to(input_dir))
                    
                    # Apply UoM extraction
                    from .uom_extractor import UoMExtractor
                    uom_extractor = UoMExtractor(rule_loader)
                    receipt_data['items'] = uom_extractor.extract_uom_from_items(receipt_data['items'])
                    
                    webstaurantstore_based_data[receipt_id] = receipt_data
                    item_count = len([i for i in receipt_data['items'] if not i.get('is_fee')])
                    logger.info(f"  ✓ Extracted {item_count} items, ${receipt_data.get('total', 0):.2f}")
                else:
                    logger.warning(f"  ✗ Failed to process {file_path.name}")
            
            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}", exc_info=True)
    
    ### Apply Category Classification (Feature 14)
    logger.info("Applying category classification to all items...")
    from .category_classifier import CategoryClassifier
    category_classifier = CategoryClassifier(rule_loader)
    
    # Classify items in each receipt type
    for source_type, receipts_data in [
        ('localgrocery_based', localgrocery_based_data),
        ('instacart_based', instacart_based_data),
        ('bbi_based', bbi_based_data),
        ('amazon_based', amazon_based_data),
        ('webstaurantstore_based', webstaurantstore_based_data)
    ]:
        if not receipts_data:
            continue
        
        for receipt_id, receipt_data in receipts_data.items():
            try:
                items = receipt_data.get('items', [])
                vendor_code = receipt_data.get('vendor_code') or receipt_data.get('detected_vendor_code')
                
                # Classify items
                classified_items = category_classifier.classify_items(items, source_type, vendor_code)
                receipt_data['items'] = classified_items
                
                # Add summary stats
                total_items = len([i for i in classified_items if not i.get('is_fee')])
                needs_review_count = sum(1 for i in classified_items if i.get('needs_category_review') and not i.get('is_fee'))
                
                if total_items > 0:
                    logger.debug(f"Classified {total_items} items in {receipt_id}: {needs_review_count} need review")
            
            except Exception as e:
                logger.warning(f"Failed to classify items in {receipt_id}: {e}")
    
    logger.info("Category classification complete")
    
    ### Save output files and generate reports
    results: Dict[str, Dict[str, Any]] = {
        'localgrocery_based': localgrocery_based_data,
        'instacart_based': instacart_based_data,
        'bbi_based': bbi_based_data,
        'amazon_based': amazon_based_data,
        'webstaurantstore_based': webstaurantstore_based_data
    }
    
    # Save vendor-based output and generate report
    if localgrocery_based_data:
        localgrocery_based_output_dir.mkdir(parents=True, exist_ok=True)
        output_file = localgrocery_based_output_dir / 'extracted_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(localgrocery_based_data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved vendor-based data to: {output_file}")
        
        # Generate vendor-based report (preserves existing report intelligence)
        try:
            from .generate_report import generate_html_report
            report_file = localgrocery_based_output_dir / 'report.html'
            generate_html_report(localgrocery_based_data, report_file)
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
    
    # Save BBI-based output and generate report
    if bbi_based_data:
        bbi_based_output_dir.mkdir(parents=True, exist_ok=True)
        output_file = bbi_based_output_dir / 'extracted_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(bbi_based_data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved BBI-based data to: {output_file}")
        
        # Generate BBI-based report
        try:
            from .generate_report import generate_html_report
            report_file = bbi_based_output_dir / 'report.html'
            generate_html_report(bbi_based_data, report_file)
            logger.info(f"Generated BBI-based report: {report_file}")
        except Exception as e:
            logger.warning(f"Could not generate BBI-based report: {e}")
    
    # Save Amazon-based output and generate report
    if amazon_based_data:
        amazon_based_output_dir.mkdir(parents=True, exist_ok=True)
        output_file = amazon_based_output_dir / 'extracted_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(amazon_based_data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved Amazon-based data to: {output_file}")
        
        # Generate Amazon-based report
        try:
            from .generate_report import generate_html_report
            report_file = amazon_based_output_dir / 'report.html'
            generate_html_report(amazon_based_data, report_file)
            logger.info(f"Generated Amazon-based report: {report_file}")
        except Exception as e:
            logger.warning(f"Could not generate Amazon-based report: {e}")
    
    # Save WebstaurantStore-based output and generate report
    if webstaurantstore_based_data:
        webstaurantstore_based_output_dir.mkdir(parents=True, exist_ok=True)
        output_file = webstaurantstore_based_output_dir / 'extracted_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(webstaurantstore_based_data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved WebstaurantStore-based data to: {output_file}")
        
        # Generate WebstaurantStore-based report
        try:
            from .generate_report import generate_html_report
            report_file = webstaurantstore_based_output_dir / 'report.html'
            generate_html_report(webstaurantstore_based_data, report_file)
            logger.info(f"Generated WebstaurantStore-based report: {report_file}")
        except Exception as e:
            logger.warning(f"Could not generate WebstaurantStore-based report: {e}")
    
    # Generate combined final report at root output directory
    all_receipts: Dict[str, Any] = {}
    all_receipts.update(localgrocery_based_data)
    all_receipts.update(instacart_based_data)
    all_receipts.update(bbi_based_data)
    all_receipts.update(amazon_based_data)
    all_receipts.update(webstaurantstore_based_data)
    
    if all_receipts:
        try:
            from .generate_report import generate_html_report
            final_report_file = output_base_dir / 'report.html'
            generate_html_report(all_receipts, final_report_file)
            logger.info(f"Generated combined final report: {final_report_file}")
        except Exception as e:
            logger.warning(f"Could not generate combined final report: {e}")
        
        # Generate classification report
        try:
            from .generate_classification_report import generate_classification_report
            html_path, csv_path = generate_classification_report(all_receipts, output_base_dir)
            logger.info(f"Generated classification report: {html_path}")
            logger.info(f"Generated classification CSV: {csv_path}")
        except Exception as e:
            logger.warning(f"Could not generate classification report: {e}", exc_info=True)
        
        # Generate PDF versions of all reports
        try:
            from .pdf_generator import generate_pdfs_for_all_reports
            pdfs = generate_pdfs_for_all_reports(output_base_dir)
            pdf_count = sum(1 for path in pdfs.values() if path.suffix == '.pdf')
            if pdf_count > 0:
                logger.info(f"✅ Generated {pdf_count} PDF reports")
            else:
                logger.info("ℹ️  PDF generation skipped (Chrome not available)")
                logger.info("   You can print HTML reports to PDF manually from your browser")
        except Exception as e:
            logger.warning(f"Could not generate PDF reports: {e}", exc_info=True)
    
    # Feature 4: Log column-mapping cache stats
    try:
        cache_stats = excel_processor.layout_applier.get_cache_stats()
        if cache_stats['enabled'] and (cache_stats['hits'] > 0 or cache_stats['misses'] > 0):
            logger.info(
                f"Column-map cache: {cache_stats['hits']} hits, {cache_stats['misses']} misses, "
                f"{cache_stats['time_saved_ms']:.1f} ms saved"
            )
    except Exception as e:
        logger.debug(f"Could not retrieve cache stats: {e}")
    
    logger.info(f"\nStep 1 Complete: Extracted {len(localgrocery_based_data)} vendor-based receipts, {len(instacart_based_data)} instacart-based receipts, {len(bbi_based_data)} BBI receipts, {len(amazon_based_data)} Amazon receipts, {len(webstaurantstore_based_data)} WebstaurantStore receipts")
    
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

