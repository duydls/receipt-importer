# Unprocessed Files Report - Step 1

## Date: 2025-11-22

## Summary

- **Total files in input folder**: 29
- **Successfully processed**: 24 files (83%)
- **Could not process**: 5 files (17%)

---

## ❌ Files That Could Not Be Processed

### 1. `Receipts/Oct/costco/Orders & Purchases _ Costco_1021.pdf`

**Status**: Processing failed  
**Reason**: No items extracted from PDF  
**Error**: `No items extracted from Orders & Purchases _ Costco_1021.pdf`  
**Action Required**: 
- Check PDF format/structure
- May need different parsing rules
- Verify PDF is not corrupted or image-based

---

### 2. `Receipts/Oct/others/88_1009.pdf`

**Status**: Vendor detection failed  
**Reason**: Vendor detected as UNKNOWN, no PDF rules available  
**Error**: `Could not detect vendor for 88_1009.pdf, using fallback: UNKNOWN`  
**Action Required**: 
- Identify actual vendor name for "88"
- Add vendor detection pattern to `step1_rules/10_vendor_detection.yaml`
- If image-based PDF, may need OCR support

**Confidence**: VERY LOW (0%) - Image-based PDF, no text extractable

---

### 3. `Receipts/Oct/others/Duverger_1009.pdf`

**Status**: Vendor detection failed  
**Reason**: Vendor detected as UNKNOWN, no PDF rules available  
**Error**: `Could not detect vendor for Duverger_1009.pdf, using fallback: UNKNOWN`  
**Action Required**: 
- Add "duverger" pattern to vendor detection rules
- Create vendor-specific PDF parsing rules (if needed)
- Expected: 4 items, $388.80 total

**Confidence**: MEDIUM-HIGH (70%) - Should work with vendor detection rules

---

### 4. `Receipts/Oct/others/FoodServiceDirect_1008.pdf`

**Status**: Vendor detection failed  
**Reason**: Vendor detected as UNKNOWN, no PDF rules available  
**Error**: `Could not detect vendor for FoodServiceDirect_1008.pdf, using fallback: UNKNOWN`  
**Action Required**: 
- Add "foodservicedirect" pattern to vendor detection rules
- Create table parsing rules for invoice format
- Handle multi-line product names
- Extract unit size (160 per case)
- Expected: 1 item (4 cases), $625.49 total

**Confidence**: MEDIUM-HIGH (75%) - Should work with vendor detection and parsing rules

---

### 5. `Receipts/Oct/others/PikeGlobalFoods_1001.pdf`

**Status**: Vendor detection failed  
**Reason**: Vendor detected as UNKNOWN, no PDF rules available  
**Error**: `Could not detect vendor for PikeGlobalFoods_1001.pdf, using fallback: UNKNOWN`  
**Action Required**: 
- Add "pike global foods" pattern to vendor detection rules
- Create invoice format parsing rules
- Expected: Invoice format, needs special handling

**Confidence**: MEDIUM (50%) - Invoice format needs special parser

---

## ⚠️ Additional Issue

### `Receipts/Oct/instacart/receipt_management_.../Uni_Uni_Uptown_2025-10-31_18410898240492500.pdf`

**Status**: Processing error (but may be in output with 0 items)  
**Error**: `TypeError: unsupported operand type(s) for +: 'float' and 'NoneType'`  
**Location**: `fee_extractor.py` line 181  
**Action Required**: 
- Fix TypeError in fee extraction logic
- Handle None values in total_price calculations

---

## ✅ Successfully Processed Files

### Local Grocery (4 receipts, 39 items)
- ✅ 3 RD CSV files (34 items, $936.93)
- ✅ 1 Costco PDF (5 items, $126.07)

### Instacart (13 receipts, 431 items)
- ✅ All 13 PDFs processed (with some total mismatches, but items extracted)

### Amazon (4 orders, 7 items)
- ✅ All 4 orders processed with CSV matching
- ✅ All 4 PDFs matched to CSV orders

---

## Recommended Actions

### Immediate (High Priority)

1. **Add Vendor Detection Rules** for:
   - Duverger
   - FoodServiceDirect
   - Pike Global Foods
   - 88 (identify vendor first)

2. **Fix Costco PDF**: Investigate why `Orders & Purchases _ Costco_1021.pdf` failed

3. **Fix Instacart TypeError**: Handle None values in fee extraction

### Medium Priority

4. **Create PDF Parsing Rules** for:
   - FoodServiceDirect (table format)
   - Pike Global Foods (invoice format)
   - Duverger (simple product list)

5. **OCR Support**: For `88_1009.pdf` if it's image-based

---

## Next Steps

1. Add vendor detection patterns to `step1_rules/10_vendor_detection.yaml`
2. Create vendor-specific PDF rules (if needed)
3. Fix known bugs (TypeError, Costco PDF)
4. Re-run Step 1 to process remaining files

