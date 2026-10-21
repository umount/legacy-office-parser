# Original ODT auxiliary tables

`auxiliary_tables.odt` was converted with LibreOffice 7.4.7.2 from the project's
handwritten `../rtf_stories/auxiliary_tables.rtf`. No personal documents are used.
The ODT stores A/B as a header table and C/D in a text box. LibreOffice changes
the source RTF footnote table into a text box during ODT export; the expected
ODT model follows the stored ODT, not the original RTF's story classification.

The native tests independently assert both tables, their cells and body text.
Synthetic tests cover footnotes/endnotes separately. This is not evidence that
LibreOffice preserves every source story identity across format conversion.
