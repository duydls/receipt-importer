# Receipts/Oct Folder Structure Review

## Date: Review Only (No Modifications Made)

## Executive Summary

**Key Findings:**
- ✅ **RD Format Confirmed**: RD orders are CSV-only (no PDFs needed). System already supports this via `RDCSVProcessor`.
- ⚠️ **Unknown Vendors**: 5 files in `others/` folder need individual testing (Duverger, FoodServiceDirect, Pike Global Foods, 88, flooranddecor)
- ✅ **Structure Compatible**: Nested folder structure (`Receipts/Oct/`) is compatible with system's recursive file discovery
- 📊 **File Count**: 24 PDFs + 6 CSVs total across all vendors
- ⚠️ **Amazon CSV**: Filename has trailing space which may cause issues

## Expected Structure (from README)

Based on the project documentation, the expected input structure is:

```
data/step1_input/
├── COSTCO/               # Costco Excel files (.xlsx) - but now PDFs
├── RD/                   # Restaurant Depot Excel files - but now PDFs
├── JEWEL/                # Jewel-Osco Excel files
├── ALDI/                 # Aldi Excel files
├── MARIANOS/             # Mariano's Excel files
├── PARKTOSHOP/           # ParkToShop Excel files
├── INSTACART/            # Instacart PDFs + CSV baseline
│   ├── *.pdf
│   └── order_summary_report.csv
├── BBI/                  # BBI Wholesale Excel files
└── AMAZON/               # Amazon Business orders
    ├── orders_from_*.csv
    └── *.pdf
```

**Key Points:**
- Vendor folders are directly under `step1_input/`
- Each vendor has its own top-level folder
- Files are organized by vendor name

---

## New Structure: Receipts/Oct

The new data is organized under `data/step1_input/Receipts/Oct/` with the following structure:

```
data/step1_input/Receipts/Oct/
├── Amazon/                       # ✅ Vendor folder (nested)
│   ├── amazon_1003_01.pdf
│   ├── amazon_1003_02.pdf
│   ├── amazon_1004.pdf
│   ├── amazon_1031.pdf
│   └── orders_from_20251001_to_20251031_20251114_0426 .csv  # ⚠️ CSV with trailing space
├── costco/                       # ✅ Vendor folder (lowercase, nested)
│   ├── Orders & Purchases _ Costco_1008.pdf
│   └── Orders & Purchases _ Costco_1021.pdf
├── RD/                           # ✅ Vendor folder (nested) - HAS CSV FILES
│   ├── RD_1013.pdf               # Note: PDFs not found, but CSVs exist
│   ├── RD_1021.pdf
│   ├── RD_1031.pdf
│   ├── receipt-18851.csv         # ⚠️ NEW: RD CSV files
│   ├── receipt-22431.csv
│   └── receipt-28998.csv
├── instacart/                    # ✅ Vendor folder (nested) - COMPLEX STRUCTURE
│   ├── instacart_order_item_summary_report_1001-1031.csv
│   ├── order_summary_report.csv
│   └── receipt_management_16430606005510172_2025-11-22_2025-10-01_2025-10-31/
│       ├── Uni_Uni_Uptown_2025-10-01_18151725418491796.pdf
│       ├── Uni_Uni_Uptown_2025-10-03_18167259985480644.pdf
│       ├── Uni_Uni_Uptown_2025-10-05_18179604832488932.pdf
│       ├── Uni_Uni_Uptown_2025-10-05_18183834172483904.pdf
│       ├── Uni_Uni_Uptown_2025-10-11_18236274577498724.pdf
│       ├── Uni_Uni_Uptown_2025-10-15_18270673516486744.pdf
│       ├── Uni_Uni_Uptown_2025-10-18_18295761163489596.pdf
│       ├── Uni_Uni_Uptown_2025-10-18_18295776893492376.pdf
│       ├── Uni_Uni_Uptown_2025-10-21_18318971874499636.pdf
│       ├── Uni_Uni_Uptown_2025-10-24_18347587090484576.pdf
│       ├── Uni_Uni_Uptown_2025-10-25_18353985027485568.pdf
│       ├── Uni_Uni_Uptown_2025-10-28_18377422545484760.pdf
│       └── Uni_Uni_Uptown_2025-10-31_18410898240492500.pdf
└── others/                       # ⚠️ NEW: Catch-all folder for unknown vendors
    ├── 88_1009.pdf
    ├── Duverger_1009.pdf
    ├── FoodServiceDirect_1008.pdf
    ├── Pike Global Foods - 20251001.pdf
    └── flooranddecor_20251021.pdf
```

