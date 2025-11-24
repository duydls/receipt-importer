# Unknown Vendor Orders - Test Results

## Date: Testing Complete

## Overview

Tested 5 unknown vendor orders from `Receipts/Oct/others/` folder to determine processing capabilities.

---

## Test Results Summary

| File | Vendor Detected | Items Extracted | Total | Status | Action Required |
|------|----------------|-----------------|-------|--------|-----------------|
| `88_1009.pdf` | Unknown | 0 | $0.00 | ❌ Failed | OCR or manual processing |
| `Duverger_1009.pdf` | Restaurant Depot (incorrect) | 1 | $972.00 | ⚠️ Partial | Vendor detection + parsing rules |
| `FoodServiceDirect_1008.pdf` | Restaurant Depot (incorrect) | 0 (6 fees) | $2,501.96 | ⚠️ Partial | Better parsing rules needed |
| `Pike Global Foods - 20251001.pdf` | Restaurant Depot (incorrect) | 0 (4 fees) | $138.20 | ⚠️ Partial | Better parsing rules needed |
| `flooranddecor_20251021.pdf` | Unknown | 0 | $0.00 | ❌ Failed | OCR or manual processing |

---

## Detailed Results

### 1. `88_1009.pdf`
- **Status**: ❌ Failed
- **Vendor Detected**: Unknown
- **Items Extracted**: 0
- **Total**: $0.00
- **Issue**: PDF appears to be image-based (no text extracted)
- **Action Required**: 
  - Requires OCR processing
  - Or manual data entry
  - Need to identify actual vendor name

---

### 2. `Duverger_1009.pdf`
- **Status**: ⚠️ Partially Working
- **Vendor Detected**: Restaurant Depot (incorrect - should be "Duverger")
- **Items Extracted**: 1 product item (out of 2 total extracted)
- **Total**: $972.00
- **Subtotal**: $972.00
- **Tax**: $0.00

**PDF Content Analysis:**
- Actual Vendor: **Duverger**
- Order #: 02686
- Date: October 09, 2025
- Items visible in PDF:
  1. Boutique - Hazelnut Brittle - 332-72 (Qty: 1, $97.20)
  2. Boutique - Orange Truffle - 333-72 (Qty: 1, $97.20)
  3. Boutique - Pistachio - 308-72 (Qty: 1, $97.20)
  4. Boutique - Raspberry - 309-72 (Qty: 1, $97.20)
- Subtotal: $388.80
- Shipping: Free shipping

**Issues:**
- Vendor incorrectly detected as Restaurant Depot
- Only 1 item extracted (should be 4)
- Total mismatch ($972.00 vs $388.80)

**Action Required:**
1. Add vendor detection rule for "Duverger"
2. Create vendor-specific parsing rules
3. Fix item extraction logic

---

### 3. `FoodServiceDirect_1008.pdf` ✅ **UPDATED**
- **Status**: ⚠️ Partially Working (Improved after update)
- **Vendor Detected**: UNKNOWN (should be "FoodServiceDirect")
- **Items Extracted**: 1 product item (but details incorrect)
- **Total**: $47.24 (incorrect - should be $625.49)
- **Subtotal**: $2,551.95 (incorrect - should be $552.72)
- **Tax**: $0.00 (should be $5.53)

**PDF Content Analysis (Updated):**
- Actual Vendor: **FoodServiceDirect.com**
- Order #: 1003623097
- Order Date: Oct 8, 2025
- **Product**: Bridor Raw Butter Straight Croissant, 2.75 Ounce
- **SKU**: 21295818
- **Quantity**: 4 cases
- **Unit Size**: 160 per case (total: 640 units)
- **Price per Case**: $138.18
- **Total Price**: $552.72 (4 × $138.18)
- **Tax**: $5.53
- **Cold Pack Fee**: $20.00
- **Shipping & Handling**: $47.24
- **Grand Total**: $625.49

