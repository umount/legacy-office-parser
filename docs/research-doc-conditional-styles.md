# Conditional table CFVanish — narrow implementation checkpoint

## Primary rules

[MS-DOC 2.9.41 CNFOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/8c71d6a6-35dd-4462-9471-d376adebfe98):
cnfc is one enumerated condition, NOT a combinable bitmask. Validate cb and its
2-byte condition before decoding bounded grpprl. Only CCnf (0xCA85) in table CHPX
is relevant to conditional CFVanish; TCnf (0xD66A) contains table properties, not
character properties. Never look for CFVanish bytes inside TCnf, shading or borders.
[Table properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b39a6648-501c-4361-8366-4f042f579469)
and [Character properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/7022285b-9621-42e9-ad4d-4e02c115ef18)
restrict these operands to their corresponding style UPX groups.

[Fatl 2.9.69](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/c2b2c89f-4ba1-4013-a459-b66caa1171c2)
TTlp.grfatl masks: header row 0x0020, last row 0x0040, logical first column
0x0080, logical last column 0x0100; disable row bands 0x0200, disable column bands
0x0400. Low bits describe previous auto-format categories, not an unconditional
CFVanish enable gate. Upper five bits are padding. Keep masks separate from CNFC.

[Formatting algorithm 2.4.6.6](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d8b66123-1a3d-4e06-94c5-5ab16e9b6417):
apply horizontal bands, vertical bands, first/last column, first/last row, then
corners. First/header beats last row; first column beats last column. Matching
special rows/columns are excluded from corresponding band conditions. For band
counting, exclude top/header rows when top-row formatting is enabled; exclude the
logical first column when its formatting is enabled. Do not additionally subtract
last row/column. Corners require both corresponding row and column options.
Top-left wins over top-right for a single-column table; bottom-left excludes
both top corners; bottom-right excludes the other three corners. Corner tests
refer to actual table corners, not every repeated header row. After conditional
properties, paragraph styles and direct character properties still apply.

TCHorzBands=0x3488 and TCVertBands=0x3489, from style TAPX, accept sizes 1..3.
For an eligible zero-based ordinal k and size n, band number is floor(k/n)+1;
odd/even picks CNFC 0x0040/0x0080 or 0x0010/0x0020 respectively. The specification
says default no band shading: do not silently invent size 1 when absent.
TTableHeader must be interpreted using its effective-row rules; don't promote an
isolated flag on a later row to a valid repeated-header prefix.

## Minimum context and dependency boundary

CCnf visibility itself cannot change cell marks, row marks, merges, TIstd or frame
identity. It is acyclic if table partitions are established before evaluating it.
BUT a general claim of no cycle is false: unsupported PCnf frame properties can
change first-cell frame identity, which changes first/last-row conditions. Phase 1
must exclude/diagnose such table-style frame cases, not recompute until stable.
Bookmark-boundary ambiguity also remains unresolved; do not claim exact last-row
conditions for a partition whose semantic boundaries are not established.

Minimum reliable first scope: complete, unmerged rectangular tables with stable
partitions; logical row/cell ordinals, row/cell counts, effective direction,
validated header-prefix flags, TTlp options, inherited band sizes and table style.
All paragraphs in one cell share position context. Use the innermost table; outer
rows don't count nested rows. TTP characters aren't ordinary cells (see
[Cell boundaries](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/e32f7b2f-4759-4e8f-9ef9-e0cdfd11a335)).
No rendered widths/heights/pages are needed. Preserve logical ordering for RTL;
do not derive first/last from already visually reversed output rows.

Ragged rows, horizontal spans, vertical continuation cells and differing grids
need a separately proven mapping to logical column positions. Existing output
cell-list indices or compressed nonempty cells are not a sufficient oracle.
Defer those with diagnostics rather than guessing a band or corner. Row-only
conditions could later be enabled independently when row partitions are reliable.

## Future bounded implementation contract

Parse each selected style's unconditional operations plus condition-indexed CCnf
operation sequences, with a validated parent graph. Reuse the shared UpxChpx
prohibitions; reject nested CCnf rather than recursively executing it. Charge
all decoded records and reject malformed lengths, unknown CNFC, forbidden sgc,
invalid CFVanish and band values. Preserve sequential operations/overrides;
do not convert toggles to a Boolean before their style base is known.