---

## Key Differences & Observations

### 1. **Nested Folder Structure**
- **Expected**: Vendor folders directly under `step1_input/`
- **New**: Vendor folders nested under `Receipts/Oct/`
- **Impact**: The system uses `glob('**/*.pdf')` which recursively searches, so this should work. Vendor detection uses filename/path patterns, so nested paths should be detected correctly.

### 2. **Case Sensitivity**
- **Expected**: `COSTCO/`, `AMAZON/` (uppercase)
- **New**: `costco/`, `Amazon/` (mixed case)
- **Impact**: Vendor detection patterns are case-insensitive (uses `.lower()`), so this should work.

### 3. **RD CSV Files** ✅ **CONFIRMED: CSV-ONLY FORMAT**
- **User Confirmation**: RD orders will be in CSV format only - no PDFs needed
- **New**: RD folder contains **3 CSV files**:
  - `receipt-18851.csv`
  - `receipt-22431.csv`
  - `receipt-28998.csv`
- **System Support**: ✅ The system already has `RDCSVProcessor` (`rd_csv_processor.py`) that handles RD CSV files
- **Expected Format**: CSV with invoice line containing "Invoice: [number]", date, and item rows with UPC, Description, Unit Qty, Case Qty, Price
- **Impact**: These CSV files should be processed automatically by the RD CSV processor. No PDF processing needed for RD.

### 4. **Instacart Complex Structure**
- **Expected**: `INSTACART/` with PDFs and CSV at same level
- **New**: `instacart/` with:
  - 2 CSV files at folder root
  - 13 PDFs in nested subfolder: `receipt_management_16430606005510172_2025-11-22_2025-10-01_2025-10-31/`
- **Impact**: The recursive `glob('**/*.pdf')` will find PDFs, but the nested folder structure is unusual. CSV matching should work if processor looks recursively.

### 5. **Amazon CSV with Trailing Space** ⚠️ **POTENTIAL ISSUE**
- **File**: `orders_from_20251001_to_20251031_20251114_0426 .csv` (note space before `.csv`)
- **Impact**: The Amazon CSV processor uses `glob('orders_from_*.csv')` which should match, but trailing spaces in filenames can cause issues on some systems. May need to handle or rename.

### 6. **Others Folder**
- **New**: `others/` folder contains all unknown/miscellaneous vendors:
  - `88_1009.pdf` - Unknown vendor
  - `Duverger_1009.pdf` - Unknown vendor
  - `FoodServiceDirect_1008.pdf` - Unknown vendor
  - `Pike Global Foods - 20251001.pdf` - Unknown vendor
  - `flooranddecor_20251021.pdf` - Floor & Decor (non-food category)
- **Impact**: These will rely on content-based vendor detection or filename patterns. May need vendor detection rules added if not recognized. The `others/` folder name won't interfere with vendor detection since it checks filename/path patterns.

### 7. **Amazon Structure**
- **Expected**: `AMAZON/` with subfolders for each order ID (e.g., `112-2077897-1883414/`)
- **New**: `Amazon/` with PDFs directly in the folder (no order ID subfolders) + CSV file
- **Impact**: Amazon processor uses CSV-first approach. It extracts order IDs from PDF filenames/paths to match CSV rows. Need to verify if PDF filenames (`amazon_1003_01.pdf`, etc.) contain order IDs that match the CSV, or if the processor can extract them from content.

---

## System Compatibility Analysis

### ✅ **Will Work (No Changes Needed)**

1. **Recursive File Discovery**: System uses `glob('**/*.pdf')` which will find all PDFs recursively
2. **Vendor Detection**: Uses filename/path patterns with case-insensitive matching
3. **Nested Folders**: `detect_group()` uses `file_path.relative_to(input_dir)` which handles nested paths
4. **Costco, RD, Amazon**: Should be detected from folder names and filenames

### ⚠️ **Potential Issues**

1. **Amazon CSV Filename**: `orders_from_20251001_to_20251031_20251114_0426 .csv` has trailing space before extension - may cause issues
2. **Amazon Order ID Matching**: PDFs named `amazon_1003_01.pdf` don't clearly show order IDs - need to verify if processor can extract from filename or content
3. **Unknown Vendors in `others/`**: Files like `Duverger_1009.pdf`, `FoodServiceDirect_1008.pdf`, `Pike Global Foods - 20251001.pdf`, `88_1009.pdf` may not be detected correctly - **User Note**: These are hard to handle and may need to test one by one
4. **Instacart Nested Structure**: PDFs in deeply nested folder - should work with recursive glob but unusual structure

