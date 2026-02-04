# SAT-GenAI Project — Architecture

## 1. Objective

This project implements a reproducible pipeline for acquiring, normalizing, and structuring SAT-style practice questions into a machine-learning–ready dataset. The primary goal is to convert heterogeneous web-delivered question content (plain text, MathML, figures/tables, and UI-embedded explanations) into a consistent schema that can support downstream tasks such as:

- data auditing and quality control,
- metadata-driven retrieval (domain/skill/difficulty),
- instruction-tuning / supervised fine-tuning of LLMs,
- evaluation set construction and benchmarking.

## 2. System Overview

The system is organized as a modular data pipeline:

1. **Data Acquisition Layer (Browser Automation)**  
   Automates navigation across a practice-test dashboard, opens an exam, iterates over questions, and extracts visible content.

2. **Content Normalization Layer (Text + Math)**  
   Converts HTML fragments into clean, model-consumable text by removing non-content UI artifacts and translating MathML structures into linearized math notation (LaTeX-like).

3. **Multimodal Capture Layer (Visual Stimuli)**  
   When a question includes visual stimuli (images, tables, SVGs), the pipeline captures them as local screenshots and stores stable file paths in the dataset.

4. **Dataset Serialization Layer (Schema + Export)**  
   Writes per-exam JSON files that preserve question text, answer options, explanation rationale, metadata, and image references.

## 3. Data Model (Schema)

Each question is serialized into a single JSON object with the following conceptual fields:

- **id**: stable question identifier within an exam export (e.g., `Q12`)
- **question_type**: a composite label derived from metadata fields (e.g., domain + skill)
- **difficulty**: difficulty level, if exposed by the platform UI
- **question_text**: normalized text (stimulus + stem) with linearized math expressions
- **options**: multiple-choice options (`A–D`)
- **solution_rationale**: explanation text captured from the platform’s explanation modal
- **image_paths**: list of local paths to captured visual stimuli (may be empty)

This schema is intentionally simple, auditable, and compatible with common fine-tuning formats (e.g., instruction–input–output triples).

## 4. Math & HTML Normalization

SAT-style mathematics is frequently rendered via MathML or UI-specific math encodings. The normalization module performs:

- structural parsing of MathML nodes (fractions, exponents, radicals, fenced expressions),
- replacement of MathML blocks with linear math strings,
- removal of non-semantic UI content (icons, scripts, assistive markup),
- whitespace normalization and symbol standardization (e.g., `× → *`, `÷ → /`).

The result is a compact representation that remains readable for humans and token-efficient for language models.

## 5. Reliability & Reproducibility Considerations

The pipeline prioritizes deterministic exports:

- explicit waits and staleness-based synchronization to avoid fragile time-based sleeps,
- per-exam folder structure to keep raw assets (images) co-located with the JSON export,
- incremental writes to reduce data loss risk on intermittent failures.

The acquisition layer is written to be platform-agnostic: URLs and selectors can be adapted to different repositories without changing the core dataset schema.

## 6. Planned Extensions

Future phases of the project include:

- **Quality filtering and deduplication** (hash-based similarity checks across large corpora),
- **Knowledge graph construction** for concept/skill dependency modeling,
- **LLM fine-tuning** using LoRA/QLoRA with instruction-tuning templates,
- **Automatic validation** (option completeness, explanation presence, metadata consistency).

## 7. Ethical and Legal Note

This system is intended for legitimate research, personal study, and dataset engineering workflows. Users should ensure they have appropriate rights and permissions to access and export any content they process.
