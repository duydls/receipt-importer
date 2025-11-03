# Receipt Importer - Complete Receipt Processing Solution

## Quick Start

**Run the complete workflow:**
```bash
python workflow.py
```

**Run a specific step:**
```bash
python workflow.py --step 1    # Extract data from receipts
python workflow.py --step 2    # Generate mapping file
python workflow.py --step 3    # Generate SQL files
```

See [README_WORKFLOW.md](README_WORKFLOW.md) for detailed workflow documentation.

---

## Overview

This project provides a complete 3-step workflow for processing receipt PDFs and importing purchase data into Odoo database. It includes:

1. **Receipt Processor** - Extract data from PDF receipts
2. **Product Matcher** - Match receipt items to existing products and UoMs in your database
3. **Odoo Importer** - Import matched items into Odoo using ORM (creates Purchase Orders, Stock Pickings, etc.)
4. **Main Workflow** - Complete pipeline from PDF to Odoo database

## Features

- ✅ PDF receipt processing (direct text extraction)
- ✅ Excel receipt processing (.xlsx, .xls files) with multiple format support:
  - Tabular format with Store Name, Transaction Date, Item Description, Extended Amount
  - Costco-specific format with Item Number column
  - Key-value format (Field/Detail columns)
- ✅ CSV file processing and linking (Instacart)
- ✅ Unified product enrichment (Costco & Restaurant Depot) via knowledge base
- ✅ Fee and discount extraction (tips, service fees, scheduled delivery discounts)
- ✅ Automatic product matching from existing database
- ✅ Automatic UoM matching and conversion
- ✅ Purchase Order creation in Odoo
- ✅ Stock Picking/Receipt creation
- ✅ Inventory updates
- ✅ Viewable in Odoo website/UI
- ✅ Batch processing support
- ✅ Logging and error handling

## Installation

### 1. Install Dependencies

```bash
cd receipt_importer
pip install -r requirements.txt
```

### 2. Configure Odoo Connection

Edit `config.py`:

```python
ODOO_CONFIG = {
    'url': 'http://localhost:8069',  # Your Odoo server
    'db': 'your_database_name',       # Your database
    'username': 'admin',              # Your username
    'password': 'admin',              # Your password
}
```

### 3. Initial Setup (One-Time)

Before regular processing, you need to set up mappings and transfer backups:

**Note**: This project focuses on the 3-step workflow for processing receipts. One-time setup tasks (database backups, initial mappings) should be handled separately.

### 4. Set Up Folder Structure

```bash
mkdir -p receipts/
mkdir -p receipts/processed/
mkdir -p receipts/failed/
mkdir -p logs/
mkdir -p output/
```

## Usage

### Regular Workflow (Process Receipts)

#### Generate SQL for All Receipts

```bash
python3 generate_receipt_sql.py --receipts-dir ../odoo_data/receipts --output-dir ../odoo_data/analysis/receipt_sql
```

This generates individual SQL files for each receipt with:
- Purchase Order INSERT statements
- Purchase Order Line INSERT statements
- Transaction wrapping (BEGIN/COMMIT)
- SELECT queries to view inserted data
- Detailed comments with original receipt values and conversions

#### Process Receipts with Main Workflow

See [README_WORKFLOW.md](README_WORKFLOW.md) for detailed usage instructions.

## Workflow

The complete workflow consists of 3 steps:

### Step 1: Extract Data from Receipts

**Rule-Driven Architecture:**
Step 1 uses a multi-stage rule-driven pipeline to extract receipt data:

1. **Vendor Detection** (`step1_rules/10_vendor_detection.yaml`)
   - Detects vendor and source type from filename/path and receipt content
   - Adds `detected_vendor_code` and `detected_source_type` to every receipt

2. **Layout Application** (`step1_rules/20_*.yaml` files)
   - Vendor-specific Excel/PDF layout rules (Costco, RD, Jewel, etc.)
   - Column mappings defined in YAML (no hardcoded column names)
   - Tries layout rules first, falls back to legacy processors if no match

3. **UoM Extraction** (`step1_rules/30_uom_extraction.yaml`)
   - Extracts raw unit/size text from receipt lines
   - Adds `raw_uom_text` and `raw_size_text` to items
   - **Does NOT normalize** (Step 2 handles normalization)

