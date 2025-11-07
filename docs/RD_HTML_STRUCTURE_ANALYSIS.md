# Restaurant Depot HTML Structure Analysis

## Overview
The Restaurant Depot member site (`member.restaurantdepot.com`) is an **Instacart-powered** JavaScript-rendered application that uses GraphQL for data fetching.

## Key Findings

### 1. Site Architecture
- **Framework**: React/Vue (JavaScript-rendered)
- **API**: GraphQL at `internal-api.icprivate.com/graphql`
- **Authentication**: Cookie-based (requires login)
- **Search URL Pattern**: `https://member.restaurantdepot.com/store/jetro-restaurant-depot/s?k={upc}`

### 2. HTML Structure
- **Root Elements**: 
  - `#store-wrapper`
  - `#js-app`
- **Content Loading**: Dynamically via JavaScript (not in initial HTML)
- **Script Tags**: 115 script tags found
- **Data Attributes**: 8 unique data attributes found:
  - `data-bypass`
  - `data-dialog`
  - `data-dialog-ref`
  - `data-emotion`
  - `data-has-button`
  - `data-id`
  - `data-sha`
  - `data-testid`

### 3. GraphQL API
- **Endpoint**: `https://internal-api.icprivate.com/graphql`
- **Query Format**: Uses persisted queries with SHA256 hashes
- **Example Operations Found**:
  - `GetRetailerBySlug`
  - `ShopCollection`
  - `DepartmentNavCollections`
  - `StorefrontLayoutsData`
  - `ItemViewLayout`
  - And many more...

### 4. Authentication
- **Method**: Cookie-based authentication
- **Cookies Found**: 12 cookies for `member.restaurantdepot.com`
  - `__stripe_mid`
  - `__stripe_sid`
  - `aws-waf-token`
  - `X-IC-bcx`
  - `__Host-instacart_sid`
  - And others...

### 5. Search Functionality
- **Current Status**: The search URL returns a page, but product results are loaded dynamically
- **Issue**: BeautifulSoup cannot see dynamically loaded content
- **Solution Options**:
  1. Use Selenium/Playwright to wait for JavaScript execution
  2. Find and call the GraphQL search query directly
  3. Monitor network requests in browser DevTools to find the search API endpoint

### 6. Page Content
- **HTML Size**: ~427KB
- **Login Requirement**: Page shows "You need to log in to continue" if not authenticated
- **Product Listings**: Not visible in static HTML (loaded via JavaScript)

## Recommendations

### For `rd_member_upc_client.py`:
1. **Current Approach**: The script correctly fetches cookies and makes requests, but returns empty results because:
   - Content is JavaScript-rendered
   - Product data is loaded dynamically via GraphQL

2. **Potential Solutions**:
   - **Option A**: Use Selenium/Playwright to wait for JavaScript execution
     ```python
     from selenium import webdriver
     from selenium.webdriver.common.by import By
     from selenium.webdriver.support.ui import WebDriverWait
     from selenium.webdriver.support import expected_conditions as EC
     ```
   
   - **Option B**: Find the GraphQL search query and call it directly
     - Monitor network requests in browser DevTools
     - Look for GraphQL queries with operation names like `SearchProducts`, `SearchItems`, or similar
     - Call the GraphQL endpoint with proper authentication
   
   - **Option C**: Use the Instacart API directly (if available)
     - May require reverse engineering the API structure
     - May violate terms of service

3. **Next Steps**:
   - Open browser DevTools and monitor network requests when searching for a UPC
   - Identify the GraphQL query used for search
   - Update `rd_member_upc_client.py` to call the GraphQL endpoint directly
   - Or integrate Selenium/Playwright for full JavaScript rendering

## Test Results

### Test UPC: `76069502838`
- **URL**: `https://member.restaurantdepot.com/store/jetro-restaurant-depot/s?k=76069502838`
- **Status**: 200 OK
- **Cookies**: 12 cookies found and sent
- **Results**: Empty array returned
- **Reason**: Content is JavaScript-rendered, not in static HTML

## Files
- **Saved HTML**: `/tmp/rd_search_page.html` (427KB)
- **Analysis Date**: 2025-01-07

