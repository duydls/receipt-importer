#!/usr/bin/env python3
"""
Chrome Cookie Extractor
Extracts cookies from Chrome's cookie database for use with web scraping.

Usage:
    python scripts/chrome_cookies.py --domain instacart.com
    python scripts/chrome_cookies.py --domain instacart.com --format header
"""

import sqlite3
import argparse
import os
from pathlib import Path
from typing import List, Dict, Optional


def get_chrome_cookie_db() -> Optional[Path]:
    """Find Chrome cookie database on macOS."""
    # Chrome cookie database location on macOS
    chrome_paths = [
        Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies",
        Path.home() / "Library/Application Support/Google/Chrome/Profile 1/Cookies",
    ]
    
    for path in chrome_paths:
        if path.exists():
            return path
    
    return None


def extract_chrome_cookies(domain: str, cookie_db: Optional[Path] = None) -> List[Dict[str, str]]:
    """
    Extract cookies from Chrome's cookie database.
    
    Args:
        domain: Domain to extract cookies for (e.g., "instacart.com")
        cookie_db: Path to Chrome cookie database (auto-detected if None)
        
    Returns:
        List of cookie dictionaries with name, value, domain, path
    """
    if cookie_db is None:
        cookie_db = get_chrome_cookie_db()
    
    if not cookie_db or not cookie_db.exists():
        raise FileNotFoundError(f"Chrome cookie database not found. Expected at: {cookie_db}")
    
    # Chrome encrypts cookies, but we can try to read them
    # Note: On macOS, Chrome uses the Keychain to encrypt cookies
    # This is a simplified version that may not work for encrypted cookies
    
    cookies = []
    try:
        # Copy the database to a temp location (Chrome locks the original)
        import tempfile
        import shutil
        
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_db.close()
        
        shutil.copy2(cookie_db, temp_db.name)
        
        conn = sqlite3.connect(temp_db.name)
        cursor = conn.cursor()
        
        # Query cookies for the domain
        query = """
            SELECT name, value, host_key, path, expires_utc, is_secure, is_httponly
            FROM cookies
            WHERE host_key LIKE ? OR host_key LIKE ?
        """
        cursor.execute(query, (f'%{domain}%', f'%.{domain}%'))
        
        for row in cursor.fetchall():
            name, value, host_key, path, expires_utc, is_secure, is_httponly = row
            cookies.append({
                'name': name,
                'value': value,
                'domain': host_key,
                'path': path or '/',
            })
        
        conn.close()
        os.unlink(temp_db.name)
        
    except Exception as e:
        print(f"Warning: Could not read Chrome cookies (may be encrypted): {e}")
        print("Try using Chrome's cookie export extension or manual copy from browser")
    
    return cookies


def format_cookie_string(cookies: List[Dict[str, str]]) -> str:
    """Format cookies as a cookie header string."""
    return "; ".join([f"{c['name']}={c['value']}" for c in cookies])


def main():
    parser = argparse.ArgumentParser(description="Extract cookies from Chrome")
    parser.add_argument("--domain", required=True, help="Domain to extract cookies for (e.g., instacart.com)")
    parser.add_argument("--format", choices=["header", "json"], default="header", help="Output format")
    parser.add_argument("--db", help="Path to Chrome cookie database (auto-detected if not provided)")
    
    args = parser.parse_args()
    
    cookie_db = Path(args.db) if args.db else None
    
    try:
        cookies = extract_chrome_cookies(args.domain, cookie_db)
        
        if not cookies:
            print(f"No cookies found for domain: {args.domain}")
            return 1
        
        if args.format == "header":
            cookie_string = format_cookie_string(cookies)
            print(cookie_string)
        else:
            import json
            print(json.dumps(cookies, indent=2))
        
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())

