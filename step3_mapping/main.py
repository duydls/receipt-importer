#!/usr/bin/env python3
"""
Step 3 Main Entry Point
Reads Step 1 outputs (or reviewed data from Step 2) and executes mapping rules
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from .rule_loader import RuleLoader
from .rule_executor import execute_stage
from .product_matcher import ProductMatcher

logger = logging.getLogger(__name__)


def load_step1_output(input_dir: Path, use_reviewed: bool = True) -> Dict[str, Any]:
    """
    Load Step 1 output data (or reviewed data from Step 2) from source-type folders
    
    Args:
        input_dir: Step 1 output directory (contains source-type folders)
        use_reviewed: If True, prefer reviewed_extracted_data.json from Step 2
        
    Returns:
        Dictionary with source-type keys containing extracted data
    """
    # Try to load reviewed data first (from Step 2)
    if use_reviewed:
        reviewed_file = input_dir / 'reviewed_extracted_data.json'
        if reviewed_file.exists():
            logger.info(f"Loading reviewed data from Step 2: {reviewed_file}")
            with open(reviewed_file, 'r', encoding='utf-8') as f:
                reviewed_data = json.load(f)
            logger.info(f"Loaded {len(reviewed_data)} receipts from reviewed data")
            # Convert to source-type structure for compatibility
            data = {
                'localgrocery_based': {},
                'instacart_based': {},
                'bbi_based': {},
                'amazon_based': {},
                'webstaurantstore_based': {}
            }
            # Group by source_type
            for receipt_id, receipt_data in reviewed_data.items():
                source_type = receipt_data.get('detected_source_type') or receipt_data.get('source_type', 'localgrocery_based')
                if source_type not in data:
                    source_type = 'localgrocery_based'  # fallback
                data[source_type][receipt_id] = receipt_data
            return data
    
    # Load from source-type folders (Step 1 output)
    source_types = ['localgrocery_based', 'instacart_based', 'bbi_based', 'amazon_based', 'webstaurantstore_based']
    
    data = {st: {} for st in source_types}
    
    for source_type in source_types:
        json_file = input_dir / source_type / 'extracted_data.json'
        if json_file.exists():
            logger.info(f"Loading {source_type} data from: {json_file}")
            with open(json_file, 'r', encoding='utf-8') as f:
                data[source_type] = json.load(f)
            logger.info(f"Loaded {len(data[source_type])} {source_type} receipts")
        else:
            logger.debug(f"{source_type} file not found: {json_file}")
    
    return data


def combine_receipts(step1_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combine receipts from all source types into a single structure
    
    Args:
        step1_data: Dictionary with source-type keys (localgrocery_based, instacart_based, etc.)
        
    Returns:
        Combined receipts dictionary with source_type metadata
    """
    combined = {}
    
    source_types = ['localgrocery_based', 'instacart_based', 'bbi_based', 'amazon_based', 'webstaurantstore_based']
    
    # Add receipts from all source types with source_type metadata
    for source_type in source_types:
        for receipt_id, receipt_data in step1_data.get(source_type, {}).items():
            receipt_data = receipt_data.copy()
            receipt_data['source_type'] = source_type
            if 'source_group' not in receipt_data:
                receipt_data['source_group'] = source_type
            combined[receipt_id] = receipt_data
    
    logger.info(f"Combined {len(combined)} total receipts")
    return combined


