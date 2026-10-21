# XLS: explicit labels for numeric values

This describes the 0.9 stage. Version 0.10 additionally supports ordinary
sign-based sections and standard colors; see [numeric sections](research-xls-sections.md).

## Purpose

Numbers such as `12.50 kg` and `USD 12.50` lose part of their meaning if only
`12.5` is returned. Labels explicitly stored in the mask are preserved in `text`;
the raw `value`, numeric type, and formula flag remain unchanged. Currencies are
not converted, units are not normalized, and formulas and external references
are not evaluated.

## Supported grammar

Exactly one previously supported numeric core: fixed, grouped, percent, or
scientific. Double-quoted text and individual backslash-escaped characters are
allowed before and after it. Empty quotes are valid: LibreOffice creates them
when exporting a numeric style with an empty label. Text cannot split the
numeric core; tokens are not joined after removing quotes. Date formats retain
their existing separate parsing path.

`0.00%` scales the number by 100; `0.00"%"` only appends the symbol.
`0"days"` remains a labeled number, not a date. Quoted text is not interpreted
as a color, condition, section separator, or numeric mask. The implicit minus
sign in a single numeric section precedes the entire label:
`"USD "0.00` with -12.5 produces `-USD 12.50`. This was verified through an
independent LibreOffice export; rounded zero remains unsigned under the
existing contract.

The complete mask is limited to 64 characters, the fractional part to 15
mandatory digits, and the exponent to 3 minimum-width digits. Appended text
counts toward the cumulative output budget. Scanning is linear; no new cache
is introduced. Sections, conditions, colors, locales, bare currency symbols,
accounting, scaling commas, fractions, and arbitrary interpolation still return
the raw number with a warning. A currency label does not imply support for
localized Excel currency formats.

## Sources and independent validation

[Microsoft: custom number format guidelines](https://support.microsoft.com/en-US/Excel/review-guidelines-for-customizing-a-number-format)
describes explicit quoted/escaped text, percent scaling, and sections.
[MS-XLS Format](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
defines the grammar. The implementation is independent and uses only the
standard library.

`tests/fixtures/xls_literals` contains an original ODS and the converted XLS.
Expectations are specified manually: mass, negative numbers, a USD label,
a literal percent sign, the word days, Cyrillic text, and two labels together.
The API and CLI preserve raw values; a separate test compares the complete
LibreOffice CSV display output. Synthetic BIFF streams supplement the actual
files with formulas, RK/MULRK, invalid syntax, limits, and extreme numeric values.
