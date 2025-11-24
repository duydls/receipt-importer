# Vendor Processing Confidence Analysis

**Purpose**: Rank vendors by processing confidence to help prioritize SQL generation and identify which receipts need more review.

**Last Updated**: Based on current codebase analysis

---

## Confidence Ranking (Highest to Lowest)

### 🟢 **HIGHEST CONFIDENCE** (95-100%)

#### 1. **Odoo** (`ODOO`)
- **Data Source**: Direct from Odoo database (PDF export)
- **Processing Method**: Structured data from Odoo system
- **Confidence**: **100%** - This is the authoritative source
- **Why High**:
  - Data comes directly from Odoo database
  - No OCR or parsing needed
  - Product IDs, names, categories already standardized
  - UoMs are already correct
  - Totals are already calculated
- **SQL Generation**: ✅ **READY** - Can generate SQL immediately
- **Notes**: These are already in Odoo, so SQL generation is just for validation/backup

---

### 🟢 **VERY HIGH CONFIDENCE** (90-95%)

#### 2. **Amazon** (`AMAZON`)
- **Data Source**: CSV file (authoritative) + PDF (optional validation)
- **Processing Method**: CSV-first processing, PDF for validation only
- **Confidence**: **92%** - CSV is structured and complete
- **Why High**:
  - CSV is treated as **authoritative source**
  - Structured data with all fields (product name, quantity, price, UoM)
  - PDF is only used for validation, not primary extraction
  - Order aggregation by Order ID
  - UNSPSC taxonomy integration for categories
- **SQL Generation**: ✅ **READY** - CSV data is reliable
- **Known Issues**:
  - CSV filename may have trailing spaces (fixed in code)
  - Nested folder structure (month-based) supported
- **Code Reference**: `amazon_csv_processor.py` - CSV-first approach

#### 3. **BBI** (`BBI`)
- **Data Source**: Excel files (.xlsx)
- **Processing Method**: Rule-driven layout + baseline matching
- **Confidence**: **90%** - Excel is structured, baseline matching improves accuracy
- **Why High**:
  - Excel files are structured (not OCR)
  - Has baseline matching system (`bbi_baseline.py`)
  - Rule-driven layout application
  - Product matching against known baseline
- **SQL Generation**: ✅ **READY** - Excel extraction is reliable
- **Known Issues**:
  - Some products may need baseline updates
  - UoM conversion may be needed
- **Code Reference**: `excel_processor.py`, `bbi_baseline.py`

---

### 🟡 **HIGH CONFIDENCE** (80-90%)

#### 4. **Instacart** (`INSTACART`)
- **Data Source**: PDF receipts + CSV baseline file
- **Processing Method**: PDF extraction + CSV matching
- **Confidence**: **85%** - CSV baseline improves PDF extraction
- **Why High**:
  - CSV baseline provides authoritative product names and prices
  - PDF extraction enriched with CSV data
  - Department/aisle mapping for categories
  - Fee extraction (tips, service fees, bag fees)
- **SQL Generation**: ⚠️ **MOSTLY READY** - Review CSV matching quality
- **Known Issues**:
  - PDF quality varies (some may need OCR)
  - CSV matching may miss some items if PDF extraction fails
  - Store name variations (IC-{store_name} format)
- **Code Reference**: `instacart_csv_matcher.py`, `csv_processor.py`

#### 5. **WebstaurantStore** (`WEBSTAUANTSTORE`)
- **Data Source**: PDF receipts
- **Processing Method**: PDF extraction with lookup
- **Confidence**: **82%** - Has product lookup system
- **Why High**:
  - Product lookup system (`webstaurantstore_lookup.py`)
  - Rule-driven PDF processing
- **SQL Generation**: ⚠️ **MOSTLY READY** - Verify lookup coverage
- **Known Issues**:
  - PDF quality dependent
  - Lookup may not cover all products
