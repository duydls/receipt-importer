# PDF Test Analysis - Findings

## Summary

Examined 6 PDF files from `data/step1_input/pdf_test/`:

1. **Costco PDFs** (3 files): Text-based, already have layout rules
   - `Costco_0907.pdf`, `Costco_0916.pdf`, `Costco_0929.pdf`
   - Format: Item code + product name + price on same line or split across lines
   - Pattern: "E          3923 LIMES 3 LB. 6.49 N"
   - Status: ✅ Layout rules exist, but parser needs fixing to handle "E" prefix

2. **Jewel-Osco PDF** (1 file): Tabular structure
   - `Jewel-Osco_0903.pdf`
   - Format: Tabular with "Total Price" column
   - Pattern: "Signature Select Sugar Granulated 10 Lb $8.99"
   - Status: ⚠️ Needs better table extraction

3. **Aldi PDF** (1 file): Image-based (needs OCR)
   - `aldi_0905.pdf`
   - Status: ⚠️ Requires OCR processing

4. **Parktoshop PDF** (1 file): Image-based (needs OCR)
   - `parktoshop_0908.pdf`
   - Status: ⚠️ Requires OCR processing

## Costco PDF Structure

```
E          3923 LIMES 3 LB. 6.49 N
E          4032 WATERMELON 6.99 N
E          512515        8.99 N
           STRAWBRY
E          3   WHOLE MILK 13.74 N
E          506970 HEAVY CREAM 95.94 N
           ORG GRN
E          1059995       6.99 N
           GRPS
E          67072 ORANGES 10.99 N
           SUBTOTAL  150.13
           TAX       0.00
       **** TOTAL    150.13
```

### Issues Found

1. **Costco Parser**: Not matching product items correctly
   - Layout rule regex doesn't account for "E" prefix
   - Need to strip "E" prefix and normalize whitespace before matching
   - Current regex: `"^(\\d{1,10})\\s+(.+?)\\s+(\\d+\\.\\d{2})\\s*N?\\s*$"`
   - Should handle: `"E\\s+(\\d{1,10})\\s+(.+?)\\s+(\\d+\\.\\d{2})\\s*N?\\s*$"`

2. **Jewel-Osco PDF**: Table extraction needs improvement
   - Table structure detected but not properly parsed
   - Need to extract table with proper column boundaries

3. **Aldi/Parktoshop PDFs**: Need OCR support
   - Image-based PDFs require OCR (pytesseract, Pillow, PyMuPDF)
   - Can use RD PDF processor as reference (already has OCR support)

## Next Steps

1. ✅ Created `costco_pdf_processor.py` - needs regex pattern fixes
2. ⏳ Create `jewel_pdf_processor.py` - better table extraction
3. ⏳ Create `aldi_pdf_processor.py` - OCR-based extraction
4. ⏳ Create `parktoshop_pdf_processor.py` - OCR-based extraction
5. ⏳ Update `main.py` to route PDFs to appropriate processors

## References

- RD PDF Processor: `step1_extract/rd_pdf_processor.py` (has OCR support)
- Costco Layout Rules: `step1_rules/20_costco_layout.yaml` (has PDF multiline layout)
- Costco Parser: `step1_extract/legacy/costco_parser.py` (needs "E" prefix handling)

