# RD Member UPC Client Enhancements

## Summary
Enhanced `rd_member_upc_client.py` with Playwright support for JavaScript-rendered content.

## Changes Made

### 1. Added Playwright Support
- **Optional dependency**: Playwright is now an optional dependency
- **Fallback mechanism**: If static HTML parsing returns no results, Playwright is used as a fallback
- **Command-line option**: Added `--use-playwright` flag to enable Playwright mode

### 2. Enhanced Functionality
- **JavaScript rendering**: Playwright waits for JavaScript to execute and render content
- **Network monitoring**: Monitors GraphQL requests for search queries
- **Product extraction**: Extracts product data from dynamically rendered content
- **Cookie handling**: Properly formats cookies for Playwright

### 3. Code Structure
- **Async function**: `fetch_by_upc_playwright()` for Playwright-based fetching
- **Modified main function**: `fetch_by_upc()` now accepts `use_playwright` parameter
- **Error handling**: Gracefully falls back to regular parsing if Playwright fails

## Usage

### Basic Usage (Static HTML)
```bash
python scripts/rd_member_upc_client.py 76069502838 --auto-cookie --json-fields --pretty
```

### With Playwright (JavaScript-rendered content)
```bash
python scripts/rd_member_upc_client.py 76069502838 --auto-cookie --use-playwright --json-fields --pretty
```

## Current Status

### ✅ Completed
1. ✅ Installed Playwright and Chromium browser
2. ✅ Created test script (`test_rd_playwright.py`) to analyze page structure
3. ✅ Enhanced `rd_member_upc_client.py` with Playwright support
4. ✅ Fixed cookie format for Playwright
5. ✅ Added network monitoring for GraphQL requests
6. ✅ Documented HTML structure and findings

### ⚠️ Known Issues
1. **Authentication Required**: Page shows "You need to log in to continue"
   - **Solution**: Log in to `member.restaurantdepot.com` in your browser to refresh cookies
   
2. **Search Query Not Found**: No GraphQL search query is executed because page redirects to login first
   - **Solution**: Need to authenticate first, then search query will execute

3. **Empty Results**: Script returns empty results because authentication is required
   - **Solution**: Once authenticated, the script should work

## Next Steps

### Immediate
1. **Refresh Cookies**: 
   - Log in to `member.restaurantdepot.com` in your browser
   - Make sure you stay logged in
   - Run the script again

2. **Test with Valid Session**:
   ```bash
   python scripts/rd_member_upc_client.py 76069502838 --auto-cookie --use-playwright --json-fields --pretty
   ```

### Future Enhancements
1. **GraphQL API Direct Access**: 
   - Find the search GraphQL query by monitoring network requests in browser DevTools
   - Call the GraphQL API directly with proper authentication
   - This would be faster than using Playwright

2. **Storage State Persistence**:
   - Save Playwright's storage state after logging in
   - Reuse storage state for subsequent requests
   - This would avoid needing to log in each time

3. **Better Error Messages**:
   - Detect authentication failures
   - Provide clear error messages
   - Suggest solutions

## Files Created/Modified

### Created
- `scripts/test_rd_playwright.py` - Test script for Playwright analysis
- `docs/RD_HTML_STRUCTURE_ANALYSIS.md` - HTML structure analysis
- `docs/RD_PLAYWRIGHT_TEST_RESULTS.md` - Playwright test results
- `docs/RD_SCRIPT_ENHANCEMENTS.md` - This file

### Modified
- `scripts/rd_member_upc_client.py` - Enhanced with Playwright support

## Testing

### Test Command
```bash
# Test with Playwright
python scripts/rd_member_upc_client.py 76069502838 --auto-cookie --use-playwright --json-fields --pretty

# Test without Playwright (fallback)
python scripts/rd_member_upc_client.py 76069502838 --auto-cookie --json-fields --pretty
```

### Expected Behavior
- **With valid cookies**: Should return product data
- **Without valid cookies**: Returns empty array (authentication required)
- **With Playwright**: Waits for JavaScript execution and extracts product data
- **Without Playwright**: Uses static HTML parsing (faster but may miss dynamic content)

## Dependencies

### Required
- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing
- `browser-cookie3` - Cookie extraction

### Optional
- `playwright` - JavaScript rendering (install with `pip install playwright && playwright install chromium`)

## Notes

1. **Authentication**: The script requires valid cookies from a logged-in browser session
2. **JavaScript Rendering**: Playwright is needed for JavaScript-rendered content
3. **Performance**: Playwright is slower than static HTML parsing but necessary for dynamic content
4. **Error Handling**: Script gracefully falls back to regular parsing if Playwright fails

