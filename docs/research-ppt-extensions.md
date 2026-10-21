# PPT slide extension warning classification

Investigated 2026-10-21 against the original project fixtures and the original
120-slide workload from `tools/check_performance.py`. No private documents were
used. This change classifies a narrow set of non-text records; it does **not**
add extraction of extension text or animation rendering.

## Observed records

`tests/fixtures/slides_notes.ppt` has three slide-level `RT_ProgTags` (5000)
containers. Each contains `RT_ProgBinaryTag` (5002), a `RT_CString` (4026) whose
UTF-16LE value is exactly `___PPT10`, and `RT_BinaryTagDataBlob` (5003).
The blob has record version zero but contains nested records in this context.
Two slides have 306-byte blobs; the remaining slide has a 105-byte blob.

The large benchmark was regenerated with the same ODP slide markup and
`expected('large')['slides']` as the performance tool, then converted using the
`MS PowerPoint 97` filter. All 120 slides contain the 306-byte form. This was a
bounded development-only LibreOffice conversion (separate disposable profile,
60-second parent timeout, converter resource limits); temporary conversion
artifacts were removed. No fixture files were changed.

The records inside these blobs are:

- 12011 / 0x2EEB: SlideTime10Atom, eight-byte creation timestamp.
- 11008 / 0x2B00: HashCode10Atom, four-byte animation hash.
- 61764 / 0xF144: ExtTimeNodeContainer, including nested time nodes.
- 61735 / 0xF127: TimeNodeAtom, 32-byte numeric timing attributes.
- 61757 / 0xF13D: TimePropertyList4TimeNodeContainer.
- 61762 / 0xF142, instance 20: TimeEffectNodeType. Five-byte integer variant;
  observed roles are 9 (root) and 4 (main sequence).
- 61761 / 0xF141: TimeSequenceDataAtom, 20-byte sequencing attributes.
- 61733 / 0xF125: TimeConditionContainer; observed instances 3 and 4.
- 61736 / 0xF128: TimeConditionAtom, 16-byte trigger attributes.
- 61756 / 0xF13C: ClientVisualElementContainer.
- 11009 / 0x2B01: VisualPageAtom, four-byte page target, value 1.
- 11010 / 0x2B02: BuildListContainer, empty in both workloads.

## Primary specification evidence

Microsoft's [RecordType enumeration, MS-PPT 2.13.24](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/38fb1fa5-0a62-477a-8b14-178df22de812)
provides the numeric mappings above.
[SlideProgBinaryTagContainer, 2.5.21](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/e25eb8d2-627e-4104-b293-fc8ed82a098c)
and [PP10SlideBinaryTagExtension, 2.5.24](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/ccb82f60-e1ae-4379-b1e0-00909bb70b17)
define the envelope, tag name and blob contents. The latter permits both timing
metadata and comments: the name alone cannot justify dropping an omission warning.
[Comment10Container, 2.5.25](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/1a15453d-859f-48ee-8dcd-4d51ab9227f8)
contains optional author/comment strings and remains unsupported.

The non-text interpretation and fixed sizes are established by:

- [SlideTime10Atom, 2.5.31](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/d5e12b99-4151-4c28-9d86-52328381c974),
  [HashCode10Atom, 2.8.3](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/bd2afac8-4f48-4071-ba1a-346546e1bee7),
  and [BuildListContainer, 2.8.4](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/48ffef8e-5b8d-4711-a598-cfa1f9fcb252).
- [ExtTimeNodeContainer, 2.8.15](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/83d39c58-0d30-46a4-bffb-188d792cb5a7)
  and [TimeNodeAtom, 2.8.17](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/a6b40fd7-decd-4d6e-991a-10394458c6a8).
- [TimePropertyList4TimeNodeContainer, 2.8.18](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/d6d7cd40-b40d-4e50-90e8-bb5464ef07c2),
  [TimeEffectNodeType, 2.8.28](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/20f25cbe-85c3-47a9-b8ab-5d4f9e82d6ed),
  and [TimePropertyID4TimeNode, 2.13.38](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/582b9812-deec-41e3-a367-4016878ca98c).
  Instance 20 identifies the role property, integer variant type 1; permitted
  role values are 1 through 9. Other TimeVariant records are not covered.
- [TimeSequenceDataAtom, 2.8.74](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/342b92a2-73df-4b0b-9878-862f3532d570),
  [TimeConditionContainer, 2.8.75](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/3b2ae2ff-52fc-405b-8c3a-fd0702f490d3),
  and [TimeConditionAtom, 2.8.76](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/6d793884-73f2-4b87-b8b1-a1b0e6310ad6).
- [ClientVisualElementContainer, 2.8.44](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/80b3266a-1fe6-4140-acef-0483ac355c89)
  and [VisualPageAtom, 2.8.46](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/4ecd8e29-93c1-4393-a31c-80a8ccd529ce).

## Implementation boundary

Only live presentation-slide containers use the classifier. It checks the
complete envelope and every traversed child using parent-specific type sets,
record versions, instances, fixed lengths, required children and duplicate
checks. The iterator stack uses the existing record and depth budgets. There
is no general string scan, decoding of opaque payloads, or recursion on the
Python call stack. Known record lengths and traversed bounds fail closed;
unrecognized layouts retain the existing warning.

Supported classification is exactly the records listed above, in the documented
parent contexts. BuildList must be empty; TimeVariant must be the integer role
property; ClientVisualElement must target the page. Empty tags/blobs contain no
text and need no omission warning. Timing values are not rendered or returned.
This is not a complete animation conformance validator: it does not evaluate
triggers, validate all timing flag semantics, or enforce every field ordering
rule. No such behavior is needed to classify these fixed numeric payloads.

Unknown tags, PPT9/PPT12, string tags, comments, text atoms, other variants,
behaviors, nonempty build lists, unknown nested children and extra envelope
records keep the warning. Notes-page extensions also keep it. Document- and
shape-level extension support is unchanged. A file without this warning is not
a claim of complete rendering or support for every Office extension.

## Validation

Independent binary builders exercise supported metadata, mixed known/unknown
content, comments and strings, bad headers/lengths, required children, sibling
tags, wrong contexts, inactive objects, shared budgets and deep nesting. A
120-slide synthetic stream checks order and content. The committed original
LibreOffice fixture is checked against its independently authored expected JSON,
including titles, body text, notes and hidden flags, with no warnings.

The separately converted original 120-slide performance workload passed
`check_performance.validate(..., 'large')`: all 960 authored paragraphs in
slide order, 120 slides, 125878 projected text characters, zero warnings and
zero validation errors. No extension text was added to the output.

Final focused regression command:

```sh
.venv/bin/python -B -m pytest -p no:cacheprovider -q tests/test_ppt_extensions.py tests/test_ppt.py tests/test_ppt_wordart.py tests/test_fixture_corpus.py tests/test_performance_tool.py
```

Result: **130 passed in 2.46s**. Ruff on the two changed Python implementation
files and the new test file: **all checks passed**. Bytecode and pytest/Ruff
cache writes were disabled for these checks.
