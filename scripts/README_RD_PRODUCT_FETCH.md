# Restaurant Depot Product Fetcher

This script fetches product information from Restaurant Depot's member website using UPC codes. It uses Chrome cookies for authentication.

## Features

- **Chrome Cookie Extraction**: Automatically extracts cookies from Chrome's cookie database
- **UPC-based Product Lookup**: Searches RD website by UPC code
- **Knowledge Base Integration**: Can update the knowledge base with fetched product information
- **Multiple URL Patterns**: Tries various URL patterns to find products

## Usage

### Basic Usage

```bash
# Fetch a single product by UPC
python scripts/rd_product_fetch.py <UPC>

# Example:
python scripts/rd_product_fetch.py 2370002749
```

### Update Knowledge Base

```bash
# Update knowledge base with multiple UPCs
python scripts/rd_product_fetch.py --update-kb <kb_file> <UPC1> <UPC2> ...

# Example:
python scripts/rd_product_fetch.py --update-kb data/step1_input/knowledge_base.json 2370002749 1234567890
```

## How It Works

1. **Cookie Extraction**: 
   - Looks for Chrome's cookie database in common locations:
     - `~/Library/Application Support/Google/Chrome/Default/Cookies`
     - `~/Library/Application Support/Google/Chrome/Profile 1/Cookies`
   - Extracts cookies for `member.restaurantdepot.com` domain
   - Creates a temporary copy of the database (Chrome locks the original)

2. **Product Search**:
   - Tries multiple URL patterns:
     - Search: `https://member.restaurantdepot.com/store/jetro-restaurant-depot/storefront/search?q={UPC}`
     - Direct product URLs (various patterns)
   - Uses extracted cookies for authentication
   - Parses HTML response to extract product information

3. **Product Information Extraction**:
   - Product name
   - Description
   - Size/UoM (e.g., "10 lb", "6/5 lb")
   - Unit price
   - Item number

## Requirements

- Python 3.7+
- Required packages:
  - `requests`
  - `beautifulsoup4`
  - `lxml` (for HTML parsing)

Install dependencies:
```bash
pip install requests beautifulsoup4 lxml
```

## Notes

- **Authentication**: You must be logged into Restaurant Depot's website in Chrome for the cookies to work
- **Rate Limiting**: Be respectful of RD's servers - don't make too many requests too quickly
- **HTML Structure**: The script tries multiple selectors to find product information, but RD's website structure may change
- **Search Results**: If a direct product page isn't found, the script will try to parse search results

## Integration with RD Processing

The RD CSV and PDF processors already use the knowledge base for product enrichment. To automatically fetch missing products:

1. Run the product fetcher for UPCs not in the knowledge base
2. Update the knowledge base with fetched products
3. Re-run Step 1 processing to use the updated knowledge base

## Troubleshooting

### No Cookies Found
- Make sure you're logged into Restaurant Depot's website in Chrome
- Check that Chrome's cookie database exists at the expected location
- Try logging out and back in to refresh cookies

### 403 Forbidden
- Your cookies may have expired - log in again in Chrome
- The website may have changed its authentication requirements

### Product Not Found
- Verify the UPC is correct
- The product may not be available on RD's website
- Try searching manually on the website to confirm the UPC works

### Wrong Product Information
- RD's website structure may have changed
- The HTML selectors may need to be updated
- Check the actual HTML structure of the product page

## Future Improvements

- Add support for batch fetching multiple UPCs
- Cache fetched products to avoid repeated requests
- Add support for other authentication methods
- Improve HTML parsing to handle dynamic content
- Add support for JavaScript-rendered content (Selenium)

