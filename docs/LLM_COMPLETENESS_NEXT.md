# Next LLM extraction work

## Purpose

Recover meaningful text and preserve ownership without duplicating alternative
representations. This work does not introduce rendering or image extraction.
The model may grow to retain those resources later; current output must not
claim that it contains everything needed to reproduce page appearance.

## Ordered work

1. RTF drawing text: revisit fallback-only shapes against the specification and
   original probes. Absence of primary text is not sufficient proof of ownership.
   If fallback recovery remains unproven, extend a separately proven explicit
   text subset and retain the documented fallback omission.
2. PPT/ODF passive content: identify explicit document ownership and representation
   selection before adding text. Keep external resources and active content inert.
   Never scrape opaque payloads or concatenate every representation of a frame.
3. Review remaining DOC/XLS cases by their effect on meaning, visibility, and
   relationships. Geometry alone is not a prerequisite for LLM extraction.

## Acceptance

- Original synthetic positive and adversarial fixtures with literal expectations.
- Shared stream, record, depth, and retained-output budgets.
- No publication of private input files or identifiers.
- Primary specification evidence and independent reader checks where applicable.
- Focused regression suites, independent review, then the full suite.
- English contract/research updates and separate conventional commits.

A successful test of a narrow subset does not close the whole format gap.
Integration corpus validation is separate from this library work.

## Completed checkpoint (0.25)

RTF explicit WordArt now accepts CP1250/CP1253; general legacy fallback recovery
remains unproven. ODP frame alternatives now have one selected text owner;
embedded extraction remains deferred. DOC supports the verified same-section
ordinary-text/complete-row comment subset. An integration-reported XLS General
whole-number display issue is corrected without recalculating formula caches.
See OUTPUT_FORMAT.md and TESTING.md for the precise contract and validation.

## Completed checkpoint (0.26)

1. Correct ODF sheet/slide hidden metadata to use XML/document-owned styles and
   family defaults, with diagnostics for unresolved definitions.
2. Extend DOC comment ranges only across verified ordinary main-story section
   boundaries; keep mixed table/section and nested-row ambiguity explicit.
3. Prove a bounded DOC vertical-merge subset for row-only conditional visibility.
4. Extend XLS optional-decimal display to percent or comma scaling, preserving
   raw caches and fallback for integral-after-rounding ambiguity.

Each change passed independent review and focused adversarial regressions.
Combined acceptance covers the full suite, mutation/resource checks and public
fixtures; results are recorded in TESTING.md. Integration validation continues
independently.
