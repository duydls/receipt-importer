#!/usr/bin/env python3
"""
AI Line Interpreter - Optional module for parsing receipt lines using local LLM
Falls back to semantic interpretation when regex parsing fails
"""

import re
import json
import logging
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)

# Check for available LLM backends
AI_AVAILABLE = False
AI_BACKEND = None

# Priority: Ollama > Transformers (local LLMs only - no API keys required)
try:
    # Try Ollama (local LLM API)
    import requests
    try:
        response = requests.get('http://localhost:11434/api/tags', timeout=1)
        if response.status_code == 200:
            AI_AVAILABLE = True
            AI_BACKEND = 'ollama'
            logger.info("Ollama LLM backend detected")
    except:
        pass
except ImportError:
    pass

if not AI_AVAILABLE:
    try:
        # Try transformers (Hugging Face local models)
        from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
        AI_AVAILABLE = True
        AI_BACKEND = 'transformers'
        logger.info("Transformers backend available")
    except ImportError:
        pass


class AILineInterpreter:
    """Interpret receipt lines using local LLM when regex parsing fails"""
    
    def __init__(self, config: Optional[Dict] = None, rule_loader=None):
        """
        Initialize AI line interpreter
        
        Args:
            config: Configuration dict with LLM settings (legacy, for backward compatibility)
            rule_loader: Optional RuleLoader instance to load rules from YAML
        """
        # Store rule_loader for fallback rule lookup
        self.rule_loader = rule_loader
        
        # Load AI fallback rules (vendor-based control)
        self.ai_fallback_rules = {}
        if rule_loader:
            self.ai_fallback_rules = rule_loader.get_ai_fallback_rules()
        self.enabled_for_vendors = self.ai_fallback_rules.get('enabled_for_vendors', [])
        self.max_lines = self.ai_fallback_rules.get('max_lines', 50)
        
        # Load rules from rule_loader if available, otherwise use config
        if rule_loader:
            rules = rule_loader.get_ai_interpreter_rules()
            # Merge config over rules (config takes precedence for backward compatibility)
            self.config = {**rules, **(config or {})}
        else:
            self.config = config or {}
        
        self.enabled = self.config.get('enabled', True) and AI_AVAILABLE
        self.backend = self.config.get('backend', AI_BACKEND)
        self.model_name = self.config.get('model_name', 'llama3.2:1b' if AI_BACKEND == 'ollama' else 'gpt2')
        # Load vendor list from rules (for legacy heuristics-based fallback)
        self.use_for_vendors = self.config.get('use_for_vendors', ['Restaurant Depot', 'Mariano'])
        self.max_retries = self.config.get('max_retries', 2)
        self.temperature = self.config.get('temperature', 0.1)  # Low temperature for consistency
        
        self._pipeline = None
        self._model = None
        self._tokenizer = None
        
        if self.enabled:
            self._initialize_backend()
    
    def _initialize_backend(self):
        """Initialize LLM backend"""
        if self.backend == 'ollama':
            self._initialize_ollama()
        elif self.backend == 'transformers':
            self._initialize_transformers()
        else:
            logger.warning(f"Unknown AI backend: {self.backend}. Only 'ollama' and 'transformers' are supported.")
            self.enabled = False
    
    def _initialize_ollama(self):
        """Initialize Ollama backend"""
        try:
            import requests
            self._ollama_base_url = self.config.get('ollama_base_url', 'http://localhost:11434')
            
            # Check if model is available
            response = requests.get(f'{self._ollama_base_url}/api/tags', timeout=5)
            if response.status_code == 200:
                models = [tag['name'] for tag in response.json().get('models', [])]
                if self.model_name not in models:
                    logger.warning(f"Model {self.model_name} not found. Available: {models}")
                    logger.info(f"Attempting to use first available model")
                    if models:
                        self.model_name = models[0]
                    else:
                        self.enabled = False
                        return
                
                logger.info(f"Using Ollama model: {self.model_name}")
            else:
                logger.warning("Ollama API not accessible")
                self.enabled = False
        except Exception as e:
            logger.warning(f"Failed to initialize Ollama: {e}")
            self.enabled = False
    
    def _initialize_transformers(self):
        """Initialize transformers backend"""
        try:
            from transformers import pipeline
            self._pipeline = pipeline(
                'text-generation',
                model=self.model_name,
                tokenizer=self.model_name,
                max_length=200,
                temperature=self.temperature,
                do_sample=True,
                device=-1  # CPU by default
            )
            logger.info(f"Using transformers model: {self.model_name}")
        except Exception as e:
            logger.warning(f"Failed to initialize transformers: {e}")
            self.enabled = False
    
    def should_interpret(self, line: str, vendor: Optional[str] = None) -> bool:
        """
        Check if line should be interpreted by AI
        
        Args:
            line: Receipt line text
            vendor: Vendor name or vendor code (if provided)
            
        Returns:
            True if AI interpretation should be used
        """
        if not self.enabled:
            return False
        
        # First check: If ai_fallback rules exist, check vendor against enabled_for_vendors list
        # This is the primary gate - vendor must be in the list to use AI
        if vendor and self.enabled_for_vendors:
            # Normalize vendor to vendor code for comparison
            vendor_upper = vendor.upper()
            # Check if vendor code matches any enabled vendor
            vendor_match = False
            for enabled_vendor in self.enabled_for_vendors:
                enabled_vendor_upper = enabled_vendor.upper()
                # Exact match or contains match (e.g., "RD" matches "Restaurant Depot" via vendor code)
                if vendor_upper == enabled_vendor_upper or enabled_vendor_upper in vendor_upper:
                    vendor_match = True
                    break
            
            # If vendor is not in enabled list, do not use AI
            if not vendor_match:
                logger.debug(f"Vendor '{vendor}' not in ai_fallback.enabled_for_vendors list, skipping AI interpretation")
                return False
        
        # Legacy check: Check if vendor is in use_for_vendors list (from ai_line_interpreter rules)
        # This is for backward compatibility with old heuristics-based approach
        if vendor and not self.enabled_for_vendors:
            vendor_lower = vendor.lower()
            if any(allowed_vendor.lower() in vendor_lower for allowed_vendor in self.use_for_vendors):
                return True
        
        # Load heuristics from rules
        heuristics = self.config.get('heuristics', {})
        
        # Check if line has numbers and letters (from rules)
        if heuristics.get('has_numbers', True):
            has_numbers = bool(re.search(r'\d+', line))
        else:
            has_numbers = False
        
        if heuristics.get('has_letters', True):
            has_letters = bool(re.search(r'[A-Za-z]', line))
        else:
            has_letters = False
        
        # Use AI if line has both numbers and letters but no clear price pattern (from rules)
        if has_numbers and has_letters and heuristics.get('use_if_no_price_pattern', True):
            # Load price patterns from rules
            price_patterns = heuristics.get('price_patterns', [
                r'\$\d+\.\d{2}',
                r'\d+\.\d{2}\s*$',
                r'U\(T\)',
                r'C\(T\)',
            ])
            has_price_pattern = any(re.search(pattern, line) for pattern in price_patterns)
            if not has_price_pattern:
                return True
        
        return False
    
    def interpret_line(self, line: str, vendor: Optional[str] = None, context: Optional[str] = None) -> Optional[Dict]:
        """
        Interpret receipt line using AI
        
        Args:
            line: Receipt line text
            vendor: Vendor name or vendor code (for context)
            context: Additional context (e.g., other items, receipt structure)
            
        Returns:
            Dictionary with extracted fields or dict with parsed_by="ai_fallback_failed" if interpretation fails
        """
        if not self.enabled:
            return None
        
        if not self.should_interpret(line, vendor):
            return None
        
        try:
            if self.backend == 'ollama':
                result = self._interpret_with_ollama(line, vendor, context)
                if result is None:
                    # AI failed - return failure marker
                    return {
                        'product_name': line.strip(),
                        'line_text': line,
                        'parsed_by': 'ai_fallback_failed',
                        'needs_review': True,
                    }
                return result
            elif self.backend == 'transformers':
                result = self._interpret_with_transformers(line, vendor, context)
                if result is None:
                    # AI failed - return failure marker
                    return {
                        'product_name': line.strip(),
                        'line_text': line,
                        'parsed_by': 'ai_fallback_failed',
                        'needs_review': True,
                    }
                return result
        except Exception as e:
            logger.debug(f"AI interpretation error for line '{line[:50]}...': {e}")
            # AI failed (timeout, error, etc.) - return failure marker
            return {
                'product_name': line.strip(),
                'line_text': line,
                'parsed_by': 'ai_fallback_failed',
                'needs_review': True,
            }
        
        return None
    
    def _interpret_with_ollama(self, line: str, vendor: Optional[str] = None, context: Optional[str] = None) -> Optional[Dict]:
        """Interpret line using Ollama"""
        try:
            import requests
            
            # Create prompt for receipt line interpretation
            prompt = self._create_interpretation_prompt(line, vendor, context)
            
            # Call Ollama API
            response = requests.post(
                f'{self._ollama_base_url}/api/generate',
                json={
                    'model': self.model_name,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': self.temperature,
                        'num_predict': 200,
                    }
                },
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                generated_text = result.get('response', '').strip()
                parsed = self._parse_ai_response(generated_text, line)
                if parsed is None:
                    # Failed to parse JSON from AI response
                    logger.debug(f"Failed to parse AI JSON response for line: {line[:50]}...")
                    return None
                return parsed
            else:
                # HTTP error
                logger.debug(f"Ollama API returned status {response.status_code}")
                return None
        except requests.Timeout:
            logger.debug(f"Ollama request timeout for line: {line[:50]}...")
            return None
        except Exception as e:
            logger.debug(f"Ollama interpretation error: {e}")
            return None
        
        return None
    
    def _interpret_with_transformers(self, line: str, vendor: Optional[str] = None, context: Optional[str] = None) -> Optional[Dict]:
        """Interpret line using transformers"""
        try:
            # Create prompt
            prompt = self._create_interpretation_prompt(line, vendor, context)
            
            # Generate response
            result = self._pipeline(
                prompt,
                max_new_tokens=100,
                return_full_text=False,
                temperature=self.temperature,
                do_sample=True,
            )
            
            if result and len(result) > 0:
                generated_text = result[0].get('generated_text', '').strip()
                return self._parse_ai_response(generated_text, line)
        except Exception as e:
            logger.debug(f"Transformers interpretation error: {e}")
        
        return None
    
    def _create_interpretation_prompt(self, line: str, vendor: Optional[str] = None, context: Optional[str] = None) -> str:
        """Create prompt for AI interpretation"""
        vendor_info = f"Vendor: {vendor}\n" if vendor else ""
        context_info = f"Context: {context}\n" if context else ""
        
        prompt = f"""You are a receipt line parser. Extract product information from this receipt line.

{vendor_info}{context_info}Receipt line: {line}

Extract and return ONLY a JSON object with these exact fields:
{{
  "product_name": "extracted product name",
  "quantity": <number or null>,
  "unit_price": <number or null>,
  "total_price": <number or null>,
  "unit": "extracted unit (LB, OZ, CT, EACH, etc.) or null",
  "confidence": <0.0 to 1.0>
}}

Rules:
- If price is missing, use null
- Extract unit from text (LB, OZ, CT, EACH, etc.)
- Product name should be cleaned (remove extra spaces, formatting artifacts)
- Quantity defaults to 1.0 if not found
- Return ONLY valid JSON, no explanations.

JSON:"""
        
        return prompt
    
    def _parse_ai_response(self, response_text: str, original_line: str) -> Optional[Dict]:
        """Parse AI response into structured dict"""
        try:
            # Try to extract JSON from response
            # Look for JSON object in the response
            json_match = re.search(r'\{[^{}]*\}', response_text)
            if json_match:
                json_str = json_match.group(0)
                parsed = json.loads(json_str)
                
                # Validate and normalize
                item = {
                    'product_name': parsed.get('product_name', '').strip(),
                    'quantity': float(parsed.get('quantity', 1.0)) if parsed.get('quantity') else 1.0,
                    'unit_price': float(parsed.get('unit_price')) if parsed.get('unit_price') else None,
                    'total_price': float(parsed.get('total_price')) if parsed.get('total_price') else None,
                    'purchase_uom': parsed.get('unit', '').upper() if parsed.get('unit') else 'EACH',
                    'line_text': original_line,
                    'ai_interpreted': True,
                    'ai_confidence': float(parsed.get('confidence', 0.5)),
                }
                
                # Calculate unit_price if missing but total_price and quantity exist
                if item['unit_price'] is None and item['total_price'] and item['quantity'] > 0:
                    item['unit_price'] = item['total_price'] / item['quantity']
                
                # Calculate total_price if missing but unit_price and quantity exist
                if item['total_price'] is None and item['unit_price'] and item['quantity'] > 0:
                    item['total_price'] = item['unit_price'] * item['quantity']
                
                # Require at least product_name and one price field
                if item['product_name'] and (item['total_price'] or item['unit_price']):
                    return item
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse AI JSON response: {e}")
        except (ValueError, KeyError) as e:
            logger.debug(f"Failed to parse AI response fields: {e}")
        
        return None
    
    def interpret_receipt(self, text: str, vendor: Optional[str] = None) -> List[Dict]:
        """
        Parse entire receipt using AI (for complex receipts like Costco)
        
        Args:
            text: Full receipt text
            vendor: Vendor name or vendor code
            
        Returns:
            List of extracted items (or items with parsed_by="ai_fallback_failed" if AI fails)
        """
        if not self.enabled:
            return []
        
        # Check vendor against enabled_for_vendors list first
        if vendor and self.enabled_for_vendors:
            vendor_upper = vendor.upper()
            vendor_match = False
            for enabled_vendor in self.enabled_for_vendors:
                enabled_vendor_upper = enabled_vendor.upper()
                if vendor_upper == enabled_vendor_upper or enabled_vendor_upper in vendor_upper:
                    vendor_match = True
                    break
            
            if not vendor_match:
                logger.debug(f"Vendor '{vendor}' not in ai_fallback.enabled_for_vendors list, skipping AI interpretation")
            return []
        
        if not text or len(text.strip()) < 50:
            return []
        
        # Apply max_lines limit from rules
        lines = text.split('\n')
        if len(lines) > self.max_lines:
            logger.debug(f"Receipt has {len(lines)} lines, limiting to {self.max_lines} lines for AI processing")
            lines = lines[:self.max_lines]
            text = '\n'.join(lines)
        
        try:
            if self.backend == 'ollama':
                result = self._parse_receipt_with_ollama(text, vendor)
                if not result:
                    # AI failed - return failure marker for the receipt
                    return [{
                        'product_name': 'AI parsing failed',
                        'line_text': text[:100] + '...' if len(text) > 100 else text,
                        'parsed_by': 'ai_fallback_failed',
                        'needs_review': True,
                    }]
                return result
            elif self.backend == 'transformers':
                # Transformers doesn't support full receipt parsing efficiently
                # Fall back to line-by-line
                return self.interpret_batch([line for line in lines if line.strip()], vendor)
        except Exception as e:
            logger.debug(f"AI receipt parsing error: {e}")
            # AI failed (timeout, error, etc.) - return failure marker
            return [{
                'product_name': 'AI parsing failed',
                'line_text': text[:100] + '...' if len(text) > 100 else text,
                'parsed_by': 'ai_fallback_failed',
                'needs_review': True,
            }]
        
        return []
    
    def _parse_receipt_with_ollama(self, text: str, vendor: Optional[str] = None) -> List[Dict]:
        """Parse entire receipt using Ollama"""
        try:
            import requests
            vendor_info = f"Vendor: {vendor}\n" if vendor else ""
            
            prompt = f"""Parse this Costco receipt and extract all product items.

{vendor_info}Receipt text:
{text[:2000]}

Extract all items and return ONLY a JSON array:
{{
  "items": [
    {{
      "item_number": "SKU or null",
      "product_name": "name",
      "quantity": <number>,
      "unit_price": <number or null>,
      "total_price": <number or null>,
      "purchase_uom": "unit or null"
    }}
  ]
}}

JSON:"""
            
            response = requests.post(
                f'{self._ollama_base_url}/api/generate',
                json={
                    'model': self.model_name,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': self.temperature,
                        'num_predict': 1500,
                    }
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('response', '').strip()
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    items_data = parsed.get('items', [])
                    
                    items = []
                    for item_data in items_data:
                        item = self._convert_to_item_dict(item_data, item_data.get('product_name', ''))
                        if item:
                            items.append(item)
                    
                    logger.info(f"Ollama parsed {len(items)} items from receipt")
                    return items
                else:
                    logger.debug("No JSON found in AI response")
                    return []  # Return empty list - will be marked as failed by caller
            else:
                logger.debug(f"Ollama API returned status {response.status_code}")
                return []  # Return empty list - will be marked as failed by caller
        except requests.Timeout:
            logger.debug("Ollama request timeout for receipt parsing")
            return []  # Return empty list - will be marked as failed by caller
        except Exception as e:
            logger.warning(f"Ollama receipt parsing error: {e}")
            return []  # Return empty list - will be marked as failed by caller
        
        return []
    
    def _convert_to_item_dict(self, parsed: Dict, original_line: str) -> Optional[Dict]:
        """Convert parsed AI response to item dict format"""
        try:
            item = {
                'product_name': parsed.get('product_name', '').strip(),
                'quantity': float(parsed.get('quantity', 1.0)) if parsed.get('quantity') else 1.0,
                'unit_price': float(parsed.get('unit_price')) if parsed.get('unit_price') else None,
                'total_price': float(parsed.get('total_price')) if parsed.get('total_price') else None,
                'purchase_uom': (parsed.get('purchase_uom') or parsed.get('unit') or 'EACH').upper(),
                'line_text': original_line,
                'ai_interpreted': True,
                'ai_confidence': float(parsed.get('confidence', 0.8)),
            }
            
            # Add item_number if present
            if parsed.get('item_number'):
                item['item_number'] = str(parsed.get('item_number'))
                item['item_code'] = str(parsed.get('item_number'))
            
            # Calculate missing prices
            if item['unit_price'] is None and item['total_price'] and item['quantity'] > 0:
                item['unit_price'] = item['total_price'] / item['quantity']
            
            if item['total_price'] is None and item['unit_price'] and item['quantity'] > 0:
                item['total_price'] = item['unit_price'] * item['quantity']
            
            # Require at least product_name and one price
            if item['product_name'] and (item['total_price'] or item['unit_price']):
                return item
        except (ValueError, KeyError) as e:
            logger.debug(f"Failed to convert AI response: {e}")
        
        return None
    
    def interpret_batch(self, lines: List[str], vendor: Optional[str] = None) -> List[Dict]:
        """
        Interpret multiple lines
        
        Args:
            lines: List of receipt lines
            vendor: Vendor name
            
        Returns:
            List of interpreted items
        """
        items = []
        for line in lines:
            item = self.interpret_line(line, vendor)
            if item:
                items.append(item)
        return items

