# Restaurant Depot (RD) Abbreviations Strategy

## **Problem Statement**

Restaurant Depot uses **heavy abbreviations** in product names:
- `CHX NUGGET BTRD TY 10LB` = Chicken Nugget Battered Tyson 10 LB
- `OIL SHRT CRM LQ SR B` = Oil Shortening Cream Liquid (Brand: SR B)
- `FF BIGC 1/2 CRINKL 6/5LB` = French Fries Big Cut 1/2" Crinkle 6 bags × 5 LB
- `CHIX BREAST BNLS SKLS` = Chicken Breast Boneless Skinless

## **Our Two-Tier Solution**

### **Tier 1: YAML Rules (Category Classification) ✅ IMPLEMENTED**

**Purpose:** Fast pattern-based classification for Step 1

**What's in YAML:**
- **Prefix patterns** (CHX=Chicken, FF=Fries, FZ=Frozen, OIL=Oil)
- **Product type keywords** (NUGGET, BREAST, CRINKL, TWISTER)
- **Descriptors** (BNLS=Boneless, SKLS=Skinless, BTRD=Battered)
- **Classification rules** → Map patterns to L2 categories

**Benefits:**
- ✅ Fast (regex matching)
- ✅ No external dependency
- ✅ Editable without code changes
- ✅ Good enough for accounting categorization

**Current Coverage:**
```yaml
# Protein patterns
CHX|CHIX → C14 Meat & Seafood
NUGGET|BREAST|WING → C14 Meat & Seafood

# Frozen potato products
FF|CRINKL|TWISTER → C13 Frozen Vegetables

# Oils
OIL|SHRT → C15 Other Ingredients

# UoM patterns
6/5LB → Extract as "6/5LB" (6 cases × 5 lb)
```

**Limitations:**
- ❌ Can't expand "CHX" → "Chicken" in product name
- ❌ Can't identify brands (TY → Tyson)
- ❌ Can't normalize for better search/ordering
- ❌ Can't provide product specs for Step 2/3

---

### **Tier 2: Knowledge Base (Product Expansion) 📋 RECOMMENDED**

**Purpose:** Full product details for ordering and inventory

**What should be in KB:**
```json
{
  "sku": "CHX-NUGGET-BTRD-TY-10LB",
  "rd_code": "CHX NUGGET BTRD TY 10LB",
  "full_name": "Tyson Chicken Nuggets Battered",
  "brand": "Tyson",
  "category": "Frozen Chicken",
  "pack_size": "1 case",
  "unit_size": "10 lb",
  "case_quantity": 1,
  "odoo_product_id": 12345,
  "vendor_code": "RD",
  "search_terms": ["chicken", "nugget", "tyson", "battered", "frozen"]
}
```

**Benefits:**
- ✅ Full product name for display
- ✅ Brand identification
- ✅ Correct pack/case quantities
- ✅ Links to Odoo products
- ✅ Better search and reporting
- ✅ Supports Step 2 (Odoo matching)

**How it works with YAML:**
```
Step 1: YAML classification
  "CHX NUGGET BTRD TY 10LB" → C14 Meat & Seafood

Step 2: KB enrichment (optional)
  KB lookup → {
    full_name: "Tyson Chicken Nuggets Battered",
    brand: "Tyson",
    normalized_uom: "10-lb"
  }

Step 3: Output
  {
    "product_name": "CHX NUGGET BTRD TY 10LB",
    "display_name": "Tyson Chicken Nuggets Battered",  // From KB
    "l2_category": "C14",
    "l2_category_name": "Meat & Seafood",
    "brand": "Tyson",  // From KB
    "raw_size_text": "10LB",
    "normalized_uom": "10-lb"  // From KB
  }
```

---

## **Implementation Phases**

### **Phase 1: YAML Patterns ✅ COMPLETE**

**Status:** ✅ Implemented in commit `15f2ef5`

**Files Updated:**
- `step1_rules/59_category_keywords.yaml` - RD abbreviation patterns
- `step1_rules/30_uom_extraction.yaml` - Multi-pack UoM (6/5LB)

**Results:**
- All RD items now correctly classified (80% confidence)
- UoM extraction working for case quantities
- 41 RD items processed successfully

---

### **Phase 2: Knowledge Base Enrichment (FUTURE)**