**Processing Groups:**
- **Vendor-based** (Excel): Costco, Jewel-Osco, RD, others
  - Processes Excel files (.xlsx, .xls)
  - Uses layout rules (`20_costco_layout.yaml`, `21_rd_layout.yaml`, `22_jewel_layout.yaml`)
  - Falls back to legacy `group1_excel.yaml` rules if layout rules don't match
- **Instacart-based** (PDF+CSV): Instacart only
  - Processes PDF files with CSV baseline matching
  - Uses legacy `group2_pdf.yaml` rules
  - Preserves all existing Instacart parsing logic

**Features:**
- **Excel Processing:**
  - Multiple format support (tabular, key-value, Costco-specific)
  - Vendor-specific column mappings from YAML rules
  - Layout detection and automatic format matching
  - Always extracts Tax and Other Charges (even if 0)
- **PDF Processing (Instacart):**
  - PDF text extraction (PyMuPDF, PyPDF2, pdfplumber, PDFMiner)
  - CSV baseline matching for enhanced item details (size, UoM, brand)
  - CSV baseline total matching: Uses `order_summary_report.csv` as authoritative source
  - Smart matching: Order ID or Date + Store Name
- **Shared Features:**
  - Vendor-specific parsers (Costco, Restaurant Depot)
  - Product enrichment via knowledge base (Costco & RD item specifications and prices)
  - Address filtering, fee and discount extraction
  - Separate outputs: `output/vendor_based/` and `output/instacart_based/`
  - Combined output for Step 2 compatibility
  - HTML reports per group

### Step 2: Match Products and UoMs

- Matches each receipt item to existing products in database
- Matches UoMs (Units, lb, kg, etc.)
- Uses fuzzy matching for product names
- Handles UoM conversions automatically

### Step 3: Import to Odoo

- Creates Purchase Order with matched items
- Creates Stock Picking (receipt)
- Updates inventory
- All visible in Odoo UI

## Example Output

```
================================================================================
Processing Receipt: Uni_Uni_Uptown_2025-09-01_17892079670490780.pdf
================================================================================
Step 1: Extracting data from PDF...
Extracted 4 items from receipt

Step 2: Matching products and UoMs...
✓ Matched: Lime 42 → Product ID 23, UoM ID 1
✓ Matched: SELECT Napkins → Product ID 141, UoM ID 1
✓ Matched: Chiquita Bananas → Product ID 105, UoM ID 15
✗ Not matched: Silk Unsweet Coconutmilk
Matched: 3/4 items

Step 3: Importing to Odoo...
Connected to Odoo: http://localhost:8069 (database: odoo)
Created Purchase Order: ID 123
Created Stock Picking: ID 456
✓ Purchase Order created: ID 123
  View in Odoo: http://localhost:8069/web#id=123&model=purchase.order
```

## File Structure

```
receipt_importer/
├── workflow.py                  # Main workflow orchestrator
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── README_WORKFLOW.md           # Workflow documentation
├── mappings/                    # Product and UoM mappings
│   ├── product_name_mapping.json
│   └── fruit_weight_conversion.json
├── step1_rules/                 # Step 1: YAML-based rule configuration
│   ├── README.md                # Rule system documentation
│   ├── shared.yaml               # Shared rules (UoM, fees, validation)
│   ├── group1_excel.yaml        # Group 1 rules (Costco, RD, Jewel-Osco, others)
│   └── group2_pdf.yaml          # Group 2 rules (Instacart)
├── step1_extract/               # Step 1: Extract data from receipts
│   ├── main.py                  # Entry point (group detection & routing)
│   ├── rule_loader.py           # YAML rule loader and merger
│   ├── logger.py                # Logging setup
│   ├── excel_processor.py       # Group 1 processor (Excel files)
│   ├── pdf_processor.py          # Group 2 processor (Instacart PDFs)
│   ├── receipt_processor.py      # Core processing logic
│   ├── generate_report.py        # HTML report generation
│   ├── csv_processor.py          # CSV file processing
│   ├── fee_extractor.py          # Fee extraction
│   ├── text_extractor.py        # Direct PDF text extraction
│   ├── costco_parser.py          # Costco receipt parser
│   ├── rd_parser.py             # Restaurant Depot parser
│   ├── address_filter.py        # Address line filtering
│   └── vendor_profiles.py       # Vendor profile handlers (web scraping)
├── step2_mapping/               # Step 2: Generate mapping file
│   ├── product_matcher.py       # Core matching logic
│   └── query_database.py        # Database queries
├── step3_sql/                  # Step 3: Generate SQL files
│   └── generate_receipt_sql.py # SQL generator
└── shared/                      # Shared utilities
    └── config.py                # Configuration
```

