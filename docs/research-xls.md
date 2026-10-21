# Focused XLS / BIFF8 extraction research

## Scope and provenance

Research preceded implementation on 2026-10-21. The selected reference was
**xlrd 2.0.2**, inspected at its tagged upstream source:

- [book.py: unpack_SST_table and workbook BOF handling](https://github.com/python-excel/xlrd/blob/2.0.2/xlrd/book.py)
- [sheet.py: unpack_RK, FORMULA, STRING, MULRK, LABEL, merged ranges](https://github.com/python-excel/xlrd/blob/2.0.2/xlrd/sheet.py)
- [upstream license](https://github.com/python-excel/xlrd/blob/2.0.2/LICENSE)

xlrd is BSD licensed. Source headers credit Stephen John Machin, Lingfo Pty Ltd
(2005–2012 book.py; 2005–2013 sheet.py). These are implementation references,
not a runtime or development dependency. No whole module or library was vendored.
The implementation is newly written around bounded record reads and the shared
extraction models. The RK bit interpretation and SST phase/continuation behavior
are informed by xlrd and the protocol. This document records the reference and attribution;
central provenance is listed in `THIRD_PARTY.md`.

Microsoft primary protocol references consulted:

- [XLUnicodeRichExtendedString](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/173d9f51-e5d3-43da-8de2-be7f22e119b9)
- [RkNumber](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/04fa5340-122f-49db-93ea-00cc75501efc)
- [FormulaValue](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/39a0757a-c7bb-4e85-b144-3e7837b059d7)
- [Formula](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/8e3c6978-6c9f-4915-a826-07613204b244)
- [String](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/504b6cfc-d57b-4296-92f4-ceefc0a2ca9b)
- [Format](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)

## Important decoding decisions

SST is segmented, not concatenated blindly. A continuation inside character data
starts with a fresh compression flag; encoding can change in either direction.
Compressed Unicode uses zero high bytes, not a locale code page. Rich-text runs,
phonetic bytes, and boundaries between strings do not consume that flag. Fixed
string headers cannot span records. UTF-16 code units cannot be split across
records, but a surrogate pair can straddle records: decode the accumulated UTF-16
once. Rich-run/phonetic bytes are bounded and skipped without creating formatting
objects. This extends the reference's happy-path behavior with explicit validation.

RK uses a signed 30-bit integer when its integer flag is set. Otherwise its bits
form the high portion of an IEEE double, with the remaining low bits zero. Apply
the optional division by 100 after decoding. MULRK validates its terminal column
and exact payload size before expanding cells.

FORMULA's eight-byte cache is numeric unless its last two bytes are FFFF. The
special tag selects STRING followup, Boolean, error, or empty string. A shared,
array, or table formula definition can precede the STRING record, as also handled
by xlrd. Empty-string results remain string cells rather than blank cells. Formula
tokens are length-checked but not interpreted, executed, or reconstructed:
`formula=None`, `is_formula=True`, and one document warning about unknown
expressions and potentially stale caches. External links are never fetched.

## Implemented contract

`parse_xls_bytes(data: bytes, limits: Limits) -> Document` uses shared bounded OLE
helpers to obtain Workbook (or the historical Book stream name). Only BIFF8 is
accepted; older BOFs raise UnsupportedFormatError. FILEPASS raises
EncryptedDocumentError, including inside skipped chart substreams.

Worksheet order comes from BOUNDSHEET, independent of physical stream order.
Hidden and very-hidden both map to `hidden=True`. Chart/macro/VB sheets are
validated structurally and omitted with a warning. Embedded chart records are
excluded from worksheet cells. Record sizes, BOFs, EOFs, unique sheet offsets,
substream boundaries, nesting, cell coordinates, and payload sizes are bounded.
Trailing OLE stream padding is tolerated after the final EOF.

Supported data: NUMBER, RK, MULRK, LABELSST, BIFF8 LABEL, BOOLERR, BLANK,
MULBLANK, FORMULA cached values and STRING continuations, MERGEDCELLS.
Sparse cells use actual 1-based positions; duplicates are rejected. Merges are
inclusive 1-based ranges, without expanding covered coordinates. Cells are sorted
by row/column. Sheet extents derive from actual cells and merge ranges;
DIMENSIONS is checked but does not allocate or inflate a dense grid.

XF/FORMAT and DATEMODE provide conservative date recognition. Common built-in
calendar/time formats and simple custom formats produce ISO strings with
`value_type='date'`; both 1900 and 1904 epochs are handled. Serial 60 in the 1900
system, negative/unrepresentable dates, elapsed-time formats, locale-dependent
built-ins, missing custom formats, and ambiguous conditional/sectioned formats
retain raw numbers with warnings. Missing XF also retains numbers with a warning.
This is not an Excel number-format renderer: numeric styles, colors, rich text,
charts, drawings, annotations, and formula expressions are not reproduced.

Resource limits apply before allocating cell/string collections where possible:
file/stream bytes via shared helpers, records, depth, sheets, row/column bounds,
combined cells plus merges, SST string count, and cumulative decoded/output text.
SST contents and their emitted references both consume text budget, intentionally
bounding unused SST data as well as repeated output. Archive limits are for ZIP
formats and do not apply to the OLE Workbook stream. Errors are content-independent
and do not include extracted private text.

## Validation

`tests/test_xls.py` contains original synthetic BIFF and CFB construction only.
55 tests pass, including:

- encoding transitions both ways, rich/phonetic continuation, a new-string boundary,
  and a surrogate pair crossing CONTINUE;
- signed/scaled/inexact RK, MULRK, blank cells, explicit merges and sparse positions;
- all formula cache kinds, intervening shared-formula definition, continued STRING;
- 1900/1904 dates, serial 60, time-only/custom formats and numeric fallback;
- malformed lengths, indices, offsets, BOFs/EOFs, coordinates, and Unicode;
- all applicable limits, including repeated SST text and aggregate cells/merges;
- synthetic OLE through `parse`, `parse_xls`, path input, and Workbook/Book names.

Commands from the repository root:

```sh
.venv/bin/python -m pytest tests/test_xls.py -q
.venv/bin/python -m ruff check src/legacy_office_parser/xls.py src/legacy_office_parser/_xls_strings.py tests/test_xls.py
```

An explicitly authorized existing local XLS corpus file was also read in place:
3 sheets, 108 sparse cells, no merges, numeric/string values, no warnings. No cell
text or names were printed, and the fixture was not copied or published. Provenance
of that external corpus is unknown; it is not part of these tests or deliverables.
