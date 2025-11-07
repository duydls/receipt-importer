# Instacart Costco Product Fetcher

## Overview
This script fetches Costco product information from Instacart's storefront. However, Instacart uses JavaScript-rendered pages (SPA) and requires authentication, so direct HTTP requests may not work without proper cookies.

## Current Status
- ✅ URL format fixed: `/store/costco/s?k=<query>`
- ⚠️  Page is JavaScript-rendered (product cards not in initial HTML)
- ⚠️  Requires authentication cookies
- ✅ Knowledge base approach (from receipts) is more reliable

## Usage

### Option 1: Manual Cookie Copy (Recommended for Testing)

1. **Open Instacart Costco in Chrome:**
   - Go to: `https://www.instacart.com/store/costco/s?k=1362911`
   - Make sure you're logged in

2. **Copy Cookies from DevTools:**
   - Press `F12` to open DevTools
   - Go to **Network** tab
   - Refresh the page
   - Click on any request (e.g., the main page request)
   - In **Headers** → **Request Headers**, find the `Cookie:` header
   - Copy the entire cookie string (e.g., `session_id=...; csrf_token=...`)

3. **Use with script:**
   ```bash
   python scripts/instacart_costco_fetch.py \
     --actid 16dcd146-06b6-4982-a522-c80340467158 \
     --item 1362911 \
     --zip 60640 \
     --cookie "YOUR_COOKIE_STRING_HERE"
   ```

### Option 2: Use Chrome Cookies (If Not Encrypted)

```bash
python scripts/instacart_costco_fetch.py \
  --actid 16dcd146-06b6-4982-a522-c80340467158 \
  --item 1362911 \
  --zip 60640 \
  --use-chrome-cookies
```

**Note:** Chrome cookies are encrypted on macOS, so this may not work.

### Option 3: Use Knowledge Base (Most Reliable)

The knowledge base is automatically updated from actual Costco receipts:
- Prices are calculated from `total_price / quantity`
- More accurate than web scraping
- No authentication required

To update KB from receipts:
```bash
python - << 'PY'
import json
from pathlib import Path
# ... (see existing KB update logic in pdf_processor_unified.py)
PY
```

## Troubleshooting

### 404 Errors
- Check if Costco is available on Instacart in your area
- Verify the `actid` parameter is correct
- Try without `--zip` parameter

### No Products Found
- Page is JavaScript-rendered - product cards load via JS
- Need to use Selenium/Playwright for full rendering
- Or rely on knowledge base approach

### Cookie Issues
- Chrome cookies are encrypted on macOS
- Use manual copy method (Option 1)
- Or use browser extension to export cookies

## Future Improvements

1. **Selenium/Playwright Integration:**
   - Render page with JavaScript
   - Extract product data from rendered DOM
   - Handle authentication automatically

2. **Cookie Export Extension:**
   - Use Chrome extension to export cookies
   - Parse exported cookies file
   - Auto-inject into requests

3. **API Endpoint Discovery:**
   - Monitor network requests in DevTools
   - Find Instacart's internal API endpoints
   - Use API directly (if public)

## Current Recommendation

**Use the knowledge base approach** - it's more reliable and doesn't require authentication:
- Prices are from actual receipts
- Automatically updated during Step 1 processing
- No rate limiting or blocking issues

