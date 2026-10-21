# Bounded currency, scaling and mixed decimal places

Research and implementation: 2026-10-21. Only `_xls_formats.py` changes runtime
behavior; no models, dependencies, formula execution or external reads are added.

## Primary sources

- [MS-XLS 2.4.126 FORMAT](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b):
  FORMAT carries the custom string; `NFPartLocaleID` has a symbol and optional
  hexadecimal identifier, and occurs at most once per section. The grammar is
  explicitly locale-sensitive. This does not justify treating arbitrary locale
  tags as disposable decoration.
- [Microsoft custom-format guidelines](https://support.microsoft.com/en-US/Excel/review-guidelines-for-customizing-a-number-format):
  mandatory zero and optional hash digits, rounding to the available decimal
  places, section routing, and scaling commas. Its explicit `0.0,,"M"` example
  maps 12,200,000 to `12.2M`.

These primary sources define the underlying constructs. The exact currency
whitelist below is additionally constrained by the independently authored
LibreOffice BIFF observations, not inferred for other locale identifiers.

## Implemented contract

- Exactly `[$$-409]`, `[$€-407]`, and `[$USD-409]`, at most once per numeric
  section, as a prefix or suffix to a fixed, nonpercent numeric core. Emit the
  explicit symbol `$`, `€`, or `USD`; do not change separators, query locale,
  or invent spacing. Existing quoted/escaped literals may surround the core.
- A fixed integer core remains `0` or `#,##0`. Contiguous commas immediately
  after the complete fixed core divide by 1000 per comma before rounding.
  Quoted/escaped suffixes follow the commas. Grouping commas within `#,##0`
  remain grouping. Scientific and percent scaling combinations are excluded.
- Fractional masks contain one or more mandatory `0` digits followed by zero
  or more optional `#` digits, with at most 15 total fractional places. Round
  to that total and trim only the optional trailing zero digits. Mandatory
  places and literal suffix zeros remain. All-optional fractions, interleaved
  zero/hash masks and optional scientific/percent fractions remain unsupported.
- Existing sign/zero sections and conditional restrictions remain. Selection
  uses the original value before scaling or rounding. Every negative conditional
  value still returns raw text with the existing unsupported-format warning.
- Empty-symbol locales, special identifiers, calendar/numeral tags, arbitrary
  currency tags, duplicate tags, currency date/scientific/percent masks and
  malformed or split cores retain raw values with the existing warning.

The stored int/float, signed-zero bits, numeric type and formula-cache metadata
are unchanged. Private precision-340 Decimal arithmetic retains the established
shortest-round-trip decimal / half-up policy. This is not a claim of complete
Excel binary-rounding emulation. All format sections are validated before routing.
The 64-character original-mask limit, 15-place limit, and cumulative text budget
are unchanged. Scaling cannot increase the existing maximum output size.

## Original BIFF evidence, including normalization limits

Read-only evidence supplied in `/tmp/xls-locale-research`:
`results.json`, `preserved.py`, `preserved.xls`, `preserved-results.json`.
The initial export/reimport probe records `actual_format`; LibreOffice can
normalize unsupported formats to General and quoted literals to escaped ones.
Those normalized exports alone are insufficient evidence for the original mask.

`preserved.py` instead exports distinct seed masks, patches their FORMAT payloads
in the Workbook stream *after* export, verifies the written stream byte-for-byte,
and independently imports that XLS to CSV. Reading the actual FORMAT records
again verified every requested mask, followed solely by empty quote pairs used
to retain record/stream lengths. The input XLS SHA-256 is
`c55c7f594f50812ed3c5fdeb696d73e485ae0cdc845bea8a1043edc4fdc51cd5`.

Seven supported preserved cases match the new renderer's unpadded-mask results:

- `[$$-409]#,##0.00`, -1234.5 → `-$1,234.50`.
- `[$€-407]#,##0.00`, -1234.5 → `-€1,234.50`.
- `[$USD-409]0.00`, 0 → `USD0.00`.
- `0.00[$€-407]`, -12.5 → `-12.50€`.
- `[$USD-409]0.00;([$USD-409]0.00)`, -12.5 → `(USD12.50)`.
- `0.0,,"M"`, 1234567 → `1.2M`.
- `0.0##`, 1 → `1.0`.

The preserved masks are 80–81 characters because of padding: they intentionally
exceed the runtime 64-character bound, so this is a semantic oracle, not an
end-to-end claim that this parser renders that entire XLS. Runtime does **not**
strip padding or relax the limit. New synthetic BIFF tests independently assert
the precise unpadded FORMAT payload before parsing it and compare against literal
expected strings. They need no LibreOffice and do not derive expectations from
this parser. No external archive or private input was used.

Preserved unsupported cases include `0.##`, empty-symbol locale 407 (whose
observed separators actually change), F800/F400, calendar/numeral identifiers,
and malformed `[$]`; these remain raw regardless of incidental Calc output.

## Validation and integration status

`tests/test_xls_scaled_currency.py`: 133 passed. Covers exact FORMAT bytes,
NUMBER and cached FORMULA values, RK/MULRK integer types, signs and signed zero,
rounding carries, scaling before rounding, optional zero trimming, unsupported
and malformed masks, all-section validation, negative conditionals, exact output
budgets, length/precision bounds, binary64 extremes and hostile Decimal contexts.

The former rejection cases for scaling now assert their exact displayed values,
while retaining raw-value, cached-formula and warning checks. Unsupported masks
continue to require the raw-value fallback. Ruff passes.

## Bounded preserved-XLS oracle (integration follow-up)

The persisted original fixture `tests/fixtures/xls_scaled_currency/preserved.xls`
closes the above 80–81-character evidence gap. Every tested FORMAT is **48 or
49 characters**, including empty-quote padding, within the unchanged 64-character
runtime bound. It contains 19 numeric-literal cells, with no formulas or links.
SHA-256: `462a619c11d90e0dad081127e1c252e02f21345e999c97089cac2c25f79ad2f2`.
Size: 8,704 bytes. Authored using isolated LibreOffice 7.4 conversion and original
seed masks, followed by in-place FORMAT patching.

`tests/test_xls_scaled_currency_ole.py` contains literal independent expectations
and the complete generator `generate_preserved(destination)`. It reuses the
existing XLSX numeric-literal probe writer and bounded converter utility. Unicode
seed labels force sufficient encoding width for the euro symbol. Each replacement
has the identical byte length to its seed. The generator checks every seed was
patched exactly once and reopens the compound file to verify the complete modified
Workbook stream byte-for-byte.

The ordinary fixture test independently reads FORMAT records, XF mappings and
NUMBER/RK/MULRK cell references to assert the actual mask used by **each cell**.
It then parses the complete same XLS through `parse_xls`, verifying raw numeric
values, numeric types, no formulas, zero warnings and all expected display strings.
The mask is not shortened, normalized, or substituted before parsing.

Coverage includes all three currency symbols, prefix and suffix placement,
negative currency sections, one/two scaling commas, literal suffixes, grouping,
negative scaled sections, optional decimals with mandatory zero preservation,
rounding carry, and a combined currency/grouping/scaling/optional-decimal mask.

The opt-in test regenerates the exported/patched file, converts that exact file
to CSV, and compares its CSV and parser output against the independent expected
strings. It also runs the same CSV comparison against the persisted fixture.
Both conversions assert input bytes remain unchanged. Conversion uses a fresh
private LibreOffice profile and the existing 45-second process-group bound.

Commands from staging:

```sh
.venv/bin/python -m pytest -q tests/test_xls_scaled_currency.py tests/test_xls_scaled_currency_ole.py
OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/python -m pytest -q tests/test_xls_scaled_currency_ole.py
```

Default tests: **134 passed, 1 skipped**. The skip is the opt-in LibreOffice test.
The opt-in run: **2 passed**, verifying both the regenerated and persisted files. Sandboxed
LibreOffice startup failed; the authorized isolated conversion was run with
escalation. Runtime parser behavior and old test expectations were not changed
for this follow-up.
