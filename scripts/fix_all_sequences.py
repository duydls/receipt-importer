#!/usr/bin/env python3
"""
Find and fix all PostgreSQL sequences that are out of sync with their tables
This prevents duplicate key errors when creating records through Odoo web interface
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def find_all_sequences(conn):
    """Find all sequences and their associated tables"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Find all sequences
        cur.execute("""
            SELECT 
                schemaname,
                sequencename,
                last_value
            FROM pg_sequences
            WHERE schemaname = 'public'
            ORDER BY sequencename
        """)
        sequences = cur.fetchall()
        
        # For each sequence, try to find the corresponding table
        sequence_info = []
        for seq in sequences:
            seq_name = seq['sequencename']
            # Try to extract table name from sequence name (usually table_name_id_seq)
            if seq_name.endswith('_id_seq'):
                table_name = seq_name[:-7]  # Remove '_id_seq'
                
                # Check if table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = %s
                    ) as exists
                """, (table_name,))
                table_exists = cur.fetchone()['exists']
                
                if table_exists:
                    # Get max ID from table
                    try:
                        cur.execute(f"SELECT MAX(id) as max_id FROM {table_name}")
                        max_id_result = cur.fetchone()
                        max_id = max_id_result['max_id'] if max_id_result else None
                    except Exception:
                        max_id = None
                    
                    sequence_info.append({
                        'sequence': seq_name,
                        'table': table_name,
                        'last_value': seq['last_value'],
                        'max_id': max_id
                    })
        
        return sequence_info


def fix_sequence(conn, sequence_name, new_value):
    """Fix a sequence by setting it to a new value"""
    with conn.cursor() as cur:
        cur.execute(f"SELECT setval(%s, %s, true)", (sequence_name, new_value))
        return cur.fetchone()[0]


def main():
    """Main function"""
    print("Connecting to database...")
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to database")
        return
    
    print("Finding all sequences...")
    sequences = find_all_sequences(conn)
    print(f"  Found {len(sequences)} sequences with corresponding tables\n")
    
    # Find sequences that need fixing
    out_of_sync = []
    for seq_info in sequences:
        if seq_info['max_id'] is not None:
            max_id = seq_info['max_id']
            last_value = seq_info['last_value']
            
            # Sequence is out of sync if last_value < max_id
            if last_value < max_id:
                out_of_sync.append({
                    'sequence': seq_info['sequence'],
                    'table': seq_info['table'],
                    'current_seq': last_value,
                    'max_id': max_id,
                    'gap': max_id - last_value
                })
    
    if not out_of_sync:
        print("✓ All sequences are in sync!")
        conn.close()
        return
    
    print(f"Found {len(out_of_sync)} sequences that need fixing:\n")
    print(f"{'Sequence':<40} {'Table':<30} {'Current':<10} {'Max ID':<10} {'Gap':<10}")
    print("-" * 100)
    
    for item in sorted(out_of_sync, key=lambda x: x['gap'], reverse=True):
        print(f"{item['sequence']:<40} {item['table']:<30} {item['current_seq']:<10} {item['max_id']:<10} {item['gap']:<10}")
    
    # Generate SQL file
    output_file = Path(__file__).parent.parent / 'fix_all_sequences.sql'
    print(f"\nGenerating SQL file: {output_file}")
    
    sql_commands = []
    sql_commands.append("-- Fix all sequences that are out of sync with their tables")
    sql_commands.append("-- Generated automatically to prevent duplicate key errors\n")
    sql_commands.append("BEGIN;\n")
    
    for item in sorted(out_of_sync, key=lambda x: x['sequence']):
        new_value = item['max_id'] + 100  # Add 100 as safety buffer
        sql_commands.append(f"-- Fix {item['sequence']} (table: {item['table']})")
        sql_commands.append(f"-- Current: {item['current_seq']}, Max ID: {item['max_id']}, Gap: {item['gap']}")
        sql_commands.append(f"SELECT setval('{item['sequence']}', {new_value}, true);\n")
    
    sql_commands.append("COMMIT;\n")
    sql_commands.append("\n-- Verify fixes (run separately)")
    for item in sorted(out_of_sync, key=lambda x: x['sequence']):
        sql_commands.append(f"-- {item['sequence']}: sequence should be > {item['max_id']}")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sql_commands))
    
    print(f"✓ Generated SQL file: {output_file}")
    print(f"\nTo fix all sequences, run:")
    print(f"  psql -h uniuniuptown.shop -U your_write_user -d odoo -f {output_file}")
    
    # Optionally, fix them directly
    print("\n" + "="*80)
    try:
        response = input("Do you want to fix them now? (yes/no): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        response = 'no'
        print("\n")
    
    if response == 'yes':
        print("\nFixing sequences...")
        try:
            for item in out_of_sync:
                new_value = item['max_id'] + 100
                old_value = fix_sequence(conn, item['sequence'], new_value)
                print(f"  ✓ Fixed {item['sequence']}: {old_value} → {new_value}")
            conn.commit()
            print("\n✓ All sequences fixed successfully!")
        except Exception as e:
            conn.rollback()
            print(f"\n✗ Error fixing sequences: {e}")
            print("You can still run the SQL file manually.")
    else:
        print("\nYou can run the SQL file later to fix the sequences.")
    
    conn.close()


if __name__ == '__main__':
    main()

