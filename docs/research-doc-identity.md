# DOC adjacent-table identity

The extraction model and runtime dependencies are unchanged.

## Primary evidence

- [MS-DOC 2.4.3, Overview of Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c): same-depth adjacency alone does not establish table identity.
- [MS-DOC 2.6.3, Table Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b39a6648-501c-4361-8366-4f042f579469): operand meanings, defaults, and invalid TIstd fallback to 11.
- [PositionCodeOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/4adae037-8747-471a-a1a0-082a5244ebc7): ignore padding; retain anchor bits.
- [PGPInfo](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/ca1d2cfd-1639-4c52-a365-9dbc212e476b): nonzero identifiers and parent/depth relationships.
- [YAS_plusOne](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5740209e-2844-4452-bf30-14c041732cc8): signed operand bounds.

## Implementation and verification

`_Props` carries immutable row identity: TIpgp, resolved table style ID, TPc,
TFNoAllowOverlap, TDxaAbs, TDyaAbs and the four FromText distances. Direction
continues using the effective OR of the two BiDi properties. Comparisons happen
at TTP, after buffering cells. A change closes and normalizes completed rows,
resets vertical merges, and attaches the pending row to a new Table. Recovery
without a TTP retains the previous identity instead of inventing a boundary.

Immutable identity also survives existing external-PAPX fallback snapshots.
Nonexistent, empty and non-table style references resolve to Normal Table;
style formatting remains explicitly unsupported. Position values are never
used for layout or text reordering.

Independent synthetic tests reuse only existing binary transport helpers and
assert literal trees: every identity property, defaults, overrides, padding,
real/invalid style IDs, nested projection, merges, grids, incomplete rows,
external properties and fallback, CLX overrides, malformed operands and budgets.

Validation: `pytest -q tests/test_doc*.py tests/test_security_side_effects.py`:
582 passed, 2 skipped. `test_doc_identity.py` contains 61 passing cases;
`test_doc_identity_ole.py` adds 3 real-OLE checks. Ruff
passes for both owned source files and the new test file.

## Reviewed TPc correction and real-OLE checkpoint

Unspecified TPc is 0xF0: both PositionCodeOperand components are 3 (none).
Explicit 0xF0, including ignored low padding bits, equals the default;
explicit 0x00 differs. Three focused regressions cover this review finding.

`tools/generate_doc_identity_fixture.py` deterministically rebuilds only the
project-authored ordinary_table.doc PAPX. First-row direct TDxaAbs=721 gives
one header-row table followed by the remaining two rows. No external fallback
or PGPInfo references are used. The new public-API test checks exact nested
structure, exact text, inline operands and reproducibility.

LibreOffice 7.4.7.2 independently retains one three-row table, with all nine
cells and identical ordered words/nonspace text. Structural comparison fails;
`tests/fixtures/doc_identity/lo-comparison.json` records the discrepancy.
The sandbox conversion failed and the authorized unsandboxed retry succeeded.

Checkpoint stops before any paragraph-frame implementation. `_doc_styles.py`
remains byte-identical to the main checkout.

## Remaining gaps and next implementation

The first-cell paragraph-frame boundary rule in section 2.4.3 remains unhandled.
It applies only when neither row has nondefault table positioning/wrapping.
The current Styles reader retains hidden-text operations, not frame properties;
correct inherited frame comparison therefore requires coordinating changes to
`_doc_styles.py`, outside this task's ownership. Next: preserve effective frame
properties from paragraph styles, capture the first paragraph of each row's
first cell, and compare only under that rule's default-position gate. Test
inherited/direct overrides, later paragraphs that must not split, and explicit
table positioning that disables the fallback.

Protection-bookmark boundaries also remain unhandled: they require SDTI/range
membership and cannot be inferred from row property operands. TIpgp comparison
does not validate the PGPInfo graph, itap, or corresponding PIpgp; synthetic
TIpgp cases test operand grouping, not a complete PGPInfo document. Table-style
formatting/conditional formatting and layout remain unsupported. No new
runtime I/O, converter invocation, network access, macro or command execution
was introduced.
