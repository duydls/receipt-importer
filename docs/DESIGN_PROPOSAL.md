# Design Proposal: Receipt Processing System Redesign

## Current Architecture Analysis

### Strengths
- ✅ Rule-driven (YAML-based) configuration
- ✅ Vendor-specific processors
- ✅ Modular components (detector, processor, classifier)
- ✅ Parallel file processing

### Pain Points
- ❌ Tight coupling between main.py and processors
- ❌ Sequential pipeline with hardcoded order
- ❌ Mixed concerns (extraction, validation, enrichment, matching)
- ❌ Difficult to add new processing steps
- ❌ Odoo matching happens after all extraction (could be integrated earlier)
- ❌ Limited error recovery and retry mechanisms
- ❌ No clear separation between data transformation and business logic

---

## Proposed Design: Pipeline Architecture with Plugin System

### Core Principles

1. **Pipeline Pattern**: Each processing step is a stage in a pipeline
2. **Plugin System**: Vendors and processors are plugins that can be registered
3. **Event-Driven**: Steps can emit events for monitoring/validation
4. **Immutable Data Flow**: Each stage transforms data without mutating input
5. **Composable**: Stages can be combined/reordered without code changes
6. **Testable**: Each stage is independently testable

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Receipt Processing Pipeline              │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Stage 1    │ ───▶ │   Stage 2    │ ───▶ │   Stage N    │
│  Detection   │      │  Extraction  │      │  Enrichment  │
└──────────────┘      └──────────────┘      └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Receipt Context  │
                    │  (Immutable)      │
                    └──────────────────┘
```

---

## Component Design

### 1. Receipt Context (Data Model)

```python
@dataclass(frozen=True)
class ReceiptContext:
    """Immutable receipt data structure passed through pipeline"""
    receipt_id: str
    source_file: Path
    vendor: str
    vendor_code: str
    source_type: str
    transaction_date: Optional[datetime]
    
    # Raw extracted data
    raw_items: List[RawItem]
    raw_totals: Dict[str, float]
    
    # Processed data
    items: List[ProcessedItem]
    metadata: Dict[str, Any]
    
    # Processing state
    stage_history: List[ProcessingStage]
    errors: List[ProcessingError]
    warnings: List[ProcessingWarning]
    
    # Validation flags
    is_valid: bool
    needs_review: bool
```

### 2. Processing Stage Interface

```python
class ProcessingStage(ABC):
    """Base class for all processing stages"""
    
    @abstractmethod
    def process(self, context: ReceiptContext) -> ReceiptContext:
        """Transform context and return new context"""
        pass
    
    @abstractmethod
    def can_handle(self, context: ReceiptContext) -> bool:
        """Check if this stage can process the context"""
        pass
    
    @property
    @abstractmethod
    def stage_name(self) -> str:
        """Name of this processing stage"""
        pass
    
    @property
    def dependencies(self) -> List[str]:
        """List of stage names this stage depends on"""
        return []
    
    @property
    def priority(self) -> int:
        """Execution priority (lower = earlier)"""
        return 100
```

### 3. Stage Implementations

#### Stage 1: Vendor Detection
```python
class VendorDetectionStage(ProcessingStage):
    """Detects vendor and source type from file path/content"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Use rule_loader to detect vendor
        # Return new context with vendor info
        pass
```

#### Stage 2: File Format Detection
```python
class FormatDetectionStage(ProcessingStage):
    """Detects file format (PDF, Excel, CSV)"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Detect format and add to metadata
        pass
```

#### Stage 3: Content Extraction
```python
class ContentExtractionStage(ProcessingStage):
    """Extracts raw content from file"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Route to appropriate extractor (PDF/Excel/CSV)
        # Return context with raw_items
        pass
```

#### Stage 4: Layout Application
```python
class LayoutApplicationStage(ProcessingStage):
    """Applies vendor-specific layout rules"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Apply layout rules from YAML
        # Parse structured data from raw content
        pass
```

#### Stage 5: UoM Extraction
```python
class UoMExtractionStage(ProcessingStage):
    """Extracts and normalizes UoM"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Extract UoM using rules
        # Normalize UoM values
        pass
```

#### Stage 6: Name Hygiene
```python
class NameHygieneStage(ProcessingStage):
    """Cleans and normalizes product names"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Apply name hygiene rules
        # Generate canonical names
        pass
