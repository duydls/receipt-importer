#!/usr/bin/env python3
"""
Redo Step 1 extraction and add standard_name (Odoo product name) to items
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step1_extract.main import process_files
from step1_extract.generate_report import generate_html_report
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_product_mapping() -> Dict[str, Dict[str, Any]]:
    """Load product mapping from matching results"""
    mapping_file = Path('data/product_standard_name_mapping.json')
    
    if not mapping_file.exists():
        logger.warning(f"Product mapping file not found: {mapping_file}")
        return {}
    
    with open(mapping_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def enrich_items_with_standard_name(receipts_data: Dict[str, Dict[str, Any]], 
                                    product_mapping: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Enrich receipt items with standard_name from product mapping"""
    
    enriched_count = 0
    total_items = 0
    
    for receipt_id, receipt_data in receipts_data.items():
        items = receipt_data.get('items', [])
        
        for item in items:
            total_items += 1
            
            # Try to find matching Odoo product name
            product_name = item.get('product_name', '') or item.get('display_name', '') or item.get('canonical_name', '')
            
            # Try exact match first
            key = f"{receipt_id}|||{product_name}"
            if key in product_mapping:
                mapping = product_mapping[key]
                item['standard_name'] = mapping.get('standard_name', '')
                item['odoo_product_id'] = mapping.get('odoo_product_id', '')
                item['odoo_l2_category'] = mapping.get('odoo_l2_category', '')
                item['odoo_l2_name'] = mapping.get('odoo_l2_name', '')
                item['odoo_l1_category'] = mapping.get('odoo_l1_category', '')
                item['odoo_l1_name'] = mapping.get('odoo_l1_name', '')
                enriched_count += 1
            else:
                # Try fuzzy matching by product name only (fallback)
                # This handles cases where receipt_id might differ slightly
                for map_key, mapping in product_mapping.items():
                    if product_name in map_key:
                        item['standard_name'] = mapping.get('standard_name', '')
                        item['odoo_product_id'] = mapping.get('odoo_product_id', '')
                        item['odoo_l2_category'] = mapping.get('odoo_l2_category', '')
                        item['odoo_l2_name'] = mapping.get('odoo_l2_name', '')
                        item['odoo_l1_category'] = mapping.get('odoo_l1_category', '')
                        item['odoo_l1_name'] = mapping.get('odoo_l1_name', '')
                        enriched_count += 1
                        break
    
    logger.info(f"Enriched {enriched_count}/{total_items} items with standard_name")
    return receipts_data


def main():
    """Main function"""
    input_dir = Path('data/step1_input')
    output_dir = Path('data/step1_output')
    rules_dir = Path('step1_rules')
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        return
    
    logger.info("=" * 100)
    logger.info("Step 1: Extracting receipt data")
    logger.info("=" * 100)
    
    # Run Step 1 extraction
    results = process_files(
        input_dir=input_dir,
        output_base_dir=output_dir,
        rules_dir=rules_dir,
        use_threads=True
    )
    
    logger.info("\n" + "=" * 100)
    logger.info("Enriching items with standard_name (Odoo product names)")
    logger.info("=" * 100)
    
    # Load product mapping
    product_mapping = load_product_mapping()
    logger.info(f"Loaded {len(product_mapping)} product mappings")
    
    # Enrich all receipts with standard_name
    enriched_results = {}
    for key, receipts_data in results.items():
        enriched_receipts = enrich_items_with_standard_name(receipts_data, product_mapping)
        enriched_results[key] = enriched_receipts
        
        # Save enriched data
        output_file = output_dir / key / 'extracted_data.json'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(enriched_receipts, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Saved enriched data to: {output_file}")
    
    logger.info("\n" + "=" * 100)
    logger.info("Regenerating standardized output with standard_name")
    logger.info("=" * 100)
    
    # Regenerate standardized output with enriched data
    all_receipts_for_output = {}
    for key, receipts_data in enriched_results.items():
        if key != 'odoo_based':  # Exclude odoo_based as it's already in localgrocery_based
            all_receipts_for_output.update(receipts_data)
    
    if all_receipts_for_output:
        try:
            from step1_extract.standardized_output import create_standardized_output
            standardized_output_dir = create_standardized_output(
                all_receipts_for_output, 
                output_dir, 
                input_dir=input_dir
            )
            logger.info(f"✅ Regenerated standardized output in: {standardized_output_dir}")
        except Exception as e:
            logger.warning(f"Could not regenerate standardized output: {e}", exc_info=True)
    
    logger.info("\n" + "=" * 100)
    logger.info("Generating reports with standard_name")
    logger.info("=" * 100)
    
    # Generate reports for each group
    for key, receipts_data in enriched_results.items():
        if receipts_data:
            try:
                report_file = output_dir / key / 'report.html'
                generate_html_report(receipts_data, report_file)
                logger.info(f"Generated report: {report_file}")
            except Exception as e:
                logger.warning(f"Could not generate report for {key}: {e}")
    
    # Generate combined report
    all_receipts = {}
    for key, receipts_data in enriched_results.items():
        if key != 'odoo_based':  # Exclude odoo_based as it's already in localgrocery_based
            all_receipts.update(receipts_data)
    
    if all_receipts:
        try:
            combined_report_file = output_dir / 'report.html'
            generate_html_report(all_receipts, combined_report_file)
            logger.info(f"✅ Generated combined HTML report: {combined_report_file}")
        except Exception as e:
            logger.warning(f"Could not generate combined HTML report: {e}")
    
    logger.info("\n" + "=" * 100)
    logger.info("✅ Step 1 complete with standard_name enrichment!")
    logger.info("=" * 100)


if __name__ == '__main__':
    main()

