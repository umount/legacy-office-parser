# XLS optional and empty metadata audit

## Outcome and scope

No proven false refusal was found in the audited BIFF8 XLS paths. Runtime code
is unchanged. Forty-four original synthetic tests establish existing safe
behavior and distinguish permitted emptiness from broken framing or required
references. No diagnostic code is needed.

The audit inspected the workbook stream reader, global-record dispatch,
worksheet dispatch, shared-string decoding and continuation accounting, and the
numeric/text formatting entry paths. The fixtures are deliberately reduced BIFF
protocol cases, not claims of exhaustive workbook conformance. Tests exercise
the public OLE-backed parser except where exact stream termination or record
budgets require the internal stream entry.

## Primary contracts and current behavior

[Header, MS-XLS 2.4.136](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/b64cf6b8-9472-4f97-9a69-d839f0fa1089)
and [Footer, 2.4.124](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/10606f3c-5e9b-4e7d-8bd9-7a28489fea4d)
permit a zero-size record with no string payload. Both are currently skipped by
worksheet dispatch. Absence, zero-size records and explicitly encoded empty
strings preserve ordinary cells. Nonempty print-header/footer extraction is not
implemented; successful parsing must not be mistaken for complete extraction of
those auxiliary texts. Skipped payloads receive outer framing checks, not full
semantic validation.

[SST, 2.4.265](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/b6231b92-d32e-4626-badd-c3310a672bab)
permits zero total and unique counts. The parser accepts the eight-byte zero
header and no entries. With no LABELSST references, an absent SST also already
works. A LABELSST reference into an absent/empty table remains invalid; missing
required string data is not optional metadata. A present SST with truncated
counts, missing claimed entries, or trailing data remains rejected.

[XLUnicodeRichExtendedString, 2.5.293](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/173d9f51-e5d3-43da-8de2-be7f22e119b9)
allows a zero phonetic-extension byte count when its flag is present. The parser
already handles that case for both compressed and UTF-16 text, including empty
base text. Negative lengths or nonzero lengths lacking their payload are
rejected. No continuation or rich-run truncation recovery was introduced.

[MergeCells, 2.4.168](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/41a3a3e7-1015-4322-8329-37dcdf41179b)
defines an unsigned range count with an upper bound and an array of exactly that
size. Zero ranges already work without emitting merges or cells. Missing count
bytes, a positive count without ranges, and extra range bytes after a zero count
remain invalid.

[Dimensions, 2.4.90](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/5fd3837c-9f3d-4952-8a85-ad93ddb37ced)
defines zero upper bounds as no used cells and includes directly formatted cells
in the used range. The all-zero record already works. Output extents come from
retained cells and merges, not an allocation based on dimensions. Present
truncated/reversed/out-of-BIFF-range dimensions remain rejected. Configured
row/column resource limits on declared dimensions remain in force; formatting
can legitimately enlarge those dimensions, so this is not an absence case and
was not used to bypass limits. No claim is made that arbitrary lower bounds are
ignorable when upper bounds are zero.

[FormulaValue, 2.5.133](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/39a0757a-c7bb-4e85-b144-3e7837b059d7)
distinguishes blank-string tag 3 from string tag 0. Tag 3 already retains an empty
string without requiring a STRING record. Tag 0 requires the subsequent string
result; EOF or an unrelated empty header cannot substitute for it. No cache is
inferred or recalculated.

[XLUnicodeString, 2.5.294](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/36ca6de7-be16-48bc-aa5e-3eaf4942f671)
has fixed character-count and encoding fields even when character count is zero.
The Header/Footer zero-size exception must not be generalized to all strings,
FORMAT records or sheet names.

## Other inspected boundaries and limitations

The OLE entry opens only Workbook (or Book); absent summary-property and drawing
streams are not accessed. Corrupt OLE directory links and a missing required
workbook stream remain container failures. Existing tests cover those shared
container paths; this audit does not alter the shared OLE helper.

Missing XF lookup data already falls back to raw numeric text with a warning.
Unknown custom-format syntax also falls back; malformed present FORMAT/XF record
framing still fails. These recovery behaviors do not establish that required
style records are optional under the complete file grammar.

Unknown worksheet metadata records are generally skipped. Row/column layout,
comments, drawings and print metadata are not newly interpreted by this audit.
Non-worksheet sheet kinds already handled as omitted substreams still require
valid BOF/EOF framing. Unsupported sheet types, encryption, missing EOF, invalid
sheet offsets, duplicate cells and nonfinite numeric values remain hard errors.
This is a scoped refusal audit, not comprehensive validation of ignored payloads.

## Regression evidence

`tests/test_xls_optional_metadata.py` contains 44 tests. Positive cases retain
ordinary numeric cells, exact empty strings and empty sheet structures. Negative
cases protect SST references, counts and sizes, formula-string dependencies,
nonzero phonetic payload lengths and record framing. Empty metadata records still
consume the cumulative record budget. They neither consume text for absent
payloads nor reset cumulative text/cell limits. No synthetic text is invented,
no broad exception recovery is added, and no resource limit is relaxed.

Validation against baseline 84b3452: dedicated suite 44 passed; complete XLS
suite 2677 passed / 15 opt-in skips; Ruff passed. All tracked baseline files
remain byte-identical; only this research file and the dedicated tests are new.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls_optional_metadata.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls*.py
.venv/bin/ruff check --no-cache tests/test_xls_optional_metadata.py
```