def process_rules(
    step1_input_dir: Path,
    output_dir: Path,
    rules_dir: Path,
    use_reviewed: bool = True
) -> Dict[str, Any]:
    """
    Main processing function - executes Step 3 rules
    
    Args:
        step1_input_dir: Step 1 output directory (or contains reviewed_extracted_data.json from Step 2)
        output_dir: Step 3 output directory
        rules_dir: Directory containing rule YAML files
        use_reviewed: If True, prefer reviewed data from Step 2
        
    Returns:
        Dictionary with mapped items and processing results
    """
    # Setup logger
    log_dir = output_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize rule loader
    rule_loader = RuleLoader(rules_dir)
    
    # Get meta information
    meta = rule_loader.get_meta()
    logger.info(f"Step 3 Rules: {meta.get('version', 'unknown')} - {meta.get('description', 'No description')}")
    
    # Load Step 1 output data (or reviewed data from Step 2)
    logger.info(f"Loading input data from: {step1_input_dir}")
    if use_reviewed and (step1_input_dir / 'reviewed_extracted_data.json').exists():
        logger.info("Using reviewed data from Step 2")
    step1_data = load_step1_output(step1_input_dir, use_reviewed=use_reviewed)
    
    # Combine receipts for processing
    combined_receipts = combine_receipts(step1_data)
    
    if not combined_receipts:
        logger.error("No receipts found in Step 1 output")
        return {}
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize ProductMatcher once at the beginning
    # Use DB_DUMP_JSON from config or default path
    try:
        import config
        db_dump_json = getattr(config, 'DB_DUMP_JSON', None)
    except ImportError:
        db_dump_json = None
    
    if not db_dump_json:
        # Default path relative to project root
        db_dump_json = Path(__file__).parent.parent.parent / 'odoo_data' / 'analysis' / 'products_uom_analysis.json'
        if not db_dump_json.exists():
            # Try alternate path
            db_dump_json = Path('../odoo_data/analysis/products_uom_analysis.json')
    
    logger.info(f"Initializing ProductMatcher with: {db_dump_json}")
    try:
        product_matcher = ProductMatcher(str(db_dump_json))
        logger.info("✓ ProductMatcher initialized")
    except Exception as e:
        logger.error(f"Failed to initialize ProductMatcher: {e}")
        logger.warning("Continuing without ProductMatcher - database matching may fail")
        product_matcher = None
    
    # Create shared context
    context = {
        'product_matcher': product_matcher,
        'output_dir': output_dir,
        'rule_loader': rule_loader
    }
    
    # Extract all items from receipts
    all_items = []
    for receipt_id, receipt_data in combined_receipts.items():
        for item in receipt_data.get('items', []):
            item_copy = item.copy()
            item_copy['receipt_id'] = receipt_id
            item_copy['receipt_data'] = receipt_data  # Include receipt context
            item_copy['source_type'] = receipt_data.get('source_type', '')
            item_copy['source_file'] = receipt_data.get('source_file', '')
            all_items.append(item_copy)
    
    logger.info(f"Found {len(all_items)} items across {len(combined_receipts)} receipts")
    
    # Get processing order from rules
    processing_order = rule_loader.get_processing_order()
    logger.info(f"Processing {len(processing_order)} rule stages: {', '.join(processing_order)}")
    
    # Execute each stage in order
    current_items = all_items
    
    for i, rule_file in enumerate(processing_order):
        logger.info("")
        logger.info(f"[{i+1}/{len(processing_order)}] Processing stage: {rule_file}")
        logger.info("=" * 80)
        
        # Execute stage
        current_items = execute_stage(current_items, rule_file, rule_loader, context)
        
        # Save intermediate stage file
        # Try to get output path from rule data
        rule_data = rule_loader.get_rule(rule_file)
        stage_file = None
        
        if rule_data:
            # Find top-level key to get stage config
            top_level_key = None
            for key in rule_data.keys():
                if key != 'meta' and not key.startswith('_'):
                    top_level_key = key
                    break
            
            if top_level_key:
                stage_config = rule_data[top_level_key]
                output_path = stage_config.get('output')
                if output_path:
                    # Extract filename from path (e.g., 'output/step2_output/_stage_vendor.json' -> '_stage_vendor.json')
                    stage_filename = Path(output_path).name
                    stage_file = output_dir / stage_filename
        
        # Fallback naming if not found in config
        if not stage_file:
            stage_key = rule_file.replace('.yaml', '').replace('_', '')
            stage_file = output_dir / f'_stage_{stage_key}.json'
        
        # Save stage output
        with open(stage_file, 'w', encoding='utf-8') as f:
            json.dump(current_items, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"✓ Saved stage output to: {stage_file}")
    
    # Get final output path from meta or outputs stage
    meta = rule_loader.get_meta()
    targets = meta.get('targets', {})
    mapped_items_file = targets.get('mapped_items')
    
    if mapped_items_file:
        # Extract filename from path
        mapped_items_filename = Path(mapped_items_file).name
        mapped_items_path = output_dir / mapped_items_filename
    else:
        # Default to mapped_items.json
        mapped_items_path = output_dir / 'mapped_items.json'
    
    # De-duplicate review lines by (source_file, canonical_product_key, unit_price, vendor_code)
    logger.info("")
    logger.info("De-duplicating review lines...")
    deduplicated_items = []
    review_key_counts = {}  # {(source_file, canonical_key, unit_price, vendor_code): count}
    
    for item in current_items:
        # Only de-duplicate items that need review
        if item.get('needs_review') and item.get('review_reasons'):
            source_file = item.get('source_file', '')
            canonical_key = item.get('canonical_product_key', '')
            unit_price = item.get('unit_price', 0)
            vendor_code = item.get('vendor_code', '')
            review_key = (source_file, canonical_key, unit_price, vendor_code)
            
            # Check if we've seen this key before
            if review_key in review_key_counts:
                # Increment count but keep the item (for now we'll consolidate later)
                review_key_counts[review_key] += 1
                # Keep first occurrence, mark others as duplicates
                item['_duplicate_count'] = review_key_counts[review_key]
                deduplicated_items.append(item)
            else:
                # First occurrence
                review_key_counts[review_key] = 1
                item['_duplicate_count'] = 1
                deduplicated_items.append(item)
        else:
            # Not a review item, keep as-is
            deduplicated_items.append(item)
    
    # Update items with duplicate counts
    for item in deduplicated_items:
        if '_duplicate_count' in item and item['_duplicate_count'] > 1:
            # Add note about duplicates
            if 'review_reasons' not in item:
                item['review_reasons'] = []
            item['review_reasons'].append(f"Duplicate entry (appears {item['_duplicate_count']} times)")
    
    logger.info(f"De-duplication: {len(current_items)} items → {len(deduplicated_items)} items")
    if review_key_counts:
        duplicate_count = sum(1 for count in review_key_counts.values() if count > 1)
        logger.info(f"  - Found {duplicate_count} review line groups with duplicates")
    
    current_items = deduplicated_items
    
    # Save final mapped items
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"Saving final mapped items to: {mapped_items_path}")
    with open(mapped_items_path, 'w', encoding='utf-8') as f:
        json.dump(current_items, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"✓ Saved mapped items: {len(current_items)} items")
    
    # Close database connection if opened
    if 'db_conn' in context:
        try:
            context['db_conn'].close()
            logger.info("✓ Database connection closed")
        except Exception as e:
            logger.warning(f"Error closing database connection: {e}")
    
    # Calculate statistics
    matched_count = len([m for m in current_items if m.get('product_id')])
    needs_review_count = len([m for m in current_items if m.get('needs_review', False)])
    
    results = {
        'receipts': combined_receipts,
        'mapped_items': current_items,
        'total_receipts': len(combined_receipts),
        'total_items': len(all_items),
        'matched_items': matched_count,
        'needs_review': needs_review_count
    }
    
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"Step 3 Complete: Processed {len(combined_receipts)} receipts, {len(all_items)} items")
    logger.info(f"  - Matched: {matched_count} items")
    logger.info(f"  - Needs Review: {needs_review_count} items")
    logger.info("=" * 80)
    
    return results