Extend the raw structural prepass to assign table/row/cell IDs, then finalize
row counts and condition context when a table closes, BEFORE clean. No CP-sized
maps, repeated table scans per character, or mutation of field/note state.
Bound paragraphs/rows/cells and depth with existing budgets before allocation.
Cache by style plus the ordered matched-condition context and underlying base,
not style alone. Hidden text never removes structural delimiters. This is a design,
not a change to currently integrated unconditional behavior.

Required tests: all option bits on/off; sizes 1/2/3; header-prefix exclusion;
first/last exclusion; one-row/one-column/corner ties; physical RTL versus logical
column order; nested/sibling/story isolation; same style with different position;
paragraph/direct show override; inherited conditions; malformed and budget bounds.

## Authored fixture and independent result

`tests/fixtures/doc_conditional_styles/generate.py` derives only ordinary_table.doc
using the existing generic CFB writer and copied inline-PAPX rebuild. Adds parent
style CCnf(header, CFVanish=1), then CCnf(top-right, CFVanish=0); child inherits.
No unconditional table hiding. All row TTPs use TIstd=17 and explicit TTlp:
`disabled`=0x600, `header`=0x620, `corner`=0x720. Cell text/grid unchanged.
Direct hidden Key and direct shown alpha beta remain independent controls.

Spec oracle: disabled has all stored words except Key; header additionally hides
Value and Примечание; corner hides Value but restores Примечание. Other two rows
and surrounding paragraphs stay identical; three rows/three cells always remain.

`compare_lo.py` separately records stored UNO cell strings and PDF text with
PrintHiddenText/ShowHiddenCharacters/ShowHiddenParagraphs=false, macros disabled
and updates disabled. See lo-comparison.json for version/settings/input hashes.
LO behavior is observational evidence, not a replacement for the spec oracle.
This fixture covers gates/header/corner priority, not the entire proposed matrix.

Observed LibreOffice 7.4.7.2 result: all three PDFs are identical. Direct-hidden
Key is omitted, but Value and Примечание remain visible even in header.doc.
Stored UNO cell text includes all words in all variants. Thus LO does not apply
this conditional hidden formatting; the negative result is explicit and does not
validate the header/corner spec expectation. Word has not been compared.


## Implemented narrow scope (after unconditional integration 28eb95c)

Runtime: `_doc_styles.py` validates bounded CCnf records and retains inherited
condition sequences/band sizes; `_doc_conditions.py` proves complete unmerged
rectangular partitions and applies literal CFVanish 0/1; `doc.py` captures TTlp /
header flags and invokes this proof before clean. The assembler and proof share
`row_boundary`: effective TIpgp/TIstd/direction/position identity and first-cell
paragraph-frame comparison under the default-position gate. No style-only grouping.

Supported: all twelve CNFC choices, flags, precedence/ties, explicit bands 1..3,
header-prefix exclusion, logical RTL cell order, paragraph/direct overrides,
independently complete innermost nested tables and separated stories. No explicit
band size means no inferred band. Existing unconditional visibility remains the
fallback. Cache scope is per story, keyed by applied style, matched conditions,
and unconditional Boolean; operation work is budgeted and never per character.
Row counting is linear, with a running header-exclusion count.

Conservative exclusions: any table-style PAPX; any TAPX other than the two band
sizes (including TCnf); relative conditional toggles 128/129 pending proof of the
correct conditional base; incomplete rows; unequal/non-increasing grids; horizontal
or vertical merges; malformed direction/option flags; enclosing rows containing
nested tables; and presence of Sdt/Prot bookmark metadata. Ambiguous boundaries
on either side contaminate both adjacent candidate partitions. Conditional-only
show/hide is not applied in these cases: unconditional visibility is retained,
a diagnostic is emitted, and note references in the affected rows receive unknown.
Nested inner tables can still be independently proven. No bookmark or frame guess.

These exclusions are deliberately broader than intrinsically unsafe formatting:
a decorative TCnf also causes fallback until its restricted properties are
independently classified. This is not complete DOC conditional-style support.

Tests: `tests/test_doc_conditional_styles.py` contains literal semantic oracles,
real authored CFB expected text, all edge/corner flags, precedence, band polarities,
header exclusion, identity/frame splits, invalid direction neighbors, direct and
paragraph overrides, nested/story separation, note visibility unknown fallback,
malformed CNFC/operations/bands, inheritance and pre-clean budget/depth checks.
The fixture wire tests and recorded LibreOffice negative comparison remain separate.
