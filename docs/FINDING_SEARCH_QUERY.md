# Finding the RD Search GraphQL Query

## Current Status

We found that:
1. ✅ Authentication works with GraphQL
2. ✅ Search is executed (found product ID `51264587` for UPC `76069502838`)
3. ✅ `UnifiedAdPlacement` query shows search results in `searchContext.organicProductIds`
4. ❌ Still need the actual search query operation name and hash

## What We Know

From the `UnifiedAdPlacement` query:
- **Endpoint**: `https://member.restaurantdepot.com/graphql`
- **Search found**: Product ID `51264587` for UPC `76069502838`
- **Search ID**: `1e39f4b2-892e-42f7-9324-1db73c2b66a5`
- **Required variables**:
  - `shopId: "59693"`
  - `postalCode: "60640"`
  - `zoneId: "974"`
  - `retailerInventorySessionToken`

## Next Steps

### Option 1: Browser DevTools (Recommended)
1. Open `member.restaurantdepot.com` in your browser
2. Open DevTools (F12) → Network tab
3. Filter by "graphql"
4. Search for UPC `76069502838`
5. Look for the GraphQL request that executes **before** `UnifiedAdPlacement`
6. Copy the `operationName` and `sha256Hash` from that request

### Option 2: Use Browser Console Script
Run the script from `find_rd_search_query.py`:
```bash
python scripts/find_rd_search_query.py --browser-script
```
Then paste the script in browser console and search for a UPC.

### Option 3: Check Network Tab Chronologically
1. Open Network tab
2. Search for UPC
3. Sort by time
4. Find the GraphQL request that happens right before `UnifiedAdPlacement`
5. That's likely the search query

## What to Look For

The search query should:
- Have `operationName` containing "search" or "product" or "item"
- Have `variables` containing the search query (UPC or text)
- Execute **before** `UnifiedAdPlacement`
- Return product IDs or product data

## Once Found

Share the curl command or the operation name and hash, and I'll integrate it into the script!

