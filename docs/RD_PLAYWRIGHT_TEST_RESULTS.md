# RD Playwright Test Results

## Summary
We successfully installed Playwright and created a test script to fetch RD product data. However, the page requires authentication before executing search queries.

## Tools Installed
- ✅ **Playwright** (v1.48.0)
- ✅ **Chromium browser** (v130.0.6723.31)

## Test Results

### Test UPC: `76069502838`
- **URL**: `https://member.restaurantdepot.com/store/jetro-restaurant-depot/s?k=76069502838`
- **Status**: Page loads but requires login
- **Cookies**: 12 cookies found from browser
- **GraphQL Requests**: 9 GraphQL requests found, but none are search queries
- **Product Results**: 0 products found (page shows login required)

### GraphQL Operations Found
1. `LandingAppTrackingProperties`
2. `LandingCurrentUser`
3. `Geolocation`
4. `LandingAppDownloadBannerQuery`
5. `LocaleBasedNudgeVariantQuery`
6. `GeolocationFromIp`
7. `AuthenticateLayout`
8. `LoxCombineAddressStepsVariant`
9. `LandingFeatureVariant`

**Note**: No search/product query operations were found because the page redirects to login before executing the search.

## Issues Identified

### 1. Authentication Required
- The page shows "You need to log in to continue"
- Search queries are not executed until after login
- Cookies might be expired or invalid

### 2. Cookie Format
- Playwright requires specific cookie format
- Some cookies had type issues (secure field was number instead of boolean)
- Fixed by converting to boolean: `bool(cookie.secure)`

### 3. Search Query Not Triggered
- The search URL (`?k=76069502838`) is in the URL, but the search query is not executed
- This is because the page redirects to login first

## Next Steps

### Option 1: Fix Authentication
1. **Refresh cookies**: Log in to `member.restaurantdepot.com` in your browser
2. **Use storage state**: Save Playwright's storage state after logging in
3. **Manual login**: Use Playwright to automate the login process

### Option 2: Find Search Query Directly
1. **Monitor network in browser**: Open DevTools and search for a UPC
2. **Find the GraphQL query**: Look for operations like `SearchProducts`, `SearchItems`, etc.
3. **Call GraphQL directly**: Use the found query with proper authentication

### Option 3: Use Existing Script
1. **Enhance `rd_member_upc_client.py`**: Add Playwright support as fallback
2. **Hybrid approach**: Try requests first, fall back to Playwright if needed
3. **Better error handling**: Detect login requirements and handle gracefully

## Files Created
- `scripts/test_rd_playwright.py` - Test script using Playwright
- `/tmp/rd_search_76069502838.html` - Saved HTML
- `/tmp/rd_search_76069502838.png` - Screenshot
- `/tmp/all_requests_76069502838.json` - All network requests
- `/tmp/all_responses_76069502838.json` - All network responses
- `/tmp/graphql_response_76069502838_*.json` - GraphQL responses

## Recommendations

1. **Immediate**: Log in to `member.restaurantdepot.com` in your browser to refresh cookies
2. **Short-term**: Use browser DevTools to find the search GraphQL query
3. **Long-term**: Integrate Playwright into `rd_member_upc_client.py` as an option

## Code Improvements Made

1. ✅ Fixed cookie format for Playwright
2. ✅ Added network request monitoring
3. ✅ Added GraphQL response capture
4. ✅ Added error handling for cookie addition
5. ✅ Added screenshot and HTML saving for debugging

