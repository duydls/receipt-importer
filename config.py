#!/usr/bin/env python3
"""
Configuration file for Receipt Importer Project
Edit these values according to your Odoo setup
"""

# Database Connection (for direct SQL queries)
# Used for read-only database queries (e.g., query_database.py)
#
# Password Reading Priority (implemented in query_database.py):
# 1. Environment variable: ODOO_DB_PASSWORD (highest priority)
#    Example: export ODOO_DB_PASSWORD="your_password"
# 2. .env file in project root: ODOO_DB_PASSWORD=your_password
#    The .env file is gitignored and not committed to version control
# 3. Interactive prompt (fallback if neither above is set)
#
DB_CONFIG = {
    'host': 'uniuniuptown.shop',
    'port': 5432,
    'database': 'odoo',
    'user': 'odoreader',
    'password': '',  # Read via ODOO_DB_PASSWORD env var or .env file (see query_database.py)
}

# Workflow Folder Structure
# Step 1: Extract data from receipts (Rule-Driven Architecture)
# Uses rule files from step1_rules/ directory:
# - 10_vendor_detection.yaml: Vendor detection rules
# - 20_*.yaml: Vendor-specific layout rules (Costco, RD, Jewel, etc.)
# - 30_uom_extraction.yaml: UoM extraction rules
# See step1_rules/README.md for detailed rule documentation
STEP1_INPUT_DIR = '../odoo_data/receipts'        # Input: Receipts folder (PDF/CSV files)
STEP1_OUTPUT_DIR = 'data/step1_output'            # Output: Extracted receipt data (Step 2 input)
STEP1_RULES_DIR = 'step1_rules'                   # Rule files directory (vendor detection, layouts, UoM extraction)

# Step 2: Generate mapping file
STEP2_INPUT_DIR = 'data/step1_output'             # Input: Extracted data from Step 1
STEP2_OUTPUT_DIR = 'data/step2_output'            # Output: Mapped receipt data (Step 3 input)

# Step 3: Generate SQL files
STEP3_INPUT_DIR = 'data/step2_output'             # Input: Mapped data from Step 2
STEP3_OUTPUT_DIR = '../odoo_data/analysis/receipt_sql'  # Output: SQL files

# Database Dump File Path
# Path to the analyzed database dump (used for product/UoM matching)
DB_DUMP_JSON = '../odoo_data/analysis/products_uom_analysis.json'

# Mapping Files (Step 2 output location)
# Step 2 will generate/save mappings to its output directory:
# - data/step2_output/product_name_mapping.json
# - data/step2_output/fruit_weight_conversion.json
# These mappings are then used as input by Step 3
PRODUCT_MAPPING_FILE = 'data/step2_output/product_name_mapping.json'
FRUIT_CONVERSION_FILE = 'data/step2_output/fruit_weight_conversion.json'

# Vendor/Partner Settings
# Note: All Instacart vendors are prefixed with "IC-" in the system
DEFAULT_VENDOR = {
    'name': 'IC-Instacart',           # Default vendor name (with IC- prefix)
    'search_names': ['IC-Instacart', 'IC-Jewel-Osco', 'IC-Jewel Osco', 'IC-Jewel', 'Instacart', 'Jewel-Osco'],
    'supplier_rank': 1,
}

# Fee Products (separate products in system for fees/charges)
FEE_PRODUCTS = {
    'bag_fee': {
        'search_names': ['Bag Fee', 'Checkout Bag Fee', 'Bag', 'Bags'],
        'default_uom': 'Units',
    },
    'tip': {
        'search_names': ['Tip', 'Grocery Tip', 'Delivery Tip', 'Gratuity'],
        'default_uom': 'Units',
    },
    'service_fee': {
        'search_names': ['Service Fee', 'Instacart Service Fee', 'Delivery Fee', 'Service'],
        'default_uom': 'Units',
    },
}

# Company Settings
DEFAULT_COMPANY_ID = 1                 # Usually 1 for main company
DEFAULT_CURRENCY = 'USD'              # Currency code

# Product Matching Settings
PRODUCT_MATCHING = {
    'min_similarity': 0.7,             # Minimum similarity score for fuzzy matching
    'exact_match_first': True,         # Try exact match before fuzzy
    'case_sensitive': False,
}

# UoM Matching Settings
UOM_MATCHING = {
    'each_variations': ['units', 'unit', 'each', 'piece', 'pieces'],
    'lb_variations': ['lb', 'lbs', 'pound', 'pounds'],
    'kg_variations': ['kg', 'kilogram', 'kilograms'],
}

# Fruit Weight to Unit Conversion
# Fruits are sold by weight (lb) but counted by units (each)
# For fruits purchased by weight: convert to units using 4-pc UoM
# Conversion rates are loaded from fruit_weight_conversion.json (Step 2 output)
FRUIT_WEIGHT_CONVERSION = {
    'mapping_file': FRUIT_CONVERSION_FILE,  # Path to fruit_weight_conversion.json (Step 2 output)
    'convert_to_units': True,                # Convert weight (lb) to units (each)
    'use_4pc_uom': True,                     # Use "4-pc" UoM if available, otherwise use "Units"
    'weight_uoms': ['lb', 'lbs', 'pound', 'pounds'],  # UoM that indicate weight-based purchase
    '4pc_uom_name': '4-pc',                  # UoM name in system
}

# Legacy: Keep BANANA_CONVERSION for backward compatibility
BANANA_CONVERSION = FRUIT_WEIGHT_CONVERSION.copy()

# Purchase Order Settings
PO_SETTINGS = {
    'default_state': 'done',            # 'draft', 'purchase', 'done'
    'auto_confirm': False,              # Automatically confirm PO
    'create_stock_picking': True,      # Create stock picking/receipt
    'validate_receipt': True,          # Validate stock picking
}

# Receipt Processing Settings
RECEIPT_PROCESSING = {
    'supported_formats': ['.pdf', '.xlsx', '.xls', '.csv'],  # All supported formats
    'date_format': '%Y-%m-%d',         # Expected date format in receipts
    'decimal_separator': '.',          # Decimal separator
    'thousands_separator': ',',         # Thousands separator
    # Excel files use openpyxl engine (xlrd blocked to prevent Python 2 syntax errors)
    'excel_engine': 'openpyxl',        # Excel reading engine
}

# Text Extraction Settings
TEXT_EXTRACTION_THRESHOLD = 200         # Minimum characters to consider text extraction successful

# File Paths (Updated to use odoo_data folder)
PATHS = {
    'receipts_folder': '../odoo_data/receipts/',    # Folder containing receipt PDFs
    'processed_folder': 'receipts/processed/',  # Folder for processed receipts
    'failed_folder': 'receipts/failed/',  # Folder for failed receipts
    'log_folder': 'logs/',             # Folder for log files
    'output_folder': 'output/',        # Folder for output files
}

# Logging Settings
LOGGING = {
    'level': 'INFO',                   # DEBUG, INFO, WARNING, ERROR
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    # Note: Log files are now in each step's output directory (logs/step*.log)
    # Workflow-level log is at logs/workflow.log
}
