# Receipt Processing Workflow

This project is organized into a clear 3-step workflow for processing receipts and generating SQL files for Odoo.

## Project Structure

```
receipt_importer/
├── workflow.py                  # Main workflow orchestrator
├── config.py                    # Configuration file
├── requirements.txt              # Python dependencies
├── README.md                     # Project overview
├── README_WORKFLOW.md            # Detailed workflow documentation
├── step1_rules/                  # Step 1: YAML-based rule configuration
│   ├── README.md                 # Rule system documentation
│   ├── shared.yaml               # Shared rules (UoM, fees, validation)
│   ├── group1_excel.yaml         # Group 1 rules (Costco, RD, Jewel-Osco, others)
│   └── group2_pdf.yaml           # Group 2 rules (Instacart)
├── step1_extract/                # Step 1: Extract data from receipts
│   ├── main.py                   # Entry point (group detection & routing)
│   ├── rule_loader.py            # YAML rule loader and merger
│   ├── logger.py                 # Logging setup
│   ├── excel_processor.py        # Group 1 processor (Excel files)
│   ├── pdf_processor.py          # Group 2 processor (Instacart PDFs)
│   ├── receipt_processor.py      # Core processing logic
│   ├── generate_report.py        # HTML report generation
│   ├── csv_processor.py          # CSV file processing
│   ├── fee_extractor.py          # Fee extraction
│   ├── text_extractor.py         # Direct PDF text extraction
│   ├── costco_parser.py           # Costco receipt parser
│   ├── rd_parser.py              # Restaurant Depot parser
│   ├── address_filter.py         # Address line filtering
│   └── vendor_profiles.py        # Vendor profile handlers (web scraping)
├── step2_mapping/                # Step 2: Generate mapping file
│   ├── product_matcher.py        # Core product matching logic
│   ├── query_database.py         # Database query utilities
│   └── (other mapping utilities)
├── step3_sql/                    # Step 3: Generate SQL files
│   └── generate_receipt_sql.py   # SQL generator
└── data/                          # Data directories
    ├── step1_output/              # Step 1 output (group1/, group2/, merged)
    ├── step2_output/               # Step 2 output (mappings)
    └── vendor_cache/               # Vendor product cache (Costco, RD)
```

## Workflow Steps

### Step 1: Extract Data from Receipts

Reads PDF, Excel, and CSV files and extracts structured receipt data using **YAML-based rule system**.

**Architecture:**
- **Group Detection**: Automatic based on folder structure
  - `Instacart/` → Group 2 (PDF + CSV processing)
  - `Costco/`, `Jewel-Osco/`, `RD/`, `others/` → Group 1 (Excel processing)
- **Rule System**: YAML-based rules in `step1_rules/`
  - `shared.yaml`: Common rules (UoM aliases, fees, validation)
  - `group1_excel.yaml`: Group 1 rules
  - `group2_pdf.yaml`: Group 2 rules (Instacart)

**Input:** PDF, Excel (.xlsx, .xls), and CSV files in receipt directory  
**Output:** 
- `output/group1/extracted_data.json` + `report.html`
- `output/group2/extracted_data.json` + `report.html`
- `output/extracted_data.json` (merged, for Step 2 compatibility)

**Key Components:**
- `main.py` - Entry point with group detection and routing
- `rule_loader.py` - Loads and merges YAML rules
- `excel_processor.py` - Group 1 processor (Excel files)
- `pdf_processor.py` - Group 2 processor (Instacart PDFs)
- `receipt_processor.py` - Core processing logic (used by both)
- `generate_report.py` - Report generation (unchanged intelligence)

**Features:**

**Group 1 (Excel-based):**
- Excel file processing with multiple format support:
  - **Tabular format**: Store Name, Transaction Date, Item Description, Extended Amount (USD)
  - **Costco-specific format**: Item Number column with special parsing for TAX/TOTAL rows
  - **Key-value format**: Field/Detail column pairs
  - Tax and Other Charges always extracted and displayed (even if 0)
- Vendor-specific column mappings from YAML rules
- Automatic vendor detection from folder/filename

**Group 2 (Instacart PDF + CSV):**
- PDF text extraction (PyMuPDF, PyPDF2, pdfplumber, PDFMiner)
- CSV baseline matching:
  - Cross-references PDF with CSV baseline for accurate item details (size, UoM, brand)
  - Uses `order_summary_report.csv` as authoritative source for totals
  - Smart matching: Order ID or Date + Store Name
  - Preserves all existing Instacart parsing logic exactly

**Shared Features:**
- Vendor-specific parsers (Costco, Restaurant Depot)
- Unified product enrichment:
  - **Costco**: Product name search with fresh price fetching (prices fluctuate daily)
  - **Restaurant Depot**: Product name search with cached prices (30-day TTL)
  - Cache locations: `data/vendor_cache/costco_cache.json` and `data/vendor_cache/rd_chicago_cache.json`
- Fee extraction (bag fee, tip, service fee, environmental fee, CRV, deposit)
- Address filtering to remove address lines

### Step 2: Generate Mapping File

Matches receipt products to database products and creates/updates the mapping file.

**Input:** Extracted receipt data from Step 1  
**Output:** Updated mapping file (`mappings/product_name_mapping.json`)

