#!/usr/bin/env python3
"""
Rebuild Knowledge Base from Extracted Receipt Data

This script rebuilds the knowledge base from extracted receipt data.
It processes receipts from different vendors and adds products to the knowledge base.

Usage:
    python scripts/rebuild_knowledge_base.py
    python scripts/rebuild_knowledge_base.py --wismettac-only
    python scripts/rebuild_knowledge_base.py --rd-only
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

KB_PATH = Path('data/step1_input/knowledge_base.json')


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return {}


def save_json(path: Path, data: Dict[str, Any]) -> None:
    """Save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def rebuild_from_wismettac() -> int:
    """Rebuild knowledge base from Wismettac receipts."""
    print("\n" + "=" * 80)
    print("REBUILDING FROM WISMETTAC RECEIPTS")
    print("=" * 80)
    
    wismettac_data_path = Path('data/step1_output/wismettac_based/extracted_data.json')
    if not wismettac_data_path.exists():
        print(f"⚠ Wismettac data not found: {wismettac_data_path}")
        print("   Run step 1 first to extract Wismettac receipts")
        return 0
    
    # Import and run the Wismettac KB builder
    try:
        import sys
        scripts_dir = Path(__file__).parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        
        # Import the module directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("add_wismettac_to_kb", scripts_dir / "add_wismettac_to_kb.py")
        add_wismettac_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(add_wismettac_module)
        
        stats = add_wismettac_module.process_wismettac_receipts(wismettac_data_path, KB_PATH)
        print(f"\n✓ Wismettac: Added {stats['added']}, Updated {stats['updated']}, Skipped {stats['skipped']}, Errors {stats['errors']}")
        return stats['added'] + stats['updated']
    except Exception as e:
        print(f"✗ Error processing Wismettac receipts: {e}")
        import traceback
        traceback.print_exc()
        return 0


def rebuild_from_rd() -> int:
    """Rebuild knowledge base from RD receipts."""
    print("\n" + "=" * 80)
    print("REBUILDING FROM RD RECEIPTS")
    print("=" * 80)
    
    rd_data_path = Path('data/step1_output/localgrocery_based/extracted_data.json')
    if not rd_data_path.exists():
        print(f"⚠ RD data not found: {rd_data_path}")
        print("   Run step 1 first to extract RD receipts")
        return 0
    
    # Import and run the RD KB builder
    try:
        import sys
        scripts_dir = Path(__file__).parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        
        # Import the module directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("kb_merge_rd", scripts_dir / "kb_merge_rd.py")
        kb_merge_rd_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kb_merge_rd_module)
        
        kb_merge_rd_module.main()
        print(f"\n✓ RD: Merged items from {rd_data_path}")
        return 1  # Count as 1 operation
    except Exception as e:
        print(f"✗ Error processing RD receipts: {e}")
        import traceback
        traceback.print_exc()
        return 0


def rebuild_from_wismettac_enrichment() -> int:
    """Rebuild knowledge base from Wismettac enrichment data."""
    print("\n" + "=" * 80)
    print("REBUILDING FROM WISMETTAC ENRICHMENT DATA")
    print("=" * 80)
    
    enrichment_path = Path('data/step1_output/wismettac_based/wismettac_enrichment.json')
    if not enrichment_path.exists():
        print(f"⚠ Wismettac enrichment data not found: {enrichment_path}")
        return 0
    
    # Import and run the Wismettac enrichment merger
    try:
        import sys
        scripts_dir = Path(__file__).parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        
        # Import the module directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("kb_merge_wismettac", scripts_dir / "kb_merge_wismettac.py")
        kb_merge_wismettac_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kb_merge_wismettac_module)
        
        kb_merge_wismettac_module.main()
        print(f"\n✓ Wismettac enrichment: Merged items from {enrichment_path}")
        return 1  # Count as 1 operation
    except Exception as e:
        print(f"✗ Error processing Wismettac enrichment: {e}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Rebuild knowledge base from extracted receipt data'
    )
    parser.add_argument(
        '--wismettac-only',
        action='store_true',
        help='Only rebuild from Wismettac receipts'
    )
    parser.add_argument(
        '--rd-only',
        action='store_true',
        help='Only rebuild from RD receipts'
    )
    parser.add_argument(
        '--enrichment-only',
        action='store_true',
        help='Only rebuild from Wismettac enrichment data'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("REBUILDING KNOWLEDGE BASE")
    print("=" * 80)
    print(f"Knowledge Base: {KB_PATH}")
    print("=" * 80)
    
    # Initialize empty KB if it doesn't exist
    if not KB_PATH.exists():
        save_json(KB_PATH, {})
        print(f"✓ Created empty knowledge base: {KB_PATH}")
    
    total_added = 0
    
    if args.wismettac_only:
        total_added += rebuild_from_wismettac()
    elif args.rd_only:
        total_added += rebuild_from_rd()
    elif args.enrichment_only:
        total_added += rebuild_from_wismettac_enrichment()
    else:
        # Rebuild from all sources
        total_added += rebuild_from_wismettac()
        total_added += rebuild_from_wismettac_enrichment()
        total_added += rebuild_from_rd()
    
    # Load final KB to show stats
    kb = load_json(KB_PATH)
    kb_count = len(kb)
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Knowledge base now contains {kb_count} items")
    print(f"Operations completed: {total_added}")
    print("=" * 80)
    
    if kb_count == 0:
        print("\n⚠ Knowledge base is empty!")
        print("   To rebuild:")
        print("   1. Run step 1 to extract receipts: python workflow.py --step 1")
        print("   2. Run this script again: python scripts/rebuild_knowledge_base.py")
        print("\n   Or for Wismettac specifically:")
        print("   python scripts/add_wismettac_to_kb.py")


if __name__ == '__main__':
    main()

