# DOC section boundaries and inline page breaks

The paragraph scanner uses PLCSED to recognize section-ending U+000C characters.
Other U+000C characters remain inline page breaks, projected as newlines within
the paragraph/cell. Neither style names nor text heuristics establish boundaries.

Primary authorities:

- [MS-DOC 2.8.26 PlcfSed](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/68a959a6-11e0-4f3e-9a99-76ca8cc4dddc):
  interior CPs start new main-document sections; the preceding character must be
  U+000C. The final CP is a sentinel at or beyond the main-document end and does
  not start another section, including when it extends into auxiliary stories.
- [MS-DOC 2.2.2 PLC](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/a649fcc5-7868-4245-be12-04eea89d916b):
  N data elements have N+1 CPs. With 12-byte SEDs, byte length is 16*N+4.
  Neither this rule nor PlcfSed specifies a positive minimum N. A zero-SED PLC
  with CP zero is accepted for an empty main story, but cannot cover nonempty text.
- [MS-DOC 2.9.243 Sed](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/ae1ec5fc-e3c0-4e27-956e-9ceedc41cc2a):
  each SED is 12 bytes. SEPX contains layout properties and is not needed to
  identify section boundaries; this fix does not follow SEPX offsets.
- [MS-DOC 2.4.2 Determining Paragraph Boundaries](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/30461a5b-e3ad-44cd-a3fe-038f86639b13):
  an end-of-section character can terminate a paragraph.
- [MS-DOC 2.2.1 CP](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/a3d44e16-7d29-46f7-bb7b-d0d8a5734f83):
  CPs are logical character positions below 0x7FFFFFFF, not byte offsets.
  The parser indexes its existing UTF-16 buffer, including surrogate pairs.

The implementation charges the section count to the record budget before
traversal/set growth, validates PLC size and strictly ascending CPs, requires
coverage of the main story, and verifies each interior boundary's U+000C.
Malformed metadata raises InvalidDocumentError; it is not silently ignored.

Tests in `tests/test_doc_sections.py` contain original tiny synthetic section
and page-break fixtures, including a two-paragraph/one-cell regression, UTF-16
across pieces, empty main stories, auxiliary-story isolation, and record limits.
The additional 46 KiB benign converted benchmark fixture guards the actual
reported failure: all 20 body paragraphs now remain outside table cells and all
60 table text entries survive. That converted file also places out-of-table
section breaks between cells; incomplete table fragments now produce warnings.
It must not be used as proof of one continuous, structurally valid DOC table.

A separate clean interoperability regression, `clean_section_before_table.doc`,
is generated from an original minimal DOCX by the fixture-local `generate_clean.py`.
Its two body paragraphs precede a single section mark at CP 32, followed by an
intact two-cell table and trailing paragraph. The test checks the actual section
mark, exact block structure, and absence of warnings. Unlike the odd benchmark
export above, this fixture establishes correct handling of a normal section
boundary before a table.