```

#### Stage 7: Odoo Matching (Early Integration)
```python
class OdooMatchingStage(ProcessingStage):
    """Matches items to Odoo purchase orders"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Match items to Odoo POs by price/name
        # Enrich with standard names and categories
        # Can run early if Odoo data is available
        pass
```

#### Stage 8: Category Classification
```python
class CategoryClassificationStage(ProcessingStage):
    """Classifies items into L1/L2 categories"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Skip if already classified by Odoo
        # Apply rule-based classification
        pass
```

#### Stage 9: Fee Extraction
```python
class FeeExtractionStage(ProcessingStage):
    """Extracts fees and adds missing fees from Odoo"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Extract fees from PDF text
        # Add missing fees from Odoo
        pass
```

#### Stage 10: Validation
```python
class ValidationStage(ProcessingStage):
    """Validates receipt data quality"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Validate totals, quantities, prices
        # Flag items needing review
        pass
```

#### Stage 11: Total Calculation
```python
class TotalCalculationStage(ProcessingStage):
    """Calculates missing totals"""
    def process(self, context: ReceiptContext) -> ReceiptContext:
        # Calculate totals from items if missing
        pass
```

---

## Pipeline Orchestrator

```python
class ReceiptPipeline:
    """Orchestrates processing stages"""
    
    def __init__(self, stages: List[ProcessingStage]):
        self.stages = self._order_stages(stages)
    
    def _order_stages(self, stages: List[ProcessingStage]) -> List[ProcessingStage]:
        """Order stages by dependencies and priority"""
        # Topological sort based on dependencies
        # Then sort by priority
        pass
    
    def process(self, context: ReceiptContext) -> ReceiptContext:
        """Execute all stages in order"""
        for stage in self.stages:
            if not stage.can_handle(context):
                continue
            
            try:
                context = stage.process(context)
                context = self._add_stage_history(context, stage)
            except Exception as e:
                context = self._add_error(context, stage, e)
                # Decide: continue, skip, or fail
                
        return context
```

---

## Plugin System for Vendors

```python
class VendorPlugin(ABC):
    """Base class for vendor-specific plugins"""
    
    @abstractmethod
    def get_vendor_code(self) -> str:
        pass
    
    @abstractmethod
    def get_extractor(self) -> ContentExtractor:
        """Returns vendor-specific content extractor"""
        pass
    
    @abstractmethod
    def get_layout_applier(self) -> LayoutApplier:
        """Returns vendor-specific layout applier"""
        pass
    
    def get_custom_stages(self) -> List[ProcessingStage]:
        """Optional: vendor-specific processing stages"""
        return []

# Example
class CostcoPlugin(VendorPlugin):
    def get_vendor_code(self) -> str:
        return 'COSTCO'
    
    def get_extractor(self) -> ContentExtractor:
        return CostcoPDFExtractor()
    
    def get_layout_applier(self) -> LayoutApplier:
        return CostcoLayoutApplier()
```

---

## Configuration-Driven Stage Registration

```yaml
# pipeline_config.yaml
stages:
  - name: vendor_detection
    class: VendorDetectionStage
    priority: 1
    enabled: true
    
  - name: format_detection
    class: FormatDetectionStage
    priority: 2
    enabled: true
    dependencies: [vendor_detection]
    
  - name: content_extraction
    class: ContentExtractionStage
    priority: 3
    enabled: true
    dependencies: [format_detection]
    
  - name: odoo_matching
    class: OdooMatchingStage
    priority: 4
    enabled: true
    dependencies: [content_extraction]
    config:
      early_matching: true
      price_tolerance: 0.05
      
  - name: category_classification
    class: CategoryClassificationStage
    priority: 5
    enabled: true
    dependencies: [odoo_matching]
    config:
      skip_odoo_matched: true
