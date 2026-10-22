# DOC identities and XLS display coverage

This iteration follows release 0.23.0. Integration/corpus feedback is handled
separately; no private files are published here.

## Ordered work

1. Preserve verified DOC auxiliary-story identities: header/footer section and
   variant, note separator slots, and live main/header textbox ranges. Retain
   source ordinals and relative UTF-16 positions; do not invent page layout,
   shape relationships, or reference anchors. Preserve legacy text projections.
2. Expand DOC comment selection and conditional table visibility only where
   source structure proves the needed boundaries. Ambiguous source cases keep
   explicit unknown metadata or diagnostic fallbacks.
3. Investigate and implement additional XLS display formats using primary format
   rules and an independent preserved-source reference. Keep raw typed values,
   bound arithmetic/output, and reject ambiguous display interpretations.
4. Verify structural contracts, synthetic negative/resource tests, independent
   reviews, packaging and regression corpora. Commit each supported subset.

The remaining coverage register is authoritative about exclusions. A completed
subset is not arbitrary-document rendering parity. Macro execution, external
resource access and conversion to OOXML are outside this work.

## Progress

- DOC auxiliary identities implemented; public corpus plain text unchanged.
- Complete outer-row comment selections implemented with bounded source proof.
- Row-only conditional visibility implemented for proven unequal/horizontally merged rows;
  malformed outer row terminators cannot establish condition context.
- XLS bounded variable-denominator fractions and nonintegral optional-decimal
  displays implemented with preserved-source reference comparisons.
- Independent reviews, full regression suite, preserved-source reference checks
  and mutation/resource sampling complete. See TESTING.md for evidence.