**UoM Structure:**
- Purchase UoM: "case" (pack)
- Purchase Quantity: 4
- Unit Size: 160 per case
- Unit UoM: "each"
- Total Units: 640 individual croissants

**Issues:**
- Vendor incorrectly detected as UNKNOWN
- Item extracted but details wrong:
  - Extracted: "Croissant" with Qty 1.0, Price $2.75
  - Should be: "Bridor Raw Butter Straight Croissant" with Qty 4 (cases), Price $138.18 per case
- Totals incorrect (extracted shipping as total)
- Unit size (160 per case) not extracted
- Multi-line product name not properly combined

**Action Required:**
1. Add vendor detection rule for "FoodServiceDirect"
2. Create table parsing rules for "Products SKU Qty Price Tax Subtotal" format
3. Handle multi-line product names ("Bridor Raw Butter Straight" + "Croissant")
4. Extract unit size from product description ("160 per case")
5. Set proper UoM: purchase_uom="case", unit_size=160, unit_uom="each"
6. Extract fees separately (Cold Pack Fee, Shipping)

---

### 4. `Pike Global Foods - 20251001.pdf`
- **Status**: ⚠️ Partially Working
- **Vendor Detected**: Restaurant Depot (incorrect - should be "Pike Global Foods")
- **Items Extracted**: 0 product items (4 items extracted but all are fees/subtotals)
- **Total**: $138.20
- **Subtotal**: $138.20
- **Tax**: $0.00

**PDF Content Analysis:**
- Actual Vendor: **Pike Global Foods**
- Invoice #: 49954
- Date: 1st Oct 2025
- Payment: Apple Pay ($34.55)
- Items extracted (but incorrectly classified):
  - Subtotal
  - Shipping
  - Taxes & Duties
  - Grand total

**Issues:**
- Vendor incorrectly detected as Restaurant Depot
- No actual product items extracted
- Only fees/subtotals extracted
- Invoice format may need special parsing

**Action Required:**
1. Add vendor detection rule for "Pike Global Foods"
2. Create invoice parsing rules
3. Extract actual product line items

---

### 5. `flooranddecor_20251021.pdf`
- **Status**: ❌ Failed
- **Vendor Detected**: Unknown
- **Items Extracted**: 0
- **Total**: $0.00
- **Issue**: PDF appears to be image-based (no text extracted)
- **Action Required**: 
  - Requires OCR processing
  - Or manual data entry
  - Vendor name: Floor & Decor (from filename)

---

## Recommendations

### Immediate Actions

1. **Add Vendor Detection Rules** for:
   - Duverger
   - FoodServiceDirect
   - Pike Global Foods
   - Floor & Decor (88 may be a code for this)

2. **Create Vendor-Specific Parsing Rules**:
   - Duverger: Simple product list format
   - FoodServiceDirect: Email-based order confirmation
   - Pike Global Foods: Invoice format
   - Floor & Decor: May need OCR first

3. **Handle Image-Based PDFs**:
   - `88_1009.pdf` and `flooranddecor_20251021.pdf` need OCR
   - Consider enabling OCR fallback for unknown vendors

### Long-term Solutions

1. **Improve Fee Detection**: Better logic to distinguish product items from fees/subtotals
2. **Email Format Support**: Handle order confirmation emails (FoodServiceDirect)
3. **Invoice Format Support**: Better parsing for invoice-style receipts (Pike Global Foods)
4. **OCR Integration**: Automatic OCR for image-based PDFs when text extraction fails

---

## Next Steps

1. ✅ **Test Complete** - All 5 files tested
2. ⏭️ **Await Instructions** - Ready to implement vendor detection rules and parsing improvements
3. 📝 **Consider**: 
   - Adding vendor detection patterns for new vendors
   - Creating vendor-specific YAML rules
   - Enabling OCR for image-based PDFs
   - Improving fee vs product item classification

