#!/usr/bin/env python3
"""
Vendor Matcher - Match extracted vendor names to database vendors
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional, List
from difflib import SequenceMatcher

try:
    from step3_mapping.query_database import connect_to_database
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

logger = logging.getLogger(__name__)


class VendorMatcher:
    """Match vendor names to database vendors"""
    
    def __init__(self, config=None, rule_loader=None):
        """
        Initialize vendor matcher
        
        Args:
            config: Optional configuration dict
            rule_loader: Optional RuleLoader instance to load vendor alias rules
        """
        self.config = config or {}
        self.database_vendors = {}  # name -> {id, supplier_rank}
        self.vendor_cache_file = Path('data/step1_output/database_vendors.json')
        # In step 1, we don't check database - only use cache if available
        self.skip_database = config.get('skip_database_check', True)
        self.rule_loader = rule_loader
        self._load_vendors()
        
        # Load vendor alias rules if rule_loader is available
        self.vendor_aliases = []
        if self.rule_loader:
            try:
                self.vendor_aliases = self.rule_loader.get_vendor_alias_rules()
                logger.debug(f"Loaded {len(self.vendor_aliases)} vendor alias rules")
            except Exception as e:
                logger.warning(f"Could not load vendor alias rules: {e}")
                self.vendor_aliases = []
    
    def _load_vendors(self):
        """Load vendors from database or cache"""
        # Try to load from cache first
        if self.vendor_cache_file.exists():
            try:
                with open(self.vendor_cache_file, 'r') as f:
                    self.database_vendors = json.load(f)
                logger.info(f"Loaded {len(self.database_vendors)} vendors from cache")
            except Exception as e:
                logger.warning(f"Could not load vendor cache: {e}")
        
        # Load from database if available and cache is stale or empty (unless skipped)
        if not self.skip_database and DB_AVAILABLE and (not self.database_vendors or self.config.get('refresh_vendors', False)):
            self._load_vendors_from_db()
    
    def _load_vendors_from_db(self):
        """Load vendors from database"""
        if self.skip_database:
            logger.debug("Database check skipped (step 1 mode)")
            return
        
        if not DB_AVAILABLE:
            logger.debug("Database not available, using cache only")
            return
        
        try:
            conn = connect_to_database()
            if not conn:
                logger.debug("Could not connect to database for vendor list")
                return
            
            from psycopg2.extras import RealDictCursor
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get all vendors (suppliers) from res_partner
                # Include IC- prefixed vendors and companies
                query = '''
                SELECT id, name, supplier_rank
                FROM res_partner
                WHERE is_company = true 
                   OR supplier_rank > 0 
                   OR name LIKE 'IC-%'
                ORDER BY name
                '''
                cur.execute(query)
                vendors = cur.fetchall()
                
                self.database_vendors = {}
                for vendor in vendors:
                    vendor_name = vendor['name'].strip()
                    self.database_vendors[vendor_name] = {
                        'id': vendor['id'],
                        'supplier_rank': vendor.get('supplier_rank', 0)
                    }
                
                logger.info(f"Loaded {len(self.database_vendors)} vendors from database")
                
                # Save to cache
                self.vendor_cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.vendor_cache_file, 'w') as f:
                    json.dump(self.database_vendors, f, indent=2)
                logger.info(f"Saved vendor list to cache: {self.vendor_cache_file}")
            
            conn.close()
        except Exception as e:
            logger.error(f"Error loading vendors from database: {e}")
    
    def extract_vendor_from_filename(self, filename: str) -> Optional[str]:
        """Extract vendor name from filename
        
        Args:
            filename: PDF filename (e.g., "Costco_0907.pdf", "Jewel-Osco_0903.pdf", "0915_marianos .pdf")
            
        Returns:
            Extracted vendor name or None
        """
        # Remove extension and clean
        base = Path(filename).stem.strip()
        
        # Common vendor name patterns from filenames
        # Examples: 
        # - "Costco_0907" -> "Costco"
        # - "Jewel-Osco_0903" -> "Jewel-Osco"
        # - "parktoshop_0908" -> "Park to Shop"
        # - "RD_0902" -> "RD"
        # - "0915_marianos " -> "Mariano's"
        # - "aldi_0905" -> "ALDI"
        
        # Pattern 1: Name before underscore or dash, followed by date/numbers
        # Match: "Costco_0907", "Jewel-Osco_0903", "parktoshop_0908", "RD_0902"
        match = re.match(r'^([A-Za-z][A-Za-z\s\-]+?)[_-]\d', base)
        if match:
            vendor_name = match.group(1).strip()
            # Normalize separators
            vendor_name = vendor_name.replace('_', ' ').replace('-', ' ')
            # Clean up common variations
            vendor_name = self._normalize_vendor_name(vendor_name)
            return vendor_name
        
        # Pattern 2: Date/number prefix, then vendor name
        # Match: "0915_marianos " -> "Mariano's"
        match = re.match(r'^\d+[_-](.+)', base)
        if match:
            vendor_name = match.group(1).strip()
            vendor_name = vendor_name.replace('_', ' ').replace('-', ' ')
            vendor_name = self._normalize_vendor_name(vendor_name)
            return vendor_name
        
        # Pattern 3: Just name (if no separator with numbers)
        # Match: "aldi" (but not "Costco_0907")
        if not re.search(r'[_-]\d', base):
            # Check if it's all caps or mixed case abbreviation
            if base.isupper() or (len(base) <= 5 and base.isupper()):
                return base
            # Normalize and capitalize
            vendor_name = base.replace('_', ' ').replace('-', ' ')
            vendor_name = self._normalize_vendor_name(vendor_name)
            return vendor_name
        
        return None
    
    def _normalize_vendor_name(self, name: str) -> str:
        """Normalize vendor name variations"""
        name = name.strip()
        
        # Common name normalizations
        name_lower = name.lower()
        
        # Fix common misspellings/variations
        if 'marianos' in name_lower or 'mariano' in name_lower:
            return "Mariano's"
        elif 'parktoshop' in name_lower or 'park to shop' in name_lower:
            return "Park to Shop"
        elif name_lower in ['rd', 'r d', 'restaurant depot', 'restaurantdept']:
            return "Restaurant Depot"  # RD is Restaurant Depot
        elif 'aldi' in name_lower:
            return "ALDI"
        elif 'costco' in name_lower:
            return "Costco"
        elif 'jewel' in name_lower and 'osco' in name_lower:
            return "Jewel-Osco"
        
        # Capitalize properly (title case)
        words = name.split()
        normalized = []
        for word in words:
            if word.isupper() and len(word) > 3:
                # Keep acronyms as-is (like ALDI)
                normalized.append(word)
            else:
                # Title case (first letter capital, rest lower)
                normalized.append(word.capitalize())
        
        return ' '.join(normalized)
    
    def _normalize_vendor_with_aliases(self, vendor_name: str) -> Optional[Dict[str, str]]:
        """
        Normalize vendor name using alias rules from 15_vendor_aliases.yaml
        
        Args:
            vendor_name: Vendor name to normalize
            
        Returns:
            Dict with 'normalized_vendor_name' and 'vendor_code' if alias matched, None otherwise
        """
        if not vendor_name or not self.vendor_aliases:
            return None
        
        vendor_name_lower = vendor_name.lower().strip()
        
        # Try to match against alias rules
        for alias_rule in self.vendor_aliases:
            match_list = alias_rule.get('match', [])
            if not match_list:
                continue
            
            for match_pattern in match_list:
                # Handle wildcard patterns (e.g., "IC-*")
                if match_pattern.endswith('*'):
                    prefix = match_pattern[:-1].lower()
                    if vendor_name_lower.startswith(prefix):
                        set_values = alias_rule.get('set', {})
                        normalized_name = set_values.get('normalized_name', vendor_name)
                        vendor_code = set_values.get('vendor_code', '')
                        logger.debug(f"Vendor alias matched (wildcard): '{vendor_name}' -> '{normalized_name}' (rule: {match_pattern})")
                        return {
                            'normalized_vendor_name': normalized_name,
                            'vendor_code': vendor_code,
                            'normalized_by': 'rule:15_vendor_aliases'
                        }
                elif vendor_name_lower == match_pattern.lower():
                    set_values = alias_rule.get('set', {})
                    normalized_name = set_values.get('normalized_name', vendor_name)
                    vendor_code = set_values.get('vendor_code', '')
                    logger.debug(f"Vendor alias matched: '{vendor_name}' -> '{normalized_name}' (rule: {match_pattern})")
                    return {
                        'normalized_vendor_name': normalized_name,
                        'vendor_code': vendor_code,
                        'normalized_by': 'rule:15_vendor_aliases'
                    }
        
        return None
    
    def match_vendor(self, vendor_name: Optional[str], store_name: Optional[str] = None, return_normalization_info: bool = False) -> Optional[str]:
        """
        Match vendor name to database vendor
        
        Args:
            vendor_name: Vendor name from receipt/filename
            store_name: Store name (for Instacart orders)
            return_normalization_info: If True, return dict with normalization info instead of just name
            
        Returns:
            Matched database vendor name, or dict with normalization info if return_normalization_info=True,
            or None if skip_database and no alias matched
        """
        if not vendor_name:
            return None
        
        vendor_name = vendor_name.strip()
        original_vendor_name = vendor_name
        
        # First, try to normalize using vendor alias rules
        alias_result = self._normalize_vendor_with_aliases(vendor_name)
        if alias_result:
            normalized_name = alias_result['normalized_vendor_name']
            normalized_by = alias_result['normalized_by']
            
            # If return_normalization_info is requested, return full info
            if return_normalization_info:
                return {
                    'normalized_vendor_name': normalized_name,
                    'vendor_code': alias_result.get('vendor_code', ''),
                    'normalized_by': normalized_by,
                    'original_vendor_name': original_vendor_name
                }
            
            # In step 1, return normalized name without database matching
            if self.skip_database:
                return normalized_name
            
            # Use normalized name for database matching
            vendor_name = normalized_name
        
        # In step 1, just return the vendor name without database matching (if no alias matched)
        if self.skip_database:
            if return_normalization_info:
                return {
                    'normalized_vendor_name': vendor_name,
                    'normalized_by': 'none',
                    'original_vendor_name': original_vendor_name
                }
            return vendor_name
        
        # First, try exact match
        if vendor_name in self.database_vendors:
            if return_normalization_info:
                return {
                    'normalized_vendor_name': vendor_name,
                    'normalized_by': 'db',
                    'original_vendor_name': original_vendor_name
                }
            return vendor_name
        
        # Try case-insensitive match
        for db_vendor in self.database_vendors.keys():
            if db_vendor.lower() == vendor_name.lower():
                if return_normalization_info:
                    return {
                        'normalized_vendor_name': db_vendor,
                        'normalized_by': 'db',
                        'original_vendor_name': original_vendor_name
                    }
                return db_vendor
        
        # Try fuzzy matching with improved logic
        best_match = None
        best_score = 0.0
        
        vendor_name_lower = vendor_name.lower().strip()
        
        for db_vendor in self.database_vendors.keys():
            db_vendor_lower = db_vendor.lower().strip()
            
            # Calculate similarity score
            score = SequenceMatcher(None, vendor_name_lower, db_vendor_lower).ratio()
            
            # Also check for partial matches (e.g., "Costco" matches "IC-Costco Business")
            if vendor_name_lower in db_vendor_lower or db_vendor_lower in vendor_name_lower:
                partial_score = min(len(vendor_name_lower), len(db_vendor_lower)) / max(len(vendor_name_lower), len(db_vendor_lower))
                score = max(score, partial_score * 0.9)  # Boost partial match score
            
            # Special handling for IC- prefix: remove it for comparison if needed
            vendor_base = vendor_name_lower
            if vendor_name_lower.startswith('ic-'):
                vendor_base = vendor_name_lower[3:]
            elif not vendor_name_lower.startswith('ic-') and db_vendor_lower.startswith('ic-'):
                # Compare extracted name to IC- vendor without prefix
                db_base = db_vendor_lower[3:]
                if db_base:
                    base_score = SequenceMatcher(None, vendor_name_lower, db_base).ratio()
                    score = max(score, base_score)
            
            # Update best match if this is better
            if score > best_score:
                best_score = score
                best_match = db_vendor
        
        # Use lower threshold for fuzzy matching (0.65 instead of 0.7)
        # This allows for more lenient matching, especially for abbreviations like "RD" -> "Restaurant Depot"
        threshold = 0.65
        
        if best_match and best_score >= threshold:
            logger.debug(f"Fuzzy matched vendor: '{vendor_name}' -> '{best_match}' (score: {best_score:.2f})")
            if return_normalization_info:
                return {
                    'normalized_vendor_name': best_match,
                    'normalized_by': 'fuzzy',
                    'original_vendor_name': original_vendor_name
                }
            return best_match
        
        # Try one more time with normalized names (remove common words, spaces)
        if not best_match or best_score < threshold:
            vendor_normalized = re.sub(r'[^a-z0-9]', '', vendor_name_lower)
            
            for db_vendor in self.database_vendors.keys():
                db_normalized = re.sub(r'[^a-z0-9]', '', db_vendor.lower())
                
                if vendor_normalized and db_normalized:
                    normalized_score = SequenceMatcher(None, vendor_normalized, db_normalized).ratio()
                    
                    # Also check if one contains the other (for cases like "Costco Business Center" vs "Costco")
                    if vendor_normalized in db_normalized or db_normalized in vendor_normalized:
                        normalized_score = max(normalized_score, 0.85)
                    
                    # Special handling for abbreviations: if one is much shorter and contained in the other
                    # (e.g., "rd" in "restaurantdepot")
                    if len(vendor_normalized) <= 3 and len(vendor_normalized) < len(db_normalized):
                        # Very short vendor name (likely abbreviation) - check if it's contained in DB name
                        if vendor_normalized in db_normalized:
                            # Calculate score based on abbreviation length and position
                            pos = db_normalized.find(vendor_normalized)
                            # Higher score if at start of name (common for abbreviations)
                            position_bonus = 0.2 if pos < 3 else 0.1
                            abbreviation_score = min(0.85, len(vendor_normalized) / len(db_normalized) * 0.9 + position_bonus)
                            normalized_score = max(normalized_score, abbreviation_score)
                    elif len(vendor_normalized) < len(db_normalized) and vendor_normalized in db_normalized:
                        # Regular abbreviation match
                        abbreviation_score = len(vendor_normalized) / len(db_normalized) * 0.9
                        normalized_score = max(normalized_score, abbreviation_score)
                    elif len(db_normalized) < len(vendor_normalized) and db_normalized in vendor_normalized:
                        abbreviation_score = len(db_normalized) / len(vendor_normalized) * 0.9
                        normalized_score = max(normalized_score, abbreviation_score)
                    
                    # Also check if abbreviation matches first letters of words
                    # e.g., "rd" could match "Restaurant Depot" (R+D)
                    if len(vendor_normalized) <= 3:
                        db_words = db_vendor.split()
                        if len(db_words) >= 2:
                            first_letters = ''.join([w[0].lower() if w else '' for w in db_words])
                            if vendor_normalized == first_letters:
                                normalized_score = max(normalized_score, 0.80)  # High score for acronym match
                    
                    if normalized_score > best_score:
                        best_score = normalized_score
                        best_match = db_vendor
            
            if best_match and best_score >= threshold:
                logger.debug(f"Fuzzy matched vendor (normalized): '{vendor_name}' -> '{best_match}' (score: {best_score:.2f})")
                if return_normalization_info:
                    return {
                        'normalized_vendor_name': best_match,
                        'normalized_by': 'fuzzy',
                        'original_vendor_name': original_vendor_name
                    }
                return best_match
        
        # Handle specific known variations
        vendor_variations = {
            'IC-Costco Business Center': 'IC-Costco Bussiness',  # Database has typo
            'Costco Business Center': 'IC-Costco Bussiness',
            'Jewel-osco': 'IC-Jewel-Osco',  # Case variation
            'Jewel Osco': 'IC-Jewel-Osco',
            # RD is Restaurant Depot - if not in DB, keep as extracted name
            'RD': None,  # Will be normalized to 'Restaurant Depot' and kept if not in DB
            'rd': None,
            'R D': None,
            'Restaurant Depot': None,  # If not in DB, will be kept as-is
        }
        
        if vendor_name in vendor_variations:
            matched_name = vendor_variations[vendor_name]
            if matched_name and matched_name in self.database_vendors:
                logger.info(f"Matched vendor variation: '{vendor_name}' -> '{matched_name}'")
                if return_normalization_info:
                    return {
                        'normalized_vendor_name': matched_name,
                        'normalized_by': 'db',
                        'original_vendor_name': original_vendor_name
                    }
                return matched_name
        
        # For Instacart: try matching IC-{store_name} format
        if store_name:
            ic_vendor = f"IC-{store_name}"
            if ic_vendor in self.database_vendors:
                if return_normalization_info:
                    return {
                        'normalized_vendor_name': ic_vendor,
                        'normalized_by': 'db',
                        'original_vendor_name': original_vendor_name
                    }
                return ic_vendor
        
        # No match found
        normalized_by = 'none'
        if alias_result:
            normalized_by = 'rule:15_vendor_aliases'
        
        if return_normalization_info:
            return {
                'normalized_vendor_name': vendor_name,
                'normalized_by': normalized_by,
                'original_vendor_name': original_vendor_name
            }
        
        # In step 1, don't warn - just return None or input name
        if self.skip_database:
            return None
        logger.debug(f"Could not match vendor: '{vendor_name}' to any database vendor")
        return None
    
    def get_all_vendors(self) -> Dict:
        """Get all database vendors"""
        return self.database_vendors.copy()

