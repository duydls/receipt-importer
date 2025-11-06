#!/usr/bin/env python3
"""
Main Workflow Script - 5-Step Receipt Processing Pipeline
        Step 1: Extract data from receipts (PDF, CSV, Excel)
        Step 2: Manual Review Export (Excel)
        Step 3: Generate mapping file (imports reviewed Excel)
        Step 4: Generate SQL files
"""

import sys
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Load environment variables from .env file if it exists
_env_file = Path(__file__).parent / '.env'
if _env_file.exists():
    with open(_env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# Import workflow steps
from step1_extract.receipt_processor import ReceiptProcessor
from step2_manual_review.main import export_to_excel, load_reviewed_excel, apply_reviewed_data
from step3_mapping.product_matcher import ProductMatcher
from step4_sql.generate_receipt_sql import ReceiptSQLGenerator
from config import *


# Configure logging
def setup_logging(log_level: str = 'INFO', log_dir: Optional[str] = None):
    """Setup logging configuration
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_dir: Directory for log files (defaults to 'logs/')
    """
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_dir = log_dir or 'logs'
    log_file = Path(log_dir) / 'workflow.log'
    
    # Create log directory
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)


class ReceiptWorkflow:
    """5-Step Receipt Processing Workflow"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize workflow with configuration
        
        Args:
            config: Configuration dictionary (defaults to shared.config)
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # Initialize step processors
        self.step1_processor = ReceiptProcessor(self.config)
        self.step3_matcher = None  # Will be initialized in step3
        self.step4_generator = None  # Will be initialized in step4
        
        # Results storage
        self.extracted_data = {}  # Step 1 results
        self.reviewed_data = {}  # Step 2 results
        self.mapped_data = {}    # Step 3 results
        
        # Step-specific loggers
        self.step_loggers = {}
    
    def _setup_step_logging(self, log_dir: Path, step_name: str):
        """Setup step-specific logging to a directory
        
        Args:
            log_dir: Directory for step logs
            step_name: Step name (step1, step2, step3, step4)
        """
        # Create log directory if it doesn't exist
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f'{step_name}.log'
        
        # Create file handler for step-specific log
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(self.logger.level)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        
        # Add handler to logger
        self.logger.addHandler(file_handler)
        
        # Store handler for potential cleanup
        if step_name not in self.step_loggers:
            self.step_loggers[step_name] = []
        self.step_loggers[step_name].append(file_handler)
    
    def _prepare_step1_input(self, receipts_source_dir: Optional[str] = None,
                               step1_input_dir: Optional[str] = None) -> Path:
        """
        Prepare Step 1 input directory by copying/linking receipts folder
        
        Args:
            receipts_source_dir: Source receipts directory (defaults to STEP1_INPUT_DIR)
            step1_input_dir: Target Step 1 input directory (defaults to 'data/step1_input')
            
        Returns:
            Path to prepared Step 1 input directory
        """
        receipts_source_dir = receipts_source_dir or self.config.get('STEP1_INPUT_DIR', STEP1_INPUT_DIR)
        step1_input_dir = step1_input_dir or self.config.get('STEP1_INPUT_DIR_WORKING', 'data/step1_input')
        
        receipts_source_path = Path(receipts_source_dir)
        step1_input_path = Path(step1_input_dir)
        
        if not receipts_source_path.exists():
            self.logger.error(f"Receipts source directory not found: {receipts_source_dir}")
            raise FileNotFoundError(f"Receipts source directory not found: {receipts_source_dir}")
        
        # Create parent directory if it doesn't exist
        step1_input_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Remove existing step1_input directory if it exists
        if step1_input_path.exists():
            if step1_input_path.is_symlink():
                step1_input_path.unlink()
                self.logger.info(f"Removed existing symlink: {step1_input_path}")
            else:
                shutil.rmtree(step1_input_path)
                self.logger.info(f"Removed existing directory: {step1_input_path}")
        
        # Create symlink or copy
        try:
            # Try creating a symlink first (preferred)
            step1_input_path.symlink_to(receipts_source_path.resolve())
            self.logger.info(f"Created symlink: {step1_input_path} -> {receipts_source_path.resolve()}")
        except (OSError, NotImplementedError):
            # If symlink fails (e.g., on Windows or no permission), copy instead
            self.logger.warning(f"Symlink creation failed, copying directory instead...")
            shutil.copytree(receipts_source_path, step1_input_path)
            self.logger.info(f"Copied receipts directory: {receipts_source_path} -> {step1_input_path}")
        
        return step1_input_path
    
    def step1_extract_all_receipts(self, receipts_source_dir: Optional[str] = None,
                                   step1_input_dir: Optional[str] = None,
                                   output_dir: Optional[str] = None) -> Dict:
        """
        Step 1: Extract data from all receipts
        
        Reads PDF, Excel, and CSV files, and extracts structured receipt data.
        First prepares the input directory by copying/linking the receipts folder.
        
        Args:
            receipts_source_dir: Source receipts directory (defaults to STEP1_INPUT_DIR)
            step1_input_dir: Working input directory for Step 1 (defaults to 'data/step1_input')
            output_dir: Output directory for extracted data (defaults to STEP1_OUTPUT_DIR)
            
        Returns:
            Dictionary mapping receipt IDs to extracted data
        """
        self.logger.info("="*80)
        self.logger.info("STEP 1: Extract Data from Receipts")
        self.logger.info("="*80)
        
        # Prepare Step 1 input directory (copy/link receipts folder)
        step1_input_path = self._prepare_step1_input(receipts_source_dir, step1_input_dir)
        
        # Get output directory from config
        output_dir = output_dir or self.config.get('STEP1_OUTPUT_DIR', STEP1_OUTPUT_DIR)
        output_path = Path(output_dir)
        
        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Setup step-specific logging
        step_log_dir = output_path / 'logs'
        step_log_dir.mkdir(parents=True, exist_ok=True)
        self._setup_step_logging(step_log_dir, 'step1')
        
        self.logger.info(f"Input directory: {step1_input_path} (from source: {receipts_source_dir})")
        self.logger.info(f"Output directory: {output_dir}")
        self.logger.info(f"Log directory: {step_log_dir}")
        
        # Use new main.py entry point for Step 1 processing
        use_new_main = False
        extracted_data = {}
        
        try:
            from step1_extract.main import process_files
            rules_dir = Path(__file__).parent / 'step1_rules'
            results = process_files(step1_input_path, output_path, rules_dir)
            
            # Merge group1 and group2 data for backward compatibility
            if 'group1' in results:
                extracted_data.update(results['group1'])
            if 'group2' in results:
                extracted_data.update(results['group2'])
            
            use_new_main = True
            self.logger.info("Using new Step 1 extraction system (main.py)")
        except (ImportError, Exception) as e:
            self.logger.warning(f"New Step 1 main.py not available, falling back to legacy processor: {e}")
            # Fallback to legacy processing - keep existing code below
            use_new_main = False
        
        # Fallback to legacy processing if new main.py failed (shouldn't happen in normal operation)
        if not use_new_main:
            self.logger.error("New Step 1 extraction system failed - falling back to legacy processor")
            self.logger.error("This should not happen. Please check for errors above.")
            # Legacy fallback code removed - use new main.py instead
        
        # If we used new main.py, reports are already generated per group
        # But we should still save merged extracted_data for Step 2 compatibility
        if 'extracted_data' not in locals() or not extracted_data:
            extracted_data = {}
        
        self.logger.info(f"\nStep 1 Complete: Extracted data from {len(extracted_data)} receipts")
        
        self.extracted_data = extracted_data
        
        # Save merged extracted data to Step 1 output directory (Step 2 input) for backward compatibility
        output_file = output_path / 'extracted_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, indent=2, ensure_ascii=False, default=str)
        self.logger.info(f"Saved merged extracted data to: {output_file}")
        
        # Generate human-readable report (merged) for backward compatibility
        try:
            from step1_extract.generate_report import generate_html_report
            report_file = output_path / 'report.html'
            generate_html_report(extracted_data, report_file)
            self.logger.info(f"Generated merged HTML report: {report_file}")
            self.logger.info(f"  Group-specific reports available in output/group1/ and output/group2/")
            self.logger.info(f"  You can open it in your browser or print to PDF")
        except Exception as e:
            self.logger.warning(f"Could not generate report: {e}")
        
        return extracted_data
    
    def step2_export_for_review(self, input_dir: Optional[str] = None,
                                 output_dir: Optional[str] = None,
                                 filename: str = "manual_review_export.xlsx") -> Path:
        """
        Step 2: Export data for manual review
        
        Exports Step 1 extracted data to Excel for manual review and corrections.
        
        Args:
            input_dir: Input directory with extracted data from Step 1 (defaults to STEP1_OUTPUT_DIR)
            output_dir: Output directory for Excel file (defaults to STEP2_OUTPUT_DIR)
            filename: Output Excel filename
            
        Returns:
            Path to generated Excel file
        """
        self.logger.info("="*80)
        self.logger.info("STEP 2: Export for Manual Review")
        self.logger.info("="*80)
        
        # Get input and output directories from config
        input_dir = input_dir or self.config.get('STEP1_OUTPUT_DIR', STEP1_OUTPUT_DIR)
        output_dir = output_dir or self.config.get('STEP2_OUTPUT_DIR', STEP2_OUTPUT_DIR)
        
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        # Validate input directory exists
        if not input_path.exists():
            self.logger.error(f"Input directory not found: {input_dir}")
            self.logger.error("Run Step 1 first to generate input data.")
            return None
        
        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Setup step-specific logging
        step_log_dir = output_path / 'logs'
        step_log_dir.mkdir(parents=True, exist_ok=True)
        self._setup_step_logging(step_log_dir, 'step2')
        
        self.logger.info(f"Input directory: {input_dir}")
        self.logger.info(f"Output directory: {output_dir}")
        self.logger.info(f"Log directory: {step_log_dir}")
        
        # Export to Excel
        excel_file = export_to_excel(input_path, output_path, filename)
        
        if excel_file and excel_file.exists():
            self.logger.info(f"\nStep 2 Complete: Exported to {excel_file}")
            self.logger.info(f"Please review and edit the Excel file, then run Step 3 with --reviewed-excel option")
            
            # Generate reports from artifacts
            try:
                from step2_manual_review.main import generate_reports_from_artifacts
                reports = generate_reports_from_artifacts(input_path, input_path)
                if reports:
                    self.logger.info(f"✅ Generated {len(reports)} reports from artifacts")
                    for name, path in reports.items():
                        self.logger.info(f"  - {name}: {path}")
                else:
                    self.logger.warning("No reports generated (artifacts may not be available)")
            except Exception as e:
                self.logger.warning(f"Could not generate reports: {e}", exc_info=True)
            
            return excel_file
        else:
            self.logger.error("Step 2 failed: Excel export failed")
            return None
    
    def step2_import_reviewed(self, reviewed_excel_path: Path,
                              step1_output_dir: Optional[str] = None) -> Dict:
        """
        Step 2 (import): Import reviewed Excel and apply changes
        
        Args:
            reviewed_excel_path: Path to reviewed Excel file
            step1_output_dir: Step 1 output directory (defaults to STEP1_OUTPUT_DIR)
            
        Returns:
            Updated extracted data with reviewed values applied
        """
        step1_output_dir = step1_output_dir or self.config.get('STEP1_OUTPUT_DIR', STEP1_OUTPUT_DIR)
        step1_output_path = Path(step1_output_dir)
        
        # Load reviewed Excel
        reviewed_data = load_reviewed_excel(reviewed_excel_path)
        
        # Load original extracted data
        all_extracted = {}
        for source_type in ['localgrocery_based', 'instacart_based', 'bbi_based', 'amazon_based', 'webstaurantstore_based']:
            json_file = step1_output_path / source_type / 'extracted_data.json'
            if json_file.exists():
                with open(json_file, 'r', encoding='utf-8') as f:
                    extracted = json.load(f)
                    all_extracted.update(extracted)
        
        # Apply reviewed data
        updated_data = apply_reviewed_data(all_extracted, reviewed_data)
        
        # Save updated data back to Step 1 output (will be used by Step 3)
        output_file = step1_output_path / 'reviewed_extracted_data.json'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, indent=2, ensure_ascii=False, default=str)
        
        self.logger.info(f"Applied reviewed data to {len(updated_data)} receipts")
        self.logger.info(f"Saved to {output_file}")
        
        self.reviewed_data = updated_data
        return updated_data
    
    def step3_generate_mapping(self, input_dir: Optional[str] = None,
                               output_dir: Optional[str] = None,
                               mapping_file: Optional[str] = None,
                               reviewed_excel_path: Optional[Path] = None) -> Dict:
        """
        Step 3: Generate mapping file
        
        Matches receipt products to database products and creates/updates the mapping file.
        Imports reviewed Excel from Step 2 if provided.
        
        Args:
            input_dir: Input directory with extracted data from Step 1 (defaults to STEP1_OUTPUT_DIR)
            output_dir: Output directory for mapped data (defaults to STEP3_OUTPUT_DIR)
            mapping_file: Path to mapping file (defaults to config)
            reviewed_excel_path: Path to reviewed Excel from Step 2 (optional)
            
        Returns:
            Dictionary of mapped products
        """
        self.logger.info("="*80)
        self.logger.info("STEP 3: Generate Mapping File")
        self.logger.info("="*80)
        
        # Import reviewed Excel if provided
        if reviewed_excel_path and reviewed_excel_path.exists():
            self.logger.info(f"Importing reviewed Excel from Step 2: {reviewed_excel_path}")
            self.step2_import_reviewed(reviewed_excel_path, input_dir)
            # Use reviewed data for mapping
            input_dir = input_dir or self.config.get('STEP1_OUTPUT_DIR', STEP1_OUTPUT_DIR)
            extracted_data_file = Path(input_dir) / 'reviewed_extracted_data.json'
            if extracted_data_file.exists():
                self.logger.info(f"Using reviewed data from: {extracted_data_file}")
                with open(extracted_data_file, 'r', encoding='utf-8') as f:
                    extracted_data = json.load(f)
                self.logger.info(f"Loaded {len(extracted_data)} receipts from reviewed data")
            else:
                self.logger.warning(f"Reviewed data file not found: {extracted_data_file}, using original data")
                extracted_data = None
        else:
            extracted_data = None
        
        # Get input and output directories from config
        input_dir = input_dir or self.config.get('STEP1_OUTPUT_DIR', STEP1_OUTPUT_DIR)
        output_dir = output_dir or self.config.get('STEP3_OUTPUT_DIR', STEP3_OUTPUT_DIR)
        
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        # Validate input directory exists
        if not input_path.exists():
            self.logger.error(f"Input directory not found: {input_dir}")
            self.logger.error("Run Step 1 first to generate input data.")
            return {}
        
        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Setup step-specific logging
        step_log_dir = output_path / 'logs'
        step_log_dir.mkdir(parents=True, exist_ok=True)
        self._setup_step_logging(step_log_dir, 'step3')
        
        # Load extracted data (use reviewed if available, otherwise original)
        if extracted_data is None:
            # Try to load reviewed data first
            reviewed_data_file = input_path / 'reviewed_extracted_data.json'
            if reviewed_data_file.exists():
                self.logger.info(f"Loading reviewed data from: {reviewed_data_file}")
                with open(reviewed_data_file, 'r', encoding='utf-8') as f:
                    extracted_data = json.load(f)
                self.logger.info(f"Using reviewed data from Step 2")
            else:
                # Fallback to original extracted data
                extracted_data_file = input_path / 'extracted_data.json'
                if not extracted_data_file.exists():
                    # Fallback to self.extracted_data if file doesn't exist (for backward compatibility)
                    extracted_data = self.extracted_data or {}
                    if not extracted_data:
                        self.logger.error(f"Input file not found: {extracted_data_file}")
                        self.logger.error("No extracted data available. Run Step 1 first.")
                        return {}
                    self.logger.warning(f"Input file not found: {extracted_data_file}, using in-memory data")
                else:
                    self.logger.info(f"Loading extracted data from: {extracted_data_file}")
                    with open(extracted_data_file, 'r', encoding='utf-8') as f:
                        extracted_data = json.load(f)
        
        self.logger.info(f"Input directory: {input_dir}")
        self.logger.info(f"Output directory: {output_dir}")
        self.logger.info(f"Log directory: {step_log_dir}")
        
        # Determine mapping file paths (always in Step 3 output directory)
        mapping_file = output_path / 'product_name_mapping.json'
        fruit_conversion_file = output_path / 'fruit_weight_conversion.json'
        
        # Use existing mappings from output if they exist, otherwise create new ones
        if mapping_file.exists():
            self.logger.info(f"Using existing mapping file from output: {mapping_file}")
        else:
            self.logger.info(f"Creating new mapping file in output: {mapping_file}")
        
        if fruit_conversion_file.exists():
            self.logger.info(f"Using existing fruit conversion file from output: {fruit_conversion_file}")
        else:
            self.logger.info(f"Creating new fruit conversion file in output: {fruit_conversion_file}")
        
        # Convert to strings for ProductMatcher
        mapping_file = str(mapping_file)
        fruit_conversion_file = str(fruit_conversion_file)
        
        db_dump_json = self.config.get('DB_DUMP_JSON', DB_DUMP_JSON)
        
        # Initialize product matcher
        if not Path(db_dump_json).exists():
            self.logger.error(f"Database dump JSON not found: {db_dump_json}")
            return {}
        
        self.step3_matcher = ProductMatcher(
            db_dump_json,
            mapping_file=mapping_file,
            fruit_conversion_file=fruit_conversion_file
        )
        
        self.logger.info(f"Using mapping file: {mapping_file}")
        self.logger.info(f"Using fruit conversion file: {fruit_conversion_file}")
        
        # Collect all unique products from receipts
        all_items = []
        for receipt_id, receipt_data in extracted_data.items():
            for item in receipt_data.get('items', []):
                item['receipt_id'] = receipt_id
                all_items.append(item)
        
        self.logger.info(f"Found {len(all_items)} total items across {len(extracted_data)} receipts")
        
        # Match items to products (this will use existing mapping file)
        matched_items = self.step3_matcher.match_receipt_items(all_items, config=self.config)
        
        self.logger.info(f"Matched {sum(1 for m in matched_items if m['matched'])} items")
        
        # Save mapped data to Step 3 output directory (Step 4 input)
        mapped_data = {
            'receipts': extracted_data,
            'matched_items': matched_items
        }
        
        output_file = output_path / 'mapped_data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(mapped_data, f, indent=2, ensure_ascii=False, default=str)
        self.logger.info(f"Saved mapped data to: {output_file}")
        
        self.mapped_data = mapped_data
        
        # Save mapping files to Step 3 output directory
        # The ProductMatcher may have updated the mapping file, so save it to output
        if hasattr(self.step3_matcher, 'product_mappings') and self.step3_matcher.product_mappings:
            mapping_output_file = output_path / 'product_name_mapping.json'
            with open(mapping_output_file, 'w', encoding='utf-8') as f:
                json.dump(self.step3_matcher.product_mappings, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved mapping file to: {mapping_output_file}")
        
        if hasattr(self.step3_matcher, 'fruit_conversions') and self.step3_matcher.fruit_conversions:
            fruit_conversion_output_file = output_path / 'fruit_weight_conversion.json'
            with open(fruit_conversion_output_file, 'w', encoding='utf-8') as f:
                json.dump(self.step3_matcher.fruit_conversions, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved fruit conversion file to: {fruit_conversion_output_file}")
        
        self.logger.info("\nStep 3 Complete: Mapping files saved to output directory")
        self.logger.info(f"Review and update mappings in: {output_path}")
        
        return mapped_data
    
    def step4_generate_sql(self, input_dir: Optional[str] = None,
                           output_dir: Optional[str] = None) -> List[str]:
        """
        Step 4: Generate SQL files
        
        Creates SQL INSERT statements for purchase orders and lines from mapped receipt data.
        Only reads from input directory (Step 3 output).
        
        Args:
            input_dir: Input directory with mapped data from Step 3 (defaults to STEP3_OUTPUT_DIR)
            output_dir: Output directory for SQL files (defaults to STEP4_OUTPUT_DIR)
            
        Returns:
            List of generated SQL file paths
        """
        self.logger.info("="*80)
        self.logger.info("STEP 4: Generate SQL Files")
        self.logger.info("="*80)
        
        # Get input and output directories from config
        input_dir = input_dir or self.config.get('STEP3_OUTPUT_DIR', STEP3_OUTPUT_DIR)
        output_dir = output_dir or self.config.get('STEP4_OUTPUT_DIR', STEP4_OUTPUT_DIR)
        
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        # Validate input directory exists
        if not input_path.exists():
            self.logger.error(f"Input directory not found: {input_dir}")
            self.logger.error("Run Step 3 first to generate input data.")
            return []
        
        # Load mapped data from Step 3 output (Step 4 input)
        mapped_data_file = input_path / 'mapped_data.json'
        if not mapped_data_file.exists():
            self.logger.error(f"Input file not found: {mapped_data_file}")
            self.logger.error("No mapped data available. Run Step 3 first.")
            return []
        
        self.logger.info(f"Loading mapped data from: {mapped_data_file}")
        with open(mapped_data_file, 'r', encoding='utf-8') as f:
            mapped_data = json.load(f)
        
        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Setup step-specific logging
        step_log_dir = output_path / 'logs'
        step_log_dir.mkdir(parents=True, exist_ok=True)
        self._setup_step_logging(step_log_dir, 'step4')
        
        self.logger.info(f"Input directory: {input_dir}")
        self.logger.info(f"Output directory: {output_dir}")
        self.logger.info(f"Log directory: {step_log_dir}")
        
        # Load mapping files from Step 3 output (Step 4 input)
        mapping_file = input_path / 'product_name_mapping.json'
        fruit_conversion_file = input_path / 'fruit_weight_conversion.json'
        
        if not mapping_file.exists():
            self.logger.error(f"Mapping file not found in input: {mapping_file}")
            self.logger.error("Run Step 3 first to generate mapping files.")
            return []
        
        if not fruit_conversion_file.exists():
            self.logger.warning(f"Fruit conversion file not found in input: {fruit_conversion_file}")
            self.logger.warning("Step 4 will continue with default fruit conversion file.")
        
        # Update config to use mapping files from input directory
        step4_config = self.config.copy()
        step4_config['PRODUCT_MAPPING_FILE'] = str(mapping_file)
        step4_config['FRUIT_CONVERSION_FILE'] = str(fruit_conversion_file) if fruit_conversion_file.exists() else self.config.get('FRUIT_CONVERSION_FILE', FRUIT_CONVERSION_FILE)
        
        self.logger.info(f"Using mapping file from input: {mapping_file}")
        if fruit_conversion_file.exists():
            self.logger.info(f"Using fruit conversion file from input: {fruit_conversion_file}")
        
        # Initialize SQL generator with updated config
        self.step4_generator = ReceiptSQLGenerator(step4_config)
        
        # Generate SQL for each receipt
        receipts = mapped_data.get('receipts', {})
        matched_items = mapped_data.get('matched_items', [])
        
        # Group matched items by receipt_id
        items_by_receipt = {}
        for item in matched_items:
            receipt_item = item.get('receipt_item', {})
            receipt_id = receipt_item.get('receipt_id') or 'unknown'
            if receipt_id not in items_by_receipt:
                items_by_receipt[receipt_id] = []
            items_by_receipt[receipt_id].append(item)
        
        sql_files = []
        for receipt_id, receipt_data in receipts.items():
            try:
                matched_items_for_receipt = items_by_receipt.get(receipt_id, [])
                
                sql_file = self.step4_generator.generate_sql_for_receipt(
                    receipt_data,
                    matched_items_for_receipt,
                    output_dir=str(output_path)
                )
                
                if sql_file:
                    sql_files.append(sql_file)
                    self.logger.info(f"  ✓ Generated: {Path(sql_file).name}")
                
            except Exception as e:
                self.logger.error(f"Error generating SQL for receipt {receipt_id}: {e}", exc_info=True)
        
        self.logger.info(f"\nStep 4 Complete: Generated {len(sql_files)} SQL files")
        
        return sql_files
    
    def run_all(self, receipts_source_dir: Optional[str] = None,
                step1_output_dir: Optional[str] = None,
                step2_output_dir: Optional[str] = None,
                step3_output_dir: Optional[str] = None,
                step4_output_dir: Optional[str] = None,
                mapping_file: Optional[str] = None,
                reviewed_excel_path: Optional[Path] = None) -> Dict:
        """
        Run all 4 steps in sequence
        
        Args:
            receipts_source_dir: Source receipts directory (defaults to STEP1_INPUT_DIR)
            step1_output_dir: Step 1 output directory (Step 2 input)
            step2_output_dir: Step 2 output directory (manual review Excel)
            step3_output_dir: Step 3 output directory (Step 4 input)
            step4_output_dir: Step 4 output directory (SQL files)
            mapping_file: Path to mapping file
            reviewed_excel_path: Path to reviewed Excel from Step 2 (optional)
            
        Returns:
            Summary dictionary with results from all steps
        """
        self.logger.info("="*80)
        self.logger.info("RECEIPT PROCESSING WORKFLOW - ALL STEPS")
        self.logger.info("="*80)
        self.logger.info(f"Started at: {datetime.now()}")
        self.logger.info("")
        
        summary = {
            'started_at': datetime.now().isoformat(),
            'step1': {},
            'step2': {},
            'step3': {},
            'step4': {}
        }
        
        # Step 1: Extract
        try:
            extracted_data = self.step1_extract_all_receipts(
                receipts_source_dir=receipts_source_dir,
                output_dir=step1_output_dir
            )
            summary['step1'] = {
                'status': 'success',
                'receipts_processed': len(extracted_data),
                'total_items': sum(len(r.get('items', [])) for r in extracted_data.values())
            }
        except Exception as e:
            self.logger.error(f"Step 1 failed: {e}", exc_info=True)
            summary['step1'] = {'status': 'failed', 'error': str(e)}
            return summary
        
        # Step 2: Export for manual review
        try:
            excel_file = self.step2_export_for_review(
                input_dir=step1_output_dir,
                output_dir=step2_output_dir
            )
            if excel_file:
                summary['step2'] = {
                    'status': 'success',
                    'excel_file': str(excel_file)
                }
                self.logger.info("Step 2: Manual review Excel exported. Please review and edit.")
                if reviewed_excel_path:
                    self.logger.info(f"Importing reviewed Excel: {reviewed_excel_path}")
                    self.step2_import_reviewed(reviewed_excel_path, step1_output_dir)
                else:
                    self.logger.info("No reviewed Excel provided. Skipping import. Run Step 3 with --reviewed-excel to import.")
            else:
                summary['step2'] = {'status': 'failed', 'error': 'Excel export failed'}
        except Exception as e:
            self.logger.error(f"Step 2 failed: {e}", exc_info=True)
            summary['step2'] = {'status': 'failed', 'error': str(e)}
            # Continue to Step 3 even if Step 2 fails
        
        # Step 3: Generate mapping
        try:
            mapped_data = self.step3_generate_mapping(
                input_dir=step1_output_dir,
                output_dir=step3_output_dir,
                mapping_file=mapping_file,
                reviewed_excel_path=reviewed_excel_path
            )
            summary['step3'] = {
                'status': 'success',
                'receipts_mapped': len(mapped_data.get('receipts', {})),
                'items_matched': sum(1 for m in mapped_data.get('matched_items', []) if m.get('matched'))
            }
        except Exception as e:
            self.logger.error(f"Step 3 failed: {e}", exc_info=True)
            summary['step3'] = {'status': 'failed', 'error': str(e)}
            return summary
        
        # Step 4: Generate SQL
        try:
            sql_files = self.step4_generate_sql(
                input_dir=step3_output_dir,
                output_dir=step4_output_dir
            )
            summary['step4'] = {
                'status': 'success',
                'sql_files_generated': len(sql_files)
            }
        except Exception as e:
            self.logger.error(f"Step 4 failed: {e}", exc_info=True)
            summary['step4'] = {'status': 'failed', 'error': str(e)}
        
        summary['completed_at'] = datetime.now().isoformat()
        
        self.logger.info("")
        self.logger.info("="*80)
        self.logger.info("WORKFLOW COMPLETE")
        self.logger.info("="*80)
        self.logger.info(f"Completed at: {datetime.now()}")
        self.logger.info(f"Summary: {json.dumps(summary, indent=2, default=str)}")
        
        return summary


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Receipt Processing Workflow')
    parser.add_argument('--step', type=int, choices=[1, 2, 3, 4], 
                       help='Run specific step only (1=extract, 2=manual_review, 3=mapping, 4=sql)')
    parser.add_argument('--receipts-source', type=str,
                       help='Source receipts directory (will be copied/linked to Step 1 input)')
    parser.add_argument('--step1-output', type=str,
                       help='Step 1 output directory (Step 2 input)')
    parser.add_argument('--step2-output', type=str,
                       help='Step 2 output directory (manual review Excel)')
    parser.add_argument('--step3-output', type=str,
                       help='Step 3 output directory (Step 4 input)')
    parser.add_argument('--step4-output', type=str,
                       help='Step 4 output directory (SQL files)')
    parser.add_argument('--mapping-file', type=str,
                       help='Path to mapping file (Step 3)')
    parser.add_argument('--reviewed-excel', type=str,
                       help='Path to reviewed Excel file from Step 2 (for Step 3)')
    parser.add_argument('--log-level', type=str, default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.log_level)
    
    # Initialize workflow
    workflow = ReceiptWorkflow()
    
    reviewed_excel_path = Path(args.reviewed_excel) if args.reviewed_excel else None
    
    # Run requested step(s)
    if args.step == 1:
        workflow.step1_extract_all_receipts(
            receipts_source_dir=args.receipts_source,
            output_dir=args.step1_output
        )
    elif args.step == 2:
        workflow.step1_extract_all_receipts(
            receipts_source_dir=args.receipts_source,
            output_dir=args.step1_output
        )
        workflow.step2_export_for_review(
            input_dir=args.step1_output,
            output_dir=args.step2_output
        )
    elif args.step == 3:
        workflow.step1_extract_all_receipts(
            receipts_source_dir=args.receipts_source,
            output_dir=args.step1_output
        )
        workflow.step3_generate_mapping(
            input_dir=args.step1_output,
            output_dir=args.step3_output,
            mapping_file=args.mapping_file,
            reviewed_excel_path=reviewed_excel_path
        )
    elif args.step == 4:
        workflow.step1_extract_all_receipts(
            receipts_source_dir=args.receipts_source,
            output_dir=args.step1_output
        )
        workflow.step3_generate_mapping(
            input_dir=args.step1_output,
            output_dir=args.step3_output,
            mapping_file=args.mapping_file,
            reviewed_excel_path=reviewed_excel_path
        )
        workflow.step4_generate_sql(
            input_dir=args.step3_output,
            output_dir=args.step4_output
        )
    else:
        # Run all steps
        workflow.run_all(
            receipts_source_dir=args.receipts_source,
            step1_output_dir=args.step1_output,
            step2_output_dir=args.step2_output,
            step3_output_dir=args.step3_output,
            step4_output_dir=args.step4_output,
            mapping_file=args.mapping_file,
            reviewed_excel_path=reviewed_excel_path
        )


if __name__ == '__main__':
    main()