```

---

## Benefits of This Design

### 1. **Flexibility**
- Easy to add/remove/reorder stages
- Stages can be enabled/disabled via config
- New vendors can be added as plugins

### 2. **Testability**
- Each stage is independently testable
- Mock stages for integration testing
- Easy to test stage combinations

### 3. **Maintainability**
- Clear separation of concerns
- Single responsibility per stage
- Easy to understand data flow

### 4. **Extensibility**
- Add new stages without modifying existing code
- Vendor-specific customizations via plugins
- Business logic changes isolated to specific stages

### 5. **Observability**
- Stage history tracking
- Error/warning collection
- Performance metrics per stage

### 6. **Early Odoo Integration**
- Odoo matching can happen earlier in pipeline
- Reduces redundant processing
- Better error handling if Odoo unavailable

---

## Migration Strategy

### Phase 1: Parallel Implementation
- Build new pipeline alongside existing code
- Run both systems in parallel
- Compare outputs for validation

### Phase 2: Gradual Migration
- Migrate one vendor at a time
- Start with simplest vendor (e.g., BBI)
- Validate each migration

### Phase 3: Full Cutover
- Migrate all vendors
- Deprecate old system
- Remove legacy code

---

## Example Usage

```python
# Initialize pipeline
pipeline = ReceiptPipeline.from_config('pipeline_config.yaml')

# Register vendor plugins
pipeline.register_plugin(CostcoPlugin())
pipeline.register_plugin(InstacartPlugin())
pipeline.register_plugin(AmazonPlugin())

# Process receipt
context = ReceiptContext.from_file(file_path)
result = pipeline.process(context)

# Access results
if result.is_valid:
    save_receipt(result)
else:
    send_to_review(result)
```

---

## Advanced Features

### 1. **Conditional Stages**
Stages can check conditions before executing:
```python
class ConditionalStage(ProcessingStage):
    def can_handle(self, context: ReceiptContext) -> bool:
        return context.vendor_code == 'COSTCO' and context.has_excel_format()
```

### 2. **Stage Composition**
Stages can be composed:
```python
composite_stage = CompositeStage([
    NameHygieneStage(),
    UoMExtractionStage(),
    PriceValidationStage()
])
```

### 3. **Parallel Stage Execution**
Independent stages can run in parallel:
```python
parallel_stages = ParallelStage([
    OdooMatchingStage(),  # Can run in parallel
    CategoryClassificationStage()  # with category classification
])
```

### 4. **Error Recovery**
Stages can implement retry logic:
```python
class RetryableStage(ProcessingStage):
    def process(self, context: ReceiptContext) -> ReceiptContext:
        for attempt in range(3):
            try:
                return self._do_process(context)
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff
```

---

## Data Flow Example

```
Input: receipt.pdf
  │
  ▼
[VendorDetectionStage]
  │ → vendor: "Costco", source_type: "localgrocery_based"
  ▼
[FormatDetectionStage]
  │ → format: "PDF"
  ▼
[ContentExtractionStage]
  │ → raw_items: [...], raw_totals: {...}
  ▼
[LayoutApplicationStage]
  │ → structured_items: [...]
  ▼
[UoMExtractionStage]
  │ → items with UoM: [...]
  ▼
[NameHygieneStage]
  │ → items with canonical names: [...]
  ▼
[OdooMatchingStage]
  │ → items with standard_name, categories: [...]
  ▼
[CategoryClassificationStage]
  │ → items with L1/L2 (skip if Odoo matched): [...]
  ▼
[FeeExtractionStage]
  │ → items with fees: [...]
  ▼
[ValidationStage]
  │ → validated items, flags: [...]
  ▼
[TotalCalculationStage]
  │ → receipt with calculated totals: {...}
  ▼
Output: ReceiptContext (ready for saving)
```

---

## Questions to Consider

1. **Should stages be synchronous or async?**
   - Async for I/O-bound stages (Odoo queries, file reads)
   - Sync for CPU-bound stages (parsing, validation)

2. **How to handle partial failures?**
   - Continue with degraded data?
   - Fail fast?
   - Configurable per stage?

3. **Caching strategy?**
   - Cache intermediate results?
   - Which stages benefit from caching?

4. **Monitoring and observability?**
   - Metrics per stage?
   - Performance profiling?
   - Error tracking?

5. **Configuration management?**
   - YAML-based (current approach)?
   - Database-driven?
   - Environment variables?

---

## Next Steps

1. **Prototype**: Build minimal pipeline with 3-4 stages
2. **Validate**: Test with one vendor (e.g., BBI)
3. **Refine**: Adjust design based on learnings
4. **Document**: Create detailed API documentation
5. **Migrate**: Gradually move vendors to new system

