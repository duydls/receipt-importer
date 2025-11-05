#!/usr/bin/env python3
"""
Unified PDF Processor
Processes PDF receipts using vendor-specific YAML rules for text-based and OCR-based extraction.

This processor replaces all vendor-specific PDF processors (Costco, Jewel, Aldi, Parktoshop, etc.)
by reading parsing rules from YAML files in step1_rules/.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Try to import pdfplumber
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available. Install with: pip install pdfplumber")

# Try to import OCR libraries
try:
    import pytesseract
    from PIL import Image
    import fitz  # PyMuPDF
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.debug("OCR libraries not available. Install with: pip install pytesseract Pillow pymupdf")

# Try to import EasyOCR (better for receipts)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logger.debug("EasyOCR not available. Install with: pip install easyocr")


class UnifiedPDFProcessor:
    """Process PDF receipts using vendor-specific YAML rules"""
    
    def __init__(self, rule_loader, input_dir=None):
        """
        Initialize unified PDF processor
        
        Args:
            rule_loader: RuleLoader instance
            input_dir: Input directory path (for knowledge base location)
        """
        self.rule_loader = rule_loader
        self.input_dir = Path(input_dir) if input_dir else None
        
        # Prepare config with knowledge base file path
        config = {}
        if self.input_dir:
            kb_file = self.input_dir / 'knowledge_base.json'
            if kb_file.exists():
                config['knowledge_base_file'] = str(kb_file)
        
        # Import ReceiptProcessor for knowledge base enrichment
        from .receipt_processor import ReceiptProcessor
        self._legacy_processor = ReceiptProcessor(config=config)
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Process a PDF file using vendor-specific YAML rules
        
        Args:
            file_path: Path to PDF file
            detected_vendor_code: Vendor code from detection (must be provided)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        if not PDFPLUMBER_AVAILABLE:
            logger.error("pdfplumber not available. Cannot process PDF files.")
            return None
        
        if not detected_vendor_code:
            logger.warning(f"No vendor code provided for {file_path.name}")
            return None
        
        try:
            # Skip Mariano's - OCR quality too poor, not supported
            if detected_vendor_code == 'MARIANOS':
                logger.info(f"Skipping Mariano's receipt {file_path.name} - not supported (OCR quality too poor)")
                return None
            
            # Load vendor-specific PDF rules
            pdf_rules = self._load_vendor_pdf_rules(detected_vendor_code)
            if not pdf_rules:
                logger.warning(f"No PDF rules found for vendor: {detected_vendor_code}")
                return None
            
            # Determine extraction method from rules
            extraction_method = pdf_rules.get('extraction_method', 'text')
            
            # Auto-detect if PDF is image-based (try text extraction first, fallback to OCR if no text)
            # Extract text from PDF
            pdf_text = self._extract_pdf_text(file_path, use_ocr=(extraction_method == 'ocr'))
            
            # If text extraction failed and extraction_method is 'text', try OCR as fallback
            if not pdf_text and extraction_method == 'text' and OCR_AVAILABLE:
                logger.debug(f"Text extraction failed for {file_path.name}, trying OCR fallback")
                pdf_text = self._extract_pdf_text_ocr(file_path)
            
            if not pdf_text:
                logger.warning(f"Could not extract text from {file_path.name}")
                return None
            
            # Parse receipt text using rules
            items = self._parse_receipt_text(pdf_text, pdf_rules)
            
            if not items:
                logger.warning(f"No items extracted from {file_path.name}")
                # Still create receipt entry for review if OCR was used
                if extraction_method == 'ocr' or (extraction_method == 'text' and not pdf_text):
                    return {
                        'filename': file_path.name,
                        'vendor': pdf_rules.get('vendor_name', detected_vendor_code),
                        'detected_vendor_code': detected_vendor_code,
                        'detected_source_type': 'localgrocery_based',
                        'source_file': str(file_path.name),
                        'items': [],
                        'parsed_by': pdf_rules.get('parsed_by', 'unified_pdf_v1'),
                        'needs_review': True,
                        'review_reasons': ['No items extracted from OCR - poor image quality or parsing failed'],
                        'subtotal': 0.0,
                        'tax': 0.0,
                        'total': 0.0,
                        'currency': 'USD'
                    }
                return None
            
            # Extract totals from PDF text
            totals = self._extract_totals_from_text(pdf_text, pdf_rules)
            
            # Build receipt data
            receipt_data = {
                'filename': file_path.name,
                'vendor': pdf_rules.get('vendor_name', detected_vendor_code),
                'detected_vendor_code': detected_vendor_code,
                'detected_source_type': 'localgrocery_based',
                'source_file': str(file_path.name),
                'items': items,
                'parsed_by': pdf_rules.get('parsed_by', 'unified_pdf_v1'),
                'subtotal': totals.get('subtotal', 0.0),
                'tax': totals.get('tax', 0.0),
                'total': totals.get('total', 0.0),
                'currency': 'USD'
            }
            
            # Extract additional fields from rules
            if pdf_rules.get('extract_items_sold'):
                items_sold = self._extract_items_sold(pdf_text, pdf_rules)
                if items_sold is not None:
                    receipt_data['items_sold'] = items_sold
            
            if pdf_rules.get('extract_transaction_date'):
                date = self._extract_transaction_date(pdf_text, pdf_rules)
                if date:
                    receipt_data['transaction_date'] = date
            
            # Costco-specific: infer integer quantities using knowledge base unit prices
            if detected_vendor_code == 'COSTCO' and receipt_data.get('items'):
                try:
                    receipt_data['items'] = self._infer_costco_quantities(receipt_data['items'])
                    # Enrich size/spec and UOM from knowledge base
                    receipt_data['items'] = self._enrich_costco_size_and_uom(receipt_data['items'])
                    # Persist new KB entries when possible
                    self._update_knowledge_base_costco(receipt_data['items'])
                except Exception as e:
                    logger.debug(f"Costco quantity inference skipped: {e}")

            # Enrich with knowledge base (general)
            if receipt_data.get('items'):
                receipt_data['items'] = self._enrich_items(receipt_data['items'], detected_vendor_code)
            
            logger.info(f"Extracted {len(items)} items from PDF {file_path.name}")
            if len(items) != len(receipt_data.get('items', [])):
                logger.warning(f"Item count mismatch: parsed {len(items)} items, but receipt_data has {len(receipt_data.get('items', []))} items")
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing PDF {file_path.name}: {e}", exc_info=True)
            return None
    
    def _load_vendor_pdf_rules(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        """Load vendor-specific PDF rules from YAML"""
        # Map vendor codes to YAML file names
        vendor_file_map = {
            'COSTCO': '20_costco_pdf.yaml',
            'JEWEL': '22_jewel_pdf.yaml',
            'JEWELOSCO': '22_jewel_pdf.yaml',
            # 'MARIANOS': '22_marianos_pdf.yaml',  # Mariano's not supported - OCR quality too poor
            'ALDI': '23_aldi_pdf.yaml',
            'PARKTOSHOP': '24_parktoshop_pdf.yaml',
            'RD': '21_rd_pdf_layout.yaml',
            'RESTAURANT_DEPOT': '21_rd_pdf_layout.yaml',
            'WISMETTAC': '31_wismettac_pdf.yaml',
        }
        
        yaml_file = vendor_file_map.get(vendor_code.upper())
        if not yaml_file:
            return None
        
        try:
            rules = self.rule_loader.load_rule_file_by_name(yaml_file)
            # Extract PDF-specific rules (might be nested)
            if 'pdf_rules' in rules:
                return rules['pdf_rules']
            elif 'pdf_layouts' in rules:
                # Find matching layout
                for layout in rules.get('pdf_layouts', []):
                    applies_to = layout.get('applies_to', {})
                    vendor_codes = applies_to.get('vendor_code', [])
                    if vendor_code.upper() in [v.upper() for v in vendor_codes]:
                        return layout
                return rules.get('pdf_layouts', [{}])[0] if rules.get('pdf_layouts') else None
            else:
                # Rules are at top level (new format)
                return rules
        except Exception as e:
            logger.warning(f"Could not load PDF rules from {yaml_file}: {e}")
            return None
    
    def _extract_pdf_text(self, file_path: Path, use_ocr: bool = False) -> str:
        """Extract text from PDF using pdfplumber or OCR"""
        text = ""
        
        # Try pdfplumber first (for text-based PDFs)
        if PDFPLUMBER_AVAILABLE:
            try:
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text(layout=True)
                        if page_text:
                            text += page_text + "\n"
            except Exception as e:
                logger.debug(f"Text extraction failed: {e}")
        
        # If text extraction failed or OCR is required, try OCR
        if (not text or use_ocr) and OCR_AVAILABLE:
            ocr_text = self._extract_pdf_text_ocr(file_path)
            if ocr_text:
                text = ocr_text
        
        return text
    
    def _extract_pdf_text_ocr(self, file_path: Path) -> str:
        """Extract text from image-based PDF using OCR with advanced preprocessing"""
        if not OCR_AVAILABLE:
            return ""
        
        try:
            text = ""
            doc = fitz.open(file_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Try multiple DPI settings for better quality (higher DPI for poor quality images)
                dpi_settings = [600, 400, 300]  # Start with highest, fallback to lower
                best_text = ""
                best_confidence = 0
                
                for dpi in dpi_settings:
                    try:
                        # Render page to image at higher DPI
                        mat = fitz.Matrix(dpi/72, dpi/72)
                        pix = page.get_pixmap(matrix=mat)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        
                        # Apply advanced image preprocessing
                        img = self._preprocess_image_for_ocr_advanced(img)
                        
                        # Use context-aware OCR with multiple attempts
                        ocr_text = self._extract_text_with_context_aware_ocr_advanced(img)
                        
                        if ocr_text:
                            # Score text quality (more alphanumeric chars = better)
                            alpha_count = sum(1 for c in ocr_text if c.isalnum())
                            if alpha_count > best_confidence:
                                best_text = ocr_text
                                best_confidence = alpha_count
                                
                            # If we got good quality text, use it
                            if alpha_count > 200:  # Threshold for good quality
                                break
                    except Exception as e:
                        logger.debug(f"OCR at {dpi} DPI failed: {e}")
                        continue
                
                if best_text:
                    text += best_text + "\n"
                    logger.debug(f"Extracted {len(best_text)} characters from page {page_num + 1} (best confidence: {best_confidence})")
            
            doc.close()
            return text
            
        except Exception as e:
            logger.debug(f"OCR text extraction failed: {e}")
            return ""
    
    def _preprocess_image_for_ocr_advanced(self, img: Image.Image) -> Image.Image:
        """
        Advanced preprocessing for better OCR accuracy using OpenCV:
        - Binarization: Convert to pure black and white (multiple methods)
        - Deskewing: Correct rotation/tilting
        - Scaling: Upscale low-resolution images
        - Perspective correction: Fix non-flat images
        - Noise reduction: Remove artifacts and noise
        - Contrast enhancement: Improve text visibility
        """
        try:
            import cv2
            import numpy as np
            
            # Convert PIL to numpy array
            img_array = np.array(img.convert('RGB'))
            
            # Step 1: Apply perspective correction/deskewing for non-flat images
            img_array = self._correct_perspective(img_array)
            
            # Step 2: Convert to grayscale
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array.copy()
            
            # Step 3: Deskewing - Correct rotation/tilting to make text horizontal
            gray = self._deskew_image(gray)
            
            # Step 4: Scaling - Upscale low-resolution images (if image is too small)
            height, width = gray.shape
            min_dimension = min(height, width)
            if min_dimension < 1500:  # More aggressive upscaling for poor quality images
                scale_factor = 1500 / min_dimension
                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)
                gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
                logger.debug(f"Upscaled image from {width}x{height} to {new_width}x{new_height}")
            
            # Step 5: Advanced noise reduction
            # Use bilateral filter to preserve edges while reducing noise
            gray = cv2.bilateralFilter(gray, 9, 75, 75)
            
            # Additional Gaussian blur for very noisy images
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            
            # Step 5.5: Contrast enhancement (CLAHE - Contrast Limited Adaptive Histogram Equalization)
            try:
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                gray = clahe.apply(gray)
            except:
                # Fallback to simple contrast enhancement
                gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
            
            # Step 6: Binarization - Try multiple methods and pick best
            # Method 1: Otsu's thresholding
            _, binary_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Method 2: Adaptive thresholding (better for uneven lighting)
            binary_adaptive = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            
            # Method 3: Adaptive thresholding with different parameters (for very poor quality)
            binary_adaptive2 = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 5
            )
            
            # Choose best binarization method based on text-like characteristics
            # Good binarization should have reasonable white/black ratio and connected components
            binaries = [
                (binary_otsu, "Otsu's"),
                (binary_adaptive, "Adaptive (11,2)"),
                (binary_adaptive2, "Adaptive (15,5)")
            ]
            
            best_binary = binary_otsu
            best_score = 0
            
            for binary, method_name in binaries:
                # Score based on white pixel ratio (should be between 0.2 and 0.8 for typical receipts)
                white_ratio = np.sum(binary == 255) / binary.size
                
                # Calculate connected components (text should have many small components)
                try:
                    num_labels, labels = cv2.connectedComponents(binary)
                    # Good text images typically have 100+ connected components
                    component_score = min(num_labels / 100, 1.0) if num_labels > 0 else 0
                except:
                    component_score = 0.5
                
                # Combined score: prefer ratios around 0.3-0.7 with good component count
                ratio_score = 1.0 - abs(white_ratio - 0.5) * 2  # Best at 0.5
                combined_score = ratio_score * 0.5 + component_score * 0.5
                
                if combined_score > best_score:
                    best_score = combined_score
                    best_binary = binary
                    logger.debug(f"Selected {method_name} binarization (score: {combined_score:.2f})")
            
            binary = best_binary
            
            # Step 7: Morphological operations to clean up the image
            # Remove small noise (opening)
            kernel = np.ones((2, 2), np.uint8)
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            
            # Convert back to PIL Image
            img = Image.fromarray(binary)
            
        except ImportError:
            # Fallback: PIL-only preprocessing if cv2 not available
            logger.warning("OpenCV not available, using PIL-only preprocessing")
            from PIL import ImageEnhance, ImageFilter
            img = img.convert('L')
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            img = img.filter(ImageFilter.SHARPEN)
            threshold = 128
            img = img.point(lambda x: 255 if x > threshold else 0, mode='1')
        except Exception as e:
            logger.debug(f"Image preprocessing error (using fallback): {e}")
            # Fallback: simple PIL processing
            from PIL import ImageEnhance, ImageFilter
            img = img.convert('L')
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            img = img.filter(ImageFilter.SHARPEN)
            threshold = 128
            img = img.point(lambda x: 255 if x > threshold else 0, mode='1')
        
        return img
    
    def _correct_perspective(self, img_array):
        """Correct perspective distortion for non-flat images"""
        try:
            import cv2
            import numpy as np
            
            # Convert to grayscale for processing
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY) if len(img_array.shape) == 3 else img_array
            
            # Apply Gaussian blur to reduce noise
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # Edge detection
            edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
            
            # Find contours
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Find the largest contour (likely the receipt)
            if contours:
                largest_contour = max(contours, key=cv2.contourArea)
                
                # Approximate contour to polygon
                epsilon = 0.02 * cv2.arcLength(largest_contour, True)
                approx = cv2.approxPolyDP(largest_contour, epsilon, True)
                
                # If we have 4 points, we can do perspective correction
                if len(approx) == 4:
                    # Order points: top-left, top-right, bottom-right, bottom-left
                    pts = approx.reshape(4, 2)
                    rect = self._order_points(pts)
                    
                    # Calculate dimensions of the receipt
                    (tl, tr, br, bl) = rect
                    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
                    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
                    maxWidth = max(int(widthA), int(widthB))
                    
                    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
                    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
                    maxHeight = max(int(heightA), int(heightB))
                    
                    # Destination points for perspective transform
                    dst = np.array([
                        [0, 0],
                        [maxWidth - 1, 0],
                        [maxWidth - 1, maxHeight - 1],
                        [0, maxHeight - 1]
                    ], dtype="float32")
                    
                    # Compute perspective transform matrix
                    M = cv2.getPerspectiveTransform(rect, dst)
                    
                    # Apply perspective correction
                    if len(img_array.shape) == 3:
                        corrected = cv2.warpPerspective(img_array, M, (maxWidth, maxHeight))
                    else:
                        corrected = cv2.warpPerspective(img_array, M, (maxWidth, maxHeight))
                    
                    return corrected
            
            # If perspective correction failed, return original
            return img_array
            
        except Exception as e:
            logger.debug(f"Perspective correction failed: {e}, using original image")
            return img_array
    
    def _order_points(self, pts):
        """Order points in the order: top-left, top-right, bottom-right, bottom-left"""
        import numpy as np
        
        # Initialize ordered coordinates
        rect = np.zeros((4, 2), dtype="float32")
        
        # Sum and difference will give us top-left and bottom-right
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]  # top-left
        rect[2] = pts[np.argmax(s)]  # bottom-right
        
        # Difference will give us top-right and bottom-left
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]  # top-right
        rect[3] = pts[np.argmax(diff)]  # bottom-left
        
        return rect
    
    def _deskew_image(self, img) -> any:
        """
        Deskew image by detecting and correcting rotation angle.
        Uses Hough transform to find text lines and calculate skew angle.
        """
        try:
            import cv2
            import numpy as np
            
            # Detect edges using Canny
            edges = cv2.Canny(img, 50, 150, apertureSize=3)
            
            # Use HoughLines to detect lines in the image
            lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
            
            if lines is None or len(lines) == 0:
                return img  # No lines detected, return original
            
            # Calculate angles of detected lines
            angles = []
            for line in lines:
                rho, theta = line[0]
                # Convert theta to degrees
                angle = np.degrees(theta)
                
                # Normalize angle to [-45, 45] range
                if angle > 45:
                    angle = angle - 90
                elif angle < -45:
                    angle = angle + 90
                
                # Only consider nearly horizontal lines (within ±10 degrees)
                if abs(angle) < 10:
                    angles.append(angle)
            
            if not angles:
                return img  # No horizontal lines found
            
            # Calculate median angle (more robust than mean)
            median_angle = np.median(angles)
            
            # Only correct if angle is significant (more than 0.5 degrees)
            if abs(median_angle) < 0.5:
                return img
            
            # Rotate image to correct skew
            (h, w) = img.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, 
                                     borderMode=cv2.BORDER_REPLICATE)
            
            logger.debug(f"Deskewed image by {median_angle:.2f} degrees")
            return rotated
            
        except Exception as e:
            logger.debug(f"Deskewing failed: {e}, using original image")
            return img
    
    def _extract_text_with_context_aware_ocr_advanced(self, img: Image.Image) -> str:
        """Extract text using advanced context-aware OCR with multiple strategies"""
        # Try EasyOCR first (better for receipts with context awareness)
        if EASYOCR_AVAILABLE:
            try:
                # Initialize EasyOCR reader (English only, optimized for receipts)
                reader = easyocr.Reader(['en'], gpu=False)
                
                # Convert PIL to numpy array
                import numpy as np
                img_array = np.array(img)
                
                # EasyOCR with different parameter settings
                # Try with paragraph mode first (better for structured text)
                try:
                    results = reader.readtext(img_array, paragraph=True, detail=0)
                    ocr_text = '\n'.join(results)
                    if ocr_text and len(ocr_text.strip()) > 50:
                        alpha_count = sum(1 for c in ocr_text if c.isalnum())
                        if alpha_count > 100:  # Good quality threshold
                            logger.debug(f"EasyOCR (paragraph) extracted {len(ocr_text)} characters")
                            return ocr_text
                except:
                    pass
                
                # Fallback to non-paragraph mode
                results = reader.readtext(img_array, paragraph=False, detail=0)
                ocr_text = '\n'.join(results)
                
                if ocr_text and len(ocr_text.strip()) > 50:
                    logger.debug(f"EasyOCR (non-paragraph) extracted {len(ocr_text)} characters")
                    return ocr_text
            except Exception as e:
                logger.debug(f"EasyOCR failed: {e}, falling back to Tesseract")
        
        # Advanced Tesseract with multiple PSM modes and configs
        if OCR_AVAILABLE:
            # Try multiple PSM modes optimized for receipts
            psm_modes = [
                ('6', 'Uniform block of text'),  # Standard for receipts
                ('4', 'Single column of text'),  # For columnar receipts
                ('11', 'Sparse text'),           # For receipts with gaps
                ('3', 'Fully automatic page segmentation'),  # Auto-detect
                ('13', 'Raw line'),              # Single text line
            ]
            
            # Also try different OCR Engine Modes
            oem_modes = ['3', '1']  # LSTM only, then legacy
            
            best_text = ""
            best_confidence = 0
            
            for oem in oem_modes:
                for psm, desc in psm_modes:
                    try:
                        # Try with different configs
                        configs = [
                            f'--oem {oem} --psm {psm}',
                            f'--oem {oem} --psm {psm} -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,$- ',
                            f'--oem {oem} --psm {psm} -c tessedit_pageseg_mode={psm}',
                        ]
                        
                        for tesseract_config in configs:
                            ocr_text = pytesseract.image_to_string(img, config=tesseract_config)
                            
                            if ocr_text:
                                # Score text quality (more alphanumeric chars = better)
                                alpha_count = sum(1 for c in ocr_text if c.isalnum())
                                
                                # Bonus for having numbers and common receipt words
                                has_numbers = any(c.isdigit() for c in ocr_text)
                                has_common_words = any(word in ocr_text.lower() for word in ['total', 'subtotal', 'tax', 'item', 'price', 'quantity'])
                                
                                if has_numbers:
                                    alpha_count += 50
                                if has_common_words:
                                    alpha_count += 30
                                
                                if alpha_count > best_confidence:
                                    best_text = ocr_text
                                    best_confidence = alpha_count
                                    
                                    # If we got very good quality, stop early
                                    if alpha_count > 300:
                                        logger.debug(f"Tesseract extracted {len(best_text)} characters (OEM {oem}, PSM {psm}, high quality)")
                                        return best_text
                    except Exception as e:
                        logger.debug(f"Tesseract OEM {oem} PSM {psm} failed: {e}")
            
            if best_text:
                logger.debug(f"Tesseract extracted {len(best_text)} characters (best confidence: {best_confidence})")
                return best_text
        
        return ""
    
    def _preprocess_image_for_ocr(self, img: Image.Image) -> Image.Image:
        """Legacy method - redirects to advanced preprocessing"""
        return self._preprocess_image_for_ocr_advanced(img)
    
    def _extract_text_with_context_aware_ocr(self, img: Image.Image) -> str:
        """Legacy method - redirects to advanced OCR"""
        return self._extract_text_with_context_aware_ocr_advanced(img)
    
    def _parse_receipt_text(self, text: str, rules: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse receipt text into items using rules from YAML
        
        Args:
            text: PDF text content
            rules: Vendor-specific PDF parsing rules
            
        Returns:
            List of item dictionaries
        """
        items = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Pre-process OCR text for Wismettac (clean OCR errors)
        vendor_name = rules.get('vendor_name', '').upper()
        if 'WISMETTAC' in vendor_name:
            # Clean OCR errors: remove brackets, pipes, normalize spacing
            lines = [self._clean_wismettac_ocr_line(line) for line in lines]
        
        # Find summary section start (from rules)
        summary_keywords = rules.get('summary_keywords', ['SUBTOTAL', 'TAX', 'TOTAL'])
        summary_start = len(lines)
        for i, line in enumerate(lines):
            line_upper = line.upper()
            # Check for summary keywords (exclude false positives)
            exclude_keywords = rules.get('summary_exclude_keywords', [])
            if any(str(kw).upper() in line_upper for kw in summary_keywords):
                if not any(str(ekw).upper() in line_upper for ekw in exclude_keywords):
                    summary_start = i
                    break
        
        # Get item patterns from rules
        item_patterns = rules.get('item_patterns', [])
        
        # Parse product lines
        line_idx = 0
        while line_idx < summary_start:
            line = lines[line_idx]
            
            # Skip non-product lines (from rules)
            skip_keywords = rules.get('skip_keywords', [])
            if any(str(kw).upper() in line.upper() for kw in skip_keywords):
                line_idx += 1
                continue
            
            # Try each pattern in order (from rules)
            match_found = False
            for pattern_def in item_patterns:
                pattern_type = pattern_def.get('type', '')
                regex_str = pattern_def.get('regex', '')
                groups = pattern_def.get('groups', [])
                
                if not regex_str:
                    continue
                
                # Compile regex (flags from rules)
                flags = re.IGNORECASE if pattern_def.get('case_insensitive', True) else 0
                match_text = line
                consumed_lines = 1
                
                if pattern_def.get('multiline'):
                    # Look ahead a few lines for the match
                    lookahead = min(len(lines) - line_idx, 5)
                    match_text = '\n'.join(lines[line_idx:line_idx + lookahead])
                    flags |= re.MULTILINE 
                
                try:
                    pattern = re.compile(regex_str, flags)
                    match = pattern.search(match_text)
                    
                    if match:
                        match_found = True
                        
                        if pattern_def.get('multiline'):
                            # Recalculate consumed lines by checking where the match ends
                            match_end_pos = match.end()
                            consumed_lines = len(match_text[:match_end_pos].split('\n'))
                        else:
                            consumed_lines = 1

                        item_data = {}
                        for idx, group_name in enumerate(groups, 1):
                            if idx <= len(match.groups()):
                                item_data[group_name] = match.group(idx)
                        
                        # Check conditions if specified (from rules)
                        conditions = pattern_def.get('conditions', [])
                        if conditions:
                            if not self._check_conditions(line, match, item_data, conditions):
                                match_found = False
                                continue
                        
                        # Build item using mapping rules
                        item = self._build_item_from_match(item_data, pattern_def, line, rules)
                        
                        if item:
                            # Handle multiline continuation (product name on following lines)
                            if pattern_def.get('multiline_continuation'):
                                product_name, name_lines_consumed = self._extract_multiline_product_name(
                                    lines, line_idx, pattern_def, summary_start
                                )
                                logger.debug(f"Multiline extraction for line {line_idx+1}: returned '{product_name}' (consumed {name_lines_consumed} lines)")
                                if product_name:
                                    item['product_name'] = product_name
                                    logger.debug(f"Set product_name to: '{product_name}'")
                                    # Update consumed_lines to include all product name lines
                                    consumed_lines = 1 + name_lines_consumed  # 1 for item code line + product name lines
                                else:
                                    # If no product name found, skip this item
                                    logger.debug(f"No product name found from multiline extraction, skipping item")
                                    match_found = False
                                    continue
                            
                            # Extract quantity and unit price from next line if specified (from rules)
                            if pattern_def.get('quantity_from_next_line'):
                                qty_info = self._extract_quantity_from_next_line(lines, line_idx, pattern_def)
                                if qty_info:
                                    quantity = qty_info.get('quantity')
                                    unit_price = qty_info.get('unit_price')
                                    if unit_price:
                                        item['unit_price'] = unit_price
                                        # If quantity not found but unit_price found, calculate from total_price
                                        if not quantity and 'total_price' in item and unit_price > 0:
                                            quantity = item['total_price'] / unit_price
                                            item['quantity'] = round(quantity, 2)
                                            logger.debug(f"Calculated quantity from total_price/unit_price: {quantity}")
                                    if quantity:
                                        item['quantity'] = quantity
                                    elif unit_price and 'total_price' in item and unit_price > 0:
                                        # Fallback: calculate quantity from total_price / unit_price
                                        quantity = item['total_price'] / unit_price
                                        item['quantity'] = round(quantity, 2)
                                        logger.debug(f"Calculated quantity from total_price/unit_price: {quantity}")
                                    consumed_lines += 1
                                else:
                                    # If no quantity found, still consume the line if it looks like a quantity line
                                    if line_idx + 1 < len(lines):
                                        next_line = lines[line_idx + 1]
                                        # Check if next line looks like a quantity line (has "x" or "@" with numbers)
                                        if re.search(r'[x@].*\d+[.,]\d', next_line, re.IGNORECASE):
                                            consumed_lines += 1 
                            
                            items.append(item)
                            line_idx += consumed_lines
                            break
                        else:
                            match_found = False
                            
                except Exception as e:
                    logger.debug(f"Error matching pattern {pattern_type}: {e}")
                    continue

            if not match_found:
                line_idx += 1
        
        return items
    
    def _build_item_from_match(self, item_data: Dict[str, str], pattern_def: Dict[str, Any], line: str, rules: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build item dictionary from regex match groups"""
        # Get field mappings from pattern definition or rules
        field_mappings = pattern_def.get('field_mappings', {})
        if not field_mappings:
            field_mappings = rules.get('field_mappings', {})
        
        # Default mappings (generic, not vendor-specific)
        default_mappings = {
            'item_number': 'item_number',
            'product_name': 'product_name',
            'quantity': 'quantity',
            'unit_price': 'unit_price',
            'total_price': 'total_price',
            'price': 'total_price',
        }
        
        # Merge defaults with pattern-specific mappings
        field_mappings = {**default_mappings, **field_mappings}
        
        # Build item
        item = {
            'vendor': rules.get('vendor_name', 'UNKNOWN'),
            'is_summary': False,
        }
        
        # Map fields
        for target_field, source_field in field_mappings.items():
            if source_field in item_data:
                value = item_data[source_field]
                if value is None:
                    continue
                # Apply transformations
                if target_field in ['unit_price', 'total_price', 'quantity']:
                    # Clean and convert to float
                    value_str = str(value).replace(',', '.').replace('$', '').strip()
                    try:
                        item[target_field] = float(value_str)
                    except ValueError:
                        continue
                else:
                    item[target_field] = str(value).strip()
        
        # Apply post-processing rules (from YAML)
        if pattern_def.get('post_process'):
            item = self._apply_post_process(item, pattern_def.get('post_process'), line, rules)
        
        # Validate item
        if not item.get('product_name') and not item.get('total_price'):
            return None
        
        # Set defaults
        if 'quantity' not in item:
            item['quantity'] = 1.0
        if 'unit_price' not in item and 'total_price' in item:
            item['unit_price'] = item['total_price'] / item['quantity'] if item['quantity'] > 0 else item['total_price']
        if 'purchase_uom' not in item:
            item['purchase_uom'] = 'EACH'
        
        return item
    
    def _apply_post_process(self, item: Dict[str, Any], post_process: Dict[str, Any], line: str, rules: Dict[str, Any]) -> Dict[str, Any]:
        """Apply post-processing rules to item (from YAML)"""
        # Extract UoM from product name (patterns from YAML)
        if post_process.get('extract_uom'):
            uom_patterns = post_process.get('uom_patterns', [])
            product_name = item.get('product_name', '')
            
            for pattern_str in uom_patterns:
                match = re.search(pattern_str, product_name, re.IGNORECASE)
                if match:
                    item['purchase_uom'] = match.group(1).upper()
                    item['product_name'] = re.sub(pattern_str, '', product_name, flags=re.IGNORECASE).strip()
                    break
        
        # Infer product name from price (mappings from YAML)
        if post_process.get('infer_product_from_price'):
            price_mappings = post_process.get('price_mappings', {})
            total_price = item.get('total_price', 0)
            
            for price_str, product_name in price_mappings.items():
                try:
                    price_value = float(price_str)
                    if abs(total_price - price_value) < 0.10:
                        item['product_name'] = product_name
                        break
                except ValueError:
                    continue
        
        # Clean product name (generic cleaning, not vendor-specific)
        if post_process.get('clean_product_name'):
            product_name = item.get('product_name', '')
            product_name = re.sub(r'\s+[a-z]\s*$', '', product_name, flags=re.IGNORECASE)
            product_name = re.sub(r'\s+\d+\s*$', '', product_name)
            item['product_name'] = product_name.strip()
        
        return item
    
    def _check_conditions(self, line: str, match: re.Match, item_data: Dict[str, str], conditions: List[str]) -> bool:
        """Check if conditions are met (from YAML rules)"""
        for condition in conditions:
            if condition.startswith('len('):
                try:
                    if 'line' in condition:
                        length = len(line)
                        if '>' in condition:
                            threshold = int(re.search(r'>\s*(\d+)', condition).group(1))
                            if length <= threshold:
                                return False
                        elif '<' in condition:
                            threshold = int(re.search(r'<\s*(\d+)', condition).group(1))
                            if length >= threshold:
                                return False
                except Exception:
                    pass
            elif condition.startswith('total_price'):
                try:
                    if '>' in condition and 'total_price' in item_data:
                        price = float(item_data['total_price'].replace(',', '.').replace('$', ''))
                        if price <= 0:
                            return False
                except Exception:
                    pass
        
        return True
    
    def _extract_multiline_product_name(self, lines: List[str], current_idx: int, pattern_def: Dict[str, Any], summary_start: int) -> tuple:
        """Extract multiline product name from lines around the item code (for Costco format)
        
        Costco format can have product name:
        - Before the item code line (e.g., "HEAVY" then "E 506970 63.96 N" then "CREAM")
        - After the item code line (e.g., "E 512515 8.99 N" then "STRAWBRY")
        - On the same line as item code (e.g., "E 3923 LIMES 3 LB. 6.49 N")
        
        Returns:
            Tuple of (product_name: str, lines_consumed: int)
        """
        max_lines = pattern_def.get('max_continuation_lines', 5)
        exclude_keywords = pattern_def.get('continuation_exclude_keywords', [])
        
        product_lines = []
        lines_consumed = 0
        
        # First, check if there's a product name BEFORE the item code line
        # (Costco sometimes puts product name on previous line, especially when item code is in merged cell)
        if current_idx > 0:
            prev_line = lines[current_idx - 1].strip()
            # Check if previous line looks like a product name (not an item code line, not a summary)
            # Look for lines that are text-only (not starting with "E " and numbers)
            if prev_line and not re.match(r'^E\s+\d+', prev_line):
                prev_upper = prev_line.upper()
                # Check it's not a summary keyword (exact word match, not substring)
                # exclude_keywords like "E", "SUBTOTAL", "TAX", "TOTAL" should match exact words
                is_excluded = False
                for kw in exclude_keywords:
                    kw_upper = str(kw).upper()
                    # Check if keyword is the entire line or is a word in the line
                    if prev_upper == kw_upper or f' {kw_upper} ' in f' {prev_upper} ' or prev_upper.startswith(f'{kw_upper} ') or prev_upper.endswith(f' {kw_upper}'):
                        is_excluded = True
                        break
                
                # Check it's not a price-only line
                is_price = bool(re.match(r'^\s*\d+\.\d{2}\s*N?\s*$', prev_line))
                # Check it's not another item line (like "E 3 WHOLE MILK")
                is_item = bool(re.search(r'^\s*E\s+\d+', prev_line))
                
                if not is_excluded and not is_price and not is_item:
                    # It's likely a product name continuation from previous line
                    # This happens when the item code is in a merged/centered cell spanning multiple product name lines
                    product_lines.insert(0, prev_line)  # Add at beginning
                    logger.debug(f"Found product name before item code: '{prev_line}' (line {current_idx - 1})")
        
        # Then, collect product name lines AFTER the item code/price line
        start_idx = current_idx + 1
        logger.debug(f"Checking next lines starting from index {start_idx} (line {start_idx+1})")
        for i in range(start_idx, min(start_idx + max_lines, summary_start, len(lines))):
            next_line = lines[i].strip()
            logger.debug(f"  Line {i+1}: {repr(next_line)}")
            
            # Stop if we hit another item line (starts with "E " and has item code pattern)
            if re.match(r'^E\s+\d+', next_line):
                logger.debug(f"    -> Matches item pattern, STOPPING")
                break  # Don't count this line, don't add it
            
            # Stop if we hit a summary keyword (exact word match, not substring)
            line_upper = next_line.upper()
            is_excluded = False
            for kw in exclude_keywords:
                kw_upper = str(kw).upper()
                # Check if keyword is the entire line or is a word in the line (word-boundary aware)
                # For single-letter keywords like "E", only match if it's at the start of a new item line
                # (already handled by the item line check above)
                if kw_upper == 'E':
                    # Skip "E" keyword check here - it's already handled by item line pattern
                    continue
                # For multi-letter keywords, check for word boundaries
                if line_upper == kw_upper or f' {kw_upper} ' in f' {line_upper} ' or line_upper.startswith(f'{kw_upper} ') or line_upper.endswith(f' {kw_upper}'):
                    is_excluded = True
                    break
            
            if is_excluded:
                break  # Don't count this line, don't add it
            
            # Stop if line looks like a price-only line (just numbers and N)
            if re.match(r'^\s*\d+\.\d{2}\s*N?\s*$', next_line):
                break  # Don't count this line, don't add it
            
            # Skip empty lines (but still count them as consumed)
            if not next_line:
                lines_consumed += 1  # Count empty lines
                continue
            
            # Add line to product name
            product_lines.append(next_line)
            lines_consumed += 1  # Count this line after we've added it
            logger.debug(f"Added next line to product name: '{next_line}' (line {i})")
        
        if product_lines:
            # Join with space and return with line count
            result_name = ' '.join(product_lines)
            logger.debug(f"Multiline product name extracted: '{result_name}' (consumed {lines_consumed} lines)")
            return result_name, lines_consumed
        
        logger.debug(f"No multiline product name found (consumed {lines_consumed} lines)")
        return None, 0
    
    def _extract_quantity_from_next_line(self, lines: List[str], current_idx: int, pattern_def: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """Extract quantity and unit price from next line (pattern from YAML rules)
        
        Returns:
            Dict with 'quantity' and 'unit_price' keys, or None if not found
        """
        if current_idx + 1 >= len(lines):
            return None
        
        next_line = lines[current_idx + 1]
        # Get quantity pattern from pattern_def (supports both quantity and unit price)
        quantity_pattern = pattern_def.get('quantity_pattern', r'(\d+)\s*(?:x|@)\s*(\d+[.,]\d{1,2})')
        
        match = re.search(quantity_pattern, next_line, re.IGNORECASE)
        if match:
            result = {}
            # Extract quantity (first group)
            if match.lastindex >= 1:
                try:
                    result['quantity'] = float(match.group(1))
                except (ValueError, IndexError):
                    pass
            
            # Extract unit price (second group)
            if match.lastindex >= 2:
                try:
                    unit_price_str = match.group(2).replace(',', '.').replace('$', '').strip()
                    result['unit_price'] = float(unit_price_str)
                except (ValueError, IndexError):
                    pass
            
            if result:
                logger.debug(f"Extracted quantity/unit_price from next line: {result} (line: {repr(next_line)})")
                return result
        else:
            # Try alternative pattern: just look for "x" or "@" followed by unit price
            # This handles OCR errors where quantity might be misread (e.g., "é x 5.39")
            alt_pattern = r'[x@]\s*(\d+[.,]\d{1,2})'
            alt_match = re.search(alt_pattern, next_line, re.IGNORECASE)
            if alt_match:
                try:
                    unit_price_str = alt_match.group(1).replace(',', '.').replace('$', '').strip()
                    result = {'unit_price': float(unit_price_str)}
                    logger.debug(f"Extracted unit_price only from next line: {result} (line: {repr(next_line)})")
                    return result
                except (ValueError, IndexError):
                    pass
            
            logger.debug(f"Quantity pattern didn't match next line: {repr(next_line)} (pattern: {quantity_pattern})")
        return None
    
    def _clean_wismettac_ocr_line(self, line: str) -> str:
        """Clean Wismettac OCR line by removing brackets, pipes, and normalizing spacing"""
        # Remove brackets and pipes
        cleaned = line.replace('[', ' ').replace(']', ' ').replace('|', ' ')
        # Remove multiple spaces
        cleaned = ' '.join(cleaned.split())
        # Normalize hyphens and dashes in numbers
        cleaned = re.sub(r'(\d+)-(\d+)', r'\1.\2', cleaned)  # 1-00 -> 1.00
        return cleaned
    
    def _extract_totals_from_text(self, text: str, rules: Dict[str, Any]) -> Dict[str, float]:
        """Extract subtotal, tax, and total from PDF text using rules (patterns from YAML)"""
        totals = {
            'subtotal': 0.0,
            'tax': 0.0,
            'total': 0.0
        }
        
        # Get total patterns from rules
        total_patterns = rules.get('total_patterns', {})
        
        # Extract subtotal (pattern from YAML)
        if 'subtotal' in total_patterns:
            subtotal_match = re.search(total_patterns['subtotal'], text, re.IGNORECASE | re.MULTILINE)
            if subtotal_match:
                cleaned_val = subtotal_match.group(1).replace(',', '.').replace('$', '')
                try:
                    totals['subtotal'] = float(cleaned_val)
                except ValueError:
                    logger.debug(f"Could not convert subtotal value: {cleaned_val}")
        
        # Extract tax - try multiple patterns and sum them
        tax_amount = 0.0
        
        # Try main tax pattern (can match multiple times)
        if 'tax' in total_patterns:
            tax_matches = re.finditer(total_patterns['tax'], text, re.IGNORECASE | re.MULTILINE)
            for tax_match in tax_matches:
                try:
                    cleaned_val = tax_match.group(1).replace(',', '.').replace('$', '').strip()
                    tax_value = float(cleaned_val)
                    tax_amount += tax_value
                    logger.debug(f"Found tax: ${tax_value:.2f} from pattern 'tax'")
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not convert tax value: {e}")
        
        # Try water tax pattern (separate)
        if 'tax_water' in total_patterns:
            tax_water_match = re.search(total_patterns['tax_water'], text, re.IGNORECASE | re.MULTILINE)
            if tax_water_match:
                try:
                    cleaned_val = tax_water_match.group(1).replace(',', '.').replace('$', '').strip()
                    tax_value = float(cleaned_val)
                    tax_amount += tax_value
                    logger.debug(f"Found tax: ${tax_value:.2f} from pattern 'tax_water'")
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not convert tax_water value: {e}")
        
        # Use combined tax pattern if main pattern didn't find anything (fallback)
        if tax_amount == 0.0 and 'tax_combined' in total_patterns:
            tax_combined_matches = re.finditer(total_patterns['tax_combined'], text, re.IGNORECASE | re.MULTILINE)
            for tax_match in tax_combined_matches:
                try:
                    cleaned_val = tax_match.group(1).replace(',', '.').replace('$', '').strip()
                    tax_value = float(cleaned_val)
                    tax_amount += tax_value
                    logger.debug(f"Found tax: ${tax_value:.2f} from pattern 'tax_combined'")
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not convert tax_combined value: {e}")
        
        if tax_amount > 0.0:
            totals['tax'] = tax_amount
            logger.debug(f"Total tax extracted: ${tax_amount:.2f}")
        
        # Extract total (pattern from YAML, handle special cases like "7 07" -> 7.07 or "11,02" -> 11.02)
        if 'total' in total_patterns:
            total_match = re.search(total_patterns['total'], text, re.IGNORECASE | re.MULTILINE)
            if total_match:
                # Check if we have two groups (dollars and cents separately - handles comma as decimal)
                if len(total_match.groups()) >= 2:
                    dollars = total_match.group(1)
                    cents = total_match.group(2)
                    totals['total'] = float(f"{dollars}.{cents}")
                elif len(total_match.groups()) == 1:
                    # Single group - handle comma as decimal separator
                    cleaned_val = total_match.group(1).replace(',', '.').replace('$', '').strip()
                    try:
                        totals['total'] = float(cleaned_val)
                    except ValueError:
                        logger.debug(f"Could not convert total value: {cleaned_val}")
        
        # For Aldi: SUBTOTAL is before tax, AMOUNT DUE is the real total (after tax)
        # If we have both subtotal and total, verify the math
        vendor_name = rules.get('vendor_name', '').upper()
        if vendor_name == 'ALDI':
            if totals['subtotal'] > 0:
                expected_total = totals['subtotal'] + totals['tax']
                # If total was not extracted or doesn't match expected, use AMOUNT DUE (subtotal + tax)
                if totals['total'] == 0.0 or abs(totals['total'] - expected_total) > 0.10:
                    # AMOUNT DUE should be the real total (subtotal + tax)
                    # Recalculate total from subtotal + tax
                    totals['total'] = expected_total
                    logger.debug(f"Aldi: Set total to subtotal + tax: ${totals['total']:.2f} (subtotal: ${totals['subtotal']:.2f}, tax: ${totals['tax']:.2f})")
                else:
                    logger.debug(f"Aldi: Total matches expected: ${totals['total']:.2f} = ${totals['subtotal']:.2f} + ${totals['tax']:.2f}")
        
        return totals

    # --- Costco quantity inference ---
    _kb_cache = None

    def _load_knowledge_base(self) -> Dict[str, Any]:
        """Load knowledge base JSON once (cached)."""
        if UnifiedPDFProcessor._kb_cache is not None:
            return UnifiedPDFProcessor._kb_cache
        try:
            # Default KB path relative to input_dir if provided
            kb_path = None
            try:
                # Attempt to use legacy processor config if available
                kb_path = Path(self._legacy_processor.config.get('knowledge_base_file')) if getattr(self, '_legacy_processor', None) else None
            except Exception:
                kb_path = None
            if not kb_path:
                kb_path = Path('data/step1_input/knowledge_base.json')
            import json
            with open(kb_path, 'r') as f:
                UnifiedPDFProcessor._kb_cache = json.load(f)
        except Exception:
            UnifiedPDFProcessor._kb_cache = {}
        return UnifiedPDFProcessor._kb_cache

    def _infer_costco_quantities(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """For Costco items without explicit quantity, use KB unit price to infer integer quantity."""
        kb = self._load_knowledge_base()
        updated: List[Dict[str, Any]] = []
        for item in items:
            try:
                item_number = str(item.get('item_number') or '').strip()
                total_price = float(item.get('total_price') or 0)
                quantity = item.get('quantity')
                unit_price = item.get('unit_price')

                # Only infer when quantity is missing/zero and total_price present and KB has price
                kb_entry = kb.get(item_number) if item_number else None
                kb_price = None
                if isinstance(kb_entry, list) and len(kb_entry) >= 4:
                    try:
                        kb_price = float(kb_entry[3])
                    except Exception:
                        kb_price = None

                if total_price > 0 and kb_price and kb_price > 0:
                    # Always infer integer quantity for Costco using KB price
                    inferred_qty = int(round(total_price / kb_price))
                    if inferred_qty < 1:
                        inferred_qty = 1
                    item['quantity'] = int(inferred_qty)
                    item['unit_price'] = float(kb_price)
                elif (unit_price is None or float(unit_price or 0) == 0.0) and total_price > 0 and float(quantity or 0) > 0:
                    # Fallback: derive unit price from total/qty
                    try:
                        item['unit_price'] = round(total_price / float(quantity), 2)
                    except Exception:
                        pass
            except Exception:
                # Don't fail the whole receipt on one item
                pass
            updated.append(item)
        return updated

    def _enrich_costco_size_and_uom(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Set size/spec (raw_uom_text) and purchase_uom for Costco items from KB size text."""
        kb = self._load_knowledge_base()
        def _derive_uom(size_text: str) -> Optional[str]:
            if not size_text:
                return None
            st = size_text.lower()
            if any(u in st for u in [' lb', 'lbs', 'pound']):
                return 'lb'
            if 'fl oz' in st or 'floz' in st or 'oz' in st:
                return 'oz'
            if 'gal' in st or 'gallon' in st:
                return 'gal'
            if 'ct' in st or 'count' in st or 'unit' in st:
                return 'ct'
            return None
        for item in items:
            try:
                item_number = str(item.get('item_number') or '').strip()
                kb_entry = kb.get(item_number) if item_number else None
                size_text = None
                if isinstance(kb_entry, list) and len(kb_entry) >= 3:
                    size_text = kb_entry[2]
                # If KB has size/spec, set raw_uom_text
                if size_text:
                    item['raw_uom_text'] = size_text
                    u = _derive_uom(size_text)
                    if u:
                        item['purchase_uom'] = u
                else:
                    # Try derive size from product_name as fallback
                    pn = (item.get('product_name') or '')
                    # Simple extraction like "3 LB", "2-lbs", "64-fl oz", "3000CT"
                    import re as _re
                    m = _re.search(r'(\d+(?:\.\d+)?)\s*(lb|lbs|fl\s*oz|oz|ct|gallon|gal)\b', pn, _re.I)
                    if m:
                        item['raw_uom_text'] = f"{m.group(1)} {m.group(2)}"
                        u = _derive_uom(item['raw_uom_text'])
                        if u:
                            item['purchase_uom'] = u
            except Exception:
                pass
        return items

    def _update_knowledge_base_costco(self, items: List[Dict[str, Any]]) -> None:
        """Append missing Costco items to KB with inferred unit price and optional size/spec."""
        try:
            kb_path = None
            try:
                kb_path = Path(self._legacy_processor.config.get('knowledge_base_file')) if getattr(self, '_legacy_processor', None) else None
            except Exception:
                kb_path = None
            if not kb_path:
                kb_path = Path('data/step1_input/knowledge_base.json')
            kb = self._load_knowledge_base()
            modified = False
            for item in items:
                try:
                    item_number = str(item.get('item_number') or '').strip()
                    if not item_number:
                        continue
                    if item_number in kb:
                        continue
                    unit_price = float(item.get('unit_price') or 0)
                    if unit_price <= 0:
                        continue
                    product_name = (item.get('product_name') or '').strip()
                    size_text = (item.get('raw_uom_text') or '').strip()
                    entry = [product_name or item_number, 'Costco', size_text, unit_price]
                    kb[item_number] = entry
                    modified = True
                except Exception:
                    continue
            if modified:
                import json as _json
                with open(kb_path, 'w') as f:
                    _json.dump(kb, f, indent=2)
                # Update cache
                UnifiedPDFProcessor._kb_cache = kb
        except Exception as e:
            logger.debug(f"Knowledge base update skipped: {e}")
    
    def _extract_items_sold(self, text: str, rules: Dict[str, Any]) -> Optional[int]:
        """Extract items sold count from text (pattern from YAML)"""
        items_sold_pattern = rules.get('items_sold_pattern', r'TOTAL NUMBER OF ITEMS SOLD\s*=\s*(\d+)')
        match = re.search(items_sold_pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _extract_transaction_date(self, text: str, rules: Dict[str, Any]) -> Optional[str]:
        """Extract transaction date from text (pattern from YAML)"""
        date_pattern = rules.get('date_pattern', r'(\d{2}/\d{2}/\d{4})')
        match = re.search(date_pattern, text)
        if match:
            return match.group(1)
        return None
    
    def _enrich_items(self, items: List[Dict], vendor_code: str) -> List[Dict]:
        """Enrich items with knowledge base data"""
        if not self._legacy_processor:
            return items
        
        # Preserve multiline-extracted product names before enrichment
        # (enrichment might overwrite them if KB lookup finds a match)
        preserved_names = {}
        for item in items:
            if item.get('product_name') and len(item.get('product_name', '').split()) > 1:
                # Multi-word product names are likely from multiline extraction - preserve them
                item_number = item.get('item_number', '')
                if item_number:
                    preserved_names[item_number] = item.get('product_name')
        
        try:
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                enriched_items = self._legacy_processor.enrich_with_vendor_kb(
                    items,
                    vendor_code=vendor_code
                )
                # Restore preserved multiline product names if they were overwritten
                for item in enriched_items:
                    item_number = item.get('item_number', '')
                    if item_number in preserved_names:
                        # Check if enrichment shortened the name (likely overwrote multiline name)
                        original_name = preserved_names[item_number]
                        current_name = item.get('product_name', '')
                        if len(original_name.split()) > len(current_name.split()):
                            # Original name had more words - restore it
                            item['product_name'] = original_name
                            logger.debug(f"Restored multiline product name for item {item_number}: '{original_name}'")
                return enriched_items
        except Exception as e:
            logger.warning(f"Error enriching items: {e}")
        
        return items
    
    def _extract_items_sold(self, text: str, rules: Dict[str, Any]) -> Optional[int]:
        """Extract items sold count from text (pattern from YAML)"""
        items_sold_pattern = rules.get('items_sold_pattern', r'TOTAL NUMBER OF ITEMS SOLD\s*=\s*(\d+)')
        match = re.search(items_sold_pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _extract_transaction_date(self, text: str, rules: Dict[str, Any]) -> Optional[str]:
        """Extract transaction date from text (pattern from YAML)"""
        date_pattern = rules.get('date_pattern', r'(\d{2}/\d{2}/\d{4})')
        match = re.search(date_pattern, text)
        if match:
            return match.group(1)
        return None
    
    def _enrich_items(self, items: List[Dict], vendor_code: str) -> List[Dict]:
        """Enrich items with knowledge base data"""
        if not self._legacy_processor:
            return items
        
        # Preserve multiline-extracted product names before enrichment
        # (enrichment might overwrite them if KB lookup finds a match)
        preserved_names = {}
        for item in items:
            if item.get('product_name') and len(item.get('product_name', '').split()) > 1:
                # Multi-word product names are likely from multiline extraction - preserve them
                item_number = item.get('item_number', '')
                if item_number:
                    preserved_names[item_number] = item.get('product_name')
        
        try:
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                enriched_items = self._legacy_processor.enrich_with_vendor_kb(
                    items,
                    vendor_code=vendor_code
                )
                # Restore preserved multiline product names if they were overwritten
                for item in enriched_items:
                    item_number = item.get('item_number', '')
                    if item_number in preserved_names:
                        # Check if enrichment shortened the name (likely overwrote multiline name)
                        original_name = preserved_names[item_number]
                        current_name = item.get('product_name', '')
                        if len(original_name.split()) > len(current_name.split()):
                            # Original name had more words - restore it
                            item['product_name'] = original_name
                            logger.debug(f"Restored multiline product name for item {item_number}: '{original_name}'")
                return enriched_items
        except Exception as e:
            logger.warning(f"Error enriching items: {e}")
        
        return items
    
    def _extract_items_sold(self, text: str, rules: Dict[str, Any]) -> Optional[int]:
        """Extract items sold count from text (pattern from YAML)"""
        items_sold_pattern = rules.get('items_sold_pattern', r'TOTAL NUMBER OF ITEMS SOLD\s*=\s*(\d+)')
        match = re.search(items_sold_pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _extract_transaction_date(self, text: str, rules: Dict[str, Any]) -> Optional[str]:
        """Extract transaction date from text (pattern from YAML)"""
        date_pattern = rules.get('date_pattern', r'(\d{2}/\d{2}/\d{4})')
        match = re.search(date_pattern, text)
        if match:
            return match.group(1)
        return None
    
    def _enrich_items(self, items: List[Dict], vendor_code: str) -> List[Dict]:
        """Enrich items with knowledge base data"""
        if not self._legacy_processor:
            return items
        
        # Preserve multiline-extracted product names before enrichment
        # (enrichment might overwrite them if KB lookup finds a match)
        preserved_names = {}
        for item in items:
            if item.get('product_name') and len(item.get('product_name', '').split()) > 1:
                # Multi-word product names are likely from multiline extraction - preserve them
                item_number = item.get('item_number', '')
                if item_number:
                    preserved_names[item_number] = item.get('product_name')
        
        try:
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                enriched_items = self._legacy_processor.enrich_with_vendor_kb(
                    items,
                    vendor_code=vendor_code
                )
                # Restore preserved multiline product names if they were overwritten
                for item in enriched_items:
                    item_number = item.get('item_number', '')
                    if item_number in preserved_names:
                        # Check if enrichment shortened the name (likely overwrote multiline name)
                        original_name = preserved_names[item_number]
                        current_name = item.get('product_name', '')
                        if len(original_name.split()) > len(current_name.split()):
                            # Original name had more words - restore it
                            item['product_name'] = original_name
                            logger.debug(f"Restored multiline product name for item {item_number}: '{original_name}'")
                return enriched_items
        except Exception as e:
            logger.warning(f"Error enriching items: {e}")
        
        return items

        return items
    
    def _extract_items_sold(self, text: str, rules: Dict[str, Any]) -> Optional[int]:
        """Extract items sold count from text (pattern from YAML)"""
        items_sold_pattern = rules.get('items_sold_pattern', r'TOTAL NUMBER OF ITEMS SOLD\s*=\s*(\d+)')
        match = re.search(items_sold_pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _extract_transaction_date(self, text: str, rules: Dict[str, Any]) -> Optional[str]:
        """Extract transaction date from text (pattern from YAML)"""
        date_pattern = rules.get('date_pattern', r'(\d{2}/\d{2}/\d{4})')
        match = re.search(date_pattern, text)
        if match:
            return match.group(1)
        return None
    
    def _enrich_items(self, items: List[Dict], vendor_code: str) -> List[Dict]:
        """Enrich items with knowledge base data"""
        if not self._legacy_processor:
            return items
        
        # Preserve multiline-extracted product names before enrichment
        # (enrichment might overwrite them if KB lookup finds a match)
        preserved_names = {}
        for item in items:
            if item.get('product_name') and len(item.get('product_name', '').split()) > 1:
                # Multi-word product names are likely from multiline extraction - preserve them
                item_number = item.get('item_number', '')
                if item_number:
                    preserved_names[item_number] = item.get('product_name')
        
        try:
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                enriched_items = self._legacy_processor.enrich_with_vendor_kb(
                    items,
                    vendor_code=vendor_code
                )
                # Restore preserved multiline product names if they were overwritten
                for item in enriched_items:
                    item_number = item.get('item_number', '')
                    if item_number in preserved_names:
                        # Check if enrichment shortened the name (likely overwrote multiline name)
                        original_name = preserved_names[item_number]
                        current_name = item.get('product_name', '')
                        if len(original_name.split()) > len(current_name.split()):
                            # Original name had more words - restore it
                            item['product_name'] = original_name
                            logger.debug(f"Restored multiline product name for item {item_number}: '{original_name}'")
                return enriched_items
        except Exception as e:
            logger.warning(f"Error enriching items: {e}")
        
        return items
    
    def _extract_items_sold(self, text: str, rules: Dict[str, Any]) -> Optional[int]:
        """Extract items sold count from text (pattern from YAML)"""
        items_sold_pattern = rules.get('items_sold_pattern', r'TOTAL NUMBER OF ITEMS SOLD\s*=\s*(\d+)')
        match = re.search(items_sold_pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _extract_transaction_date(self, text: str, rules: Dict[str, Any]) -> Optional[str]:
        """Extract transaction date from text (pattern from YAML)"""
        date_pattern = rules.get('date_pattern', r'(\d{2}/\d{2}/\d{4})')
        match = re.search(date_pattern, text)
        if match:
            return match.group(1)
        return None
    
    def _enrich_items(self, items: List[Dict], vendor_code: str) -> List[Dict]:
        """Enrich items with knowledge base data"""
        if not self._legacy_processor:
            return items
        
        # Preserve multiline-extracted product names before enrichment
        # (enrichment might overwrite them if KB lookup finds a match)
        preserved_names = {}
        for item in items:
            if item.get('product_name') and len(item.get('product_name', '').split()) > 1:
                # Multi-word product names are likely from multiline extraction - preserve them
                item_number = item.get('item_number', '')
                if item_number:
                    preserved_names[item_number] = item.get('product_name')
        
        try:
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                enriched_items = self._legacy_processor.enrich_with_vendor_kb(
                    items,
                    vendor_code=vendor_code
                )
                # Restore preserved multiline product names if they were overwritten
                for item in enriched_items:
                    item_number = item.get('item_number', '')
                    if item_number in preserved_names:
                        # Check if enrichment shortened the name (likely overwrote multiline name)
                        original_name = preserved_names[item_number]
                        current_name = item.get('product_name', '')
                        if len(original_name.split()) > len(current_name.split()):
                            # Original name had more words - restore it
                            item['product_name'] = original_name
                            logger.debug(f"Restored multiline product name for item {item_number}: '{original_name}'")
                return enriched_items
        except Exception as e:
            logger.warning(f"Error enriching items: {e}")
        
        return items
