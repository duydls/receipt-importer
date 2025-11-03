import sys, os, json, re
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    print("Installing pandas & openpyxl...")
    import subprocess, sys as _sys
    subprocess.check_call([_sys.executable, "-m", "pip", "install", "pandas", "openpyxl"])
    import pandas as pd

REQ = ["Item Description", "Extended Amount (USD)"]
ALIASES = {
    "Item Description": ["Item Description", "Description", "Item"],
    "Extended Amount (USD)": ["Extended Amount (USD)", "Extended Amount", "Amount (USD)", "Amount"],
    "QTY": ["QTY", "Qty", "Quantity", "QTY Ordered"],
    "Unit Price": ["Unit Price", "Price", "UnitPrice"],
    "UPC": ["UPC", "Barcode"],
    "Item Number": ["Item Number", "Item #", "Item No.", "Item#", "SKU"],
    "Transaction Date": ["Transaction Date", "Date", "Trans Date", "TransactionDate"],
}
SKIP = ["SUBTOTAL","TAX","TOTAL","BALANCE","ITEMS SOLD"]

def norm(s):
    if s is None: return ""
    s = str(s).replace("\u00A0"," ").strip()
    s = re.sub(r"\s+"," ", s)
    return s

def canon(h):
    h2 = norm(h)
    for k, vs in ALIASES.items():
        for v in vs:
            if h2.lower() == norm(v).lower():
                return k
    return None

def clean_num(x):
    if x is None or (isinstance(x,float) and pd.isna(x)): return None
    if isinstance(x,(int,float)): return float(x)
    s = str(x).strip().replace("$","").replace(",","")
    if re.fullmatch(r"\(.*\)", s): s = "-" + s[1:-1]
    try: return float(s)
    except: return None

def to_iso_date(x):
    if x is None or (isinstance(x,float) and pd.isna(x)): return None
    try:
        if isinstance(x, (int, float)):
            dt = pd.to_datetime(x, origin="1899-12-30", unit="d")
            return dt.strftime("%Y-%m-%d")
        dt = pd.to_datetime(str(x))
        return dt.strftime("%Y-%m-%d")
    except: return None

def find_header_row(df, top=30):
    best_row, best_score, best_hits = -1, -1, []
    for r in range(min(top, len(df))):
        row = [df.iat[r,c] for c in range(df.shape[1])]
        hits=set()
        for v in row:
            c = canon(v)
            if c: hits.add(c)
        score = sum(3 for h in hits if h in REQ) + sum(1 for h in hits if h in ALIASES and h not in REQ)
        if score > best_score:
            best_row, best_score, best_hits = r, score, sorted(list(hits))
    return best_row, best_score, best_hits

def read_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in [".xlsx",".xls"]:
        xls = pd.ExcelFile(path, engine="openpyxl")
        for name in xls.sheet_names:
            df = pd.read_excel(path, sheet_name=name, header=None, dtype=object, engine="openpyxl")
            yield name, df
    else:
        df = pd.read_csv(path, header=None, dtype=object, encoding="utf-8-sig")
        yield "CSV", df

def main(file):
    all_records=[]
    for sheet_name, df in read_any(file):
        print(f"\n=== Sheet: {sheet_name} ===")
        print("[peek top 5 rows (raw)]:")
        print(df.head(5).to_string(index=False, header=False))

        hr, score, hits = find_header_row(df)
        print(f"[header detection] row={hr}, score={score}, hits={hits}")
        if hr < 0 or score < 3*len(REQ):
            print("!! Header too weak here, skipping this sheet.")
            continue

        header_raw = [norm(df.iat[hr,c]) for c in range(df.shape[1])]
        header_map = [canon(h) for h in header_raw]
        print("[header raw]:", header_raw)
        print("[header mapped]:", header_map)

        for need in REQ:
            if need not in header_map:
                lowers = {h.lower():h for h in header_raw}
                if need.lower() in lowers:
                    print(f'>> Suggest: make header matching case-insensitive for "{need}"')
                else:
                    print(f'>> Suggest: add alias for "{need}" (seen headers: {header_raw})')

        data = df.iloc[hr+1:].copy()
        data.columns = header_map
        keep_cols = [c for c in data.columns if c]
        data = data[keep_cols]

        def row_skip(row):
            hay = " | ".join(str(row.get(k,"")).upper() for k in ["Item Description","Extended Amount (USD)","Extended Amount","Amount (USD)"])
            return any(k in hay for k in SKIP)

        out=[]
        for _, row in data.iterrows():
            if all(pd.isna(v) or str(v).strip()=="" for v in row.values):
                continue
            if row_skip(row):
                continue

            total = clean_num(row.get("Extended Amount (USD)")) or clean_num(row.get("Extended Amount")) or clean_num(row.get("Amount (USD)"))
            unit  = clean_num(row.get("Unit Price"))
            qty   = clean_num(row.get("QTY"))
            if qty is None and unit not in (None,0) and total not in (None,0):
                qty = round(total/unit, 3)
            if unit is None and qty not in (None,0) and total not in (None,0):
                unit = round(total/qty, 4)

            rec = {
                "product_name": row.get("Item Description"),
                "quantity": qty,
                "unit_price": unit,
                "total_price": total,
                "upc": row.get("UPC"),
                "item_number": row.get("Item Number"),
                "transaction_date": to_iso_date(row.get("Transaction Date")),
                "__sheet": sheet_name
            }
            if not rec["product_name"] and rec["total_price"] is None:
                continue
            out.append(rec)

        print(f"[parsed rows]: {len(out)}")
        if out:
            print("[sample 5]:")
            print(json.dumps(out[:5], ensure_ascii=False, indent=2))
        all_records.extend(out)

    if not all_records:
        print("\nNo detail rows parsed. Likely causes:")
        print("- Header text differs (check 'peek top 5 rows' and 'header raw').")
        print("- True header isn’t on the first visible row (script scans top rows but adjust if needed).")
        print("- Rows filtered by SKIP keywords; edit SKIP list.")
        sys.exit(2)
    else:
        print(f"\n✅ Done. Total rows: {len(all_records)}")
        out_path = os.path.splitext(file)[0] + ".rd_parsed.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_records, f, ensure_ascii=False, indent=2)
        print(f"Saved -> {out_path}")

if __name__ == "__main__":
    if len(sys.argv)<2:
        print("Usage: python rd_quick_try.py <RD.xlsx|RD.csv>")
        sys.exit(1)
    main(sys.argv[1])


