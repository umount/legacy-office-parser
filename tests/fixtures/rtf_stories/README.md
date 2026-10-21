# Original auxiliary-table RTF

`auxiliary_tables.rtf` is handwritten project test data. Its header contains
Before, table A/B, After; its footnote contains table C/D; the body is Body.
No personal or third-party documents are included.

Tests independently assert structure and legacy text projections. The opt-in
LibreOffice test reads tables from DOCX header/footnote parts and compares cells.

LibreOffice versions may export separate identical first/default header parts;
the oracle validates every variant instead of requiring one physical XML part.

Only active header references are compared: first-page and even-page templates
are selected by titlePg/evenAndOddHeaders. Inactive empty templates do not
represent the authored visible header. An active empty header is still checked.
