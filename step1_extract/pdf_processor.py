#!/usr/bin/env python3
"""
PDF Processor - Instacart-based receipts
Processes PDF files with CSV baseline matching.

Processing Flow:
1. Vendor detection (handled by main.py via VendorDetector)
2. Legacy PDF processing (preserves all existing Instacart logic)
3. UoM extraction (always applied: 30_uom_extraction.yaml)

See step1_rules/README.md for rule file documentation.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PDFProcessor:
    """Process PDF files for Group 2 (Instacart) - preserves all existing logic exactly"""
    
    def __init__(self, rule_loader, input_dir=None):
        """
        Initialize PDF processor
        
        Args:
            rule_loader: RuleLoader instance
            input_dir: Input directory path (for knowledge base location)
        """
        self.rule_loader = rule_loader
        self.group_rules = rule_loader.load_group_rules('group2')
        self.input_dir = Path(input_dir) if input_dir else None
        
        # Prepare config with knowledge base file path (from input folder)
        config = {}
        if self.input_dir:
            kb_file = self.input_dir / 'knowledge_base.json'
            if kb_file.exists():
                config['knowledge_base_file'] = str(kb_file)
        
        # Import existing ReceiptProcessor for PDF processing
        # This preserves ALL Instacart logic exactly:
        # - CSV matching algorithm
        # - Fuzzy threshold ≈ 0.8
        # - UoM normalization and match diagnostics
        # - Fee extraction and subtotal/total validation
        # - PDF text parsing logic
        # - AI fallback mechanism
        from .receipt_processor import ReceiptProcessor
        self._legacy_processor = ReceiptProcessor(config=config)
    
    def process_file(self, file_path: Path) -> Dict:
        """
        Process a PDF file (Instacart)
        
        Processing Flow:
        1. Try modern PDF layout rules (26_instacart_pdf_layout.yaml) first
        2. If layout matches, use ReceiptLineEngine to parse
        3. Apply CSV matching (if available)
        4. Fall back to legacy processor if no layout matches
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Dictionary containing extracted receipt data
        """
        # For Instacart, load items from CSV first (CSV has product names)
        # PDF is only used for fees and validation
        vendor_code = 'INSTACART'
        
        # Use legacy processor's CSV-first approach (it has all the CSV logic)
        # But mark it as modern if CSV is successfully used
        try:
            # Find receipt folder - search parent folders for CSV files (handles nested folder structure)
            receipt_folder = file_path.parent
            order_id = self._legacy_processor._extract_order_id_from_filename(file_path.name)
            
            # If CSV files are not in immediate folder, search parent folders
            # Look for instacart folder that contains CSV files
            current_folder = receipt_folder
            max_depth = 3  # Limit search depth
            depth = 0
            found_csv_folder = None
            
            while depth < max_depth and current_folder != self.input_dir and current_folder.parent != current_folder:
                # Check if this folder contains instacart CSV files
                csv_files = list(current_folder.glob('*order*summary*.csv')) + list(current_folder.glob('*instacart*.csv'))
                if csv_files:
                    found_csv_folder = current_folder
                    logger.debug(f"Found Instacart CSV files in parent folder: {found_csv_folder}")
                    break
                # Check if folder name contains 'instacart' (likely the right folder)
                if 'instacart' in current_folder.name.lower():
                    found_csv_folder = current_folder
                    logger.debug(f"Found instacart folder: {found_csv_folder}")
                    break
                current_folder = current_folder.parent
                depth += 1
            
            # Use found folder if available, otherwise use original parent
            if found_csv_folder:
                receipt_folder = found_csv_folder
            
            if order_id and self._legacy_processor.csv_processor:
                # Use legacy processor's CSV logic (which has all the CSV extraction built in)
                csv_data = self._legacy_processor.csv_processor.process_receipt_with_csv(receipt_folder, order_id)
                
                if csv_data and csv_data.get('items'):
                    logger.info(f"Loaded {len(csv_data['items'])} items from CSV for {file_path.name}")
                    
                    # Extract fees and tax from PDF (fees and tax are in PDF, not CSV)
                    pdf_text = self._legacy_processor._get_pdf_text(file_path)
                    if pdf_text:
                        # Extract fees from PDF
                        if self._legacy_processor.fee_extractor:
                            fees = self._legacy_processor.fee_extractor.extract_fees_from_receipt_text(pdf_text)
                            if fees:
                                csv_data = self._legacy_processor.fee_extractor.add_fees_to_receipt_items(csv_data, fees)
                                logger.info(f"Extracted {len(fees)} fee items from PDF")
                        
                        # Extract tax from PDF text
                        if self._legacy_processor.total_validator:
                            extracted_totals = self._legacy_processor.total_validator.extract_totals(pdf_text)
                            if extracted_totals.get('tax'):
                                csv_data['tax'] = extracted_totals['tax']
                                logger.info(f"Extracted tax from PDF: ${csv_data['tax']:.2f}")
                            if extracted_totals.get('subtotal') and not csv_data.get('subtotal'):
                                csv_data['subtotal'] = extracted_totals['subtotal']
                                logger.debug(f"Extracted subtotal from PDF: ${csv_data['subtotal']:.2f}")
                    
                    # Validate total from CSV baseline
                    if self._legacy_processor.csv_processor:
                        validation = self._legacy_processor.csv_processor.validate_receipt_total(receipt_folder, csv_data, order_id)
                        if validation and validation.get('expected_total') is not None:
                            csv_data['total'] = validation.get('expected_total')
                            logger.info(f"✓ Total set from CSV baseline: ${csv_data['total']:.2f}")
                    
                    # Apply unit detection and UoM normalization (from legacy processor logic)
                    # This preserves the CSV unit processing
                    from step1_extract.csv_processor import derive_uom_from_size
                    for item in csv_data.get('items', []):
                        current_uom = item.get('purchase_uom', '').lower() if item.get('purchase_uom') else ''
                        size_field = item.get('size', '')
                        
                        if (not current_uom or current_uom == '' or current_uom == 'each') and size_field:
                            derived_uom, extra_fields = derive_uom_from_size(size_field)
                            if derived_uom and derived_uom != 'each':
                                item['purchase_uom'] = derived_uom
                                item['unit_confidence'] = 0.9
                                item.update(extra_fields)
                    
                    # Update receipt data with modern layout markers
                    csv_data['parsed_by'] = 'instacart_pdf_v1'
                    csv_data['detected_vendor_code'] = vendor_code
                    csv_data['detected_source_type'] = 'instacart_based'
                    csv_data['source_file'] = str(file_path.relative_to(self.input_dir) if self.input_dir and self.input_dir in file_path.parents else file_path.name)
                    csv_data['source_group'] = 'instacart_based'
                    csv_data['needs_review'] = False
                    csv_data['review_reasons'] = []
                    
                    # Apply UoM extraction (adds raw_uom_text, raw_size_text)
                    from .uom_extractor import UoMExtractor
                    uom_extractor = UoMExtractor(self.rule_loader)
                    csv_data['items'] = uom_extractor.extract_uom_from_items(csv_data['items'])
                    
                    # Add parsed_by and csv_source flag to all items
                    for item in csv_data['items']:
                        item['parsed_by'] = 'instacart_pdf_v1'
                        # csv_source flag is already set by csv_processor._extract_item_from_csv_row
                        # but ensure it's set here as well for clarity
                        if 'csv_source' not in item:
                            item['csv_source'] = True
                    
                    logger.info(f"Processed {file_path.name} using modern CSV-first approach for {vendor_code}")
                    return csv_data
                else:
                    logger.debug(f"No items found in CSV for {file_path.name}, falling back to legacy processor")
            else:
                logger.debug(f"Could not extract order ID from filename {file_path.name} or CSV processor not available, falling back to legacy processor")
        except Exception as csv_error:
            logger.debug(f"Error loading items from CSV for {file_path.name}: {csv_error}, falling back to legacy processor")
        
        # Check if legacy parsers are enabled (feature flag)
        legacy_enabled = True
        if self.rule_loader:
            legacy_enabled = self.rule_loader.get_legacy_enabled()
        
        if not legacy_enabled:
            logger.warning(f"[LEGACY] Legacy parsers disabled, but no modern layout matched for PDF {file_path.name}")
            return {
                'filename': file_path.name,
                'vendor': 'Instacart',
                'items': [],
                'total': 0.0,
                'parsed_by': 'none',
                'needs_review': True,
                'review_reasons': ['step1: no modern layout matched and legacy parsers disabled']
            }
        
        # Fall back to legacy processor (preserves all existing Instacart logic)
        logger.info(f"[LEGACY] Using legacy parser for: {file_path.name} (vendor=INSTACART, reason=no modern layout matched)")
        try:
            receipt_data = self._legacy_processor.process_pdf(str(file_path))
            
            # Ensure vendor is set correctly
            if not receipt_data.get('vendor'):
                receipt_data['vendor'] = 'Instacart'
            
            # Preserve fields from vendor detection (don't overwrite if already exist)
            preserve_fields = self.group_rules.get('preserve_fields', [])
            if preserve_fields:
                # These fields were set by vendor detection and should not be overwritten
                # They're already in receipt_data from the initial detection, so we don't need to do anything
                # But we ensure they're not removed
                pass
            
            # Mark as parsed by legacy group2 (PDF processing always uses legacy)
            parsed_by_value = self.group_rules.get('parsed_by', 'legacy_group2_pdf')
            receipt_data['parsed_by'] = parsed_by_value
            receipt_data['needs_review'] = True
            if 'review_reasons' not in receipt_data:
                receipt_data['review_reasons'] = []
            receipt_data['review_reasons'].append("step1: no modern layout matched, used legacy group rules")
            
            # Apply UoM extraction
            if receipt_data.get('items'):
                from .uom_extractor import UoMExtractor
                uom_extractor = UoMExtractor(self.rule_loader)
                receipt_data['items'] = uom_extractor.extract_uom_from_items(receipt_data['items'])
                
                # Add parsed_by to all items
                for item in receipt_data['items']:
                    item['parsed_by'] = parsed_by_value
            
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing PDF file {file_path.name}: {e}", exc_info=True)
            return {
                'filename': file_path.name,
                'vendor': 'Instacart',
                'items': [],
                'total': 0.0,
                'needs_review': True,
                'review_reasons': [f'Error processing: {str(e)}']
            }
    
    def _apply_csv_matching(self, receipt_data: Dict, file_path: Path) -> Dict:
        """
        Apply Instacart CSV matching to receipt data (if CSV is available)
        
        Args:
            receipt_data: Receipt data dictionary
            file_path: Path to PDF file
            
        Returns:
            Updated receipt data with CSV-matched fields
        """
        try:
            from .instacart_csv_matcher import InstacartCSVMatcher
            
            # Find receipt folder - check current folder and parent folders for CSV files
            receipt_folder = file_path.parent
            order_id = receipt_data.get('order_id')
            
            # If CSV files are not in immediate folder, search parent folders
            # Look for instacart folder that contains CSV files
            current_folder = receipt_folder
            max_depth = 3  # Limit search depth
            depth = 0
            while depth < max_depth and current_folder != self.input_dir and current_folder.parent != current_folder:
                # Check if this folder contains instacart CSV files
                csv_files = list(current_folder.glob('*order*summary*.csv')) + list(current_folder.glob('*instacart*.csv'))
                if csv_files:
                    receipt_folder = current_folder
                    logger.debug(f"Found Instacart CSV files in parent folder: {receipt_folder}")
                    break
                # Check if folder name contains 'instacart' (likely the right folder)
                if 'instacart' in current_folder.name.lower():
                    receipt_folder = current_folder
                    logger.debug(f"Found instacart folder: {receipt_folder}")
                    break
                current_folder = current_folder.parent
                depth += 1
            
            # Load Instacart CSV matching rules
            instacart_rules = {}
            if self.rule_loader:
                instacart_rules = {'instacart_csv_match': self.rule_loader.get_instacart_csv_match_rules()}
            
            # Apply CSV matching
            instacart_matcher = InstacartCSVMatcher(rules=instacart_rules, receipt_folder=receipt_folder, rule_loader=self.rule_loader)
            
            if instacart_matcher.should_match(file_path.name, vendor='Instacart'):
                receipt_data['items'] = instacart_matcher.match_items(
                    receipt_data.get('items', []),
                    order_id,
                    vendor='Instacart'
                )
                logger.debug(f"Applied CSV matching to {len(receipt_data.get('items', []))} items")
        except Exception as e:
            logger.debug(f"CSV matching not available or failed: {e}")
        
        return receipt_data