def main() -> None:
    """Main entry point for step3_mapping"""
    import argparse
    from pathlib import Path
    
    # Setup basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(
        description='Step 3: Map receipt items to database products using rules',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        'input_dir',
        type=str,
        help='Step 1 output directory (or contains reviewed_extracted_data.json from Step 2)'
    )
    parser.add_argument(
        'output_dir',
        type=str,
        nargs='?',
        default='data/step3_output',
        help='Step 3 output directory (default: data/step3_output)'
    )
    parser.add_argument(
        '--rules-dir',
        type=str,
        default=None,
        help='Directory containing rule YAML files (default: step3_rules in parent directory)'
    )
    parser.add_argument(
        '--no-reviewed',
        action='store_true',
        help='Skip reviewed data from Step 2, use original Step 1 output only'
    )
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    rules_dir = Path(args.rules_dir) if args.rules_dir else Path(__file__).parent.parent / 'step3_rules'
    
    logger.info(f"Input directory (Step 1 output): {input_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Rules directory: {rules_dir}")
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        logger.error("Run Step 1 first to generate input data.")
        return
    
    if not rules_dir.exists():
        logger.error(f"Rules directory not found: {rules_dir}")
        return
    
    process_rules(input_dir, output_dir, rules_dir, use_reviewed=not args.no_reviewed)


if __name__ == "__main__":
    main()

