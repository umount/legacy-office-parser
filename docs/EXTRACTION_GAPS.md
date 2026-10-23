# Remaining extraction work

Format pages hold current support, exclusions and specification links:
[DOC](DOC.md), [XLS](XLS.md), [PPT](PPT.md), [RTF](RTF.md),
[ODT](ODT.md), [ODS](ODS.md), [ODP](ODP.md).

Prioritize reproducible losses of meaningful text in real documents:

PPT and ODF are complete for the current text-extraction scope. Arbitrary OLE
objects and unknown extensions are exclusions, not pending release tasks.
Revisit them only with a concrete example of missing required text.

- XLS: specialized masks and worksheet conditional-formatting rules; see
  [the supported numeric/date boundaries](XLS.md).

No formula execution, macros, network lookup, page renderer or image extraction
is planned in this stage. Unsupported older binary formats and encryption need
separate decoders. Passing tests is not a claim of universal office-suite parity.
