#!/usr/bin/env python3
"""
Examine PDF Test Files
Analyzes PDF files in pdf_test folder to discover patterns and structure.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
import re

logger = logging.getLogger(__name__)

# Try to import pdfplumber
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available. Install with: pip install pdfplumber")

# Try to import PyMuPDF
try:
    import fitz  # PyMuPDF
    MUPDF_AVAILABLE = True
except ImportError:
    MUPDF_AVAILABLE = False
    logger.warning("PyMuPDF not available. Install with: pip install pymupdf")


def examine_pdf_structure(file_path: Path) -> Dict[str, Any]:
    """
    Examine PDF structure and extract patterns
    
    Returns:
        Dictionary with PDF structure information
    """
    result = {
        'filename': file_path.name,
        'vendor': _detect_vendor_from_filename(file_path.name),
        'text_extracted': False,
        'tables_found': 0,
        'sample_text': '',
        'sample_table': None,
        'page_count': 0,
        'has_tables': False,
        'structure_type': 'unknown',  # 'tabular', 'text', 'image'
    }
    
    if not PDFPLUMBER_AVAILABLE:
        logger.warning(f"Cannot examine {file_path.name}: pdfplumber not available")
        return result
    
    try:
        with pdfplumber.open(file_path) as pdf:
            result['page_count'] = len(pdf.pages)
            
            # Extract text from first page
            if pdf.pages:
                first_page = pdf.pages[0]
                text = first_page.extract_text()
                if text:
                    result['text_extracted'] = True
                    result['sample_text'] = text[:2000]  # First 2000 chars
                    result['structure_type'] = 'text'
                
                # Try to extract tables
                tables = first_page.extract_tables()
                if tables:
                    result['tables_found'] = len(tables)
                    result['has_tables'] = True
                    result['structure_type'] = 'tabular'
                    
                    # Get first table as sample
                    if tables[0]:
                        result['sample_table'] = {
                            'rows': len(tables[0]),
                            'columns': len(tables[0][0]) if tables[0] else 0,
                            'header': tables[0][0] if tables[0] else None,
                            'sample_rows': tables[0][:5] if len(tables[0]) > 1 else None
                        }
                
                # Try with different table settings if no tables found
                if not tables:
                    tables = first_page.extract_tables(table_settings={
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "snap_tolerance": 3,
                        "join_tolerance": 3,
                    })
                    if tables:
                        result['tables_found'] = len(tables)
                        result['has_tables'] = True
                        result['structure_type'] = 'tabular'
                        
                        if tables[0]:
                            result['sample_table'] = {
                                'rows': len(tables[0]),
                                'columns': len(tables[0][0]) if tables[0] else 0,
                                'header': tables[0][0] if tables[0] else None,
                                'sample_rows': tables[0][:5] if len(tables[0]) > 1 else None
                            }
                
                # Check if image-based (no text, no tables)
                if not text and not tables:
                    result['structure_type'] = 'image'
                    logger.info(f"{file_path.name} appears to be image-based (no text, no tables)")
    
    except Exception as e:
        logger.error(f"Error examining {file_path.name}: {e}", exc_info=True)
    
    return result


def _detect_vendor_from_filename(filename: str) -> str:
    """Detect vendor from filename"""
    filename_lower = filename.lower()
    
    if 'costco' in filename_lower:
        return 'COSTCO'
    elif 'jewel' in filename_lower or 'osco' in filename_lower:
        return 'JEWEL'
    elif 'aldi' in filename_lower:
        return 'ALDI'
    elif 'parktoshop' in filename_lower or 'park' in filename_lower:
        return 'PARKTOSHOP'
    elif 'mariano' in filename_lower:
        return 'MARIANOS'
    else:
        return 'UNKNOWN'


def analyze_pdf_patterns(file_path: Path) -> Dict[str, Any]:
    """
    Analyze PDF patterns for processing
    
    Returns:
        Dictionary with analysis results
    """
    result = examine_pdf_structure(file_path)
    
    # Additional pattern analysis
    if result.get('sample_text'):
        text = result['sample_text']
        
        # Look for common receipt patterns
        patterns = {
            'has_item_description': bool(re.search(r'(?i)(item|description|product)', text)),
            'has_quantity': bool(re.search(r'(?i)(qty|quantity|qty\.)', text)),
            'has_unit_price': bool(re.search(r'(?i)(unit\s*price|price|unit)', text)),
            'has_total': bool(re.search(r'(?i)(total|amount|subtotal)', text)),
            'has_tax': bool(re.search(r'(?i)(tax|taxes)', text)),
            'has_date': bool(re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', text)),
            'has_receipt_number': bool(re.search(r'(?i)(receipt|invoice|order)\s*#?\s*\d+', text)),
        }
        result['patterns'] = patterns
    
    # Analyze table structure if available
    if result.get('sample_table'):
        table = result['sample_table']
        if table.get('header'):
            header = table['header']
            result['table_analysis'] = {
                'header_columns': header,
                'column_count': len(header),
                'has_product_name': any(re.search(r'(?i)(item|description|product)', str(col)) for col in header if col),
                'has_quantity': any(re.search(r'(?i)(qty|quantity)', str(col)) for col in header if col),
                'has_price': any(re.search(r'(?i)(price|amount|total)', str(col)) for col in header if col),
            }
    
    return result


def main():
    """Main function to examine all PDFs in pdf_test folder"""
    input_dir = Path('data/step1_input/pdf_test')
    
    if not input_dir.exists():
        logger.error(f"PDF test folder not found: {input_dir}")
        return
    
    pdf_files = list(input_dir.glob('*.pdf'))
    
    if not pdf_files:
        logger.warning(f"No PDF files found in {input_dir}")
        return
    
    logger.info(f"Found {len(pdf_files)} PDF files to examine")
    
    results = []
    for pdf_file in sorted(pdf_files):
        logger.info(f"\n{'='*80}")
        logger.info(f"Examining: {pdf_file.name}")
        logger.info(f"{'='*80}")
        
        analysis = analyze_pdf_patterns(pdf_file)
        results.append(analysis)
        
        # Print summary
        print(f"\nVendor: {analysis.get('vendor', 'UNKNOWN')}")
        print(f"Structure Type: {analysis.get('structure_type', 'unknown')}")
        print(f"Pages: {analysis.get('page_count', 0)}")
        print(f"Text Extracted: {analysis.get('text_extracted', False)}")
        print(f"Tables Found: {analysis.get('tables_found', 0)}")
        
        if analysis.get('sample_table'):
            table = analysis['sample_table']
            print(f"\nTable Structure:")
            print(f"  Rows: {table.get('rows', 0)}")
            print(f"  Columns: {table.get('columns', 0)}")
            if table.get('header'):
                print(f"  Header: {table['header']}")
        
        if analysis.get('patterns'):
            patterns = analysis['patterns']
            print(f"\nPatterns Found:")
            for key, value in patterns.items():
                if value:
                    print(f"  ✓ {key.replace('has_', '').replace('_', ' ').title()}")
        
        if analysis.get('sample_text'):
            print(f"\nSample Text (first 500 chars):")
            print(f"{analysis['sample_text'][:500]}...")
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"\nTotal PDFs: {len(results)}")
    print(f"Tabular: {sum(1 for r in results if r.get('structure_type') == 'tabular')}")
    print(f"Text-based: {sum(1 for r in results if r.get('structure_type') == 'text')}")
    print(f"Image-based: {sum(1 for r in results if r.get('structure_type') == 'image')}")
    
    # Group by vendor
    vendors = {}
    for result in results:
        vendor = result.get('vendor', 'UNKNOWN')
        if vendor not in vendors:
            vendors[vendor] = []
        vendors[vendor].append(result)
    
    print(f"\nBy Vendor:")
    for vendor, vendor_results in vendors.items():
        print(f"  {vendor}: {len(vendor_results)} files")
        for result in vendor_results:
            print(f"    - {result['filename']}: {result.get('structure_type', 'unknown')}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    main()