- **Code Reference**: `webstaurantstore_pdf_processor.py`, `webstaurantstore_lookup.py`

#### 6. **Wismettac** (`WISMETTAC`)
- **Data Source**: PDF receipts + API client
- **Processing Method**: PDF extraction + API integration
- **Confidence**: **80%** - Has API client for validation
- **Why High**:
  - API client available (`wismettac_client.py`)
  - Rule-driven PDF processing
  - Category mapping available
- **SQL Generation**: ⚠️ **MOSTLY READY** - Verify API integration
- **Known Issues**:
  - PDF quality dependent
  - API may not be always available
- **Code Reference**: `wismettac_client.py`, `31_wismettac_pdf.yaml`

---

### 🟡 **MEDIUM CONFIDENCE** (70-80%)

#### 7. **Costco** (`COSTCO`)
- **Data Source**: PDF receipts (Excel no longer supported)
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **75%** - Good rules, but PDF quality varies
- **Why Medium**:
  - Multiple layout support (3 variants)
  - Knowledge base enrichment (item specs, sizes)
  - Abbreviation handling ("ORG STRAWBRY" → organic strawberry)
  - Tax-exempt validation
- **SQL Generation**: ⚠️ **REVIEW RECOMMENDED** - Check PDF quality
- **Known Issues**:
  - PDF quality varies (some may need OCR)
  - OCR may fail on poor quality scans
  - Abbreviations may not always match
- **Code Reference**: `20_costco_pdf.yaml`, `pdf_processor_unified.py`

#### 8. **Restaurant Depot** (`RD`, `RESTAURANT_DEPOT`)
- **Data Source**: PDF receipts (Excel no longer supported)
- **Processing Method**: Grid-based PDF extraction
- **Confidence**: **75%** - Complex but rule-driven
- **Why Medium**:
  - Grid-based layout rules
  - Heavy abbreviation handling ("CHX NUGGET", "FF CRINKL", "OIL SHRT")
  - Multi-pack UoM parsing ("6/5LB", "25LB")
  - Duplicate line aggregation
  - Knowledge base enrichment
  - Amount reconciliation system (`rd_amount_reconciler.py`)
- **SQL Generation**: ⚠️ **REVIEW RECOMMENDED** - Complex abbreviations
- **Known Issues**:
  - Heavy abbreviation handling may miss some products
  - PDF grid extraction may fail on non-standard layouts
  - OCR quality critical for grid detection
- **Code Reference**: `21_rd_pdf_layout.yaml`, `rd_pdf_processor.py`, `rd_amount_reconciler.py`

#### 9. **Jewel-Osco** (`JEWEL`, `JEWELOSCO`)
- **Data Source**: PDF receipts
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **73%** - Standard PDF processing
- **Why Medium**:
  - Rule-driven layout
  - Standard PDF extraction
- **SQL Generation**: ⚠️ **REVIEW RECOMMENDED** - Check PDF quality
- **Known Issues**:
  - PDF quality dependent
  - OCR may fail on poor quality scans
- **Code Reference**: `22_jewel_pdf.yaml`

#### 10. **Aldi** (`ALDI`)
- **Data Source**: PDF receipts
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **72%** - Standard PDF processing
- **Why Medium**:
  - Rule-driven layout
  - Standard PDF extraction
- **SQL Generation**: ⚠️ **REVIEW RECOMMENDED** - Check PDF quality
- **Known Issues**:
  - PDF quality dependent
  - OCR may fail on poor quality scans
- **Code Reference**: `23_aldi_pdf.yaml`

#### 11. **ParkToShop** (`PARKTOSHOP`)
- **Data Source**: PDF receipts
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **70%** - Standard PDF processing
- **Why Medium**:
  - Rule-driven layout
  - Standard PDF extraction
- **SQL Generation**: ⚠️ **REVIEW RECOMMENDED** - Check PDF quality
- **Known Issues**:
  - PDF quality dependent
  - OCR may fail on poor quality scans
