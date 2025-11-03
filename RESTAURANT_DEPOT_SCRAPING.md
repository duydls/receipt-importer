# Restaurant Depot Website Scraping

## Current Status

The Restaurant Depot website (`https://www.restaurantdepot.com`) **requires authentication/login** to access product pages. Direct scraping attempts result in **403 Forbidden** errors.

## Authentication Required

The Restaurant Depot website uses authentication and bot protection, which means:

1. **Product pages require login**: Without proper authentication, all requests to product URLs return 403 Forbidden
2. **No public API available**: Restaurant Depot does not provide a public API for product information
3. **Cache-based approach recommended**: Use the `rd_item_map.csv` cache file to store and retrieve product information

## Current Implementation

The scraper (`step1_extract/vendor_profiles.py`) is configured to:

1. **Check cache first**: Loads existing product data from `step1_rules/rd_item_map.csv`
2. **Attempt web scraping**: Tries to fetch product pages (will fail with 403 errors)
3. **Handle gracefully**: Logs authentication requirement and returns `None` when scraping fails

## Alternative Approaches

### Option 1: Use Existing Cache (Recommended)
- Manually populate `step1_rules/rd_item_map.csv` with product information
- System will automatically use cached data for UoM and size information

### Option 2: Manual Data Entry
- For new items, manually add them to the cache file with size and UoM information
- Format: `item_number,product_name,size,uom,unit_price,url`

### Option 3: Future Authentication Support (If Needed)
If authentication becomes necessary, the scraper could be enhanced with:
- Session-based login (requires Restaurant Depot credentials)
- Cookie-based authentication
- API key support (if Restaurant Depot provides one)

## Cache File Format

The `rd_item_map.csv` file uses the following format:

```csv
item_number,product_name,size,uom,unit_price,url
980356,Chicken Nuggets,10 lb bag,LB,12.99,https://www.restaurantdepot.com/product/980356
```

## Testing

To test Restaurant Depot scraping:

```python
from step1_extract.vendor_profiles import VendorProfileHandler
from step1_extract.rule_loader import RuleLoader
from pathlib import Path

rules_dir = Path('step1_rules')
rule_loader = RuleLoader(rules_dir)
rules = rule_loader.load_all_rules()

handler = VendorProfileHandler(rules.get('vendor_profiles', {}), rules_dir)

# This will fail with 403 Forbidden (authentication required)
result = handler._scrape_rd_page(
    'https://www.restaurantdepot.com/product/980356',
    rules.get('vendor_profiles', {}).get('restaurant_depot', {})
)
```

## Recommendation

**Use the cache file (`rd_item_map.csv`)** to store Restaurant Depot product information. The system will automatically:
- Load cached data for known items
- Use cached UoM and size information
- Skip web scraping (which would fail anyway)

For new items, manually add them to the cache file with the correct size and UoM information.

