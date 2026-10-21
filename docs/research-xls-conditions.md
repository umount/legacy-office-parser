# XLS: bounded numeric conditions

The operators `<`, `<=`, `>`, `>=`, `=`, and `<>` are supported at the start
of the first two sections. The first matching section is selected before
rounding and percent scaling. A final unconditional section is allowed.
All sections, including those not selected, are validated before producing
the result. A color tag may precede or follow the condition; duplicate tags
are rejected.

## Incomplete support and avoiding guesses

Support applies only to nonnegative values. All negative values with conditional
masks retain their raw numeric representation with a warning: the normative rule
for an implicit minus sign in arbitrary conditional sections has not been
established reliably enough. The previously investigated heuristic based on a few
LibreOffice examples is not used. Ordinary sign-based sections are unchanged.

Mixed implicit/conditional three-section masks, a condition only in the second
section, unsupported numeric cores, and cases where no section matches also
remain unsupported. Width-dependent `#####` output is not generated. Zero in a
two-section `[>0]...;fallback` mask still falls back because LibreOffice transforms
that format ambiguously. A single conditional section is allowed only with General.

## Precision and limits

The threshold is a bounded ASCII decimal representation within the finite
binary64 range. It must also equal its shortest decimal representation after
conversion to binary64: `Decimal(str(float(threshold)))`.
Overprecise thresholds are rejected. For example, `1.00000000000000001` cannot
be compared as an exact Decimal if an Office reader rounds it to 1; otherwise,
a different section would be selected without a warning.

Comparisons involve no arithmetic rounding and do not depend on the caller's
Decimal context. The raw value and its sign are unchanged. The complete mask
is limited to 64 characters; the cumulative text budget remains in force.

## Sources and validation

- [MS-XLS Format grammar](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
- [Microsoft numbering formats](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.numberingformats)
- [LibreOffice format codes](https://help.libreoffice.org/latest/en-US/text/shared/01/05020301.html)

Synthetic BIFF streams test all operators, boundaries, raw types, FORMULA caches,
limits, and hostile Decimal contexts. Authored OOXML workbooks pass through
XLSX→CSV and XLSX→XLS→CSV. An additional probe modifies the actual FORMAT in the
exported XLS so that export normalization cannot conceal the overprecise-threshold
comparison. Independent review checked 3336 rows, including 1992 nonnegative cases,
and found the threshold-precision bug; it was fixed by rejecting the ambiguous
case. This expands verified coverage but does not provide complete support for
conditional formats.