- **Code Reference**: `24_parktoshop_pdf.yaml`

---

### 🟠 **LOWER CONFIDENCE** (60-70%)

#### 12. **Duverger** (`DUVERGER`)
- **Data Source**: PDF receipts
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **65%** - Limited testing/validation
- **Why Lower**:
  - Rule-driven but less tested
  - PDF quality dependent
- **SQL Generation**: ⚠️ **REVIEW REQUIRED** - Limited validation
- **Known Issues**:
  - Less tested than other vendors
  - PDF quality critical
- **Code Reference**: `34_duverger_pdf.yaml`

#### 13. **FoodServiceDirect** (`FOODSERVICEDIRECT`)
- **Data Source**: PDF receipts
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **65%** - Limited testing/validation
- **Why Lower**:
  - Rule-driven but less tested
  - PDF quality dependent
- **SQL Generation**: ⚠️ **REVIEW REQUIRED** - Limited validation
- **Known Issues**:
  - Less tested than other vendors
  - PDF quality critical
- **Code Reference**: `35_foodservicedirect_pdf.yaml`

#### 14. **Pike Global Foods** (`PIKE_GLOBAL_FOODS`)
- **Data Source**: PDF receipts
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **65%** - Limited testing/validation
- **Why Lower**:
  - Rule-driven but less tested
  - PDF quality dependent
- **SQL Generation**: ⚠️ **REVIEW REQUIRED** - Limited validation
- **Known Issues**:
  - Less tested than other vendors
  - PDF quality critical
- **Code Reference**: `36_pike_global_foods_pdf.yaml`

#### 15. **88** (`88`)
- **Data Source**: PDF receipts
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **60%** - Limited testing/validation
- **Why Lower**:
  - Rule-driven but less tested
  - PDF quality dependent
- **SQL Generation**: ⚠️ **REVIEW REQUIRED** - Limited validation
- **Known Issues**:
  - Less tested than other vendors
  - PDF quality critical
- **Code Reference**: `37_88_pdf.yaml`

---

### 🔴 **LOWEST CONFIDENCE** (<60%)

#### 16. **Mariano's** (`MARIANOS`)
- **Data Source**: PDF receipts
- **Processing Method**: Rule-driven PDF extraction
- **Confidence**: **30%** - **NOT RECOMMENDED**
- **Why Low**:
  - **Explicitly commented in code**: "Mariano's not supported - OCR quality too poor"
  - PDF quality is consistently poor
  - OCR extraction unreliable
- **SQL Generation**: ❌ **NOT RECOMMENDED** - OCR quality too poor
- **Known Issues**:
  - OCR quality consistently poor
  - Extraction unreliable
  - May need manual processing
- **Code Reference**: `pdf_processor_unified.py` line 319 - commented out

---

## Summary Table

| Rank | Vendor | Confidence | Data Source | SQL Ready? | Review Needed? |
|------|--------|-----------|-------------|------------|----------------|
| 1 | **Odoo** | 100% | Database | ✅ Yes | No |
| 2 | **Amazon** | 92% | CSV | ✅ Yes | Minimal |
| 3 | **BBI** | 90% | Excel | ✅ Yes | Minimal |
| 4 | **Instacart** | 85% | PDF + CSV | ⚠️ Mostly | Yes |
| 5 | **WebstaurantStore** | 82% | PDF | ⚠️ Mostly | Yes |
| 6 | **Wismettac** | 80% | PDF + API | ⚠️ Mostly | Yes |
| 7 | **Costco** | 75% | PDF | ⚠️ Review | Yes |
| 8 | **Restaurant Depot** | 75% | PDF | ⚠️ Review | Yes |
| 9 | **Jewel-Osco** | 73% | PDF | ⚠️ Review | Yes |
| 10 | **Aldi** | 72% | PDF | ⚠️ Review | Yes |
| 11 | **ParkToShop** | 70% | PDF | ⚠️ Review | Yes |
| 12-15 | **Duverger, FoodServiceDirect, Pike, 88** | 60-65% | PDF | ⚠️ Review | Yes |
| 16 | **Mariano's** | 30% | PDF | ❌ No | Manual |

