# Receipt Processing and Product Name Mapping Guide

**Complete guide to how vendor receipts are processed and product names are mapped to Odoo standard names.**

---

## Table of Contents

1. [Overview](#overview)
2. [Receipt Processing Workflow](#receipt-processing-workflow)
3. [Vendor-Specific Processing](#vendor-specific-processing)
4. [Product Name Mapping](#product-name-mapping)
5. [Mapping File Structure](#mapping-file-structure)
6. [How Mappings Are Used](#how-mappings-are-used)
7. [Creating and Managing Mappings](#creating-and-managing-mappings)
8. [Examples](#examples)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This system processes receipts from multiple vendors (Costco, Restaurant Depot, Amazon, Instacart, BBI, etc.) and maps receipt product names to standard Odoo product names. The process involves:

1. **Receipt Extraction**: Extract structured data from PDF, Excel, or CSV files
2. **Product Matching**: Match receipt product names to Odoo products
3. **Mapping**: Use manual mappings to ensure accurate matching
4. **SQL Generation**: Generate SQL to create purchase orders in Odoo

---

## Receipt Processing Workflow

### High-Level Flow

```
Receipt Files (PDF/Excel/CSV)
    ↓
Step 1: Extract Receipts
    ├─ Vendor Detection
    ├─ Layout Application
    ├─ Text Extraction (PDF OCR)
    ├─ Item Parsing
    ├─ UoM Extraction
    └─ Odoo Matching
    ↓
Step 2: Manual Review (Optional)
    ↓
Step 3: Product Mapping
    ├─ Load Mapping File
    ├─ Match Products
    └─ Apply Mappings
    ↓
Step 4: Generate SQL
    └─ Create Purchase Order SQL
```

### Step 1: Receipt Extraction

**Location**: `step1_extract/main.py`

**Process**:

1. **File Detection**: Scans input directory for receipt files
   - PDF files: `.pdf`
   - Excel files: `.xlsx`, `.xls`
   - CSV files: `.csv`

2. **Vendor Detection**: Identifies vendor from file path or content
   - Uses `10_vendor_detection.yaml` rules
   - Checks folder structure (e.g., `Receipts/Costco/`, `Receipts/AMAZON/`)
   - Analyzes file content for vendor signatures

3. **Source Type Detection**: Determines receipt type
   - `localgrocery_based`: Costco, RD, Jewel-Osco, Aldi, ParkToShop
   - `instacart_based`: Instacart orders
   - `amazon_based`: Amazon orders
   - `bbi_based`: BBI wholesale
   - `odoo_based`: Odoo purchase orders
   - `webstaurantstore_based`: WebstaurantStore
   - `wismettac_based`: Wismettac

4. **Format-Specific Processing**:
   - **PDF**: OCR extraction using Tesseract, layout detection, grid parsing
   - **Excel**: Structured data extraction using pandas, header detection
   - **CSV**: Direct parsing (Amazon, Instacart baseline files)

5. **Item Extraction**:
   - Product name extraction
   - Quantity parsing
   - Price extraction (unit price, total price)
   - UoM extraction (lb, kg, units, etc.)
   - Fee identification (tips, service fees, taxes)

6. **Odoo Matching** (if enabled):
   - Matches receipt items to Odoo purchase orders
   - Uses price-based matching (total price, unit price)
   - Name similarity matching
   - Sets `odoo_product_id` and `standard_name` on items

**Output**: `data/step1_output/*/extracted_data.json`

---

## Vendor-Specific Processing

### 1. Costco

**Format**: PDF receipts

**Processing**:
- Multiple layout support (3 variants)
- Knowledge base enrichment (item specs, sizes)
- Abbreviation handling ("ORG STRAWBRY" → "organic strawberry")
- Tax-exempt validation

**Rule File**: `step1_rules/20_costco_pdf.yaml`

**Example**:
```
Receipt Line: "ORG STRAWBRY 2.99"
  → Extracted: product_name="ORG STRAWBRY", price=2.99
  → Knowledge Base: "organic strawberry"
  → Final: product_name="organic strawberry"
```

### 2. Restaurant Depot (RD)

**Format**: PDF receipts (Excel no longer supported)

**Processing**:
- Grid-based layout extraction
- Heavy abbreviation handling:
  - "CHX NUGGET" → "chicken nuggets"
  - "FF CRINKL" → "french fries crinkle"
  - "OIL SHRT" → "oil shortening"
- Multi-pack UoM parsing ("6/5LB", "25LB")
- Duplicate line aggregation
- Amount reconciliation

**Rule File**: `step1_rules/21_rd_pdf_layout.yaml`

**Example**:
```
Receipt Line: "CHX NUGGET 5LB 25.99"
  → Extracted: product_name="CHX NUGGET", quantity=5, uom="LB", price=25.99
  → Abbreviation: "chicken nuggets"
  → Final: product_name="chicken nuggets", purchase_uom="lb"
```

### 3. Amazon

**Format**: CSV file (authoritative) + PDF (optional validation)

**Processing**:
- **CSV-first approach**: CSV is the source of truth
- Order aggregation by Order ID
- UNSPSC taxonomy integration for categories
- PDF used only for validation

**Rule File**: `step1_rules/28_amazon_csv.yaml`

**Example**:
```
CSV Row: Order ID="112-1234567-8901234", Title="Chicken Breast", Quantity=2, Price=15.99
  → Extracted: product_name="Chicken Breast", quantity=2, price=15.99
  → PDF validation: Matches PDF receipt
```

### 4. Instacart

**Format**: PDF receipts + CSV baseline file

**Processing**:
- PDF text extraction
- CSV baseline matching (authoritative product names)
- Department/aisle mapping for categories
- Fee extraction (tips, service fees, bag fees)

**Rule File**: `step1_rules/25_instacart_csv.yaml`

**Example**:
```
PDF: "Chicken Breast 2.5 lb $12.99"
CSV: "Chicken Breast", Department="Meat & Seafood", Aisle="Chicken"
  → Extracted: product_name="Chicken Breast" (from CSV), quantity=2.5, uom="lb"
  → Category: L2="Fresh Meat" (from department mapping)
```

### 5. BBI (Boba Baron Inc)

**Format**: Excel files

**Processing**:
- Structured Excel extraction
- Baseline matching (known product database)
- Product name normalization

**Rule File**: `step1_rules/27_bbi_layout.yaml`

### 6. Odoo Purchase Orders

**Format**: PDF exports from Odoo

**Processing**:
- Direct structured data extraction
- No OCR needed (already structured)
- Product IDs already present

**Rule File**: `step1_rules/32_odoo_pdf.yaml`

---

## Product Name Mapping

### Why Mapping is Needed

Receipt product names often differ from Odoo standard names:

| Receipt Name | Odoo Standard Name |
|--------------|-------------------|
| "CHX NUGGET" | "Chicken Nuggets 5-LB" |
| "Chicken Nuggets Box (~225 pc)" | "Chicken Nuggets 5-LB" |
| "Crinkle Cut Fries Bag" | "Crinkle Cut Fries 5-LB" |
| "Chocolate Mousse Cake (Regular)" | "Chocolate Mousse Cake" |

### Mapping Process

**Location**: `step1_extract/odoo_matcher.py` and `step3_mapping/match_to_odoo.py`

**Steps**:

1. **Load Mapping File**: `data/product_standard_name_mapping.json`
   ```json
   {
     "Chicken Nuggets Box": {
       "database_product_id": 12345,
       "database_product_name": "Chicken Nuggets 5-LB",
       "vendors": ["Restaurant Depot", "Costco"]
     }
   }
   ```

2. **Match Receipt Items**:
   - First: Check mapping file (exact match)
   - Second: Try Odoo matching (price-based, name similarity)
   - Third: Fuzzy matching (if enabled)

3. **Set Product ID**:
   - If match found: Set `odoo_product_id` on receipt item
   - If not found: Item marked for review

### Mapping Priority

1. **Manual Mappings** (Highest Priority)
   - From `product_standard_name_mapping.json`
   - Confidence: 100%

2. **Odoo Purchase Order Matching**
   - Matches to existing Odoo purchase orders
   - Price-based matching (total price, unit price)
   - Confidence: 90-95%

3. **Name Similarity Matching**
   - Fuzzy string matching
   - Jaccard similarity
   - Confidence: 60-80%

4. **No Match**
   - Item marked for review
   - Manual mapping required

---

## Mapping File Structure

### JSON Format

**File**: `data/product_standard_name_mapping.json`

```json
{
  "_metadata": {
    "source": "Excel file",
    "generated_at": "2025-11-23T18:39:00",
    "total_mappings": 239
  },
  "Chicken Nuggets Box": {
    "database_product_id": 12345,
    "database_product_name": "Chicken Nuggets 5-LB",
    "receipt_uom": "box",
    "odoo_uom_id": 2,
    "odoo_uom_name": "Units",
    "uom_conversion_ratio": 1.0,
    "vendors": ["Restaurant Depot", "Costco"],
    "notes": "Auto-generated from September orders",
    "active": true
  },
  "Crinkle Cut Fries Bag": {
    "database_product_id": 67890,
    "database_product_name": "Crinkle Cut Fries 5-LB",
    "vendors": ["Restaurant Depot"],
    "active": true
  }
}
```

### Excel Format

**File**: `data/product_mapping_template.xlsx`

**Columns**:
- **Receipt Product Name**: Product name as it appears on receipts
- **Odoo Product ID**: `product_product.id` from Odoo
- **Odoo Product Name**: Standard product name in Odoo (for reference)
- **Receipt UoM**: UoM as it appears on receipt (optional)
- **Odoo UoM ID**: Odoo UoM ID (optional)
- **Odoo UoM Name**: Odoo UoM name (optional)
- **UoM Conversion Ratio**: Conversion ratio if UoM differs (e.g., 4.0 for banana: 1 lb = 4 units)
- **Vendors**: Comma-separated list of vendors (e.g., "Costco, RD, Instacart")
- **Notes**: Any notes about this mapping
- **Active**: TRUE/FALSE - whether mapping is active

---

## How Mappings Are Used

### Step 1: Receipt Extraction

**Location**: `step1_extract/odoo_matcher.py`

**Process**:

1. Receipt items are extracted with product names
2. For each item, check mapping file:
   ```python
   receipt_name = item.get('product_name')  # "Chicken Nuggets Box"
   
   if receipt_name in product_mapping:
       mapping = product_mapping[receipt_name]
       item['odoo_product_id'] = mapping['database_product_id']
       item['standard_name'] = mapping['database_product_name']
   ```

3. If mapping found:
   - Set `odoo_product_id` on item
   - Set `standard_name` on item
   - Set `odoo_category_matched = True` (skip reclassification)

### Step 3: Product Matching

**Location**: `step3_mapping/match_to_odoo.py`

**Process**:

1. Load mapping file
2. For each receipt item:
   ```python
   # Try mapping first (highest priority)
   if product_name in product_mapping:
       product_id = product_mapping[product_name]['database_product_id']
       confidence = 1.0  # 100% confidence
       return match
   
   # Fallback: Try Odoo matching
   match = match_to_odoo_by_price_or_name(...)
   ```

### Step 4: SQL Generation

**Location**: `scripts/generate_purchase_order_sql.py`

**Process**:

1. For each receipt item:
   ```python
   product_id = item.get('odoo_product_id')
   if not product_id:
       return None  # Skip item - no SQL generated
   ```

2. Generate SQL INSERT:
   ```sql
   INSERT INTO purchase_order_line (
       product_id,  -- From mapping!
       name,        -- Standard Odoo name
       product_qty,
       price_unit,
       ...
   )
   VALUES (
       12345,  -- From mapping
       'Chicken Nuggets 5-LB',
       1.0,
       25.99,
       ...
   )
   ```

**Without mapping**: Item skipped, no SQL generated  
**With mapping**: Item included, SQL generated successfully

---

## Creating and Managing Mappings

### Method 1: Excel Template (Recommended)

**Step 1: Generate Excel Template**
```bash
python scripts/generate_product_mapping_excel.py -o data/product_mapping_template.xlsx
```

This creates an Excel file with:
- Existing mappings (if any)
- Odoo Products Reference sheet (all products for lookup)
- Instructions sheet

**Step 2: Edit Excel File**
1. Open `data/product_mapping_template.xlsx`
2. Go to "Product Mappings" sheet
3. Add/edit rows:
   - **Receipt Product Name**: How product appears on receipts
   - **Odoo Product ID**: Find in "Odoo Products Reference" sheet
   - **Odoo Product Name**: Copy from reference sheet
   - **Vendors**: List vendors (comma-separated)

**Step 3: Convert to JSON**
```bash
python scripts/convert_mapping_excel_to_json.py data/product_mapping_template.xlsx -o data/product_standard_name_mapping.json
```

### Method 2: Generate from September Orders

**Automatically create mappings from Odoo purchase orders**:

```bash
python scripts/generate_mappings_from_september_orders.py
```

This script:
1. Loads September purchase orders from Odoo
2. Extracts products where `line_name` differs from `product_name`
3. Creates mappings automatically
4. Adds to Excel file

**Example Output**:
```
Loaded 41 September purchase orders with 239 lines
Found 28 products with different line names
Created 23 new mappings
Added to Excel: data/product_mapping_template.xlsx
```

### Method 3: Manual JSON Editing

Edit `data/product_standard_name_mapping.json` directly:

```json
{
  "Your Receipt Product Name": {
    "database_product_id": 12345,
    "database_product_name": "Standard Odoo Name",
    "vendors": ["Vendor1", "Vendor2"],
    "active": true
  }
}
```

---

## Examples

### Example 1: Restaurant Depot Abbreviation

**Receipt**: "CHX NUGGET 5LB 25.99"

**Processing**:
1. Extract: `product_name="CHX NUGGET"`, `quantity=5`, `uom="LB"`
2. Abbreviation expansion: `product_name="chicken nuggets"`
3. Check mapping: `"chicken nuggets"` → Product ID 12345
4. Set: `odoo_product_id=12345`, `standard_name="Chicken Nuggets 5-LB"`
5. SQL: `INSERT INTO purchase_order_line (product_id=12345, ...)`

### Example 2: Amazon CSV Processing

**CSV Row**: `Order ID="112-1234567-8901234", Title="Organic Chicken Breast", Quantity=2, Price=29.98`

**Processing**:
1. Extract: `product_name="Organic Chicken Breast"`, `quantity=2`, `price=29.98`
2. Check mapping: `"Organic Chicken Breast"` → Product ID 67890
3. Set: `odoo_product_id=67890`, `standard_name="Organic Chicken Breast"`
4. SQL: `INSERT INTO purchase_order_line (product_id=67890, ...)`

### Example 3: Instacart with CSV Baseline

**PDF**: "Chicken Breast 2.5 lb $12.99"  
**CSV**: `Title="Chicken Breast", Department="Meat & Seafood"`

**Processing**:
1. Extract from PDF: `product_name="Chicken Breast"`, `quantity=2.5`, `uom="lb"`
2. Enrich from CSV: `department="Meat & Seafood"`
3. Check mapping: `"Chicken Breast"` → Product ID 11111
4. Set: `odoo_product_id=11111`, `standard_name="Chicken Breast"`
5. Category: L2="Fresh Meat" (from department mapping)
6. SQL: `INSERT INTO purchase_order_line (product_id=11111, ...)`

### Example 4: UoM Conversion

**Receipt**: "Banana 2 lb $3.98"  
**Mapping**: `"Banana"` → Product ID 99999, `uom_conversion_ratio=4.0` (1 lb = 4 units)

**Processing**:
1. Extract: `product_name="Banana"`, `quantity=2`, `uom="lb"`
2. Check mapping: `"Banana"` → Product ID 99999, conversion=4.0
3. Convert: `quantity=2 * 4.0 = 8 units`
4. SQL: `INSERT INTO purchase_order_line (product_id=99999, product_qty=8, ...)`

---

## Troubleshooting

### Problem: Items Not Matching to Odoo

**Symptoms**:
- Items have no `odoo_product_id`
- SQL generation skips items

**Solutions**:
1. **Check mapping file**: Is the receipt product name in the mapping?
   ```bash
   python -c "import json; m=json.load(open('data/product_standard_name_mapping.json')); print('Chicken Nuggets Box' in m)"
   ```

2. **Add mapping**: Use Excel template to add missing mappings

3. **Check Odoo matching**: Review logs for matching attempts
   ```bash
   grep "Matching" data/step1_output/logs/*.log
   ```

### Problem: Wrong Product Matched

**Symptoms**:
- Item matched to wrong Odoo product
- SQL has incorrect product_id

**Solutions**:
1. **Update mapping**: Edit Excel file with correct Product ID
2. **Check vendor**: Ensure mapping applies to correct vendor
3. **Verify product name**: Check exact spelling/casing

### Problem: UoM Conversion Issues

**Symptoms**:
- Quantities incorrect in SQL
- UoM mismatch errors

**Solutions**:
1. **Add conversion ratio**: In Excel, set "UoM Conversion Ratio" column
2. **Check UoM names**: Ensure receipt UoM and Odoo UoM are correctly specified
3. **Verify conversion**: Test conversion manually

### Problem: Mapping Not Applied

**Symptoms**:
- Mapping exists but not used
- Item still unmatched

**Solutions**:
1. **Check active flag**: Ensure `Active=TRUE` in Excel
2. **Verify JSON format**: After converting Excel, check JSON is valid
3. **Re-run Step 1**: Mappings are loaded at Step 1 start
4. **Check file path**: Ensure mapping file is in correct location

---

## File Locations

### Key Files

- **Mapping JSON**: `data/product_standard_name_mapping.json`
- **Mapping Excel**: `data/product_mapping_template.xlsx`
- **Step 1 Output**: `data/step1_output/*/extracted_data.json`
- **Step 3 Output**: `data/step3_output/mapped_data.json`
- **SQL Output**: `data/sql/purchase_order_*.sql`

### Scripts

- **Generate Excel**: `scripts/generate_product_mapping_excel.py`
- **Convert Excel to JSON**: `scripts/convert_mapping_excel_to_json.py`
- **Generate from September**: `scripts/generate_mappings_from_september_orders.py`
- **Generate SQL**: `scripts/generate_purchase_order_sql.py`

### Rule Files

- **Vendor Detection**: `step1_rules/10_vendor_detection.yaml`
- **Vendor Rules**: `step1_rules/20_*.yaml` (vendor-specific)
- **UoM Extraction**: `step1_rules/30_uom_extraction.yaml`
- **Category Rules**: `step1_rules/55_*.yaml`, `step1_rules/56_*.yaml`

---

## Best Practices

1. **Use Excel Template**: Easier to edit and review than JSON
2. **Regular Updates**: Add mappings as you discover new product name variations
3. **Vendor-Specific**: Create separate mappings for vendor-specific names
4. **Documentation**: Use "Notes" column to document why mapping exists
5. **Validation**: After adding mappings, re-run Step 1 to verify
6. **Backup**: Keep backup of mapping file before major changes

---

## Summary

**Receipt Processing**:
- Vendor-specific extraction (PDF/Excel/CSV)
- Rule-driven architecture (YAML files)
- OCR for PDF receipts
- Structured data for Excel/CSV

**Product Mapping**:
- Manual mappings (highest priority)
- Odoo purchase order matching
- Name similarity matching
- Essential for SQL generation

**Workflow**:
1. Extract receipts → Get product names
2. Match products → Get Odoo product IDs
3. Generate SQL → Create purchase orders

**Key Point**: Without mappings, items may not get `odoo_product_id`, and SQL generation will skip them. Mappings ensure complete and accurate SQL generation.