**When to implement:**
- When you need **better product names** for reports
- When you need **brand tracking** for vendor management
- When you need **accurate pack/case specs** for ordering
- When you need **Odoo product linking** in Step 2/3

**How to implement:**

**Option A: CSV Knowledge Base** (Simple)
```csv
rd_code,full_name,brand,category,pack_format,odoo_product_id
"CHX NUGGET BTRD TY 10LB","Tyson Chicken Nuggets Battered","Tyson","Frozen Chicken","1x10lb",12345
"FF BIGC 1/2 CRINKL 6/5LB","Big Cut Crinkle Fries 1/2 Inch","Generic","Frozen Potatoes","6x5lb",12346
```

**Option B: Database Table** (Scalable)
```sql
CREATE TABLE rd_products (
  rd_code VARCHAR(100) PRIMARY KEY,
  full_name VARCHAR(255),
  brand VARCHAR(100),
  category VARCHAR(100),
  pack_quantity INT,
  unit_size VARCHAR(50),
  odoo_product_id INT,
  search_terms TEXT[]
);
```

**Integration Point:**
In `step1_extract/vendor_profiles.py`, add RD product lookup:
```python
def enrich_rd_product(item):
    rd_code = item['product_name']
    kb_product = lookup_rd_product(rd_code)
    if kb_product:
        item['display_name'] = kb_product['full_name']
        item['brand'] = kb_product['brand']
        item['kb_pack_format'] = kb_product['pack_format']
        # ... other enrichments
```

---

## **Comparison: YAML vs Knowledge Base**

| Feature | YAML Rules | Knowledge Base |
|---------|-----------|----------------|
| **Category Classification** | ✅ Excellent | ✅ Excellent |
| **Speed** | ✅ Very Fast | ⚠️ DB lookup needed |
| **Full Product Name** | ❌ No | ✅ Yes |
| **Brand Identification** | ❌ No | ✅ Yes |
| **Pack/Case Specs** | ⚠️ Basic (UoM only) | ✅ Detailed |
| **Odoo Linking** | ❌ No | ✅ Yes |
| **Maintenance** | ✅ Edit YAML | ⚠️ Update DB/CSV |
| **Setup Effort** | ✅ Done | ⚠️ Need to build |

---

## **Recommendation**

### **For Now (Phase 1):** ✅
Use **YAML patterns only** - they work great for:
- Category classification (accounting)
- UoM extraction
- Basic reporting
- Step 1 completion

### **For Future (Phase 2):** 📋
Add **Knowledge Base** when you need:
- Better product names in reports
- Brand-level analysis
- Precise ordering specs
- Odoo product matching in Step 2/3

---

## **Testing Results**

### **Before YAML Patterns:**
```
CHX NUGGET BTRD TY 10LB     → C99 Unknown (20%)
OIL SHRT CRM LQ SR B        → C99 Unknown (20%)
FF BIGC 1/2 CRINKL 6/5LB    → C99 Unknown (20%)
CHIX BREAST BNLS SKLS       → C99 Unknown (20%)
```

### **After YAML Patterns:** ✅
```
CHX NUGGET BTRD TY 10LB     → C14 Meat & Seafood (80%)
OIL SHRT CRM LQ SR B        → C15 Other Ingredients (80%)
FF BIGC 1/2 CRINKL 6/5LB    → C13 Frozen Vegetables (80%), UoM: 6/5LB
FF ZESTY TWISTER 20LB       → C13 Frozen Vegetables (80%)
CHIX BREAST BNLS SKLS       → C14 Meat & Seafood (80%)
```

---

## **Next Steps**

1. ✅ **Phase 1 Complete:** YAML classification working
2. 📊 **Monitor:** Review RD classification accuracy over time
3. 📋 **Decide:** Do you need full product names and brand tracking?
4. 🔨 **If yes:** Build knowledge base (CSV or DB)
5. 🔗 **If yes:** Integrate KB lookup in Step 1 enrichment

---

## **Questions to Consider**

**Do you need to:**
- Show "Tyson Chicken Nuggets" instead of "CHX NUGGET BTRD TY" in reports? → **KB needed**
- Track spending by brand (Tyson vs Generic)? → **KB needed**
- Link RD products to Odoo for auto-ordering? → **KB needed**
- Just categorize for accounting? → **YAML is enough** ✅

Let me know which direction makes sense for your business needs!

