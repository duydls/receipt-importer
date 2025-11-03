"""
PDF Generator for HTML Reports
Provides utility functions to generate PDF versions of HTML reports
"""

import logging
from pathlib import Path
import subprocess
import sys

logger = logging.getLogger(__name__)


def html_to_pdf_chrome(html_path: Path, pdf_path: Path) -> bool:
    """
    Convert HTML to PDF using Chrome/Chromium headless mode
    
    Args:
        html_path: Path to HTML file
        pdf_path: Path for output PDF
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Try common Chrome/Chromium paths on macOS
        chrome_paths = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        ]
        
        chrome_cmd = None
        for path in chrome_paths:
            if Path(path).exists():
                chrome_cmd = path
                break
        
        if not chrome_cmd:
            logger.warning("Chrome/Chromium not found, skipping PDF generation")
            return False
        
        # Convert to absolute path and file:// URL
        html_file_url = f"file://{html_path.absolute()}"
        
        # Run Chrome headless to generate PDF
        cmd = [
            chrome_cmd,
            '--headless',
            '--disable-gpu',
            '--print-to-pdf=' + str(pdf_path.absolute()),
            '--no-margins',  # Remove default margins for better use of space
            '--print-to-pdf-no-header',  # Remove header/footer
            html_file_url
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and pdf_path.exists():
            logger.info(f"Generated PDF: {pdf_path}")
            return True
        else:
            logger.warning(f"PDF generation failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.warning("PDF generation timed out")
        return False
    except Exception as e:
        logger.warning(f"PDF generation error: {e}")
        return False


def generate_pdf_for_report(html_path: Path) -> Path:
    """
    Generate PDF version of an HTML report
    
    Args:
        html_path: Path to HTML report
        
    Returns:
        Path to generated PDF (or HTML path if PDF generation failed)
    """
    pdf_path = html_path.with_suffix('.pdf')
    
    if html_to_pdf_chrome(html_path, pdf_path):
        logger.info(f"✅ PDF generated: {pdf_path.name}")
        return pdf_path
    else:
        logger.info(f"⚠️  PDF generation skipped (Chrome not available)")
        logger.info(f"   You can manually print {html_path.name} to PDF from your browser")
        return html_path


def generate_pdfs_for_all_reports(output_dir: Path) -> dict:
    """
    Generate PDF versions of all HTML reports in output directory
    
    Args:
        output_dir: Base output directory
        
    Returns:
        Dictionary mapping report names to PDF paths
    """
    pdfs = {}
    
    # Find all HTML reports
    html_reports = {
        'classification_report': output_dir / 'classification_report.html',
        'combined_report': output_dir / 'report.html',
        'localgrocery_report': output_dir / 'localgrocery_based' / 'report.html',
        'instacart_report': output_dir / 'instacart_based' / 'report.html',
        'bbi_report': output_dir / 'bbi_based' / 'report.html',
        'amazon_report': output_dir / 'amazon_based' / 'report.html',
    }
    
    logger.info("Generating PDF versions of reports...")
    
    for name, html_path in html_reports.items():
        if html_path.exists():
            pdf_path = generate_pdf_for_report(html_path)
            pdfs[name] = pdf_path
        else:
            logger.debug(f"Skipping {name} (file not found)")
    
    # Count successful PDFs
    pdf_count = sum(1 for path in pdfs.values() if path.suffix == '.pdf')
    logger.info(f"PDF generation complete: {pdf_count}/{len(pdfs)} reports")
    
    return pdfs


def add_print_friendly_styles(html_content: str) -> str:
    """
    Add print-friendly CSS to HTML content
    
    Args:
        html_content: HTML string
        
    Returns:
        HTML with print styles added
    """
    print_css = """
    <style media="print">
        @page {
            size: letter;
            margin: 0.5in;
        }
        
        body {
            font-size: 10pt;
        }
        
        .kpi-card {
            break-inside: avoid;
            page-break-inside: avoid;
        }
        
        table {
            break-inside: avoid;
            page-break-inside: avoid;
        }
        
        h1, h2, h3 {
            break-after: avoid;
            page-break-after: avoid;
        }
        
        .chart-container {
            break-inside: avoid;
            page-break-inside: avoid;
        }
        
        /* Hide interactive elements in print */
        button, .no-print {
            display: none;
        }
    </style>
    """
    
    # Insert before </head>
    if '</head>' in html_content:
        html_content = html_content.replace('</head>', print_css + '\n</head>')
    
    return html_content