**Key Components:**
- `product_matcher.py` - Core matching logic
- `query_database.py` - Database queries for product info
- `fix_all_mappings.py` - Fix UoM categories
- `match_from_csv.py` - Match products from CSV

**Features:**
- Uses existing mapping file (if available)
- Fuzzy matching for unmapped products
- Fruit weight conversion (lb → units)
- UoM category validation

### Step 3: Generate SQL Files

Creates SQL INSERT statements for purchase orders and lines from mapped receipt data.

**Input:** Mapped receipt data from Step 2  
**Output:** SQL files (one per receipt)

**Key Components:**
- `generate_receipt_sql.py` - SQL generator

**Features:**
- Purchase order header creation
- Purchase order line items
- UoM conversions applied
- Transaction wrappers (BEGIN/COMMIT)
- SELECT statements for verification

## Usage

### Run All Steps

```bash
python workflow.py
```

### Run Specific Step

```bash
# Step 1 only
python workflow.py --step 1

# Steps 1 and 2
python workflow.py --step 2

# Steps 1, 2, and 3
python workflow.py --step 3
```

### With Options

```bash
# Specify receipts directory
python workflow.py --receipts-dir /path/to/receipts

# Specify mapping file
python workflow.py --mapping-file mappings/product_name_mapping.json

# Specify SQL output directory
python workflow.py --output-dir ../odoo_data/analysis/receipt_sql

# Set log level
python workflow.py --log-level DEBUG
```

### Programmatic Usage

```python
from workflow import ReceiptWorkflow

# Initialize workflow
workflow = ReceiptWorkflow()

# Step 1: Extract
extracted_data = workflow.step1_extract_all_receipts()

# Step 2: Generate mapping
mapped_data = workflow.step2_generate_mapping(extracted_data)

# Step 3: Generate SQL
sql_files = workflow.step3_generate_sql(mapped_data)

# Or run all at once
summary = workflow.run_all()
```

## Configuration

Configuration is in `config.py`. Key settings:

### Step 1 Configuration
- `STEP1_INPUT_DIR` - Input directory (receipts folder with subfolders)
- `STEP1_OUTPUT_DIR` - Output directory (`data/step1_output`)
- `RECEIPT_PROCESSING.supported_formats` - Supported formats (`.pdf`, `.xlsx`, `.xls`, `.csv`)
- `RECEIPT_PROCESSING.excel_engine` - Excel engine (`openpyxl` - xlrd blocked)
- `TEXT_EXTRACTION_THRESHOLD` - Minimum characters for successful text extraction (200)

### Step 1 Rules
Rules are in `step1_rules/`:
- `shared.yaml` - Common rules (UoM aliases, fees, validation)
- `group1_excel.yaml` - Group 1 rules (Costco, RD, Jewel-Osco, others)
- `group2_pdf.yaml` - Group 2 rules (Instacart)

See `step1_rules/README.md` for detailed rule documentation.

### Step 2 & 3 Configuration
- `STEP2_INPUT_DIR` - Input from Step 1 output
- `STEP2_OUTPUT_DIR` - Output directory (`data/step2_output`)
- `STEP3_OUTPUT_DIR` - SQL output directory
- `DB_DUMP_JSON` - Path to database analysis JSON
- `PRODUCT_MAPPING_FILE` - Path to mapping file
- `FRUIT_CONVERSION_FILE` - Path to fruit conversion file

## Mapping Files

### `mappings/product_name_mapping.json`

Maps receipt product names to database products with:
- `database_product_id` - Odoo product ID
- `database_product_name` - Odoo product name
- `receipt_uom` - UoM from receipt
- `odoo_uom` - UoM in Odoo database
- `uom_conversion_ratio` - Conversion ratio (e.g., 4.0 for banana: 1 lb = 4 units)
- `vendors` - List of vendor names

### `mappings/fruit_weight_conversion.json`

Conversion rates for fruits purchased by weight:
- `items_per_lb` - Number of items per pound
- Used for converting weight (lb) to units (each)

## Output Files

### Step 1 Output

```
data/step1_output/
├── group1/
│   ├── extracted_data.json    # Group 1 extracted data (Costco, RD, Jewel-Osco, others)
│   └── report.html            # Group 1 HTML report
├── group2/
│   ├── extracted_data.json    # Group 2 extracted data (Instacart)
│   └── report.html            # Group 2 HTML report
├── extracted_data.json        # Merged data (for Step 2 compatibility)
├── report.html                # Merged report
└── logs/
    └── step1_extract.log      # Step 1 log file
```

### Step 2 Output
- `data/step2_output/mapped_data.json` - All mapped receipt data
- `data/step2_output/product_name_mapping.json` - Updated mapping file
- `data/step2_output/fruit_weight_conversion.json` - Fruit conversion mappings

### Step 3 Output
- `../odoo_data/analysis/receipt_sql/*.sql` - SQL files (one per receipt)

## Logs

All logs are written to:
- Console output (stdout)
- `data/step1_output/logs/step1_extract.log` - Step 1 log
- `logs/workflow.log` - Main workflow log (if configured)

## Setup Scripts

One-time setup scripts are in `setup/`:
- Database backup transfer
- Initial mapping extraction
- UoM validation
- etc.

These are not part of the main workflow and should be run separately as needed.

