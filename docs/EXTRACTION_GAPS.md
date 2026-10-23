# Remaining extraction work

Format pages hold current support, exclusions and specification links:
[DOC](DOC.md), [XLS](XLS.md), [PPT](PPT.md), [RTF](RTF.md),
[ODT](ODT.md), [ODS](ODS.md), [ODP](ODP.md).

Prioritize reproducible losses of meaningful text in real documents:

- RTF: authoritative fallback-only shape text.
- PPT/ODF: additional passive embedded text with proven ownership; embedded
  ODP notes and paragraph-anchored drawings.
- DOC: remaining conditional table styles, page-dependent header selection,
  partial/multiple/deeper inner-row and cross-section table comment selections.
- XLS: localization, wider conditional/decimal/fraction display masks.

No formula execution, macros, network lookup, page renderer or image extraction
is planned in this stage. Unsupported older binary formats and encryption need
separate decoders. Passing tests is not a claim of universal office-suite parity.
