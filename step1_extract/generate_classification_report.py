"""
Generate Classification Report
Creates a dedicated report showing category classification statistics and unmapped items
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple
from collections import defaultdict, Counter
import csv

logger = logging.getLogger(__name__)


def generate_classification_report(
    all_receipts_data: Dict[str, Any],
    output_dir: Path
) -> Tuple[Path, Path]:
    """
    Generate classification report (HTML + CSV)
    
    Args:
        all_receipts_data: Combined data from all receipt types
        output_dir: Base output directory
        
    Returns:
        Tuple of (html_path, csv_path)
    """
    logger.info("Generating category classification report...")
    
    # Collect all items across all receipts
    all_items = []
    for receipt_id, receipt_data in all_receipts_data.items():
        items = receipt_data.get('items', [])
        vendor_code = receipt_data.get('vendor_code') or receipt_data.get('detected_vendor_code', 'UNKNOWN')
        source_type = receipt_data.get('source_type', 'unknown')
        
        for item in items:
            if not item.get('is_fee', False):  # Exclude fee items
                item_copy = item.copy()
                item_copy['_receipt_id'] = receipt_id
                item_copy['_vendor_code'] = vendor_code
                item_copy['_source_type'] = source_type
                all_items.append(item_copy)
    
    # Calculate statistics
    stats = _calculate_statistics(all_items)
    
    # Generate HTML report
    html_path = output_dir / 'classification_report.html'
    _generate_html(stats, all_items, html_path)
    
    # Generate CSV report
    csv_path = output_dir / 'classification_report.csv'
    _generate_csv(stats, all_items, csv_path)
    
    logger.info(f"Generated classification report: {html_path}")
    logger.info(f"Generated classification CSV: {csv_path}")
    
    return html_path, csv_path


def _calculate_statistics(items: List[Dict]) -> Dict[str, Any]:
    """Calculate classification statistics"""
    total_items = len(items)
    total_spend = sum(float(item.get('total_price') or 0) for item in items)
    total_qty = sum(float(item.get('quantity') or 0) for item in items)
    
    # Count by L1
    l1_stats = defaultdict(lambda: {'count': 0, 'spend': 0.0, 'qty': 0.0, 'vendors': set()})
    for item in items:
        l1 = item.get('l1_category', 'A99')
        l1_name = item.get('l1_category_name', 'Unknown')
        vendor = item.get('_vendor_code', 'UNKNOWN')
        l1_stats[l1]['name'] = l1_name
        l1_stats[l1]['count'] += 1
        l1_stats[l1]['spend'] += float(item.get('total_price') or 0)
        l1_stats[l1]['qty'] += float(item.get('quantity') or 0)
        l1_stats[l1]['vendors'].add(vendor)
    
    # Count by L2
    l2_stats = defaultdict(lambda: {'count': 0, 'spend': 0.0, 'qty': 0.0, 'l1': None, 'vendors': set()})
    for item in items:
        l2 = item.get('l2_category', 'C99')
        l2_name = item.get('l2_category_name', 'Unknown')
        l1 = item.get('l1_category', 'A99')
        vendor = item.get('_vendor_code', 'UNKNOWN')
        l2_stats[l2]['name'] = l2_name
        l2_stats[l2]['l1'] = l1
        l2_stats[l2]['count'] += 1
        l2_stats[l2]['spend'] += float(item.get('total_price') or 0)
        l2_stats[l2]['qty'] += float(item.get('quantity') or 0)
        l2_stats[l2]['vendors'].add(vendor)
    
    # Count by source type
    source_stats = Counter(item['_source_type'] for item in items)
    
    # Count by vendor
    vendor_stats = defaultdict(lambda: {'count': 0, 'spend': 0.0})
    for item in items:
        vendor = item.get('_vendor_code', 'UNKNOWN')
        vendor_stats[vendor]['count'] += 1
        vendor_stats[vendor]['spend'] += float(item.get('total_price') or 0)
    
    # Count classified vs unmapped
    classified_count = sum(1 for item in items if item.get('l2_category') != 'C99')
    unmapped_count = total_items - classified_count
    
    # Count needing review
    review_count = sum(1 for item in items if item.get('needs_category_review', False))
    
    # Top 5 L2 by spend
    top_l2_by_spend = sorted(
        l2_stats.items(),
        key=lambda x: x[1]['spend'],
        reverse=True
    )[:5]
    
    return {
        'total_items': total_items,
        'total_spend': total_spend,
        'total_qty': total_qty,
        'classified_count': classified_count,
        'unmapped_count': unmapped_count,
        'review_count': review_count,
        'classification_rate': (classified_count / total_items * 100) if total_items > 0 else 0,
        'l1_stats': dict(l1_stats),
        'l2_stats': dict(l2_stats),
        'source_stats': dict(source_stats),
        'vendor_stats': dict(vendor_stats),
        'top_l2_by_spend': top_l2_by_spend
    }


def _generate_html(stats: Dict, items: List[Dict], output_path: Path):
    """Generate HTML classification report"""
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Category Classification Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            border-bottom: 2px solid #ecf0f1;
            padding-bottom: 5px;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .kpi-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .kpi-card h3 {{
            font-size: 2em;
            margin: 0;
        }}
        .kpi-card p {{
            margin: 5px 0 0 0;
            opacity: 0.9;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
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
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 500;
        }}
        .badge-green {{
            background: #28a745;
            color: white;
        }}
        .badge-yellow {{
            background: #ffc107;
            color: #333;
        }}
        .badge-red {{
            background: #dc3545;
            color: white;
        }}
        .badge-gray {{
            background: #6c757d;
            color: white;
        }}
        .unmapped-section {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .chart-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 30px;
            margin: 30px 0;
        }}
        .chart-container {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .chart-container h3 {{
            margin-top: 0;
            color: #2c3e50;
            text-align: center;
        }}
        canvas {{
            max-height: 400px;
        }}
    </style>
    <style media="print">
        @page {{
            size: letter;
            margin: 0.5in;
        }}
        body {{
            font-size: 10pt;
        }}
        .kpi-card {{
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        table {{
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        h1, h2, h3 {{
            break-after: avoid;
            page-break-after: avoid;
        }}
        .chart-container {{
            break-inside: avoid;
            page-break-inside: avoid;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Category Classification Report</h1>
        <p style="color: #666;">Generated classification statistics for all receipt items</p>
        
        <h2>Summary KPIs</h2>
        <div class="kpi-grid">
            <div class="kpi-card">
                <h3>{stats['total_items']}</h3>
                <p>Total Items</p>
            </div>
            <div class="kpi-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">
                <h3>${stats['total_spend']:,.2f}</h3>
                <p>Total Spend</p>
            </div>
            <div class="kpi-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);">
                <h3>{stats['classification_rate']:.1f}%</h3>
                <p>Classification Rate</p>
            </div>
            <div class="kpi-card" style="background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);">
                <h3>{stats['classified_count']}</h3>
                <p>Classified Items</p>
            </div>
            <div class="kpi-card" style="background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);">
                <h3>{stats['unmapped_count']}</h3>
                <p>Unmapped (C99)</p>
            </div>
            <div class="kpi-card" style="background: linear-gradient(135deg, #fccb90 0%, #d57eeb 100%);">
                <h3>{stats['review_count']}</h3>
                <p>Need Review</p>
            </div>
        </div>
        
        <h2>📈 Category Distribution</h2>
        <div class="chart-grid">
            <div class="chart-container">
                <h3>L1 Categories by Item Count</h3>
                <canvas id="l1ItemChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>L1 Categories by Spend</h3>
                <canvas id="l1SpendChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>Top 10 L2 Categories</h3>
                <canvas id="l2Chart"></canvas>
            </div>
            <div class="chart-container">
                <h3>Vendors by Spend</h3>
                <canvas id="vendorChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>Classification Sources</h3>
                <canvas id="sourceChart"></canvas>
            </div>
        </div>
        
        <h2>L1 Category Breakdown (Accounting)</h2>
        <table>
            <tr>
                <th>L1 Category</th>
                <th>Item Count</th>
                <th>Total Spend</th>
                <th>% of Total Spend</th>
                <th>Vendors</th>
            </tr>
"""
    
    # L1 breakdown
    for l1_id in sorted(stats['l1_stats'].keys()):
        l1_data = stats['l1_stats'][l1_id]
        pct_spend = (l1_data['spend'] / stats['total_spend'] * 100) if stats['total_spend'] > 0 else 0
        # Convert set to sorted list for display
        vendors_list = sorted(list(l1_data.get('vendors', set())))
        vendors_display = ', '.join(vendors_list) if vendors_list else 'N/A'
        
        html += f"""
            <tr>
                <td><strong>{l1_id}</strong> - {l1_data['name']}</td>
                <td>{l1_data['count']}</td>
                <td>${l1_data['spend']:,.2f}</td>
                <td>{pct_spend:.1f}%</td>
                <td>{vendors_display}</td>
            </tr>
"""
    
    html += """
        </table>
        
        <h2>L2 Category Details (Operational)</h2>
        <table>
            <tr>
                <th>L2 Category</th>
                <th>Parent L1</th>
                <th>Item Count</th>
                <th>Total Spend</th>
                <th>Vendors</th>
            </tr>
"""
    
    # L2 breakdown (sorted by spend)
    sorted_l2 = sorted(stats['l2_stats'].items(), key=lambda x: x[1]['spend'], reverse=True)
    for l2_id, l2_data in sorted_l2[:20]:  # Top 20
        vendors_list = sorted(list(l2_data.get('vendors', set())))
        vendors_display = ', '.join(vendors_list) if vendors_list else 'N/A'
        
        html += f"""
            <tr>
                <td><strong>{l2_id}</strong> - {l2_data['name']}</td>
                <td>{l2_data['l1']}</td>
                <td>{l2_data['count']}</td>
                <td>${l2_data['spend']:,.2f}</td>
                <td>{vendors_display}</td>
            </tr>
"""
    
    html += """
        </table>
        
        <h2>Unmapped Items Queue (Needs Review)</h2>
        <div class="unmapped-section">
            <p><strong>⚠️ {unmapped_count} items</strong> need manual classification (L2=C99 or confidence < 0.60)</p>
        </div>
        <table>
            <tr>
                <th>Product Name</th>
                <th>Vendor</th>
                <th>Source</th>
                <th>Price</th>
                <th>Current Category</th>
                <th>Confidence</th>
            </tr>
""".format(unmapped_count=stats['review_count'])
    
    # Show items needing review
    review_items = [item for item in items if item.get('needs_category_review', False)]
    for item in review_items[:50]:  # Limit to 50
        product_name = item.get('product_name', 'Unknown')[:80]
        vendor = item['_vendor_code']
        source = item['_source_type']
        price = float(item.get('total_price') or 0)
        l2_cat = item.get('l2_category', 'C99')
        l2_name = item.get('l2_category_name', 'Unknown')
        confidence = item.get('category_confidence', 0)
        
        html += f"""
            <tr>
                <td>{product_name}</td>
                <td><span class="badge badge-gray">{vendor}</span></td>
                <td>{source}</td>
                <td>${price:.2f}</td>
                <td>{l2_cat} - {l2_name}</td>
                <td>{confidence:.0%}</td>
            </tr>
"""
    
    html += """
        </table>
    </div>
    
    <script>
        // Prepare data for charts
        const l1Data = """ + json.dumps({
            'labels': [f"{k} - {v['name']}" for k, v in sorted(stats['l1_stats'].items())],
            'counts': [v['count'] for k, v in sorted(stats['l1_stats'].items())],
            'spend': [round(v['spend'], 2) for k, v in sorted(stats['l1_stats'].items())]
        }) + """;
        
        const l2Data = """ + json.dumps({
            'labels': [f"{k} - {v['name']}" for k, v in sorted(stats['l2_stats'].items(), key=lambda x: x[1]['count'], reverse=True)[:10]],
            'counts': [v['count'] for k, v in sorted(stats['l2_stats'].items(), key=lambda x: x[1]['count'], reverse=True)[:10]]
        }) + """;
        
        const sourceData = """ + json.dumps({
            k: sum(1 for item in items if item.get('category_source') == k)
            for k in set(item.get('category_source', 'unknown') for item in items)
        }) + """;
        
        const vendorData = """ + json.dumps({
            'labels': [k for k in sorted(stats['vendor_stats'].keys())],
            'counts': [stats['vendor_stats'][k]['count'] for k in sorted(stats['vendor_stats'].keys())],
            'spend': [round(stats['vendor_stats'][k]['spend'], 2) for k in sorted(stats['vendor_stats'].keys())]
        }) + """;
        
        // Color palette
        const colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
            '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0', '#FF6384',
            '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40'
        ];
        
        // L1 Item Count Chart
        new Chart(document.getElementById('l1ItemChart'), {
            type: 'pie',
            data: {
                labels: l1Data.labels,
                datasets: [{
                    data: l1Data.counts,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, font: { size: 10 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return label + ': ' + value + ' items (' + percentage + '%)';
                            }
                        }
                    }
                }
            }
        });
        
        // L1 Spend Chart
        new Chart(document.getElementById('l1SpendChart'), {
            type: 'pie',
            data: {
                labels: l1Data.labels,
                datasets: [{
                    data: l1Data.spend,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, font: { size: 10 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return label + ': $' + value.toFixed(2) + ' (' + percentage + '%)';
                            }
                        }
                    }
                }
            }
        });
        
        // L2 Chart (Top 10)
        new Chart(document.getElementById('l2Chart'), {
            type: 'doughnut',
            data: {
                labels: l2Data.labels,
                datasets: [{
                    data: l2Data.counts,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, font: { size: 9 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                return label + ': ' + value + ' items';
                            }
                        }
                    }
                }
            }
        });
        
        // Vendor Chart
        new Chart(document.getElementById('vendorChart'), {
            type: 'pie',
            data: {
                labels: vendorData.labels,
                datasets: [{
                    data: vendorData.spend,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, font: { size: 10 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return label + ': $' + value.toFixed(2) + ' (' + percentage + '%)';
                            }
                        }
                    }
                }
            }
        });
        
        // Source Chart
        const sourceLabels = Object.keys(sourceData);
        const sourceValues = Object.values(sourceData);
        
        new Chart(document.getElementById('sourceChart'), {
            type: 'pie',
            data: {
                labels: sourceLabels.map(s => s.charAt(0).toUpperCase() + s.slice(1)),
                datasets: [{
                    data: sourceValues,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, font: { size: 11 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return label + ': ' + value + ' items (' + percentage + '%)';
                            }
                        }
                    }
                }
            }
        });
    </script>
</body>
</html>
"""
    
    output_path.write_text(html, encoding='utf-8')


