#!/usr/bin/env python3
"""
Generate human-readable report from Step 1 extracted data
Outputs HTML report (can be printed to PDF or opened in Word)
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _load_picked_weight_rules() -> Dict:
    """Load rules for using picked weight for weight items"""
    try:
        from step1_extract.rule_loader import RuleLoader
        rules_dir = Path(__file__).parent.parent / 'step1_rules'
        loader = RuleLoader(rules_dir)
        instacart_rules = loader.get_instacart_csv_match_rules()
        return instacart_rules.get('instacart_csv_match', {}).get('use_picked_weight_for_weight_items', {})
    except Exception as e:
        logger.debug(f"Could not load picked weight rules: {e}")
        return {}


def _format_size_for_display(size_str: str) -> str:
    """
    Format size string for display: "3.0 lb" -> "3-lb", "64 fl oz" -> "64-fl oz"
    
    Args:
        size_str: Size string (e.g., "3.0 lb", "64 fl oz", "1 Gallon")
        
    Returns:
        Formatted size string (e.g., "3-lb", "64-fl oz", "1-Gallon")
    """
    if not size_str or size_str == "N/A":
        return size_str
    
    import re
    
    # Pattern: number (with optional decimal) followed by unit(s)
    # Match patterns like "3.0 lb", "1 Gallon", "64 fl oz", "2 lbs bag"
    # This handles cases like "64 fl oz", "10.0 lb", "1 Gallon / unit"
    pattern = r'(\d+(?:\.\d+)?)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)'
    
    def replace_func(match):
        num_str = match.group(1)
        unit = match.group(2).strip()
        
        # Remove trailing zeros from number (e.g., "3.0" -> "3", "10.0" -> "10")
        try:
            num_float = float(num_str)
            if num_float == int(num_float):
                num = str(int(num_float))
            else:
                num = num_str.rstrip('0').rstrip('.')
        except (ValueError, TypeError):
            num = num_str
        
        # Remove trailing 's' from units like "lbs" -> "lb", "Gallons" -> "Gallon" (but keep "fl oz")
        # Only remove 's' if it's at the end and preceded by a letter (not space)
        if unit.endswith('s') and len(unit) > 1 and unit[-2].isalpha():
            # Check if it's a simple plural (not "fl oz" or "ct")
            if not unit.startswith('fl ') and unit.lower() not in ['fl oz', 'ct', 'count']:
                unit = unit[:-1]  # Remove trailing 's'
        
        return f"{num}-{unit}"
    
    # Replace number + unit patterns throughout the string
    formatted = re.sub(pattern, replace_func, size_str)
    return formatted


def _should_use_picked_weight(item: Dict, picked_weight_rules: Dict) -> bool:
    """Check if item should use picked weight instead of size"""
    if not picked_weight_rules.get('enabled', False):
        return False
    
    # Apply to all Instacart items with picked_weight if enabled
    apply_to_all = picked_weight_rules.get('apply_to_all_instacart_items', False)
    
    purchase_uom = item.get('purchase_uom', '').lower()
    picked_weight = item.get('picked_weight', '')
    
    # Check if UoM is in weight UoM list
    weight_uom = [uom.lower() for uom in picked_weight_rules.get('weight_uom', [])]
    matches_uom = purchase_uom in weight_uom
    
    # Check if picked_weight is available and valid (presence of picked_weight indicates Instacart CSV source)
    has_picked_weight = picked_weight and str(picked_weight).strip() and str(picked_weight) != '0' and str(picked_weight).lower() != '0.0'
    
    if apply_to_all:
        # Apply to any item with picked_weight and weight UoM (picked_weight presence indicates Instacart order)
        return matches_uom and has_picked_weight
    else:
        # Original logic: check product keywords (backward compatibility)
        product_name = item.get('product_name', '').lower()
        product_keywords = picked_weight_rules.get('product_keywords', [])
        matches_keyword = any(keyword.lower() in product_name for keyword in product_keywords)
        return matches_keyword and matches_uom and has_picked_weight


def _get_category_badge_html(item: Dict) -> str:
    """Generate HTML for category badges"""
    l2_cat = item.get('l2_category')
    l2_name = item.get('l2_category_name')
    l1_cat = item.get('l1_category')
    l1_name = item.get('l1_category_name')
    confidence = item.get('category_confidence', 0)
    needs_review = item.get('needs_category_review', False)
    
    if not l2_cat:
        return ""
    
    # Color coding based on L1 category
    l1_colors = {
        'A01': '#28a745',  # COGS-Ingredients (green)
        'A02': '#17a2b8',  # COGS-Packaging (cyan)
        'A03': '#6c757d',  # COGS-Non-food (gray)
        'A04': '#fd7e14',  # Smallwares (orange)
        'A05': '#6f42c1',  # Cleaning (purple)
        'A06': '#20c997',  # Office (teal)
        'A07': '#dc3545',  # Taxes (red)
        'A08': '#ffc107',  # Shipping (yellow)
        'A09': '#e83e8c',  # Tips (pink)
        'A99': '#6c757d',  # Unknown (gray)
    }
    
    l1_color = l1_colors.get(l1_cat, '#6c757d')
    
    # Add warning for items needing review
    review_badge = ""
    if needs_review:
        review_badge = '<span style="background: #dc3545; color: white; padding: 2px 6px; border-radius: 3px; font-size: 0.75em; margin-left: 5px;">⚠️ Review</span>'
    
    confidence_display = f"{confidence:.0%}" if confidence else "N/A"
    
    return f'''
        <div style="font-size: 0.85em; margin-top: 5px;">
            <span style="background: {l1_color}; color: white; padding: 3px 8px; border-radius: 4px; font-weight: 500; margin-right: 5px;">
                L1: {l1_cat} - {l1_name}
            </span>
            <span style="background: #e9ecef; color: #495057; padding: 3px 8px; border-radius: 4px; font-size: 0.9em;">
                L2: {l2_cat} - {l2_name}
            </span>
            <span style="color: #6c757d; font-size: 0.85em; margin-left: 8px;">
                Confidence: {confidence_display}
            </span>
            {review_badge}
        </div>
    '''


def generate_html_report(extracted_data: Dict, output_path: Path) -> Path:
    """
    Generate HTML report from extracted receipt data
    
    Args:
        extracted_data: Dictionary mapping receipt IDs to extracted data
        output_path: Path to save HTML report
        
    Returns:
        Path to generated HTML report
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load rules for picked weight display
    picked_weight_rules = _load_picked_weight_rules()
    
    # Calculate summary statistics
    total_receipts = len(extracted_data)
    # Use items_sold (total purchased items) if available, otherwise count items
    total_items = 0
    for receipt in extracted_data.values():
        items_sold = receipt.get('items_sold')
        if items_sold is not None:
            total_items += float(items_sold)
        else:
            total_items += len(receipt.get('items', []))
    total_amount = sum(float(receipt.get('total', 0) or 0) for receipt in extracted_data.values())
    
    # Group by vendor
    vendor_stats = {}
    for receipt_id, receipt_data in extracted_data.items():
        vendor = receipt_data.get('vendor') or 'Unknown'
        if vendor not in vendor_stats:
            vendor_stats[vendor] = {'count': 0, 'total': 0, 'items': 0.0}
        vendor_stats[vendor]['count'] += 1
        vendor_stats[vendor]['total'] += float(receipt_data.get('total', 0) or 0)
        # Use items_sold (total purchased items) if available, otherwise count items
        items_sold = receipt_data.get('items_sold')
        if items_sold is not None:
            vendor_stats[vendor]['items'] += float(items_sold)
        else:
            vendor_stats[vendor]['items'] += len(receipt_data.get('items', []))
    
    # Generate HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Receipt Extraction Report - Step 1</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 30px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            border-bottom: 2px solid #ecf0f1;
            padding-bottom: 5px;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .stat-card h3 {{
            font-size: 2em;
            margin-bottom: 5px;
        }}
        .stat-card p {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        .vendor-stats {{
            margin-bottom: 30px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 30px;
            background: white;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #3498db;
            color: white;
            font-weight: 600;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .receipt-section {{
            margin-bottom: 30px;
            page-break-inside: avoid;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 0;
            background: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .receipt-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px 8px 0 0;
        }}
        .receipt-header h3 {{
            margin: 0;
            font-size: 1.3em;
            font-weight: 600;
        }}
        .review-warning {{
            margin: 15px;
            padding: 12px 15px;
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            border-radius: 4px;
        }}
        .review-warning strong {{
            color: #856404;
            display: block;
            margin-bottom: 8px;
        }}
        .review-warning ul {{
            margin: 0;
            padding-left: 20px;
            color: #856404;
        }}
        .review-warning li {{
            margin-bottom: 4px;
        }}
        .item-row {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
            align-items: flex-start;
        }}
        .item-name {{
            flex: 2;
            font-weight: 500;
        }}
        .item-details {{
            flex: 1;
            text-align: right;
            color: #666;
            min-width: 150px;
        }}
        .unit-info {{
            font-size: 0.85em;
            color: #666;
            margin-top: 3px;
            line-height: 1.4;
        }}
        .unit-badge {{
            display: inline-block;
            background: #ecf0f1;
            color: #34495e;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.8em;
            margin-right: 5px;
        }}
        .confidence-high {{
            color: #27ae60;
        }}
        .confidence-medium {{
            color: #f39c12;
        }}
        .confidence-low {{
            color: #e74c3c;
        }}
        .receipt-total {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 2px solid #3498db;
            text-align: right;
            font-size: 1.2em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .metadata {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin-bottom: 15px;
            font-size: 0.9em;
            color: #666;
        }}
        .metadata-item {{
            display: flex;
            align-items: center;
        }}
        .metadata-label {{
            font-weight: 600;
            margin-right: 5px;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 2px solid #ecf0f1;
            text-align: center;
            color: #666;
            font-size: 0.9em;
        }}
        @media print {{
            body {{
                background: white;
            }}
            .container {{
                box-shadow: none;
            }}
            .receipt-section {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📋 Receipt Extraction Report - Step 1</h1>
        <p style="color: #666; margin-bottom: 30px;">Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>📊 Summary Statistics</h2>
        <div class="summary">
            <div class="stat-card">
                <h3>{total_receipts}</h3>
                <p>Total Receipts</p>
            </div>
            <div class="stat-card">
                <h3>{total_items}</h3>
                <p>Total Items</p>
            </div>
            <div class="stat-card">
                <h3>${total_amount:,.2f}</h3>
                <p>Total Amount</p>
            </div>
        </div>
        
        <h2>🏪 Vendor Statistics</h2>
        <div class="vendor-stats">
            <table>
                <thead>
                    <tr>
                        <th>Vendor</th>
                        <th>Receipts</th>
                        <th>Items</th>
                        <th>Total Amount</th>
                    </tr>
                </thead>
                <tbody>
"""
    
    # Add vendor statistics
    for vendor, stats in sorted(vendor_stats.items(), key=lambda x: x[1]['count'], reverse=True):
        html_content += f"""
                    <tr>
                        <td><strong>{vendor}</strong></td>
                        <td>{stats['count']}</td>
                        <td>{stats['items']:.0f}</td>
                        <td>${stats['total']:,.2f}</td>
                    </tr>
"""
    
    html_content += """
                </tbody>
            </table>
        </div>
        
        <h2>🧾 Receipt Details</h2>
"""
    
    # Add receipt details
    for receipt_id, receipt_data in sorted(extracted_data.items()):
        items = receipt_data.get('items', [])
        vendor = receipt_data.get('vendor') or 'Unknown'
        order_date = receipt_data.get('order_date') or receipt_data.get('date') or 'N/A'
        filename = receipt_data.get('filename', receipt_id)
        total = receipt_data.get('total', 0)
        
        # Get source type information
        source_type = receipt_data.get('source_type', 'unknown')
        source_info = []
        
        # Display source type if available
        if source_type and source_type != 'unknown':
            source_label = source_type.upper().replace('_', ' ')
            source_info.append(f'<span style="background: #95a5a6; color: white; padding: 3px 8px; border-radius: 3px; font-size: 0.85em;">{source_label}</span>')
        
        # Check if vendor was detected from filename
        vendor_from_filename = receipt_data.get('vendor_source') == 'filename'
        # For Group 1 Excel files, if vendor_source is not set, check if vendor likely came from filename
        if not vendor_from_filename and receipt_data.get('source_group') == 'group1':
            # Check if filename contains vendor identifier patterns
            filename_lower = filename.lower()
            vendor_lower = vendor.lower() if vendor else ''
            # If vendor name or common identifiers appear in filename, likely from filename
            vendor_from_filename = (
                vendor_lower in filename_lower or
                any(keyword in filename_lower for keyword in ['costco', 'rd_', 'restaurant', 'jewel', 'mariano', 'aldi', 'parktoshop'])
            )
        
        vendor_attention = ' <span style="color: #ffc107; font-size: 0.9em;" title="Vendor detected from filename">⚠️</span>' if vendor_from_filename else ''
        
        html_content += f"""
        <div class="receipt-section">
            <div class="receipt-header">
                <h3>{receipt_id}</h3>
            </div>
            <div style="padding: 20px;">
            <div class="metadata">
                <div class="metadata-item">
                    <span class="metadata-label">File:</span>
                    <span>{filename}</span>
                </div>
                <div class="metadata-item">
                    <span class="metadata-label">Vendor:</span>
                    <span><strong>{vendor}</strong>{vendor_attention}</span>
                </div>
                <div class="metadata-item">
                    <span class="metadata-label">Date:</span>
                    <span>{order_date}</span>
                </div>
                <div class="metadata-item">
                    <span class="metadata-label">Total Items Sold:</span>
                    <span><strong>{receipt_data.get('items_sold', len(items))}</strong></span>
                </div>
"""
        
        # Add source information if available
        if source_info:
            html_content += f"""
                <div class="metadata-item">
                    <span class="metadata-label">Source:</span>
                    <span>{' | '.join(source_info)}</span>
                </div>
"""
        
        html_content += """
            </div>
"""
        
        # Add review flags if needed (exclude "Vendor not confidently identified" as we show that with attention sign)
        needs_review = receipt_data.get('needs_review', False)
        review_reasons = receipt_data.get('review_reasons', [])
        # Filter out "Vendor not confidently identified" from review reasons
        filtered_review_reasons = [r for r in review_reasons if r != "Vendor not confidently identified"]
        
        if needs_review and filtered_review_reasons:
            html_content += """
                <div class="review-warning">
                    <strong>⚠️ Needs Review:</strong>
                    <ul>
"""
            for reason in filtered_review_reasons:
                html_content += f"                        <li>{reason}</li>\n"
            html_content += """                    </ul>
                </div>
"""
        
        html_content += f"""
            <div style="margin-top: 15px;">
"""
        
        # Detect if this is Group 1 (Excel-based) receipt
        source_group = receipt_data.get('source_group', '')
        is_group1 = source_group == 'group1'
        
        # Add items
        for item in items:
            # Use codes-first display name if available
            product_name = item.get('display_name_codes_first') or item.get('product_name', 'Unknown Product')
            quantity = item.get('quantity', 0)
            # Use purchase_uom if available, otherwise fallback to raw_uom_text from Excel
            purchase_uom = item.get('purchase_uom') or item.get('raw_uom_text') or 'unknown'
            unit_price = item.get('unit_price', 0)
            total_price = item.get('total_price', 0)
            
            # Item number and UPC (for Group 1 receipts)
            item_number = item.get('item_number')
            item_code = item.get('item_code')
            upc = item.get('upc')
            
            # Unit details
            size = item.get('size', '')
            unit_confidence = item.get('unit_confidence')
            count_per_package = item.get('count_per_package')
            csv_linked = item.get('csv_linked', False)
            
            # Knowledge base information (for Costco and RD only)
            kb_size = item.get('kb_size')  # Size/spec from knowledge base (e.g., "3-lbs bag", "6 × 32-fl oz")
            kb_source = item.get('kb_source')  # "knowledge_base" if enriched
            price_source = item.get('price_source')  # "knowledge_base" if unit_price is from KB
            
            # Legacy vendor information (backward compatibility)
            vendor_size = item.get('vendor_size')
            vendor_price = item.get('vendor_price')
            
            # Format sizes for display (view-friendly)
            size = _format_size_for_display(size) if size else ''
            kb_size_display = _format_size_for_display(kb_size) if kb_size else kb_size
            vendor_size = _format_size_for_display(vendor_size) if vendor_size else ''
            
            # Check if this is Costco or RD receipt
            vendor_name = receipt_data.get('vendor', '').lower()
            is_costco_or_rd = 'costco' in vendor_name or 'restaurant' in vendor_name or 'rd' == vendor_name.strip().lower()
            
            # Build unit information display
            uom_display = purchase_uom.upper() if purchase_uom and purchase_uom != 'unknown' else 'UNKNOWN'
            
            # Build detailed unit information
            unit_info_parts = []
            
            # For Group 1 receipts, display UPC and Item Number first if available
            if is_group1:
                if upc is not None:
                    unit_info_parts.insert(0, f'<strong>UPC:</strong> {upc}')
                if item_number is not None:
                    unit_info_parts.insert(1, f'<strong>Item #:</strong> {item_number}')
            
            if size:
                unit_info_parts.append(f'<strong>Size:</strong> {size}')
            
            # Display KB size and source for Costco and RD only
            if is_costco_or_rd:
                if kb_size:
                    # Use green badge for KB-enriched items
                    kb_badge = '<span style="background: #d4edda; color: #155724; padding: 2px 6px; border-radius: 3px; font-size: 0.8em; margin-left: 5px;">📚 KB</span>'
                    unit_info_parts.append(f'<strong>KB Size/Spec:</strong> {kb_size_display} {kb_badge}')
                elif vendor_size:
                    # Fallback to legacy vendor_size if available
                    unit_info_parts.append(f'<strong>Vendor Size:</strong> {vendor_size}')
                
                # Show if price was sourced from KB
                if price_source == 'knowledge_base':
                    unit_info_parts.append(f'<span style="background: #d4edda; color: #155724; padding: 2px 6px; border-radius: 3px; font-size: 0.8em;">💰 KB Price</span>')
                elif vendor_price is not None:
                    # Fallback to legacy vendor_price if available
                    unit_info_parts.append(f'<strong>Vendor Price:</strong> ${vendor_price:.2f}')
            
            if count_per_package:
                unit_info_parts.append(f'<strong>Count:</strong> {count_per_package} per package')
            
            if unit_confidence is not None:
                confidence_pct = int(unit_confidence * 100)
                confidence_class = 'confidence-high' if unit_confidence >= 0.8 else 'confidence-medium' if unit_confidence >= 0.5 else 'confidence-low'
                unit_info_parts.append(f'<strong>Confidence:</strong> <span class="{confidence_class}">{confidence_pct}%</span>')
            
            if csv_linked:
                unit_info_parts.append('<strong>Source:</strong> CSV')
            
            # Build unit info HTML
            unit_info_html = ""
            if unit_info_parts:
                unit_info_html = f'''
                <div class="unit-info">
                    {', '.join(unit_info_parts)}
                </div>'''
            
            # Use Size instead of UoM for price display, but use picked weight + UoM for weight items (like bananas)
            if _should_use_picked_weight(item, picked_weight_rules):
                # For weight items with picked_weight, use picked_weight + UoM instead of size
                picked_weight = item.get('picked_weight', '')
                try:
                    picked_weight_float = float(picked_weight)
                    # Display picked_weight with UoM (format: "3.61-lb")
                    unit_str = f"-{purchase_uom}" if purchase_uom and purchase_uom != 'unknown' else ""
                    # Update quantity to use picked_weight for display
                    quantity = picked_weight_float
                except (ValueError, TypeError):
                    # Fallback to size if picked_weight can't be parsed (already formatted)
                    unit_str = f" {size}" if size else (f"-{purchase_uom}" if purchase_uom and purchase_uom != 'unknown' else "")
            else:
                # Default: use Size instead of UoM for price display (already formatted)
                unit_str = f" {size}" if size else (f"-{purchase_uom}" if purchase_uom and purchase_uom != 'unknown' else "")
            
            # Validate: Check if unit_price × quantity equals total_price
            # Convert to floats for comparison (handle None/0 values)
            qty_float = float(quantity) if quantity else 0.0
            unit_price_float = float(unit_price) if unit_price else 0.0
            total_price_float = float(total_price) if total_price else 0.0
            
            # Get vendor code for vendor-specific validation
            vendor_code = receipt_data.get('vendor') or receipt_data.get('detected_vendor_code') or ''
            is_webstaurantstore = 'WEBSTAURANTSTORE' in vendor_code.upper()
            
            # Calculate expected total (vendor-specific logic)
            if is_webstaurantstore:
                # WEBSTAURANTSTORE-specific: total_price = (unit_price × quantity) + item_tax
                item_tax = float(item.get('item_tax') or 0)
                expected_total = (qty_float * unit_price_float) + item_tax if qty_float > 0 and unit_price_float > 0 else total_price_float
                calculation_display = f"{qty_float:g} × ${unit_price_float:.2f} + ${item_tax:.2f} (tax) = ${expected_total:.2f}"
            else:
                # For other vendors: total_price = unit_price × quantity
                expected_total = qty_float * unit_price_float if qty_float > 0 and unit_price_float > 0 else total_price_float
                calculation_display = f"{qty_float:g} × ${unit_price_float:.2f} = ${expected_total:.2f}"
            
            # Check if they match (allow small rounding differences of 0.01)
            price_match = abs(expected_total - total_price_float) < 0.01
            
            # Apply highlighting if prices don't match
            price_style = ""
            price_warning = ""
            if not price_match and qty_float > 0 and unit_price_float > 0 and total_price_float > 0:
                price_style = 'background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 8px; margin-top: 5px; border-radius: 4px;'
                price_warning = f'<div style="color: #856404; font-weight: bold; font-size: 0.9em; margin-top: 5px;">⚠️ Price Mismatch: Expected ${expected_total:.2f} ({calculation_display}), Got ${total_price_float:.2f}, Difference: ${abs(expected_total - total_price_float):.2f}</div>'
            
            # Badge for missing codes (for manual attention)
            missing_codes_badge = ''
            if is_group1 and not item.get('has_codes', False):
                missing_codes_badge = '<span style="background: #ffeeba; color: #856404; padding: 2px 6px; border-radius: 3px; font-size: 0.75em; margin-left: 6px;">No UPC/Item#</span>'

            html_content += f"""
                <div class="item-row" style="{price_style if not price_match else ''}">
                    <div style="flex: 2;">
                        <div class="item-name">{product_name}{missing_codes_badge}</div>
                        {unit_info_html}
                    </div>
                    <div class="item-details">
                        <div style="font-size: 1em; margin-bottom: 5px;">
                            <strong>Quantity:</strong> {qty_float:g}{unit_str} | <strong>Unit Price:</strong> ${unit_price_float:.2f} | <strong>Total Price:</strong> ${total_price_float:.2f}
                        </div>
                        <div style="font-size: 0.9em; color: #666; margin-top: 3px;">
                            Calculation: {calculation_display} {'✅' if price_match else '❌'}
                        </div>
                        {price_warning}
                        <div style="font-size: 0.85em; color: #666; margin-top: 3px;">
                            <span class="unit-badge">UoM: {uom_display}</span>
                        </div>
                        {_get_category_badge_html(item)}
                    </div>
                </div>
"""
        
        # Get tax and other charges (always show, even if 0)
        # Handle None values explicitly
        tax_raw = receipt_data.get('tax')
        tax = float(tax_raw) if tax_raw is not None else 0.0
        
        # Get shipping & handling (always show, even if 0)
        shipping_raw = receipt_data.get('shipping')
        shipping = float(shipping_raw) if shipping_raw is not None else 0.0
        
        # Calculate other_charges from fees (bag fee, tips, service fees) if not already set
        # Other charges should include all fees except tax and shipping
        other_charges_raw = receipt_data.get('other_charges')
        other_charges = float(other_charges_raw) if other_charges_raw is not None else 0.0
        
        # Also sum fees from items (items with is_fee=True) if other_charges is not already calculated
        if other_charges == 0.0:
            fee_items = [item for item in receipt_data.get('items', []) if item.get('is_fee', False)]
            if fee_items:
                other_charges = sum(float(item.get('total_price') or 0) for item in fee_items)
        
        subtotal_raw = receipt_data.get('subtotal')
        subtotal = float(subtotal_raw) if subtotal_raw is not None else 0.0
        
        # Get vendor code to apply vendor-specific logic
        vendor_code = receipt_data.get('vendor') or receipt_data.get('detected_vendor_code') or ''
        upper_vendor = vendor_code.upper()
        is_webstaurantstore = 'WEBSTAURANTSTORE' in upper_vendor
        
        # Verify calculated total against receipt total
        calculated_item_total = sum(
            float(item.get('total_price') or 0) 
            for item in items 
            if not item.get('is_fee', False)
        )
        
        # Vendor-specific logic for subtotal calculation
        if is_webstaurantstore:
            # WEBSTAURANTSTORE-specific logic:
            # - Subtotal (summary) is TAX EXCLUDED (sum of unit_price × quantity only)
            # - Item total_price includes tax: total_price = (unit_price × quantity) + item_tax
            # - So sum of item total_price ≠ subtotal (summary) because it includes tax
            # - We MUST use the extracted subtotal (tax excluded) if provided
            if subtotal > 0:
                calculated_subtotal = subtotal
            else:
                # Fallback: calculate from items (unit_price × quantity, tax excluded)
                calculated_subtotal = sum(
                    float(item.get('unit_price') or 0) * float(item.get('quantity') or 0)
                    for item in items 
                    if not item.get('is_fee', False)
                )
        else:
            # For other vendors: use extracted subtotal if provided, otherwise use calculated from items
            if subtotal > 0:
                calculated_subtotal = subtotal
            else:
                calculated_subtotal = calculated_item_total
        
        calculated_total = calculated_subtotal + shipping + tax + other_charges
        receipt_total = receipt_data.get('total', 0.0) or 0.0
        
        # Verify calculated items quantity against items_sold from receipt
        calculated_items_qty = sum(
            float(item.get('quantity') or 0) 
            for item in items 
            if not item.get('is_fee', False)
        )
        receipt_items_sold = receipt_data.get('items_sold')
        
        # Prepare validation messages and check marks
        total_validation_warning = ""
        items_validation_warning = ""
        total_check = ""
        items_check = ""
        
        if receipt_total > 0:
            total_diff = abs(calculated_total - receipt_total)
            if total_diff > 0.01:  # Allow 1 cent tolerance
                total_validation_warning = f'<div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 8px; margin: 10px 0; border-radius: 4px;"><strong>⚠️ Total Mismatch:</strong> Calculated ${calculated_total:.2f} (Subtotal: ${calculated_subtotal:.2f} + Shipping: ${shipping:.2f} + Tax: ${tax:.2f} + Other Charges: ${other_charges:.2f}) ≠ Receipt Total ${receipt_total:.2f}, Difference: ${total_diff:.2f}</div>'
            else:
                total_check = ' <span style="color: #28a745;">✅</span>'
        
        if receipt_items_sold is not None:
            items_sold_float = float(receipt_items_sold)
            items_diff = abs(calculated_items_qty - items_sold_float)
            if items_diff > 0.5:  # Allow 0.5 tolerance for rounding
                items_validation_warning = f'<div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 8px; margin: 10px 0; border-radius: 4px;"><strong>⚠️ Items Quantity Mismatch:</strong> Calculated {calculated_items_qty:.1f} items ≠ Receipt Items Sold {items_sold_float:.1f}, Difference: {items_diff:.1f}</div>'
            else:
                items_check = ' <span style="color: #28a745;">✅</span>'
        
        # Get receipt total (use calculated if not available from receipt)
        total = receipt_data.get('total', 0.0) or calculated_total or 0.0
        
        # RD-specific: label tax as "Total Tax"
        tax_label = 'Total Tax' if ('RD' in upper_vendor or 'RESTAURANT_DEPOT' in upper_vendor) else 'Tax'

        html_content += f"""
            </div>
            <div class="receipt-total" style="padding: 0 20px 20px 20px;">
                {total_validation_warning}
                {items_validation_warning}
                <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                    <tr>
                        <td style="text-align: right; padding: 5px 10px; border-bottom: 1px solid #ddd;">Subtotal:</td>
                        <td style="text-align: right; padding: 5px 10px; border-bottom: 1px solid #ddd; font-weight: bold;">${float(calculated_subtotal):,.2f}</td>
                    </tr>
                    <tr>
                        <td style="text-align: right; padding: 5px 10px; border-bottom: 1px solid #ddd;">Shipping & Handling:</td>
                        <td style="text-align: right; padding: 5px 10px; border-bottom: 1px solid #ddd; font-weight: bold;">${float(shipping):,.2f}</td>
                    </tr>
                    <tr>
                        <td style="text-align: right; padding: 5px 10px; border-bottom: 1px solid #ddd;">{tax_label}:</td>
                        <td style="text-align: right; padding: 5px 10px; border-bottom: 1px solid #ddd; font-weight: bold;">${float(tax):,.2f}</td>
                    </tr>
                    <tr>
                        <td style="text-align: right; padding: 5px 10px; border-bottom: 1px solid #ddd;">Other Charges:</td>
                        <td style="text-align: right; padding: 5px 10px; border-bottom: 1px solid #ddd; font-weight: bold;">${float(other_charges):,.2f}</td>
                    </tr>
                    <tr>
                        <td style="text-align: right; padding: 5px 10px; font-size: 1.1em; font-weight: bold;">Calculated Total:</td>
                        <td style="text-align: right; padding: 5px 10px; font-size: 1.1em; font-weight: bold;">${float(calculated_total):,.2f}{total_check}</td>
                    </tr>
                    <tr>
                        <td style="text-align: right; padding: 5px 10px; font-size: 1.1em; font-weight: bold;">Receipt Total:</td>
                        <td style="text-align: right; padding: 5px 10px; font-size: 1.1em; font-weight: bold;">${float(receipt_total):,.2f}</td>
                    </tr>
                    <tr>
                        <td style="text-align: right; padding: 5px 10px; font-size: 0.9em; color: #666;">Total Items Sold:</td>
                        <td style="text-align: right; padding: 5px 10px; font-size: 0.9em; color: #666;">{receipt_items_sold if receipt_items_sold is not None else "N/A"}{items_check}</td>
                    </tr>
                </table>
            </div>
            </div>
        </div>
"""
    
    html_content += f"""
        <div class="footer">
            <p>Report generated by Receipt Importer Workflow - Step 1</p>
            <p>Total Receipts: {total_receipts} | Total Items: {total_items} | Total Amount: ${total_amount:,.2f}</p>
        </div>
    </div>
</body>
</html>
"""
    
    # Write HTML file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    logger.info(f"Generated HTML report: {output_path}")
    return output_path


def main():
    """Main function"""
    import sys
    from pathlib import Path
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load extracted data
    extracted_file = Path('data/step1_output/extracted_data.json')
    if not extracted_file.exists():
        print(f"ERROR: Extracted data file not found: {extracted_file}")
        sys.exit(1)
    
    with open(extracted_file, 'r', encoding='utf-8') as f:
        extracted_data = json.load(f)
    
    # Generate report
    output_file = Path('data/step1_output/report.html')
    report_path = generate_html_report(extracted_data, output_file)
    
    print(f"\n✓ Report generated successfully!")
    print(f"  Location: {report_path}")
    print(f"\nYou can:")
    print(f"  1. Open {report_path} in your web browser")
    print(f"  2. Print to PDF (File > Print > Save as PDF)")
    print(f"  3. Open in Microsoft Word (File > Open > {report_path})")


if __name__ == '__main__':
    main()

