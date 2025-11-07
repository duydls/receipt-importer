# Instacart Store IDs

This document lists the correct store IDs for different vendors in Instacart.

## Store IDs

### Costco
- **Shop ID**: `83`
- **URL**: `https://www.instacart.com/store/costco`
- **GraphQL Endpoint**: `https://www.instacart.com/graphql`
- **Used in**: 
  - `instacart_costco_search.py` (default: `83`)
  - `enrich_costco_products.py` (default: `83`)

### Restaurant Depot (RD)
- **Shop ID**: `523`
- **URL**: `https://www.instacart.com/store/restaurant-depot`
- **GraphQL Endpoint**: `https://www.instacart.com/graphql`
- **Used in**: 
  - `instacart_rd_search.py` (default: `523`)
  - `enrich_rd_products.py` (default: `523`)

## Notes

- **Costco and RD have different store IDs in Instacart**
- The shop ID is required for GraphQL queries to work correctly
- Using the wrong shop ID will return incorrect or no results
- The shop ID is passed in the `shopId` field of the GraphQL query variables

## Example GraphQL Query

### Costco
```json
{
  "query": "3923",
  "shopId": "83",
  "postalCode": "60601",
  "zoneId": "974",
  ...
}
```

### Restaurant Depot
```json
{
  "query": "2370002749",
  "shopId": "523",
  "postalCode": "60601",
  "zoneId": "974",
  ...
}
```

## Important

- For Costco searches, always use `shopId: "83"`
- For RD searches, always use `shopId: "523"`
- These are different from the member site IDs (e.g., RD member site uses `59693`)