### ❓ **Needs Verification**

1. **Amazon Order ID Extraction**: Do PDF filenames (`amazon_1003_01.pdf`) contain order IDs, or does processor extract from PDF content?
2. **RD CSV Format**: Do the CSV files (`receipt-18851.csv`, etc.) match the expected RD CSV format? (System supports RD CSV, but format needs verification)
3. **Unknown Vendors**: Need to test one by one:
   - `Duverger_1009.pdf`
   - `FoodServiceDirect_1008.pdf`
   - `Pike Global Foods - 20251001.pdf`
   - `88_1009.pdf`
   - `flooranddecor_20251021.pdf` (non-food category)
4. **Instacart CSV Matching**: Will the processor correctly match 13 PDFs in nested folder with 2 CSV files?

---

## Recommendations

### 1. **Vendor Detection Rules**
Consider adding detection rules for:
- `Duverger` → Vendor code?
- `FoodServiceDirect` → Vendor code?
- `Pike Global Foods` → Vendor code?
- `88` → Vendor code? (or determine what vendor this is)
- `flooranddecor` → Vendor code? (or mark as non-food/exclude)

### 2. **Instacart CSV**
- Move CSV to `Receipts/Oct/INSTACART/` or ensure CSV processor can find it in the Oct folder
- Verify PDFs are in the correct location for matching

### 3. **Amazon Structure**
- Verify Amazon CSV exists and contains matching order IDs
- Check if PDF filenames contain order IDs for matching

### 4. **Folder Organization**
- Consider standardizing to match expected structure OR
- Update documentation to reflect new nested structure as acceptable

---

## Files Summary

| Location | Count | Type | Status |
|----------|-------|------|--------|
| `Amazon/` | 4 PDFs, 1 CSV | Amazon | ✅ Should work (⚠️ CSV has trailing space) |
| `costco/` | 2 PDFs | Costco | ✅ Should work |
| `RD/` | 0 PDFs, 3 CSVs | Restaurant Depot | ✅ CSV-only format (confirmed by user) |
| `instacart/` | 13 PDFs, 2 CSVs | Instacart | ✅ Should work (nested structure) |
| `others/` | 5 PDFs | Various unknown vendors | ⚠️ Needs vendor detection |

**Total**: 24 PDFs, 6 CSVs

### Detailed Breakdown:

**PDFs by Vendor:**
- Amazon: 4 PDFs
- Costco: 2 PDFs
- Instacart: 13 PDFs (in nested folder)
- RD: 0 PDFs (CSV-only format - confirmed)
- Unknown (others/): 5 PDFs

**CSVs by Vendor:**
- Amazon: 1 CSV (`orders_from_20251001_to_20251031_20251114_0426 .csv` - trailing space)
- RD: 3 CSVs (`receipt-18851.csv`, `receipt-22431.csv`, `receipt-28998.csv`)
- Instacart: 2 CSVs (`instacart_order_item_summary_report_1001-1031.csv`, `order_summary_report.csv`)

---

## Key Discoveries from Second Review

1. **RD CSV-Only Format** ✅: User confirmed RD orders will be in CSV format only - no PDFs needed. System already supports this via `RDCSVProcessor`.

2. **Instacart Has Proper Structure**: Instacart folder is correctly organized with CSVs and PDFs, though PDFs are in a nested subfolder.

3. **Amazon CSV Present**: Amazon folder has the expected CSV file, but filename has trailing space which may cause issues.

4. **Others Folder Organization**: All unknown vendor files are properly organized in `others/` folder, not scattered in root.

5. **Unknown Vendors**: User noted these are hard to handle and may need to test one by one. No automatic solution expected.

## Next Steps

1. ✅ **Review Complete** - Structure fully documented without modifications
2. ✅ **RD Format Confirmed** - CSV-only format confirmed by user, system already supports this
3. ⏭️ **Await Instructions** - Ready to implement changes if needed
4. 📝 **Consider**: 
   - Verifying RD CSV format matches expected structure (system supports it, but format validation needed)
   - Checking if Amazon CSV filename trailing space needs fixing
   - Testing unknown vendors in `others/` folder one by one (as noted by user)
   - Verifying Instacart and Amazon CSV matching works with nested structures

