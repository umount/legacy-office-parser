# Post-0.22 implementation sequence

The published 0.22.0 contract and tag remain immutable. Work below is developed
in ordered, independently reviewable commits for the next minor release.

1. Resolve supported inherited RTF visibility and ODF hidden paragraph/style/
   section semantics. Test direct overrides, suppressed stories, cycles and limits.
2. Provide an explicit text-normalization API: line-ending/control cleanup,
   optional NFC, preserved tabs and meaningful whitespace, unchanged source
   references, and an independent returned document. Preserve raw extraction
   when normalization is not requested.
3. Expose stable diagnostic codes alongside existing human-readable warnings.
   Assign codes at emission sites; do not infer codes by matching message text.
4. Accept ODF template MIME families with the existing text/sheet/slide model.
5. Preserve individual RTF/ODT note-body boundaries without inventing source
   offsets or anchors that the format traversal does not establish.
6. Expand independently verified spreadsheet formatting and passive text
   constructs. Add only bounded, evidence-backed subsets; retain explicit
   unsupported fallbacks for unresolved formats.
7. Verify deep serialization, deterministic output and process isolation across
   all seven format families. Run the full suite, mutation/resource checks,
   package checks and private-corpus comparisons without publishing private data.

Each behavior change must update OUTPUT_FORMAT.md and the extraction register.
Use original synthetic fixtures. Office-suite conversions are development
references, never runtime dependencies. A supported subset is not a claim of
complete rendering, revision acceptance or arbitrary-format equivalence.

## Progress

- Step 1: supported RTF/ODF visibility implemented and regression-tested.
- Step 2: explicit normalization and iterative model copying implemented.
- Step 3: warning codes assigned at emission sites; legacy strings retained.
- Step 4: OTT/OTS/OTP MIME families accepted with existing ODF validation.
- Step 5: individual RTF/ODT note ranges retained, including visible empty bodies;
  repeat budgets and suppressed destinations covered by regression tests.
- Step 6: bounded fixed-denominator XLS fractions verified against an independent
  reader; alternate PPT metroBlob content remains excluded as specified.
