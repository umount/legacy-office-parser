# XLS: literal-only fourth text sections and fraction investigation

## Fraction decision

Microsoft's [Display numbers as fractions](https://support.microsoft.com/en-us/excel/display-numbers-as-fractions)
confirms fixed denominators such as `# ?/16` and describes nearest-result rounding.
The [MS-XLS FORMAT grammar](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
permits fraction syntax and delegates interpretation to ECMA-376 section 18.8.31.
These consulted sources do not settle the required tie-breaking and exact
zero/integer spacing contract for the proposed implementation. This investigation
does not claim that no primary specification could settle those questions.

A Calc-only observation would not establish an Excel-wide rounding rule. Fraction
formatting therefore remains unsupported, including fixed denominators. No new
numeric approximation, locale, width, or negative-conditional behavior is added.
Synthetic controls confirm raw fallback for fraction masks across zero, integers,
negative values, ties, and a large value. The narrower text-literal
subset described below is implemented instead.

## Primary text contract

Microsoft's [custom number-format guidelines](https://support.microsoft.com/en-us/excel/review-guidelines-for-customizing-a-number-format)
describe quoted and escaped literals and explicitly state that omitting `@` from
the text section prevents typed text from being displayed. Combined with the
literal-character rules, this supports replacing a string's display with the
fourth section's literal characters. The exact same-XLS oracle below independently
checks the selected subset.

The fourth section may consist entirely of quoted fragments or single-character
backslash escapes. It has no active `@`. Quoted or escaped `@` remains literal.
Adjacent fragments concatenate, including empty quoted fragments. Empty sections
continue to hide text. The existing one-placeholder affix behavior remains intact.

All three numeric sections must validate under the existing bounded ordinary
sign-section grammar, even when unused by a string cell. Numeric cells continue
to use those sections. Conditional combinations, bare unquoted text, colors in
the fourth section, locale directives, fill/alignment codes, malformed quotes or
escapes, and a fifth section remain unsupported. The 64-character whole-mask
limit is unchanged. Boolean/error handling and negative conditional fallback are
unchanged. Nothing is evaluated or executed.

## Retained values and limits

The original string value, type, and formula-cache marker survive. The literal
becomes only the display text. The parser charges the retained raw string as
before, then charges a different literal display before publishing the cell.
An identical literal adds no duplicate display charge; an empty literal has zero
additional length. The literal itself is bounded by the format's 64-character
limit; no allocation proportional to the input string is required to replace it.

Tests cover LABEL, cached formula STRING, and repeated SST references. The decoder
charges UTF-16 units for source strings, while each SST reference charges the
decoded string length; that existing conservative distinction is preserved.
Exact-limit and one-below tests include astral Unicode, empty strings, identical
replacement, and three uses of an SST string. Public autodetection, `parse_xls`,
JSON and CLI checks preserve stored values while projecting the replacement.
No model/API changes are needed.

## Original complete XLS evidence

`tests/test_xls_text_literals_ole.py` contains a reproducible generator with literal
expected outputs. `tests/fixtures/xls_text_literals/` contains its seed XLSX,
patched XLS, and observed CSV. Ten string cases cover quotes, escapes, Unicode,
semicolons, literal `@`, empty fragments, and identical replacement. Three numeric
controls cover positive, negative, and zero values under a literal text section.

Harmless distinct Unicode seed masks are exported with LibreOffice, then only
equal-length FORMAT character bytes are patched. The complete Workbook stream
is checked against the intended patched bytes, and each cell XF is resolved to
its exact stored mask. All masks are within 64 characters and unpadded. The
public parser and a separate LibreOffice CSV conversion read the same patched
XLS; the input file must remain byte-identical after conversion. All 13 expected
displays match. A persisted SHA-256 assertion detects fixture changes. The XLSX
seed input alone is not treated as evidence for post-import format semantics.
No private corpus is used; LibreOffice is only an opt-in test oracle.

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_xls_text_literals.py
PYTHONPATH=src OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/python -m pytest -q tests/test_xls_text_literals_ole.py
```

Prior rejection cases that became supported have moved to exact positive
assertions; unrelated malformed/unsupported-mask checks remain in place.
