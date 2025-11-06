#!/usr/bin/env python3
"""
BBI Baseline Loader and UoM/Pack Determinator
Loads BBI_Size.xlsx baseline and determines if receipt prices are per UoM or per Pack.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logging.warning("pandas not available. Install with: pip install pandas")

logger = logging.getLogger(__name__)


class BBIBaseline:
    """Load and manage BBI baseline data from BBI_Size.xlsx"""
    
    def __init__(self, baseline_file: Path):
        """
        Initialize BBI baseline loader
        
        Args:
            baseline_file: Path to BBI_Size.xlsx file
        """
        self.baseline_file = Path(baseline_file)
        self.baseline_data: List[Dict[str, any]] = []
        self.load_baseline()
    
    def load_baseline(self) -> bool:
        """Load baseline data from BBI_Size.xlsx"""
        if not PANDAS_AVAILABLE:
            logger.error("pandas not available. Cannot load BBI baseline.")
            return False
        
        if not self.baseline_file.exists():
            logger.warning(f"BBI baseline file not found: {self.baseline_file}")
            return False
        
        try:
            # Check file extension and use appropriate reader
            if self.baseline_file.suffix.lower() == '.csv':
                df = pd.read_csv(self.baseline_file)
            else:
                # Use openpyxl engine for .xlsx files (avoids xlrd compatibility issues)
                try:
                    df = pd.read_excel(self.baseline_file, engine='openpyxl')
                except Exception as e:
                    # Fallback: try without specifying engine
                    logger.warning(f"Failed to read with openpyxl engine: {e}, trying default engine")
                    try:
                        df = pd.read_excel(self.baseline_file)
                    except Exception as e2:
                        logger.error(f"Failed to read Excel file with both engines: {e2}")
                        raise e2
            logger.info(f"Loaded BBI baseline from {self.baseline_file.name}: {len(df)} rows, {len(df.columns)} columns")
            
            # Normalize column names (case-insensitive)
            df.columns = df.columns.str.strip()
            column_map = {}
            for col in df.columns:
                col_lower = col.lower().strip()
                # Check exact matches first (new baseline uses lowercase)
                if col_lower == 'description':
                    column_map['description'] = col
                elif col_lower == 'uom':
                    column_map['uom'] = col
                elif col_lower == 'uom_price' or col_lower == 'uom price':
                    column_map['uom_price'] = col
                elif col_lower == 'pack_size' or col_lower == 'pack size':
                    column_map['pack_size'] = col
                elif col_lower == 'pack_price' or col_lower == 'pack price':
                    column_map['pack_price'] = col
                # Fallback for older formats with different capitalization
                elif 'description' in col_lower and 'description' not in column_map:
                    column_map['description'] = col
                elif (col_lower.startswith('uom') and 'price' not in col_lower) and 'uom' not in column_map:
                    column_map['uom'] = col
                elif ('uom price' in col_lower or 'uom_price' in col_lower) and 'uom_price' not in column_map:
                    column_map['uom_price'] = col
                elif ('pack size' in col_lower or 'pack_size' in col_lower) and 'pack_size' not in column_map:
                    column_map['pack_size'] = col
                elif ('pack price' in col_lower or 'pack_price' in col_lower) and 'pack_price' not in column_map:
                    column_map['pack_price'] = col
            
            if 'description' not in column_map:
                logger.error(f"Required column 'Description' not found in BBI baseline")
                return False
            
            # Load data
            for idx, row in df.iterrows():
                # Extract UoM unit from UoM field (e.g., "1-pc" -> "pc", "Pack/Roll" -> "Roll")
                uom_raw = str(row[column_map.get('uom', '')]).strip() if column_map.get('uom') and pd.notna(row[column_map['uom']]) else ''
                uom_unit = self._extract_uom_unit(uom_raw) if uom_raw else ''
                
                # Parse UoM Price (handle both numeric and string formats)
                uom_price = None
                if column_map.get('uom_price'):
                    uom_price_val = row[column_map['uom_price']]
                    if pd.notna(uom_price_val):
                        try:
                            # If it's already a number, use it directly
                            if isinstance(uom_price_val, (int, float)):
                                uom_price = float(uom_price_val)
                            else:
                                # Try to parse as string
                                uom_price_str = str(uom_price_val).strip()
                                if uom_price_str and uom_price_str.lower() not in ['nan', 'none', '']:
                                    # Remove $ and commas, then convert to float
                                    uom_price_clean = uom_price_str.replace('$', '').replace(',', '').strip()
                                    if uom_price_clean:
                                        uom_price = float(uom_price_clean)
                        except (ValueError, AttributeError):
                            logger.debug(f"Could not parse UoM Price: {uom_price_val}")
                
                # Parse Pack Price (handle both numeric and string formats)
                pack_price = None
                if column_map.get('pack_price'):
                    pack_price_val = row[column_map['pack_price']]
                    if pd.notna(pack_price_val):
                        try:
                            # If it's already a number, use it directly
                            if isinstance(pack_price_val, (int, float)):
                                pack_price = float(pack_price_val)
                            else:
                                # Try to parse as string
                                pack_price_str = str(pack_price_val).strip()
                                if pack_price_str and pack_price_str.lower() not in ['nan', 'none', '']:
                                    # Remove $ and commas, then convert to float
                                    pack_price_clean = pack_price_str.replace('$', '').replace(',', '').strip()
                                    if pack_price_clean:
                                        pack_price = float(pack_price_clean)
                        except (ValueError, AttributeError):
                            logger.debug(f"Could not parse Pack Price: {pack_price_val}")
                
                item = {
                    'description': str(row[column_map['description']]).strip() if pd.notna(row[column_map['description']]) else '',
                    'uom': uom_unit,  # Use extracted unit (e.g., "pc", "Roll")
                    'uom_raw': uom_raw,  # Keep original for reference
                    'uom_price': uom_price,
                    'pack_size': str(row[column_map['pack_size']]).strip() if column_map.get('pack_size') and pd.notna(row[column_map['pack_size']]) else '',
                    'pack_price': pack_price,  # Store pack price directly from baseline
                }
                
                # Parse pack size to get pack count (e.g., "20*1-kg" -> 20)
                if item['pack_size']:
                    pack_count = self._parse_pack_count(item['pack_size'])
                    if pack_count:
                        item['pack_count'] = pack_count
                        # Use pack_price from baseline if available, otherwise calculate from UoM price
                        if item['pack_price'] is None and item['uom_price'] is not None:
                            item['pack_price'] = item['uom_price'] * pack_count
                    else:
                        item['pack_count'] = 1  # Default to 1 if can't parse
                        if item['pack_price'] is None:
                            item['pack_price'] = item['uom_price'] if item['uom_price'] is not None else None
                else:
                    item['pack_count'] = 1  # No pack size means 1-pc
                    if item['pack_price'] is None:
                        item['pack_price'] = item['uom_price'] if item['uom_price'] is not None else None
                
                if item['description']:
                    self.baseline_data.append(item)
            
            logger.info(f"Loaded {len(self.baseline_data)} items from BBI baseline")
            return True
            
        except Exception as e:
            logger.error(f"Error loading BBI baseline: {e}", exc_info=True)
            return False
    
    def _extract_uom_unit(self, uom_raw: str) -> str:
        """
        Extract unit name from UoM field
        Examples: "1-pc" -> "pc", "Pack/Roll" -> "Roll", "20-oz" -> "oz", "3kg-can" -> "kg"
        """
        if not uom_raw or uom_raw.strip() == '':
            return ''
        
        uom_raw = uom_raw.strip()
        
        # Skip if it looks like a price (starts with $ or is just numbers with decimals)
        if uom_raw.startswith('$') or re.match(r'^\d+\.\d+$', uom_raw):
            return ''
        
        # Pattern: "Pack/Roll" -> "Roll"
        if '/' in uom_raw:
            parts = uom_raw.split('/')
            if len(parts) > 1:
                unit = parts[-1].strip()
                # Normalize common units
                if unit.lower() in ['roll', 'rolls']:
                    return 'Roll'
                elif unit.lower() in ['pack', 'packs']:
                    return 'Pack'
                else:
                    return unit
        
        # Pattern: "1-pc" or "20-oz" -> extract unit after dash
        match = re.search(r'[-](\w+)$', uom_raw)
        if match:
            unit = match.group(1).lower()
            # Normalize common units
            if unit in ['pc', 'pcs', 'piece', 'pieces']:
                return 'pc'
            elif unit in ['oz', 'ounce', 'ounces']:
                return 'oz'
            elif unit in ['lb', 'lbs', 'pound', 'pounds']:
                return 'lb'
            elif unit in ['kg', 'kilogram', 'kilograms']:
                return 'kg'
            elif unit in ['g', 'gram', 'grams']:
                return 'g'
            elif unit in ['can', 'cans']:
                return 'can'
            else:
                return unit
        
        # Pattern: "3kg-can" -> extract "kg" or "can"
        # Look for unit patterns like kg, oz, lb, g, pc, can
        unit_patterns = ['kg', 'oz', 'lb', 'g', 'pc', 'can', 'roll']
        for pattern in unit_patterns:
            if pattern in uom_raw.lower():
                return pattern
        
        # Pattern: numbers at end like "pc", "can", etc.
        match = re.search(r'(\d+)?([a-z]+)$', uom_raw.lower())
        if match:
            unit = match.group(2)
            if unit in ['pc', 'pcs', 'piece', 'pieces']:
                return 'pc'
            elif unit in ['can', 'cans']:
                return 'can'
            elif unit in ['roll', 'rolls']:
                return 'Roll'
            else:
                return unit
        
        # Default: return as-is (lowercase) if it doesn't look like a price
        return uom_raw.lower()
    
    def _parse_pack_count(self, pack_size: str) -> Optional[int]:
        """
        Parse pack count from pack size string
        Examples: "20*1-kg" -> 20, "6*2.5kg-bucket" -> 6, "1-pc" -> 1
        """
        if not pack_size:
            return None
        
        # Pattern: number at start followed by * (e.g., "20*1-kg" -> 20)
        match = re.match(r'^(\d+)\*', pack_size)
        if match:
            return int(match.group(1))
        
        # Pattern: "1-pc" or "1 pc" -> 1
        match = re.match(r'^(\d+)\s*[-]?\s*pc', pack_size, re.IGNORECASE)
        if match:
            return int(match.group(1))
        
        # If no multiplier pattern, assume 1
        return 1
    
    def find_match(self, description: str, threshold: float = 0.6) -> Optional[Dict[str, any]]:
        """
        Find matching baseline item by description using fuzzy matching
        
        Args:
            description: Product description from receipt
            threshold: Minimum similarity score (default: 0.6, lowered for better matching)
        
        Returns:
            Matching baseline item or None
        """
        if not self.baseline_data:
            return None
        
        description_lower = description.lower().strip()
        best_match = None
        best_score = 0.0
        
        for item in self.baseline_data:
            baseline_desc = item['description'].lower().strip()
            
            # Calculate similarity
            score = SequenceMatcher(None, description_lower, baseline_desc).ratio()
            
            # Boost score if description contains baseline or vice versa
            if description_lower in baseline_desc or baseline_desc in description_lower:
                score = max(score, 0.9)
            
            # Boost score if key words match
            desc_words = set(description_lower.split())
            baseline_words = set(baseline_desc.split())
            common_words = desc_words & baseline_words
            if len(common_words) >= 2:
                word_score = len(common_words) / max(len(desc_words), len(baseline_words), 1)
                score = max(score, word_score * 0.9)
            
            # Additional boost for exact word matches (case-insensitive)
            if desc_words == baseline_words:
                score = 1.0
            
            if score > best_score and score >= threshold:
                best_score = score
                best_match = item.copy()
                best_match['match_score'] = best_score
        
        return best_match
    
    def determine_pricing_unit(self, description: str, receipt_unit_price: float, 
                               receipt_qty: Optional[float] = None, 
                               price_tolerance: float = 0.20) -> Tuple[Optional[str], Optional[float], Optional[Dict]]:
        """
        Determine if receipt price is per UoM or per Pack by comparing to baseline prices
        Uses a reasonable price tolerance (default 20%) to account for price changes over time
        
        Args:
            description: Product description from receipt
            receipt_unit_price: Unit price from receipt
            receipt_qty: Optional quantity from receipt (not used in current logic)
            price_tolerance: Maximum allowed price difference as a ratio (default 0.20 = 20%)
        
        Returns:
            Tuple of (pricing_unit, confidence_score, baseline_item)
            pricing_unit: 'UoM' or 'Pack' or None
            confidence_score: 0.0 to 1.0
            baseline_item: Matched baseline item or None
        """
        # Find matching baseline item
        baseline_item = self.find_match(description)
        if not baseline_item:
            logger.debug(f"No baseline match for: {description}")
            return None, 0.0, None
        
        uom_price = baseline_item.get('uom_price')
        pack_price = baseline_item.get('pack_price')
        
        # If we only have one price, use that
        if uom_price is None and pack_price is None:
            logger.debug(f"No prices in baseline for: {description}")
            return None, 0.0, baseline_item
        
        if pack_price is None:
            # Only UoM price available - check if receipt price matches
            if uom_price and uom_price > 0:
                price_diff = abs(receipt_unit_price - uom_price) / uom_price
                if price_diff <= price_tolerance:
                    return 'UoM', max(0.0, 1.0 - price_diff), baseline_item
            return None, 0.0, baseline_item
        
        if uom_price is None:
            # Only Pack price available - check if receipt price matches
            if pack_price and pack_price > 0:
                price_diff = abs(receipt_unit_price - pack_price) / pack_price
                if price_diff <= price_tolerance:
                    return 'Pack', max(0.0, 1.0 - price_diff), baseline_item
            return None, 0.0, baseline_item
        
        # Both prices available - compare receipt price to both
        uom_diff = abs(receipt_unit_price - uom_price) / uom_price if uom_price > 0 else float('inf')
        pack_diff = abs(receipt_unit_price - pack_price) / pack_price if pack_price > 0 else float('inf')
        
        # Check if receipt price is within tolerance of either baseline price
        uom_within_tolerance = uom_diff <= price_tolerance
        pack_within_tolerance = pack_diff <= price_tolerance
        
        if uom_within_tolerance and pack_within_tolerance:
            # Both match - use the closer one
            if uom_diff < pack_diff:
                return 'UoM', max(0.0, 1.0 - uom_diff), baseline_item
            else:
                return 'Pack', max(0.0, 1.0 - pack_diff), baseline_item
        elif uom_within_tolerance:
            # Only UoM matches
            return 'UoM', max(0.0, 1.0 - uom_diff), baseline_item
        elif pack_within_tolerance:
            # Only Pack matches
            return 'Pack', max(0.0, 1.0 - pack_diff), baseline_item
        else:
            # Neither matches within tolerance - use the closer one but with lower confidence
            if uom_diff < pack_diff:
                # Still prefer UoM if it's closer, but with lower confidence
                confidence = max(0.0, 0.5 - uom_diff)  # Lower confidence for out-of-tolerance
                return 'UoM', confidence, baseline_item
            else:
                confidence = max(0.0, 0.5 - pack_diff) if pack_price else 0.0
                return 'Pack', confidence, baseline_item if pack_price else None


def load_bbi_baseline(input_dir: Path) -> Optional[BBIBaseline]:
    """
    Load BBI baseline from BBI_Size.xlsx or BBI_Size_merged.xlsx in input directory
    
    Args:
        input_dir: Input directory to search for BBI_Size.xlsx
    
    Returns:
        BBIBaseline instance or None if not found
    """
    # Search for BBI_Size.xlsx, BBI_Size_merged.xlsx, or BBI_Size.csv in input directory
    baseline_file = None
    possible_names = ['BBI_Size.xlsx', 'BBI_Size_merged.xlsx', 'BBI_Size.csv']
    
    for name in possible_names:
        candidate = input_dir / name
        if candidate.exists():
            baseline_file = candidate
            break
    
    if not baseline_file:
        # Try searching in subdirectories (but skip if it's in a BBI receipt folder)
        for name in possible_names:
            baseline_files = list(input_dir.glob(f'**/{name}'))
            if baseline_files:
                # Use the first one found (prefer root level)
                baseline_file = baseline_files[0]
                logger.info(f"Found BBI baseline file: {baseline_file.relative_to(input_dir)}")
                break
    
    if not baseline_file:
        logger.warning(f"BBI_Size.xlsx or BBI_Size_merged.xlsx not found in {input_dir}")
        return None
    
    logger.info(f"Loading BBI baseline from: {baseline_file.relative_to(input_dir)}")
    
    try:
        baseline = BBIBaseline(baseline_file)
        if baseline.baseline_data:
            return baseline
        else:
            logger.warning(f"BBI baseline loaded but contains no data")
            return None
    except Exception as e:
        logger.error(f"Error loading BBI baseline: {e}", exc_info=True)
        return None

