Your approved defaults still work: immutable source captures, Evidence locators, and versioned menu interpretations provide much of the foundation.
I would frame your idea as an extraction dataset and feedback loop. A training example needs more than flags:
Record	What to retain
Source input	Immutable capture/version reference; original HTML, PDF, or image; rendered representation when used
Extraction attempt	Extractor/model version, configuration, predicted fields, source locators, failure reasons
Reviewed answer	Corrected fields and relationships, reviewer, review status, label version
Dataset version	Exact examples used for training and evaluation


The distinction between predicted output and reviewed answers matters. Passing Menu’s database constraints does not prove an extracted price belongs to the correct item. Training indiscriminately on accepted predictions could reinforce extraction mistakes. Reviewed corrections—and examples where extraction failed—are particularly valuable.
Keep source material in Bronze. A future extraction workflow should own attempts and annotations; Menu should continue owning accepted menu facts. We do not need a generic inference table inside Menu or Identity.
Existing models can help. I would benchmark these before considering training from scratch:
- NuExtract: models specifically designed to produce structured information from text/images; its project provides fine-tuning guidance. A plausible candidate for menu-specific adaptation, subject to testing on our examples. NuExtract project
https://github.com/numindai/nuextract

- Docling: a document-processing framework with schema-directed extraction capabilities. Useful to evaluate for document preparation and PDF/image extraction; it is not itself a guarantee of correct menu interpretation. Docling extraction documentation
https://docling-project.github.io/docling/_generated/examples/extraction/

My recommended progression is rules/site adapters → pretrained-model benchmark → targeted fine-tuning if justified. All paths should produce the same extraction DTO and pass the same Evidence and Menu admission checks. Evaluate on entirely unseen websites/templates, not just different pages from sites represented in training. Measure item–price pairing, variants/modifiers, missing or invented fields, review rate, and processing cost.
The timing should be:
1. Now: record this as a deferred requirement in the Step 5 proposal; add no ML tables.
2. Plan-0001 Step 7, capture/replay: decide which source artifacts must be preserved.
3. Before Step 8, extraction: design attempt logging, reviewed annotations, and an evaluation dataset.
4. After baseline extraction results: propose the model experiment and training plan under the existing [model-fallback review gate (line 219)](/home/fortune/CodeProjects/First-Helios/docs/rfc/0001-menu-pricing-first.md:219). This is separate from Plan-0002 Step 6, which concerns Gold.
Use this prompt when approaching capture/extraction:
Plan an extraction dataset and feedback loop for Helios before implementing Plan-0001’s capture and extraction steps. Reuse Bronze captures and Evidence, preserve module ownership, and distinguish extraction predictions from reviewed training labels. Propose the smallest design for source artifacts, extraction attempts, corrections, and versioned datasets. Compare rules/site adapters with existing self-hostable extraction models and targeted fine-tuning. Define evaluation on unseen websites, accuracy and abstention requirements, hardware/cost limits, and a staged experiment. Produce a proposed RFC/ADR and implementation plan only; do not add models, tables, dependencies, or training code yet.
