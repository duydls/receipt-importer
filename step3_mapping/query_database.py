#!/usr/bin/env python3
"""
Query Odoo database to get product information and fix mappings
Uses database connection to get accurate product default UoMs and categories
"""

import json
import os
import getpass
from pathlib import Path
from typing import Dict, Optional

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("Warning: psycopg2 not available. Install with: pip install psycopg2-binary")


def get_db_password() -> str:
    """Get database password securely"""
    # Try environment variable first
    password = os.environ.get('ODOO_DB_PASSWORD')
    if password:
        return password
    
    # Try .env file
    env_file = Path('.env')
    if env_file.exists():
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('ODOO_DB_PASSWORD=') and not line.startswith('#'):
                        password = line.split('=', 1)[1].strip()
                        if password and password != 'your_password_here':
                            return password
        except Exception:
            pass
    
    # Otherwise prompt securely
    return getpass.getpass("Enter Odoo database password: ")


def connect_to_database() -> Optional[object]:
    """
    Connect to Odoo database using READ-ONLY user.
    
    Uses readonly user 'odooreader' by default to ensure read-only access.
    Connection details can be overridden via environment variables or .env file.
    """
    if not PSYCOPG2_AVAILABLE:
        print("ERROR: psycopg2 not available. Please install: pip install psycopg2-binary")
        return None
    
    try:
        # Get connection details from environment or .env file
        # Default to readonly user 'odooreader' for safety
        host = os.environ.get('ODOO_DB_HOST', 'uniuniuptown.shop')
        user = os.environ.get('ODOO_DB_USER', 'odooreader')  # READ-ONLY user by default
        database = os.environ.get('ODOO_DB_NAME', 'odoo')
        port = int(os.environ.get('ODOO_DB_PORT', '5432'))
        
        # Load from .env if not in environment
        env_file = Path('.env')
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('#') or not line:
                            continue
                        if '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            if key == 'ODOO_DB_HOST' and not os.environ.get('ODOO_DB_HOST'):
                                host = value
                            elif key == 'ODOO_DB_USER' and not os.environ.get('ODOO_DB_USER'):
                                user = value
                            elif key == 'ODOO_DB_NAME' and not os.environ.get('ODOO_DB_NAME'):
                                database = value
                            elif key == 'ODOO_DB_PORT' and not os.environ.get('ODOO_DB_PORT'):
                                port = int(value) if value.isdigit() else 5432
            except Exception:
                pass
        
        password = get_db_password()
        
        # Log connection details (without password)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Connecting to database as readonly user: {user}@{host}:{port}/{database}")
        
        conn = psycopg2.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port
        )
        
        # Verify we're using readonly user (log warning if not)
        if user != 'odooreader' and 'read' not in user.lower() and 'readonly' not in user.lower():
            logger.warning(f"Using non-readonly user '{user}'. Consider using 'odooreader' for safety.")
        else:
            logger.info(f"✓ Connected to database as readonly user: {user}")
        
        return conn
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        return None


def get_product_default_uoms(conn) -> Dict[int, Dict]:
    """Get all products with their default UoMs and categories"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Query product.product table for product ID, name, and default UoM
        query = """
        SELECT 
            pp.id as product_id,
            pt.name->>'en_US' as product_name,
            pt.uom_id as default_uom_id,
            uom.name as default_uom_name,
            uom.category_id as uom_category_id,
            uom_cat.name as uom_category_name
        FROM product_product pp
        JOIN product_template pt ON pp.product_tmpl_id = pt.id
        JOIN uom_uom uom ON pt.uom_id = uom.id
        JOIN uom_category uom_cat ON uom.category_id = uom_cat.id
        WHERE pt.active = true
        ORDER BY pp.id
        """
        
        cur.execute(query)
        products = {}
        
        for row in cur.fetchall():
            product_id = row['product_id']
            products[product_id] = {
                'name': row['product_name'] or '',
                'default_uom_id': row['default_uom_id'],
                'default_uom_name': row['default_uom_name'] or '',
                'uom_category_id': row['uom_category_id'],
                'uom_category_name': row['uom_category_name'] or ''
            }
        
        return products


def get_uom_categories(conn) -> Dict[int, Dict]:
    """Get all UoMs with their categories, keyed by UoM ID"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = """
        SELECT 
            uom.id as uom_id,
            uom.name as uom_name,
            uom.category_id,
            uom_cat.name as category_name
        FROM uom_uom uom
        JOIN uom_category uom_cat ON uom.category_id = uom_cat.id
        WHERE uom.active = true
        ORDER BY uom.id
        """
        
        cur.execute(query)
        uoms = {}  # Keyed by uom_id
        
        for row in cur.fetchall():
            uom_id = row['uom_id']
            uoms[uom_id] = {
                    'category_id': row['category_id'],
                    'category_name': row['category_name'] or ''
                }
        
        return uoms


def main():
    """Main function"""
    print("Connecting to Odoo database...")
    print("="*80)
    
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to database")
        return
    
    print("✓ Connected to database")
    print()
    
    # Get product information
    print("Querying product default UoMs...")
    products = get_product_default_uoms(conn)
    print(f"✓ Found {len(products)} products")
    print()
    
    # Get UoM information
    print("Querying UoM categories...")
    uoms = get_uom_categories(conn)
    print(f"✓ Found {len(uoms)} UoMs")
    print()
    
    # Save to file for reference
    output_file = Path('database_products_uoms.json')
    with open(output_file, 'w') as f:
        json.dump({
            'products': products,
            'uoms': uoms
        }, f, indent=2)
    
    print(f"✓ Saved database data to: {output_file}")
    print()
    
    conn.close()
    print("✓ Database connection closed")
    print()
    
    return products, uoms


if __name__ == '__main__':
    main()