---

## Key Factors Affecting Confidence

### 1. **Data Source Quality** (Highest Impact)
- **Structured Data (CSV/Excel)**: 90-100% confidence
  - Amazon (CSV)
  - BBI (Excel)
  - Odoo (Database)
- **PDF with Baseline**: 80-90% confidence
  - Instacart (PDF + CSV baseline)
- **PDF Only**: 60-80% confidence
  - Costco, RD, Jewel, Aldi, etc.
  - Quality depends on OCR accuracy

### 2. **Processing Complexity**
- **Simple**: Direct data extraction (Odoo, Amazon CSV)
- **Medium**: Rule-driven with enrichment (BBI, Instacart)
- **Complex**: Heavy abbreviation handling (RD), multiple layouts (Costco)

### 3. **Validation & Matching**
- **Odoo Matching**: Items matched to Odoo purchase orders have higher confidence
- **Baseline Matching**: BBI baseline matching improves confidence
- **CSV Validation**: Instacart CSV validation improves confidence

### 4. **Known Issues**
- **Mariano's**: Explicitly marked as poor OCR quality
- **PDF Quality**: All PDF-based vendors depend on OCR quality
- **Abbreviations**: RD has heavy abbreviation handling (may miss some)

---

## Recommendations for SQL Generation

### ✅ **Generate SQL Immediately** (High Confidence)
1. **Odoo** - 100% confidence
2. **Amazon** - 92% confidence (CSV is authoritative)
3. **BBI** - 90% confidence (Excel is structured)

### ⚠️ **Generate SQL with Review** (Medium-High Confidence)
4. **Instacart** - 85% confidence (verify CSV matching)
5. **WebstaurantStore** - 82% confidence (verify lookup coverage)
6. **Wismettac** - 80% confidence (verify API integration)

### ⚠️ **Review Before SQL Generation** (Medium Confidence)
7-11. **Costco, RD, Jewel, Aldi, ParkToShop** - 70-75% confidence
   - Check PDF quality
   - Verify item extraction
   - Check Odoo matching rates
   - Review totals

### ⚠️ **Thorough Review Required** (Lower Confidence)
12-15. **Duverger, FoodServiceDirect, Pike, 88** - 60-65% confidence
   - Manual review recommended
   - Verify all items extracted
   - Check totals match

### ❌ **Manual Processing Recommended** (Low Confidence)
16. **Mariano's** - 30% confidence
   - OCR quality too poor
   - Consider manual entry or alternative processing

---

## Odoo Matching Impact

**Important**: Items that are **matched to Odoo purchase orders** have significantly higher confidence because:
- Product IDs are verified
- Standard names are from Odoo
- Categories are from Odoo
- Prices are validated against Odoo

**Recommendation**: Prioritize SQL generation for receipts with high Odoo matching rates (>90%).

---

## Next Steps

1. **Run Odoo matching analysis** to get actual match rates per vendor
2. **Generate SQL for high-confidence vendors first** (Odoo, Amazon, BBI)
3. **Review medium-confidence vendors** before SQL generation
4. **Manual review for low-confidence vendors** (Mariano's, untested vendors)

---

## Code References

- **Amazon CSV**: `step1_extract/amazon_csv_processor.py`
- **BBI Baseline**: `step1_extract/bbi_baseline.py`
- **Instacart CSV**: `step1_extract/instacart_csv_matcher.py`
- **Odoo Matching**: `step1_extract/odoo_matcher.py`
- **PDF Processing**: `step1_extract/pdf_processor_unified.py`
- **RD Reconciliation**: `step1_extract/rd_amount_reconciler.py`
- **Vendor Rules**: `step1_rules/*.yaml`

