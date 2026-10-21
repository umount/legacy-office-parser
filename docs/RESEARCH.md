# Research before implementation — 2026-10-21

This is a historical record of the revisions and implementation stages studied below.
Statements about limitations describe the state at the time of each investigation,
not necessarily current package support. For the current comparison scope and
recorded evidence, see [Comparison with libraries and office suites](COMPARISON.md).
These findings do not constitute a broad ranking of libraries.

Source code was studied before implementation began. This is an analysis with small
checks of individual functions, not independent certification of existing libraries.

## sharepoint-to-text

Revision: `6f2e77ca4b5fcf4e42550b9d1bb3cd51a4078dec`.

DOC: `_find_text_start_and_enc` guesses the location/encoding, then reads the body
sequentially. It does not use the actual CLX/PlcPcd piece table.
Tables are inferred from a flat string: Latin-script words in the first half,
numbers in the second. Probes of individual functions revealed incorrect classification
of Cyrillic text and false recognition of ordinary text as tables.

PPT: records are scanned across the entire stream without building the current persist directory.
Empty slides may disappear, notes are associated by position, and shape text
may be discarded when outline text is present. Function probes confirmed
these cases; a full end-to-end run of the package was not performed.

Decision: do not mechanically fork the two files. Use verified low-level reading
ideas and the specifications. Do not carry over the shared router,
SharePoint client, images, PDF, archives, or other formats.

Source: https://github.com/Horsmann/sharepoint-to-text

## WordCraft

Revision: `e05b7fe86f3b85454000dffc321de638d7009817`.

`crates/docbin` does read FIB/CLX/piece table and FKP/PAPX/SPRM,
and assembles tables and merges. Useful references: `piece.rs`, `fkp.rs`,
`sprm.rs`, `table.rs`, `notes.rs`, and synthetic tests in `tests.rs`.

Limitation: `table.rs` explicitly limits the structural representation to depth
1; deeper tables become paragraphs. DOC versions before Word 97 are also outside
this reader's scope. “DOC support” does not mean complete coverage of all variants.

Decision: use it as a technical reference and check it against the specification.
Rust does not prevent an independent Python implementation; we do not need the editor itself.
When adapting source code, retain the required attribution notices.

Source: https://github.com/storytold/wordcraft/tree/main/crates/docbin

## office_oxide

Investigated as an existing alternative: a Rust core with Python bindings, actual
DOC piece/table parsing, and a PPT persist directory. It is a candidate for
comparison, not an adopted runtime dependency of our package.

Nested DOC tables are flattened. Completeness of PPT notes is unconfirmed; fallback
to old records in some paths needs checking. Findings from studying main
must not automatically be attributed to the published Python wheel.

Source: https://github.com/yfedoseev/office_oxide

## Specifications and independent references

- DOC: https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/01d5d8c4-cf9c-4ef9-80fd-439e763cfe01
- PPT: https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/5bda8009-6612-4679-a6eb-6fb83cbcf195
- Apache POI HSLF/HWPF: an additional reference for slides/notes relationships and
  table depth, without a Java runtime in our package.
- LibreOffice: an independent tool for comparative validation,
  but not the sole source of truth—the expected content of synthetic files is known.

## Additional DOC comparison: encodings and boundaries

The comparison used the same pinned WordCraft revision, `e05b7fe`:
`piece.rs`, `fib.rs`, `fkp.rs`, `sprm.rs`, `table.rs`, `notes.rs`, `lib.rs`,
and tests. This is a comparison of source code and individual reproducible cases;
the full WordCraft project was neither built nor run against the private corpus.
The original Rust modules `piece.rs` and `encoding.rs` were included unchanged
in a separate small probe: it confirmed U+20AC/U+017D/U+017E output
for bytes 80/8E/9E and two U+FFFD characters for a broken UTF-16 pair.

The independent basis for encodings remains
[MS-DOC FcCompressed](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/aa2e55a2-f4f2-4795-bab5-6d9d7a0ed249).
In DOC 97–2003, uncompressed pieces use UTF-16LE; compressed pieces use single-byte
Unicode values with the substitutions listed in the specification. This does not
select CP1251 based on the document language. The code pages in WordCraft's shared
`encoding.rs` also serve RTF and do not imply their use in DOC.

In the studied WordCraft version, `piece.rs` calls `cp1252`: values
`0x80`, `0x8E`, and `0x9E` differ from the MS-DOC table. Our mapping for these
bytes is retained. WordCraft combines a UTF-16 pair only within a single
piece; we assemble the logical sequence of code units before decoding,
so a pair spanning a piece boundary is preserved.

`tests/test_doc_encoding.py` checks every byte from `0x20–0xFF`, every UTF-16
boundary in a multilingual string, isolated surrogates, the exact length limit
in code units, and ignoring the reserved FcCompressed bit.
For DOC input, `max_text_chars` counts UTF-16 units including control
characters, so a character outside the BMP occupies two units.

Comparison of the remaining components identified and fixed these extraction defects:

- The obfuscation flag without the encryption flag incorrectly caused rejection.
- `cswNew/nFibNew` were not considered when checking the FIB version and the size of the
  offset array. The effective version is now checked, including extension bounds.
- `sprmPDtap` did not apply signed changes to table depth; short
  overrides could not reset the two independent nesting flags.
- Adjacent tables with different directions were combined. The boundary is now
  established before merging cells in the next row.
- Auxiliary and reused textbox ranges were included in extracted
  text. Both textbox PLCs are now considered, and field state is reset
  between active ranges. If PLCs are absent, the result explicitly
  warns that active ranges cannot be verified.

The changes are covered by `test_doc_fib.py`, `test_doc_table_properties.py`,
`test_doc_textboxes.py`, and `test_doc_textboxes_integration.py`. Unimplemented
`TDxaCol` geometry now produces a warning instead of being silently skipped.

Style inheritance, other Prm0 properties, external table properties, and hidden/deleted text
remain limitations. WordCraft contains useful implementations of these areas,
but they must not be considered ported to this package. The completeness of its editor
does not imply the completeness of our extraction; source comparisons supplement,
rather than replace, independent expected results.


The additional regression `test_doc_fidelity.py` covers the compact Prm0 properties
`PFInTable` and `PFTtp`, including explicit resets and selection of the properties
of the piece containing the paragraph-end mark. Unsupported Prm0 properties
still produce a warning. This defect was reproduced using original
synthetic data, not the private corpus.


`sprmCSymbol` characters are extracted using CHPX/FKP and applicable piece properties
in place of the control character `(`. Formatting and font tables are checked
against bounds and the shared record budget. The `font/code` pair is not replaced
with a guessed glyph mapping: the original Unicode code is retained, while PUA and
symbol fonts produce warnings. Two characters were corrected in one local document:
the result now matches LibreOffice apart from whitespace differences.
Original regressions also check CHPX boundaries, overrides, and surrogates.
