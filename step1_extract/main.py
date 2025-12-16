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
     a. PDF processing only (Excel files no longer supported for localgrocery vendors):
        - 20_costco_pdf.yaml - Costco PDF rules
        - 21_rd_pdf_layout.yaml - RD PDF grid rules
        - 22_jewel_pdf.yaml - Jewel-Osco PDF rules
        - 23_aldi_pdf.yaml - Aldi PDF rules
        - 24_parktoshop_pdf.yaml - Parktoshop PDF rules
     b. 30_uom_extraction.yaml - Extract raw UoM/size text (no normalization)

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
        'localgrocery_based', 'instacart_based', 'bbi_based', 'amazon_based', 'webstaurantstore_based', 'wismettac_based', or 'odoo_based'
    """
    try:
        rel_path = file_path.relative_to(input_dir)
        # Get full path parts for nested folder detection
        path_parts = [part.lower() for part in rel_path.parts]
        folder_name = str(rel_path.parent).lower() if rel_path.parent != Path('.') else ''
        filename_lower = file_path.name.lower()
        
        # Odoo-based = Receipts/Odoo folder (new structure)
        if 'odoo' in path_parts or 'odoo' in folder_name:
            return 'odoo_based'
        
        # Wismettac-based = Wismettac folder or filename patterns
        if 'wismettac' in folder_name or 'wismettac' in filename_lower:
            return 'wismettac_based'
        
        # WebstaurantStore-based = WebstaurantStore folder
        if 'webstaurant' in folder_name:
            return 'webstaurantstore_based'
        
        # BBI-based = BBI folder or BBI filename patterns
        if 'bbi' in folder_name or 'uni_il_ut' in filename_lower:
            return 'bbi_based'
        
        # Amazon-based = AMAZON folder or Amazon order ID pattern
        if 'amazon' in folder_name or 'orders_from_' in filename_lower:
            return 'amazon_based'
        
        # Instacart-based = Instacart folder (check all path parts for nested folders)
        if 'instacart' in path_parts or 'instarcart' in path_parts or 'instacart' in folder_name or 'instarcart' in folder_name:
            return 'instacart_based'
        
        # Local grocery-based = Costco, Jewel-Osco, RD, Aldi, Parktoshop, etc.
        return 'localgrocery_based'
    except ValueError:
        # If can't determine relative path, check filename
        filename_lower = file_path.name.lower()
        if 'odoo' in filename_lower:
            return 'odoo_based'
        if 'wismettac' in filename_lower:
            return 'wismettac_based'
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
    
    # Initialize rule loader with hot-reload enabled to rescan rules on every run
    rule_loader = RuleLoader(rules_dir, enable_hot_reload=True)
    
    # Initialize vendor detector (load vendor detection rule first)
    from .vendor_detector import VendorDetector
    vendor_detector = VendorDetector(rule_loader)
    
    # Initialize processors (pass input_dir for knowledge base location)
    from .excel_processor import ExcelProcessor
    from .pdf_processor import PDFProcessor
    from .rd_pdf_processor import RDPDFProcessor
    from .pdf_processor_unified import UnifiedPDFProcessor
    
    excel_processor = ExcelProcessor(rule_loader, input_dir=input_dir)
    pdf_processor = PDFProcessor(rule_loader, input_dir=input_dir)
    rd_pdf_processor = RDPDFProcessor(rule_loader, input_dir=input_dir)
    unified_pdf_processor = UnifiedPDFProcessor(rule_loader, input_dir=input_dir)
    
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
    wismettac_based_files: List[Path] = []
    odoo_based_files: List[Path] = []
    
    # Group PDF files (Excel files removed - no longer processed for RD, Costco, Aldi, Jewel, Parktoshop)
    for file_path in pdf_files:
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
        elif receipt_type == 'wismettac_based':
            wismettac_based_files.append(file_path)
        elif receipt_type == 'odoo_based':
            odoo_based_files.append(file_path)
    
    # Process Excel files - BBI and Odoo Excel purchase orders
    # Exclude BBI_Size.xlsx files (baseline files)
    for file_path in excel_files:
        # Skip BBI baseline files (they should not be processed as receipts)
        if 'BBI_Size' in file_path.name:
            logger.debug(f"Skipping BBI baseline file (not a receipt): {file_path.relative_to(input_dir)}")
            continue
        
        receipt_type = detect_group(file_path, input_dir)
        if receipt_type == 'bbi_based':
            bbi_based_files.append(file_path)
        elif receipt_type == 'odoo_based':
            odoo_based_files.append(file_path)
        elif receipt_type == 'localgrocery_based':
            logger.warning(f"Skipping Excel file for localgrocery vendor (PDF only now): {file_path.relative_to(input_dir)}")
        else:
            logger.warning(f"Excel file in unsupported location: {file_path.relative_to(input_dir)}")
    
    # CSV files are for instacart-based (Instacart baseline files) or RD (Restaurant Depot)
    # They should be in Instacart folders or RD folder
    for file_path in csv_files:
        receipt_type = detect_group(file_path, input_dir)
        if receipt_type == 'instacart_based':
            instacart_based_files.append(file_path)
        elif receipt_type == 'localgrocery_based' and ('RD' in str(file_path) or 'Restaurant Depot' in str(file_path)):
            # RD CSV files are allowed in localgrocery location
            localgrocery_based_files.append(file_path)
        else:
            logger.warning(f"CSV file found in localgrocery location (ignoring): {file_path.relative_to(input_dir)}")
    
    logger.info(f"LocalGrocery-based files: {len(localgrocery_based_files)}, Instacart-based files: {len(instacart_based_files)}, BBI-based files: {len(bbi_based_files)}, Amazon-based files: {len(amazon_based_files)}, WebstaurantStore-based files: {len(webstaurantstore_based_files)}, Wismettac-based files: {len(wismettac_based_files)}, Odoo-based files: {len(odoo_based_files)}")
    
    ### Process localgrocery-based files (Costco, RD, Aldi, Jewel-Osco, Parktoshop)
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
                
                # Process PDF files or CSV files (for RD)
                if file_path.suffix.lower() == '.pdf':
                    # Route to appropriate PDF processor
                    if detected_vendor_code in ['RD', 'RESTAURANT_DEPOT']:
                        # RD uses grid-based extraction (different approach)
                        receipt_data = rd_pdf_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                    else:
                        # Use unified PDF processor for all other vendors (Costco, Jewel, Aldi, Parktoshop)
                        receipt_data = unified_pdf_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                elif file_path.suffix.lower() == '.csv' and detected_vendor_code in ['RD', 'RESTAURANT_DEPOT']:
                    # RD CSV files
                    from .rd_csv_processor import RDCSVProcessor
                    rd_csv_processor = RDCSVProcessor(rule_loader, input_dir=input_dir)
                    receipt_data = rd_csv_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                else:
                    logger.warning(f"Unsupported file type for localgrocery vendor: {file_path.suffix}")
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
                    # RD-only amount reconciliation (post-extraction, pre-report)
                    # Note: merge_duplicates=False to keep items separate as they appear on receipt
                    try:
                        from .rd_amount_reconciler import reconcile_rd_amounts
                        if receipt_data and (receipt_data.get('vendor') in ('RD', 'Restaurant Depot') or receipt_data.get('detected_vendor_code') in ('RD', 'RESTAURANT_DEPOT')):
                            receipt_data = reconcile_rd_amounts(receipt_data, merge_duplicates=False)
                    except Exception as e:
                        logger.debug(f"RD reconciler skipped: {e}")
                    
                    # Apply date hierarchy to normalize transaction_date from all available date fields
                    try:
                        from .date_normalizer import apply_date_hierarchy
                        receipt_data = apply_date_hierarchy(receipt_data)
                    except Exception as e:
                        logger.debug(f"Date normalization skipped: {e}")

                    # Ensure all items have unit_size, unit_uom, and qty
                    if receipt_data.get('items'):
                        from .utils.item_size_extractor import ensure_unit_size_uom_qty
                        receipt_data['items'] = ensure_unit_size_uom_qty(receipt_data['items'])

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
    
    # Load BBI baseline for UoM/Pack determination (before processing)
    from .bbi_baseline import load_bbi_baseline
    bbi_baseline = load_bbi_baseline(input_dir)
    if not bbi_baseline:
        logger.warning("BBI baseline (BBI_Size.xlsx) not found. UoM/Pack determination will be skipped.")
    else:
        logger.info(f"Loaded BBI baseline with {len(bbi_baseline.baseline_data)} items")
    
    if bbi_based_files:
        logger.info("Processing BBI-based receipts...")
        
        def extract_uom_from_bbi_filename(filename: str, product_name: str) -> Optional[Dict[str, Any]]:
            """
            Extract UoM information from BBI filename patterns like "Uni Straws 3000pcs"
            
            Args:
                filename: BBI filename (e.g., "Uni Straws 3000pcs.pdf")
                product_name: Product name from receipt item
            
            Returns:
                Dict with 'purchase_uom', 'unit_size', 'unit_uom' if found, None otherwise
            """
            import re
            
            # Remove file extension
            filename_base = filename.rsplit('.', 1)[0] if '.' in filename else filename
            
            # Pattern: number + unit (e.g., "3000pcs", "500pc", "2lb", "1kg")
            # Match patterns like: 3000pcs, 500-pc, 2-lb, 1.5kg, etc.
            uom_patterns = [
                r'(\d+(?:\.\d+)?)\s*[-]?\s*(pcs?|pieces?|pc|piece)',  # 3000pcs, 500-pc
                r'(\d+(?:\.\d+)?)\s*[-]?\s*(lb|lbs?|pound|pounds)',  # 2lb, 3-lb
                r'(\d+(?:\.\d+)?)\s*[-]?\s*(kg|g|gram|grams)',  # 1kg, 500g
                r'(\d+(?:\.\d+)?)\s*[-]?\s*(oz|ounce|ounces)',  # 16oz
                r'(\d+(?:\.\d+)?)\s*[-]?\s*(fl\s*oz|floz)',  # 64fl oz
                r'(\d+(?:\.\d+)?)\s*[-]?\s*(gal|gallon|gallons)',  # 1gal
                r'(\d+(?:\.\d+)?)\s*[-]?\s*(ml|l|liter|liters)',  # 500ml, 1l
                r'(\d+(?:\.\d+)?)\s*[-]?\s*(ct|count|counts)',  # 100ct
            ]
            
            for pattern in uom_patterns:
                match = re.search(pattern, filename_base, re.IGNORECASE)
                if match:
                    size = float(match.group(1))
                    unit = match.group(2).lower()
                    
                    # Normalize unit
                    if unit in ['pcs', 'pieces', 'piece']:
                        unit = 'pc'
                    elif unit in ['lbs', 'pound', 'pounds']:
                        unit = 'lb'
                    elif unit in ['g', 'gram', 'grams']:
                        unit = 'g'
                    elif unit in ['oz', 'ounce', 'ounces']:
                        unit = 'oz'
                    elif unit in ['fl oz', 'floz']:
                        unit = 'fl_oz'
                    elif unit in ['gal', 'gallon', 'gallons']:
                        unit = 'gal'
                    elif unit in ['ml', 'l', 'liter', 'liters']:
                        unit = unit if unit in ['ml', 'l'] else ('ml' if unit.startswith('ml') else 'l')
                    elif unit in ['ct', 'count', 'counts']:
                        unit = 'pc'  # Treat count as pieces
                    
                    # Format as compound UoM (e.g., "3000-pc")
                    purchase_uom = f"{int(size)}-{unit}" if size == int(size) else f"{size}-{unit}"
                    
                    return {
                        'purchase_uom': purchase_uom,
                        'unit_size': size,
                        'unit_uom': unit,
                        'source': 'filename'
                    }
            
            return None
        
        def enrich_bbi_items_from_filename(filename: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            """
            Enrich BBI items with UoM information extracted from filename or product name.
            Filename UoM takes priority over baseline UoM when product name matches filename.
            If filename doesn't contain UoM, extract from product names that contain UoM patterns.
            
            Args:
                filename: BBI filename (e.g., "Uni Straws 3000pcs.pdf" or "UNI_IL_UT_1025.pdf")
                items: List of extracted items
            
            Returns:
                Enriched items list
            """
            enriched_count = 0
            
            # Extract UoM from filename first
            filename_uom = extract_uom_from_bbi_filename(filename, '')
            filename_base = filename.rsplit('.', 1)[0] if '.' in filename else filename
            filename_lower = filename_base.lower()
            
            # Extract key words from filename (excluding numbers and UoM units)
            import re
            filename_words = [w for w in re.split(r'[\s\-_]+', filename_lower) 
                            if w and not w.isdigit() and w not in ['pcs', 'pc', 'pieces', 'piece', 'lb', 'lbs', 'kg', 'g', 'oz', 'gal', 'ml', 'l', 'ct', 'count']]
            
            for item in items:
                product_name = item.get('product_name', '') or item.get('display_name', '') or item.get('canonical_name', '')
                if not product_name:
                    continue
                
                product_name_lower = product_name.lower()
                
                # Try to extract UoM from product name if filename doesn't have one
                product_uom = None
                if not filename_uom:
                    product_uom = extract_uom_from_bbi_filename(product_name, '')
                    if product_uom:
                        product_uom['source'] = 'product_name'
                
                # Determine which UoM to use
                uom_to_use = filename_uom if filename_uom else product_uom
                if not uom_to_use:
                    continue  # No UoM found in filename or product name
                
                # Check if we should apply this UoM to this item
                should_enrich = False
                
                if filename_uom:
                    # Filename has UoM - check if product name matches filename
                    product_words = [w for w in re.split(r'[\s\-_]+', product_name_lower) if len(w) > 2]
                    
                    if filename_words and product_words:
                        # Check if significant words match
                        matching_words = [w for w in product_words if any(fw in w or w in fw for fw in filename_words)]
                        if len(matching_words) >= min(2, len(product_words) // 2):
                            should_enrich = True
                    elif any(word in filename_lower for word in product_words if len(word) > 3):
                        # Product word appears in filename
                        should_enrich = True
                    elif any(word in product_name_lower for word in filename_words if len(word) > 3):
                        # Filename word appears in product name
                        should_enrich = True
                elif product_uom:
                    # Product name has UoM - always apply it
                    should_enrich = True
                
                if should_enrich:
                    # Check if current UoM is less specific than the extracted one
                    current_purchase_uom = item.get('purchase_uom', '')
                    current_is_generic = current_purchase_uom.lower() in ['pack', 'each', 'unit', 'units', 'pc', '']
                    
                    # Check if extracted UoM matches current UoM (already correct)
                    extracted_uom = uom_to_use['purchase_uom']
                    uom_matches = current_purchase_uom.lower() == extracted_uom.lower()
                    
                    # Check if product name explicitly contains a UoM pattern (e.g., "1000pcs" in "Uni Lids Yellow 1000pcs")
                    # In this case, prioritize product name UoM over baseline
                    product_name_has_explicit_uom = product_uom is not None and product_uom['source'] == 'product_name'
                    
                    # Extract numeric value from current and extracted UoM for comparison
                    def extract_uom_number(uom_str: str) -> float:
                        """Extract numeric value from UoM string (e.g., '1000-pc' -> 1000.0)"""
                        if not uom_str:
                            return 0.0
                        match = re.search(r'(\d+(?:\.\d+)?)', uom_str)
                        return float(match.group(1)) if match else 0.0
                    
                    current_uom_num = extract_uom_number(current_purchase_uom)
                    extracted_uom_num = extract_uom_number(extracted_uom)
                    
                    # Apply UoM if:
                    # 1. Current is generic or empty, OR
                    # 2. Extracted UoM matches current (to mark source), OR
                    # 3. Product name has explicit UoM and it's different from current (prioritize product name)
                    should_apply = (
                        current_is_generic or 
                        not current_purchase_uom or 
                        uom_matches or
                        (product_name_has_explicit_uom and extracted_uom_num != current_uom_num)
                    )
                    
                    if should_apply:
                        item['purchase_uom'] = uom_to_use['purchase_uom']
                        item['unit_size'] = uom_to_use['unit_size']
                        item['unit_uom'] = uom_to_use['unit_uom']
                        item['uom_source'] = uom_to_use['source']
                        enriched_count += 1
                        if uom_matches:
                            logger.debug(f"  Marked '{product_name[:50]}' UoM source as {uom_to_use['source']}: {uom_to_use['purchase_uom']}")
                        elif product_name_has_explicit_uom:
                            logger.debug(f"  Overrode baseline UoM '{current_purchase_uom}' with product name UoM '{uom_to_use['purchase_uom']}' for '{product_name[:50]}'")
                        else:
                            logger.debug(f"  Enriched '{product_name[:50]}' with UoM from {uom_to_use['source']}: {uom_to_use['purchase_uom']}")
            
            if enriched_count > 0:
                logger.info(f"  ✓ Enriched {enriched_count} items with UoM from filename/product name")
            
            return items
        
        def process_bbi_file(file_path: Path) -> Tuple[str, Optional[Dict[str, Any]]]:
            """Process a single BBI file and return (receipt_id, receipt_data)"""
            try:
                logger.info(f"Processing [BBI]: {file_path.name}")
                
                # Apply vendor detection FIRST (before processing)
                initial_receipt_data = {'filename': file_path.name}
                initial_receipt_data = vendor_detector.apply_detection_to_receipt(file_path, initial_receipt_data)
                detected_vendor_code = initial_receipt_data.get('detected_vendor_code')
                
                # BBI files can be Excel (.xlsx) or PDF (UNI_IL_UT_*.pdf)
                if file_path.suffix.lower() in ['.xlsx', '.xls']:
                    receipt_data = excel_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                elif file_path.suffix.lower() == '.pdf':
                    # BBI PDF files - use unified PDF processor
                    receipt_data = unified_pdf_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                else:
                    logger.warning(f"Unsupported file type for BBI (Excel or PDF only): {file_path.suffix}")
                    return file_path.stem, None
                
                if receipt_data:
                    receipt_id = receipt_data.get('order_id') or file_path.stem
                    # Preserve fields from vendor detection
                    if 'detected_vendor_code' not in receipt_data:
                        receipt_data['detected_vendor_code'] = detected_vendor_code
                    if 'detected_source_type' not in receipt_data:
                        receipt_data['detected_source_type'] = initial_receipt_data.get('detected_source_type', 'bbi_based')
                    # Set source_group and source_file
                    receipt_data['source_group'] = 'bbi_based'
                    if 'source_file' not in receipt_data:
                        receipt_data['source_file'] = str(file_path.relative_to(input_dir))
                    
                    # Apply UoM/Pack determination for BBI items (if baseline is available)
                    items = receipt_data.get('items', [])
                    
                    # Filter out items with zero amount for BBI orders
                    if items:
                        filtered_items = []
                        removed_items = []
                        for item in items:
                            total_price = float(item.get('total_price', 0.0))
                            # Keep discounts even if total_price is 0 or negative
                            if total_price < 0:
                                filtered_items.append(item)
                            # Filter if total_price is 0 (unless it's a discount)
                            elif total_price == 0.0:
                                removed_items.append(item)
                            else:
                                filtered_items.append(item)
                        
                        if removed_items:
                            logger.info(f"  Filtered out {len(removed_items)} item(s) with zero amount")
                            for item in removed_items:
                                logger.debug(f"    - Removed: {item.get('product_name', 'Unknown')} (${item.get('total_price', 0):.2f})")
                        
                        receipt_data['items'] = filtered_items
                        items = filtered_items
                    
                    item_count = len(items)
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
                receipt_id = file_path.stem
                error_data: Dict[str, Any] = {
                    'filename': file_path.name,
                    'vendor': 'BBI',
                    'items': [],
                    'total': 0.0,
                    'source_group': 'bbi_based',
                    'source_file': str(file_path.relative_to(input_dir)),
                    'needs_review': True,
                    'review_reasons': [f'Error processing: {str(e)}']
                }
                return receipt_id, error_data
        
        for file_path in bbi_based_files:
            receipt_id, receipt_data = process_bbi_file(file_path)
            if receipt_data:
                items = receipt_data.get('items', [])
                
                # Fill missing quantity safely for BBI items (only when blank)
                inferred_count = 0
                for item in items:
                    quantity = item.get('quantity')
                    unit_price = item.get('unit_price')
                    total_price = item.get('total_price')
                    
                    # Check if quantity is missing/non-numeric
                    quantity_is_valid = False
                    try:
                        if quantity is not None:
                            qty_float = float(quantity)
                            if qty_float > 0:
                                quantity_is_valid = True
                    except (ValueError, TypeError):
                        quantity_is_valid = False
                    
                    # Only fill if quantity is missing/non-numeric and both unit_price and total_price are present
                    if not quantity_is_valid and unit_price is not None and total_price is not None:
                        try:
                            unit_price_float = float(unit_price)
                            total_price_float = float(total_price)
                            
                            if unit_price_float > 0:
                                # Calculate qty = total_price / unit_price
                                qty = total_price_float / unit_price_float
                                
                                # If abs(qty - round(qty)) < 1e-6, use int(round(qty))
                                if abs(qty - round(qty)) < 1e-6:
                                    qty = int(round(qty))
                                else:
                                    qty = round(qty, 3)
                                
                                item['quantity'] = qty
                                item['needs_quantity_review'] = True
                                # Store metadata about the inference for future processing
                                item['quantity_inferred'] = True
                                item['quantity_inferred_from'] = {
                                    'unit_price': unit_price_float,
                                    'total_price': total_price_float,
                                    'calculation': f"{total_price_float:.2f} / {unit_price_float:.2f} = {qty}"
                                }
                                inferred_count += 1
                                logger.debug(f"  Inferred quantity for '{item.get('product_name', '')}': {qty} (from ${total_price_float:.2f} / ${unit_price_float:.2f})")
                        except (ValueError, TypeError, ZeroDivisionError):
                            # Skip if calculation fails
                            pass
                
                if inferred_count > 0:
                    logger.info(f"  ✓ Inferred quantity for {inferred_count}/{len(items)} items (marked needs_quantity_review)")
                
                # Apply UoM/Pack determination if baseline is available
                if bbi_baseline:
                    determined_count = 0
                    uom_set_count = 0
                    
                    for item in items:
                        # Use canonical_name (with aliases applied) for matching, fall back to product_name
                        product_name = item.get('canonical_name') or item.get('product_name', '')
                        unit_price = item.get('unit_price', 0.0)
                        quantity = item.get('quantity', 0.0)
                        
                        # First, try to find a baseline match (even without pricing determination)
                        baseline_item = None
                        if product_name:
                            # Use lower threshold for matching (0.6 instead of 0.8)
                            # Note: find_match already applies aliases, but we're using canonical_name which already has aliases
                            baseline_item = bbi_baseline.find_match(product_name, threshold=0.6)
                        
                        if baseline_item:
                            # Store baseline match info
                            item['baseline_match'] = baseline_item
                            item['baseline_description'] = baseline_item.get('description', '')
                            item['baseline_match_score'] = baseline_item.get('match_score', 0.0)
                            
                            # Determine pricing unit (UoM vs Pack) by comparing receipt price to baseline prices
                            # Use 20% tolerance to account for price changes over time
                            if unit_price > 0:
                                pricing_unit, confidence, _ = bbi_baseline.determine_pricing_unit(
                                    product_name, unit_price, quantity, price_tolerance=0.20
                                )
                                
                                if pricing_unit:
                                    item['pricing_unit'] = pricing_unit  # 'UoM' or 'Pack'
                                    item['pricing_confidence'] = confidence
                                    determined_count += 1
                                    
                                    # D) Fix pack/EACH inconsistency - set purchase_uom based on pricing_unit
                                    if pricing_unit == 'Pack':
                                        # Pack items: use compound UoM from pack_size if available (e.g., "10-pc", "20*1-kg")
                                        # Otherwise fall back to "pack"
                                        pack_size = baseline_item.get('pack_size', '').strip()
                                        if pack_size:
                                            item['baseline_pack_size'] = pack_size
                                            
                                            # Check if pack_size is a compound UoM format (e.g., "10-pc", "2-lb", "20*1-kg")
                                            # Pattern: number(s) followed by unit (with optional multiplier like "20*1-kg")
                                            import re
                                            # Match patterns like "10-pc", "2-lb", "20*1-kg", "3.5-lb"
                                            compound_uom_match = re.match(r'^(\d+(?:\.\d+)?)\s*[-]?\s*(pc|lb|pound|pounds|kg|g|oz|fl\s*oz|gal|qt|pt|ml|l|each|ea|unit|units|roll|bag|ct|count)$', pack_size.lower())
                                            if compound_uom_match:
                                                # Use the compound UoM directly (e.g., "10-pc")
                                                item['purchase_uom'] = pack_size.lower().replace(' ', '-')  # Normalize spaces to hyphens
                                                logger.debug(f"  Set Pack pricing for '{product_name}': purchase_uom={item['purchase_uom']} (from pack_size)")
                                            else:
                                                # Check for multiplier format like "20*1-kg" -> use "20-kg" or "1-kg" depending on what makes sense
                                                multiplier_match = re.match(r'^(\d+)\s*\*\s*(\d+(?:\.\d+)?)\s*[-]?\s*(pc|lb|kg|g|oz|fl\s*oz|gal|qt|pt|ml|l|each|ea|unit|units|roll|bag|ct|count)$', pack_size.lower())
                                                if multiplier_match:
                                                    # Use the per-unit size (e.g., "20*1-kg" -> "1-kg")
                                                    unit_size = multiplier_match.group(2)
                                                    unit = multiplier_match.group(3)
                                                    item['purchase_uom'] = f"{unit_size}-{unit}"
                                                    logger.debug(f"  Set Pack pricing for '{product_name}': purchase_uom={item['purchase_uom']} (from pack_size multiplier format)")
                                                else:
                                                    # Not a compound format, use "pack"
                                                    item['purchase_uom'] = 'pack'
                                                    logger.debug(f"  Set Pack pricing for '{product_name}': purchase_uom=pack (pack_size not in compound format)")
                                            
                                            # Extract UoM from pack size for reference (e.g., "20*1-kg" -> "kg")
                                            baseline_uom = bbi_baseline._extract_uom_unit(pack_size)
                                            if baseline_uom:
                                                item['baseline_uom'] = baseline_uom
                                                item['raw_uom_text'] = baseline_uom
                                        else:
                                            # If no pack_size, use uom from baseline if available
                                            baseline_uom = baseline_item.get('uom', '').strip()
                                            if baseline_uom:
                                                item['baseline_uom'] = baseline_uom
                                                item['raw_uom_text'] = baseline_uom
                                            # Default to "pack" if no pack_size
                                            item['purchase_uom'] = 'pack'
                                        
                                        item['baseline_pack_count'] = baseline_item.get('pack_count', 1)
                                        uom_set_count += 1
                                    else:  # pricing_unit == 'UoM'
                                        # UoM items: use UoM from baseline
                                        baseline_uom = baseline_item.get('uom', '').strip()
                                        if baseline_uom:
                                            item['baseline_uom'] = baseline_uom
                                            item['purchase_uom'] = baseline_uom
                                            item['raw_uom_text'] = baseline_uom
                                            uom_set_count += 1
                                            logger.debug(f"  Set UoM from baseline for '{product_name}': {baseline_uom}")
                                        else:
                                            # If baseline has no UoM but pack_size exists, it's a Pack item
                                            # This handles cases where baseline.uom == "" and baseline.pack_size exists
                                            pack_size = baseline_item.get('pack_size', '').strip()
                                            if pack_size:
                                                item['pricing_unit'] = 'Pack'
                                                item['purchase_uom'] = 'pack'
                                                item['baseline_pack_size'] = pack_size
                                                item['baseline_pack_count'] = baseline_item.get('pack_count', 1)
                                                uom_set_count += 1
                                                logger.debug(f"  Set Pack pricing for '{product_name}' (baseline has pack_size but no uom): purchase_uom=pack")
                    
                    if uom_set_count > 0:
                        logger.info(f"  ✓ Set UoM from baseline for {uom_set_count}/{len(items)} items")
                    if determined_count > 0:
                        logger.info(f"  ✓ Determined pricing unit for {determined_count}/{len(items)} items")
                    
                    # Enrich items with UoM from filename (as fallback or supplement to baseline)
                    items = enrich_bbi_items_from_filename(file_path.name, items)
                
                # Vendor-scoped UNI_Mousse: clean description and stitch tails
                vendor_name = (receipt_data.get('vendor_name') or '').strip()
                if vendor_name == 'UNI_Mousse':
                    try:
                        from repairs.vendor_uni_mousse import stitch_tail_items
                        items = stitch_tail_items(items)
                        receipt_data['items'] = items
                    except Exception as e:
                        logger.warning(f"UNI_Mousse stitch/clean failed: {e}")

                # Set quantity_display for all BBI items (after UoM/Pack determination)
                from .generate_report import _format_bbi_quantity_display
                for item in items:
                    item['quantity_display'] = _format_bbi_quantity_display(item)
                
                # Stitch wrapped descriptions for UNI_Mousse (re-attach stray tail lines like "Cake")
                vendor = receipt_data.get('vendor_name', '')
                if vendor == 'UNI_Mousse' or 'MOUSSE' in vendor.upper():
                    from repairs.stitch_wrapped_desc import stitch_wrapped_descriptions
                    items = stitch_wrapped_descriptions(items, vendor)
                    receipt_data['items'] = items
                    logger.debug(f"  Applied stitch repair for {receipt_id}: {len(items)} items after stitching")
                
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
    
    ### Process Wismettac-based files (PDF invoices)
    wismettac_based_output_dir = output_base_dir / 'wismettac_based'
    wismettac_based_data: Dict[str, Any] = {}
    
    if wismettac_based_files:
        logger.info("Processing Wismettac-based receipts...")
        
        for file_path in wismettac_based_files:
            try:
                logger.info(f"Processing [Wismettac]: {file_path.name}")
                
                # Apply vendor detection FIRST (before processing)
                initial_receipt_data = {'filename': file_path.name}
                initial_receipt_data = vendor_detector.apply_detection_to_receipt(file_path, initial_receipt_data)
                detected_vendor_code = initial_receipt_data.get('detected_vendor_code', 'WISMETTAC')
                
                # Wismettac files are PDF files - use unified PDF processor
                if file_path.suffix.lower() == '.pdf':
                    receipt_data = unified_pdf_processor.process_file(file_path, detected_vendor_code=detected_vendor_code)
                else:
                    logger.warning(f"Unsupported file type for Wismettac (PDF only): {file_path.suffix}")
                    continue
                
                if receipt_data:
                    receipt_id = receipt_data.get('order_id') or receipt_data.get('receipt_number') or file_path.stem
                    
                    # Preserve fields from vendor detection
                    if 'detected_vendor_code' not in receipt_data:
                        receipt_data['detected_vendor_code'] = detected_vendor_code
                    if 'detected_source_type' not in receipt_data:
                        receipt_data['detected_source_type'] = initial_receipt_data.get('detected_source_type', 'wismettac_based')
                    
                    # Add source info
                    receipt_data['source_group'] = 'wismettac_based'
                    if 'source_file' not in receipt_data:
                        receipt_data['source_file'] = str(file_path.relative_to(input_dir))
                    
                    # Apply UoM extraction
                    from .uom_extractor import UoMExtractor
                    uom_extractor = UoMExtractor(rule_loader)
                    receipt_data['items'] = uom_extractor.extract_uom_from_items(receipt_data.get('items', []))
                    
                    wismettac_based_data[receipt_id] = receipt_data
                    item_count = len([i for i in receipt_data.get('items', []) if not i.get('is_fee')])
                    logger.info(f"  ✓ Extracted {item_count} items")
                else:
                    logger.warning(f"  ✗ Failed to process {file_path.name}")
                    
            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}", exc_info=True)
    
    ### Process Odoo-based files (Receipts/Odoo folder - Excel purchase orders)
    # Odoo purchase orders are now in Excel format instead of PDF
    # Process Excel files directly to extract purchase order data
    
    odoo_based_data: Dict[str, Dict[str, Any]] = {}
    
    if odoo_based_files:
        logger.info("Processing Odoo-based Excel purchase orders...")
        
        # Import the Odoo Excel processor
        from .odoo_excel_processor import process_odoo_excel
        
        for file_path in odoo_based_files:
            try:
                logger.info(f"Processing [Odoo Excel]: {file_path.name}")
                
                # Process Excel file directly
                if file_path.suffix.lower() in ['.xlsx', '.xls']:
                    receipt_data_dict = process_odoo_excel(file_path)
                    if receipt_data_dict:
                        # Add to odoo_based_data (merge with any existing data)
                        odoo_based_data.update(receipt_data_dict)
                    else:
                        logger.warning(f"No data extracted from {file_path.name}")
                    continue
                else:
                    logger.warning(f"Unsupported file type for Odoo Excel: {file_path.suffix}")
                    continue
                
                if receipt_data:
                    receipt_id = receipt_data.get('order_id') or receipt_data.get('receipt_number') or file_path.stem
                    
                    # Set vendor info (for saving/display) but keep source as odoo_based
                    receipt_data['vendor_code'] = detected_vendor_code
                    receipt_data['detected_vendor_code'] = detected_vendor_code
                    receipt_data['vendor_name'] = detected_vendor_name
                    receipt_data['source_type'] = 'odoo_based'
                    receipt_data['detected_source_type'] = 'odoo_based'
                    receipt_data['source_group'] = 'odoo_based'
                    receipt_data['source_file'] = str(file_path.relative_to(input_dir))
                    receipt_data['odoo_original'] = True  # Flag that this came from Odoo folder
                    receipt_data['odoo_vendor_match_score'] = vendor_match_score
                    
                    # Apply UoM extraction
                    from .uom_extractor import UoMExtractor
                    uom_extractor = UoMExtractor(rule_loader)
                    receipt_data['items'] = uom_extractor.extract_uom_from_items(receipt_data.get('items', []))
                    
                    odoo_based_data[receipt_id] = receipt_data
                    item_count = len([i for i in receipt_data.get('items', []) if not i.get('is_fee')])
                    logger.info(f"  ✓ Processed as Odoo format, detected vendor: {detected_vendor_code}, extracted {item_count} items")
                else:
                    logger.warning(f"  ✗ Failed to process {file_path.name} as Odoo format")
                    
            except Exception as e:
                logger.error(f"Error processing Odoo receipt {file_path.name}: {e}", exc_info=True)
    
    ### Apply Name Hygiene (extract UPC/Item# and clean names BEFORE classification)
    logger.info("Applying name hygiene to all items...")
    
    from .name_hygiene import apply_name_hygiene_batch
    
    # Apply name hygiene to all receipt types
    for receipts_data in [
        localgrocery_based_data,
        instacart_based_data,
        bbi_based_data,
        amazon_based_data,
        webstaurantstore_based_data,
        wismettac_based_data,
        odoo_based_data,
    ]:
        if not receipts_data:
            continue
        
        for receipt_id, receipt_data in receipts_data.items():
            try:
                items = receipt_data.get('items', [])
                if items:
                    # Apply name hygiene: extract UPC/Item# and create clean_name
                    receipt_data['items'] = apply_name_hygiene_batch(items)
                    # Ensure all items have unit_size, unit_uom, and qty
                    from .utils.item_size_extractor import ensure_unit_size_uom_qty
                    receipt_data['items'] = ensure_unit_size_uom_qty(receipt_data['items'])
            except Exception as e:
                logger.warning(f"Error applying name hygiene to {receipt_id}: {e}", exc_info=True)
    
    ### Normalize item names (fold whitespace, apply alias, keep CJK) BEFORE classification
    logger.info("Normalizing item names (fold whitespace, keep CJK)...")
    
    from preprocess.normalize import normalize_item_name, english_canonicalize
    
    # Normalize all items (sets canonical_name with fold_ws)
    for receipts_data in [
        localgrocery_based_data,
        instacart_based_data,
        bbi_based_data,
        amazon_based_data,
        webstaurantstore_based_data,
        wismettac_based_data,
        odoo_based_data,
    ]:
        if not receipts_data:
            continue
        
        for receipt_id, receipt_data in receipts_data.items():
            try:
                items = receipt_data.get('items', [])
                if items:
                    for item in items:
                        normalize_item_name(item)
                        # For BBI/UNI_Mousse vendors, force English-only canonical names to stabilize classification
                        vendor_name = (receipt_data.get('vendor_name') or receipt_data.get('vendor') or '').strip()
                        if vendor_name in ('BBI', 'UNI_Mousse'):
                            # Force English-only for canonical and display names to stabilize downstream rules
                            item['canonical_name'] = english_canonicalize(item.get('canonical_name', '') or (item.get('display_name') or item.get('product_name') or ''))
                            item['display_name'] = english_canonicalize(item.get('display_name', '') or item.get('product_name', '') or item.get('canonical_name', ''))
            except Exception as e:
                logger.warning(f"Error normalizing names for {receipt_id}: {e}", exc_info=True)
    
    # Optional: Enrich Wismettac items from knowledge base (brand/category/pack/barcode)
    try:
        from pathlib import Path as _Path
        import json as _json
        # Load knowledge base
        kb_path = _Path('data/step1_input/knowledge_base.json')
        if not kb_path.exists():
            kb_path = _Path('data/knowledge_base.json')
        
        if kb_path.exists() and wismettac_based_data:
            with open(kb_path, 'r', encoding='utf-8') as f:
                kb = _json.load(f)
            
            enriched_count = 0
            for receipt_id, receipt_data in wismettac_based_data.items():
                for item in receipt_data.get('items', []):
                    item_no = (item.get('item_number') or '').strip().lstrip('#')
                    if not item_no:
                        continue
                    
                    # Look up in knowledge base
                    kb_entry = kb.get(item_no)
                    if not kb_entry:
                        continue
                    
                    # Handle both old format (list) and new format (dict)
                    if isinstance(kb_entry, dict):
                        # New format with all fields
                        # Brand & Category from KB (vendor-scoped fields)
                        if kb_entry.get('brand') and not item.get('vendor_brand'):
                            item['vendor_brand'] = kb_entry['brand']
                        if kb_entry.get('category') and not item.get('vendor_category'):
                            item['vendor_category'] = kb_entry['category']
                        # Pack size enrichment
                        if kb_entry.get('pack_size') and not item.get('pack_size_raw'):
                            item['pack_size_raw'] = kb_entry['pack_size']
                        # Product name enrichment (if better than OCR)
                        if kb_entry.get('name') and not item.get('product_name'):
                            item['product_name'] = kb_entry['name']
                        # Size spec enrichment
                        if kb_entry.get('size_spec') and not item.get('size_spec'):
                            item['size_spec'] = kb_entry['size_spec']
                        enriched_count += 1
                    elif isinstance(kb_entry, list) and len(kb_entry) >= 4:
                        # Old format: [name, store, size_spec, unit_price]
                        if kb_entry[0] and not item.get('product_name'):
                            item['product_name'] = kb_entry[0]
                        if kb_entry[2] and not item.get('size_spec'):
                            item['size_spec'] = kb_entry[2]
                        enriched_count += 1
            
            if enriched_count > 0:
                logger.info("Enriched %d Wismettac items from knowledge base", enriched_count)
        else:
            # Fallback to old enrichment file if KB doesn't exist
            enrich_path = _Path(wismettac_based_output_dir) / 'wismettac_enrichment.json'
            if enrich_path.exists() and wismettac_based_data:
                with open(enrich_path, 'r', encoding='utf-8') as f:
                    wismettac_enrich = _json.load(f)
                # Build map by itemNumber string
                enrich_map = {str(k): v for k, v in wismettac_enrich.items()}
                for receipt_id, receipt_data in wismettac_based_data.items():
                    for item in receipt_data.get('items', []):
                        item_no = (item.get('item_number') or '').strip()
                        if not item_no:
                            continue
                        rec = enrich_map.get(item_no)
                        if not rec:
                            continue
                        # Brand & Category from site (vendor-scoped fields)
                        if rec.get('brand'):
                            item['vendor_brand'] = rec['brand']
                        if rec.get('category'):
                            item['vendor_category'] = rec['category']
                        # Barcode/UPC
                        if rec.get('barcode') and not item.get('upc'):
                            item['upc'] = rec['barcode']
                        # Pack size enrichment
                        if rec.get('packSizeRaw') and not item.get('pack_size_raw'):
                            item['pack_size_raw'] = rec['packSizeRaw']
                        pp = rec.get('packParsed') or {}
                        if pp and isinstance(pp, dict):
                            if pp.get('caseQty') is not None and not item.get('pack_case_qty'):
                                item['pack_case_qty'] = pp.get('caseQty')
                            if pp.get('each') is not None and not item.get('each_qty'):
                                item['each_qty'] = pp.get('each')
                            if pp.get('uom') and not item.get('each_uom'):
                                item['each_uom'] = pp.get('uom')
            logger.info("Applied Wismettac enrichment from %s", enrich_path)
    except Exception as e:
        logger.warning("Wismettac enrichment failed: %s", e, exc_info=True)

    ### Match receipts to Odoo purchase orders and update with standard names
    logger.info("Matching receipts to Odoo purchase orders...")
    try:
        from .odoo_matcher import match_receipts_to_odoo
        
        # Combine all receipts for matching
        all_receipts = {}
        for receipts_data in [
            localgrocery_based_data,
            instacart_based_data,
            bbi_based_data,
            amazon_based_data,
            webstaurantstore_based_data,
            wismettac_based_data,
            odoo_based_data,
        ]:
            all_receipts.update(receipts_data)
        
        if all_receipts:
            stats = match_receipts_to_odoo(all_receipts)
            logger.info(f"Odoo matching complete: {stats['matched_receipts']}/{stats['total_receipts']} receipts, {stats['matched_items']}/{stats['total_items']} items")
    except Exception as e:
        logger.warning(f"Odoo matching failed: {e}", exc_info=True)

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
        ('webstaurantstore_based', webstaurantstore_based_data),
        ('wismettac_based', wismettac_based_data),
        ('odoo_based', odoo_based_data),
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
    
    # Calculate totals for all receipts (if missing)
    logger.info("Calculating receipt totals...")
    all_receipts_list = [
        localgrocery_based_data,
        instacart_based_data,
        bbi_based_data,
        amazon_based_data,
        webstaurantstore_based_data,
        wismettac_based_data,
        odoo_based_data,
    ]
    
    for receipts_data in all_receipts_list:
        for receipt_id, receipt_data in receipts_data.items():
            # If total is missing or 0, calculate from items
            current_total = receipt_data.get('total', 0) or 0
            if current_total == 0:
                items = receipt_data.get('items', [])
                if items:
                    # Sum all items (including fees)
                    items_total = sum(float(item.get('total_price', 0) or item.get('extended_amount', 0) or 0) for item in items)
                    # Add tax if present (but don't double-count if already in items)
                    tax = float(receipt_data.get('tax', 0) or 0)
                    shipping = float(receipt_data.get('shipping', 0) or 0)
                    other_charges = float(receipt_data.get('other_charges', 0) or 0)
                    
                    # Calculate total: items (which may include fees) + tax + shipping + other_charges
                    # Note: If shipping/other_charges are already in items as fees, they're already counted
                    calculated_total = items_total + tax + shipping + other_charges
                    
                    # Only set if we have a meaningful total
                    if calculated_total > 0:
                        receipt_data['total'] = calculated_total
                        logger.info(f"Calculated total for {receipt_id}: ${calculated_total:.2f} (items: ${items_total:.2f}, tax: ${tax:.2f}, shipping: ${shipping:.2f}, other: ${other_charges:.2f})")
    
    logger.info("Receipt totals calculated")
    
    # Route Odoo orders to their vendor-specific folders BEFORE saving
    # Odoo orders should be saved to both odoo_based folder AND their vendor's folder
    if odoo_based_data:
        # Group Odoo orders by vendor
        odoo_by_vendor = {}
        for receipt_id, receipt_data in odoo_based_data.items():
            vendor = receipt_data.get('vendor', 'UNKNOWN')
            # Normalize vendor name for folder matching
            vendor_normalized = vendor.strip().upper()
            
            # Map vendor to output folder - check for exact matches first
            target_folder = None
            
            # Check for Costco variations
            if 'COSTCO' in vendor_normalized:
                target_folder = 'localgrocery_based'
            # Check for 88 MarketPlace
            elif '88' in vendor_normalized or 'MARKETPLACE' in vendor_normalized:
                target_folder = 'localgrocery_based'
            # Check for other common local grocery vendors
            elif any(v in vendor_normalized for v in ['JEWEL', 'ALDI', 'RD', 'RESTAURANT', 'PARK', 'MARIANO', 'DUVERGER', 'FOODSERVICE', 'PIKE']):
                target_folder = 'localgrocery_based'
            
            if target_folder:
                if target_folder not in odoo_by_vendor:
                    odoo_by_vendor[target_folder] = {}
                odoo_by_vendor[target_folder][receipt_id] = receipt_data
                logger.debug(f"Routing Odoo order {receipt_id} (vendor: {vendor}) to {target_folder}")
        
        # Add Odoo orders to their vendor folders BEFORE saving
        for folder_name, receipts in odoo_by_vendor.items():
            if folder_name == 'localgrocery_based':
                localgrocery_based_data.update(receipts)
                logger.info(f"Added {len(receipts)} Odoo orders to localgrocery_based folder")
            # Add more folder mappings as needed
    
    ### Save output files and generate reports
    results: Dict[str, Dict[str, Any]] = {
        'localgrocery_based': localgrocery_based_data,
        'instacart_based': instacart_based_data,
        'bbi_based': bbi_based_data,
        'amazon_based': amazon_based_data,
        'webstaurantstore_based': webstaurantstore_based_data,
        'wismettac_based': wismettac_based_data,
        'odoo_based': odoo_based_data,
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
    
    # Save Wismettac-based output and generate report
    if wismettac_based_data:
        wismettac_based_output_dir.mkdir(parents=True, exist_ok=True)
        output_file = wismettac_based_output_dir / 'extracted_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(wismettac_based_data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved Wismettac-based data to: {output_file}")
        
        # Generate Wismettac-based report
        try:
            from .generate_report import generate_html_report
            report_file = wismettac_based_output_dir / 'report.html'
            generate_html_report(wismettac_based_data, report_file)
            logger.info(f"Generated Wismettac-based report: {report_file}")
        except Exception as e:
            logger.warning(f"Could not generate Wismettac-based report: {e}")
    
    # Generate combined final report at root output directory
    # Note: Odoo receipts are routed to their matched vendor groups, so they're already included in localgrocery_based_data
    # We exclude odoo_based_data from the combined report to avoid duplicates
    all_receipts: Dict[str, Any] = {}
    all_receipts.update(localgrocery_based_data)  # Already includes Odoo orders
    all_receipts.update(instacart_based_data)
    all_receipts.update(bbi_based_data)
    all_receipts.update(amazon_based_data)
    all_receipts.update(webstaurantstore_based_data)
    all_receipts.update(wismettac_based_data)
    # Note: odoo_based_data is NOT included here since those orders are already in localgrocery_based_data
    
    if all_receipts:
        # Generate standardized output FIRST (timestamped folder with CSV files)
        standardized_output_dir = None
        try:
            from .standardized_output import create_standardized_output
            standardized_output_dir = create_standardized_output(all_receipts, output_base_dir, input_dir=input_dir)
            logger.info(f"✅ Generated standardized output in: {standardized_output_dir}")
        except Exception as e:
            logger.warning(f"Could not generate standardized output: {e}", exc_info=True)
        
        # Reports are now generated in Step 2
        logger.info("✅ Standardized output created. Reports will be generated in Step 2.")
    
    # Generate combined HTML report (excluding odoo_based since those are already in localgrocery_based)
    if all_receipts:
        try:
            from .generate_report import generate_html_report
            combined_report_file = output_base_dir / 'report.html'
            generate_html_report(all_receipts, combined_report_file)
            logger.info(f"✅ Generated combined HTML report: {combined_report_file}")
        except Exception as e:
            logger.warning(f"Could not generate combined HTML report: {e}", exc_info=True)
    
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
    
    # Also save to odoo_based folder for reference (Odoo orders already routed to vendor folders above)
    odoo_based_output_dir = output_base_dir / 'odoo_based'
    odoo_based_output_dir.mkdir(parents=True, exist_ok=True)
    output_file = odoo_based_output_dir / 'extracted_data.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(odoo_based_data, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"Saved Odoo-based data to: {output_file}")
    
    # Generate Odoo-based report
    try:
        from .generate_report import generate_html_report
        report_file = odoo_based_output_dir / 'report.html'
        generate_html_report(odoo_based_data, report_file)
        logger.info(f"Generated Odoo-based report: {report_file}")
    except Exception as e:
        logger.warning(f"Could not generate Odoo-based report: {e}")
    
    logger.info(f"\nStep 1 Complete: Extracted {len(localgrocery_based_data)} vendor-based receipts, {len(instacart_based_data)} instacart-based receipts, {len(bbi_based_data)} BBI receipts, {len(amazon_based_data)} Amazon receipts, {len(webstaurantstore_based_data)} WebstaurantStore receipts, {len(wismettac_based_data)} Wismettac receipts, {len(odoo_based_data)} Odoo receipts")
    
    return results


def main() -> None:
    """Main entry point for step1_extract"""
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser(
        description='Step 1: Extract receipt data from PDF files (CSV baseline files for Instacart/Amazon)',
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

