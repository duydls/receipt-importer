#!/usr/bin/env python3
"""
Script to fix duplicate and incorrect PO IDs in SQL files.
"""
import re
from pathlib import Path
from typing import Dict, List, Tuple

def get_current_ids(sql_dir: Path) -> Dict[int, List[str]]:
    """Get all current PO IDs and their files."""
    id_to_files = {}
    
    for sql_file in sql_dir.glob('purchase_order_*.sql'):
        if '_rollback' not in sql_file.name:
            try:
                with open(sql_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Find PO ID
                    po_match = re.search(
                        r"INSERT INTO purchase_order[^;]*?SELECT\s+(\d+),\s*\n\s*id,\s*-- partner_id[^;]*?;",
                        content,
                        re.MULTILINE | re.DOTALL
                    )
                    if po_match:
                        po_id = int(po_match.group(1))
                        if po_id not in id_to_files:
                            id_to_files[po_id] = []
                        id_to_files[po_id].append(sql_file.name)
            except Exception as e:
                print(f"Error reading {sql_file.name}: {e}")
    
    return id_to_files

def fix_po_id_in_file(sql_file: Path, old_id: int, new_id: int) -> bool:
    """Replace PO ID in a SQL file and update all references."""
    try:
        with open(sql_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace PO ID in purchase_order INSERT
        # More precise replacement - preserve the column list and only replace the ID
        pattern = rf"(INSERT INTO purchase_order[^;]*?SELECT\s+){old_id}(,\s*\n\s*id,\s*-- partner_id)"
        replacement = rf"\g<1>{new_id}\g<2>"
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE | re.DOTALL)
        
        # Replace order_id references in purchase_order_line (old_id -> new_id)
        # Pattern: order_id field in purchase_order_line INSERT
        content = re.sub(
            rf"(\s+){old_id}(\s+-- order_id)",
            rf"\g<1>{new_id}\g<2>",
            content
        )
        
        # Replace line IDs that are based on PO ID
        # Line IDs are typically: po_id * 1000 + sequence (1, 2, 3, ...)
        # So old_line_id = old_id * 1000 + seq, new_line_id = new_id * 1000 + seq
        def replace_line_id_in_content(text, old_po_id, new_po_id):
            """Replace line IDs in text based on PO ID change"""
            # Find all line IDs that start with old_po_id
            # Pattern: number starting with old_po_id followed by 3+ digits
            def replace_line_id(match):
                old_line_id_str = match.group(1)
                old_line_id = int(old_line_id_str)
                # Check if this is a line ID (starts with old_po_id and has 3+ more digits)
                if old_line_id >= old_po_id * 1000 and old_line_id < (old_po_id + 1) * 1000:
                    sequence = old_line_id % 1000
                    new_line_id = new_po_id * 1000 + sequence
                    return f"{new_line_id}{match.group(2)}"
                return match.group(0)  # No change
            
            # Match line IDs in INSERT statements: SELECT\n    (old_id\d{3,}),  -- id
            text = re.sub(
                rf"SELECT\s+({old_po_id}\d{{3,}}),\s*-- id",
                replace_line_id,
                text,
                flags=re.MULTILINE
            )
            
            # Also replace standalone line IDs (for rollback files)
            def replace_standalone_line_id(match):
                old_line_id_str = match.group(1)
                old_line_id = int(old_line_id_str)
                if old_line_id >= old_po_id * 1000 and old_line_id < (old_po_id + 1) * 1000:
                    sequence = old_line_id % 1000
                    new_line_id = new_po_id * 1000 + sequence
                    return str(new_line_id)
                return match.group(0)
            
            # Replace in DELETE statements: WHERE id IN (old_id\d{3,}, ...)
            text = re.sub(
                rf"({old_po_id}\d{{3,}})",
                replace_standalone_line_id,
                text
            )
            
            return text
        
        content = replace_line_id_in_content(content, old_id, new_id)
        
        # Write back
        with open(sql_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return True
    except Exception as e:
        print(f"Error fixing {sql_file.name}: {e}")
        return False

def main():
    import sys
    from pathlib import Path as PathLib
    sys.path.insert(0, str(PathLib(__file__).parent.parent))
    
    sql_dir = Path('data/sql')
    
    # Get current IDs
    id_to_files = get_current_ids(sql_dir)
    
    print("Current ID assignments:")
    for po_id, files in sorted(id_to_files.items()):
        print(f"  ID {po_id}: {len(files)} file(s)")
        for f in files:
            print(f"    - {f}")
    
    # Find duplicates and incorrect IDs
    duplicates = {k: v for k, v in id_to_files.items() if len(v) > 1}
    incorrect_ids = {k: v for k, v in id_to_files.items() if k >= 1000}
    
    print(f"\nFound {len(duplicates)} duplicate ID(s) and {len(incorrect_ids)} incorrect ID(s)")
    
    # Get next available ID
    
    from step3_mapping.query_database import connect_to_database
    from scripts.generate_purchase_order_sql import get_next_id
    
    conn = connect_to_database()
    if conn:
        next_id = get_next_id(conn, 'purchase_order', check_sql_files=True)
        conn.close()
    else:
        next_id = 68
    
    print(f"\nStarting from ID: {next_id}\n")
    
    # Fix incorrect IDs first
    for old_id, files in sorted(incorrect_ids.items()):
        for filename in files:
            sql_file = sql_dir / filename
            rollback_file = sql_dir / filename.replace('.sql', '_rollback.sql')
            
            print(f"Fixing {filename}: {old_id} -> {next_id}")
            if fix_po_id_in_file(sql_file, old_id, next_id):
                print(f"  ✅ Fixed {filename}")
            
            # Fix rollback file if exists
            if rollback_file.exists():
                print(f"  Fixing rollback file: {rollback_file.name}")
                if fix_po_id_in_file(rollback_file, old_id, next_id):
                    print(f"  ✅ Fixed {rollback_file.name}")
            
            next_id += 1
    
    # Fix duplicates - keep first file, reassign others
    for old_id, files in sorted(duplicates.items()):
        # Keep first file with current ID, reassign others
        keep_file = files[0]
        reassign_files = files[1:]
        
        print(f"\nFixing duplicates for ID {old_id}:")
        print(f"  Keeping: {keep_file}")
        
        for filename in reassign_files:
            sql_file = sql_dir / filename
            rollback_file = sql_dir / filename.replace('.sql', '_rollback.sql')
            
            print(f"  Reassigning {filename}: {old_id} -> {next_id}")
            if fix_po_id_in_file(sql_file, old_id, next_id):
                print(f"    ✅ Fixed {filename}")
            
            # Fix rollback file if exists
            if rollback_file.exists():
                print(f"    Fixing rollback file: {rollback_file.name}")
                if fix_po_id_in_file(rollback_file, old_id, next_id):
                    print(f"    ✅ Fixed {rollback_file.name}")
            
            next_id += 1
    
    print(f"\n✅ All IDs fixed! Next available ID: {next_id}")

if __name__ == '__main__':
    main()

