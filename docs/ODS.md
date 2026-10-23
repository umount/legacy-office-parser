# ODS / OTS

## Supported

- Sparse typed cells, repeated rows/cells under shared limits, merges, stored
  formula text/results and sheet-owned ordinary drawing labels.
- Hidden sheets remain in the model and text with their flag. Styles resolve
  in their XML/document scope; embedded definitions cannot override host sheets.
- Optional metadata/styles and empty sheets are accepted. Text is not obtained
  by allocating a dense spreadsheet or filling absent coordinates.

## Limits and remaining work

No formula recalculation, generated chart text, layout, recursive embedded
objects or external resource lookup. Missing cached results are not inferred.
Style/display support is bounded; unresolved visibility produces diagnostics.
Consume `sheets[].cells` for indexing rows, rather than splitting flat text.

## References

- [ODF 1.3 Part 3](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html): §9 tables/cells/repetition; §16 and §19.510 style scope/inheritance.
- [ODF packages](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part2-packages/OpenDocument-v1.3-os-part2-packages.html): package validation and encryption.

Tests are in `tests/test_ods*.py` and shared `test_odf*.py`. See
[spreadsheet integration](INTEGRATION.md) and [output contract](OUTPUT_FORMAT.md#sheets-and-sparse-spreadsheet-cells).