def _generate_csv(stats: Dict, items: List[Dict], output_path: Path):
    """Generate CSV classification report"""
    
    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Write summary
        writer.writerow(['Category Classification Report'])
        writer.writerow([])
        writer.writerow(['Total Items', stats['total_items']])
        writer.writerow(['Total Spend', f"${stats['total_spend']:.2f}"])
        writer.writerow(['Classification Rate', f"{stats['classification_rate']:.1f}%"])
        writer.writerow(['Classified Items', stats['classified_count']])
        writer.writerow(['Unmapped Items', stats['unmapped_count']])
        writer.writerow(['Items Needing Review', stats['review_count']])
        writer.writerow([])
        
        # Write L1 breakdown
        writer.writerow(['L1 Category Breakdown'])
        writer.writerow(['L1 ID', 'L1 Name', 'Item Count', 'Total Spend', '% of Total'])
        for l1_id in sorted(stats['l1_stats'].keys()):
            l1_data = stats['l1_stats'][l1_id]
            pct = (l1_data['spend'] / stats['total_spend'] * 100) if stats['total_spend'] > 0 else 0
            writer.writerow([
                l1_id,
                l1_data['name'],
                l1_data['count'],
                f"${l1_data['spend']:.2f}",
                f"{pct:.1f}%"
            ])
        writer.writerow([])
        
        # Write unmapped items
        writer.writerow(['Unmapped Items (Need Review)'])
        writer.writerow(['Product Name', 'Vendor', 'Source', 'Price', 'Current L2', 'Confidence', 'Receipt ID'])
        review_items = [item for item in items if item.get('needs_category_review', False)]
        for item in review_items:
            writer.writerow([
                item.get('product_name', 'Unknown'),
                item['_vendor_code'],
                item['_source_type'],
                f"${float(item.get('total_price') or 0):.2f}",
                f"{item.get('l2_category', 'C99')} - {item.get('l2_category_name', 'Unknown')}",
                f"{item.get('category_confidence', 0):.0%}",
                item['_receipt_id']
            ])

