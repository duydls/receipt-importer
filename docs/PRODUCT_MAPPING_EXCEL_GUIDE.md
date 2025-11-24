# Product to Odoo Product Name Mapping - Excel Guide

## Overview

The Excel template allows you to easily create and manage product name mappings from receipt product names to Odoo standard product names.

**File Location**: `data/product_mapping_template.xlsx`

---

## Excel Structure

The Excel file contains 3 sheets:

### 1. **Product Mappings** (Main Sheet)
This is where you add/edit your mappings. Columns:

| Column | Description | Required | Example |
|--------|-------------|----------|---------|
| **Receipt Product Name** | Product name as it appears on receipts | ✅ Yes | "Chicken Breast" |
| **Odoo Product ID** | The `product_product.id` from Odoo | ✅ Yes | `12345` |
| **Odoo Product Name** | Standard product name in Odoo (for reference) | No | "Chicken Breast" |
| **Odoo Template ID** | `product_template.id` (for reference) | No | `6789` |
| **Receipt UoM** | UoM as it appears on receipt | No | "lb" |
| **Odoo UoM ID** | Odoo UoM ID (if different from product default) | No | `2` |
| **Odoo UoM Name** | Odoo UoM name (for reference) | No | "Units" |
| **UoM Conversion Ratio** | Conversion ratio if UoM differs | No | `4.0` (1 lb = 4 units) |
| **Vendors** | Comma-separated list of vendors | No | "Costco, RD, Instacart" |
| **Category** | Product category (for reference) | No | "Fresh Meat" |
| **Product Type** | product, consu, or service (for reference) | No | "product" |
| **Notes** | Any notes about this mapping | No | "Used for all vendors" |
| **Active** | TRUE/FALSE - whether mapping is active | No | `TRUE` |

### 2. **Odoo Products Reference**
Complete list of all products in Odoo database for easy lookup:
- Product ID
- Product Name
- UoM Name
- Category
- Product Type

**Use this sheet to find the correct Odoo Product ID when creating mappings.**

### 3. **Instructions**
Detailed instructions on how to use the template.

---

## How to Use

### Step 1: Generate/Open Excel Template

```bash
# Generate new template (or update existing)
python scripts/generate_product_mapping_excel.py -o data/product_mapping_template.xlsx
```

This will:
- Load existing mappings from `data/product_standard_name_mapping.json` (if it exists)
- Load all products from Odoo database
- Create the Excel file with 3 sheets

### Step 2: Edit Mappings

1. Open `data/product_mapping_template.xlsx` in Excel
2. Go to **Product Mappings** sheet
3. Add/edit rows:
   - **Receipt Product Name**: How the product appears on receipts
   - **Odoo Product ID**: Find this in the **Odoo Products Reference** sheet
   - **Odoo Product Name**: Copy from reference sheet (for your reference)
   - **Vendors**: List vendors this mapping applies to (comma-separated)
   - **UoM Conversion Ratio**: Only if receipt UoM differs from Odoo UoM

### Step 3: Convert Back to JSON

After editing, convert Excel back to JSON:

```bash
python scripts/convert_mapping_excel_to_json.py data/product_mapping_template.xlsx -o data/product_standard_name_mapping.json
```

This will:
- Read all mappings from Excel
- Convert to JSON format
- Save to `data/product_standard_name_mapping.json`

### Step 4: Use in Processing

The JSON mapping file will be automatically used by:
- Step 1 extraction (Odoo matching)
- Step 3 product matching
- SQL generation

---

## Examples

### Example 1: Simple Mapping

| Receipt Product Name | Odoo Product ID | Odoo Product Name | Vendors |
|---------------------|-----------------|-------------------|---------|
| Chicken Breast | 12345 | Chicken Breast | Costco, RD |

### Example 2: Mapping with UoM Conversion

| Receipt Product Name | Odoo Product ID | Receipt UoM | Odoo UoM Name | UoM Conversion Ratio | Notes |
|---------------------|-----------------|-------------|---------------|----------------------|-------|
| Banana | 67890 | lb | Units | 4.0 | 1 lb = 4 units |

### Example 3: Vendor-Specific Mapping

| Receipt Product Name | Odoo Product ID | Vendors | Notes |
|---------------------|-----------------|---------|-------|
| CHX NUGGET | 11111 | RD | Restaurant Depot abbreviation |
| Chicken Nuggets | 11111 | Costco, Instacart | Standard name for other vendors |

---

## Tips

1. **Use Odoo Products Reference Sheet**: 
   - Search for products by name
   - Copy Product ID and Product Name to your mapping

2. **Vendor-Specific Mappings**:
   - Create separate rows for different vendor abbreviations
   - Example: "CHX NUGGET" (RD) and "Chicken Nuggets" (Costco) both map to same Odoo product

3. **UoM Conversions**:
   - Only needed if receipt UoM differs from Odoo default UoM
   - Example: Receipt shows "lb" but Odoo product uses "Units"
   - Conversion ratio: how many Odoo units = 1 receipt unit

4. **Active Flag**:
   - Set to `FALSE` to disable a mapping without deleting it
   - Useful for testing or temporarily disabling mappings

5. **Notes Column**:
   - Use to document why this mapping exists
   - Helpful for future reference

---

## Workflow

```
1. Generate Excel Template
   ↓
2. Edit Mappings in Excel
   ↓
3. Convert Excel to JSON
   ↓
4. Re-run Step 1 (uses new mappings)
   ↓
5. Generate SQL (with correct product IDs)
```

---

## Command Reference

### Generate Excel Template

```bash
# Basic usage
python scripts/generate_product_mapping_excel.py

# Custom output file
python scripts/generate_product_mapping_excel.py -o my_mappings.xlsx

# Skip Odoo products (faster, but no reference sheet)
python scripts/generate_product_mapping_excel.py --no-odoo-products

# Load from different mapping file
python scripts/generate_product_mapping_excel.py -m data/custom_mapping.json
```

### Convert Excel to JSON

```bash
# Basic usage (outputs to same name with .json extension)
python scripts/convert_mapping_excel_to_json.py data/product_mapping_template.xlsx

# Custom output file
python scripts/convert_mapping_excel_to_json.py data/product_mapping_template.xlsx -o data/custom_mapping.json
```

---

## Troubleshooting

### "Could not connect to database"
- The script will still generate the template, but without the Odoo Products Reference sheet
- You can manually add Product IDs by looking them up in Odoo

### "Skipping row: missing Odoo Product ID"
- Make sure you fill in the **Odoo Product ID** column
- Use the **Odoo Products Reference** sheet to find the correct ID

### "Invalid Odoo Product ID"
- Make sure the Product ID is a number
- Check that it exists in Odoo (use Reference sheet)

### Excel file won't open
- Make sure you have `openpyxl` installed: `pip install openpyxl`
- Try regenerating: `python scripts/generate_product_mapping_excel.py`

---

## File Locations

- **Excel Template**: `data/product_mapping_template.xlsx`
- **JSON Mapping**: `data/product_standard_name_mapping.json`
- **Scripts**: 
  - `scripts/generate_product_mapping_excel.py`
  - `scripts/convert_mapping_excel_to_json.py`

---

## Next Steps

1. ✅ Excel template generated: `data/product_mapping_template.xlsx`
2. Edit the Excel file with your mappings
3. Convert back to JSON: `python scripts/convert_mapping_excel_to_json.py data/product_mapping_template.xlsx`
4. Re-run Step 1 to use the new mappings