## Configuration

### Odoo Connection

```python
ODOO_CONFIG = {
    'url': 'http://localhost:8069',
    'db': 'your_database_name',
    'username': 'admin',
    'password': 'admin',
}
```

### Product Matching

```python
PRODUCT_MATCHING = {
    'min_similarity': 0.7,      # Minimum similarity score
    'exact_match_first': True,   # Try exact match first
}
```

### Purchase Order Settings

```python
PO_SETTINGS = {
    'default_state': 'done',            # 'draft', 'purchase', 'done'
    'auto_confirm': False,
    'create_stock_picking': True,       # Create receipt
    'validate_receipt': True,           # Auto-validate receipt
}
```

## Viewing in Odoo

After import, you can view the Purchase Order in Odoo:

1. **Web Interface**: Login to Odoo → Purchase → Orders
2. **Direct Link**: `http://your-odoo-server/web#id=<po_id>&model=purchase.order`
3. **API**: Use Odoo API to query purchase orders

## Troubleshooting

### PDF Extraction Fails

- **Direct text extraction fails**: Install PyMuPDF (`pip install PyMuPDF`) or PyPDF2 (`pip install PyPDF2`)
- **PDFMiner extraction fails**: Install pdfminer.six (`pip install pdfminer.six`)
- **pdfplumber extraction fails**: Install pdfplumber (`pip install pdfplumber`)
- **No items extracted**: Check receipt format - may require vendor-specific parser
- **Costco receipts**: Ensure Costco receipts are in Excel format (.xlsx) for best results

### Excel Processing Fails

- **Excel file not readable**: Install pandas and openpyxl (`pip install pandas openpyxl`)
- **No items extracted from Excel**: Check Excel file format - supported formats:
  - Tabular format: Store Name, Transaction Date, Item Description, Extended Amount (USD)
  - Costco format: Item Number column (see below)
  - Key-value format: Field/Detail columns
- **Costco Excel format**: 
  - Must include Item Number column with item codes
  - TAX (Fee) and TOTAL (Grand Total) amounts are in the next row's Extended Amount column
  - Citation markers in Item Description are automatically cleaned
- **Tax/Other Charges not showing**: These fields are always extracted and displayed in reports, even if 0

### Receipt Parsing Issues

- **Missing items**: Check vendor-specific parser is being used (Costco, Restaurant Depot)
- **Incorrect prices**: Verify receipt format matches expected patterns
- **Missing UoM**: Check Instacart CSV linking for enhanced UoM detection
- **Review flagged receipts**: Check `data/step1_output/report.html` for review reasons

### Products Not Matching

- Check `products_uom_analysis.json` exists
- Adjust `min_similarity` in config
- Manually review unmatched items

### Odoo Connection Fails

- Check Odoo server is running
- Verify credentials in `config.py`
- Check network/firewall settings

### UoM Mismatches

- System handles UoM conversions automatically
- Product default UoM can differ from purchase UoM
- Check logs for conversion warnings

## Advanced Usage

### Custom Receipt Formats

Modify `receipt_processor.py` to handle custom receipt formats.

### Custom Product Matching

Modify `product_matcher.py` to add custom matching logic.

### Batch Processing

```python
from main import ReceiptImporterWorkflow

workflow = ReceiptImporterWorkflow()
results = workflow.process_receipts_folder('receipts/')
```

## Support

For issues or questions:
1. Check logs in `logs/receipt_importer.log`
2. Review error messages
3. Check Odoo logs

## License

See LICENSE file in parent directory.

