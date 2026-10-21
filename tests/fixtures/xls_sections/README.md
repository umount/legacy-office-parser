# Original XLS sign sections

`sign_sections.xlsx` is an independently authored OOXML source with exact
number masks; it does not imply XLSX runtime support. The deterministic
`tools/generate_xls_sections_fixture.py` creates it using only stdlib, then
LibreOffice 7.4.7.2 exports `sign_sections.xls`. No personal documents are used.

Hand-authored expectations cover positive, negative, zero, parentheses,
percent, currency labels, quoted semicolons, an unsigned negative display,
a negative rounded to zero, and a cached formula. Raw signs are preserved even
when the displayed mask suppresses them. The zero label is not an empty cell.

Public API and CLI tests validate values and display separately; the opt-in
LibreOffice CSV oracle verifies every displayed cell. Source reproducibility
is tested; XLS binary metadata may vary between LibreOffice runs.
