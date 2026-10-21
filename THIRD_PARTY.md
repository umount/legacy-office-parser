# Sources and provenance

This package was developed with reference to Microsoft's MS-DOC and MS-PPT
format specifications and inspected open-source implementations. It is not
Microsoft Office and is not affiliated with the referenced projects.

- `olefile` is a runtime dependency; its own license accompanies that package.
- WordCraft (`storytold/wordcraft`, revision
  `e05b7fe86f3b85454000dffc321de638d7009817`) was consulted for DOC parsing.
  MIT attribution is retained in `licenses/WORDCRAFT-MIT.txt` for any adapted
  portions. Its UI, assets, fonts and rendering engine are not included.
- `Horsmann/sharepoint-to-text`, revision
  `6f2e77ca4b5fcf4e42550b9d1bb3cd51a4078dec`, was studied as a reference.
  Its heuristic DOC core and complete application are not bundled.
- Apache POI and office_oxide were investigated as algorithm/reference options,
  not runtime dependencies.

Original test fixtures are generated specifically for this project. Personal
lecture notes/books and their extracted content must remain under ignored tmp/.

Additional format references:

- xlrd 2.0.2 (BSD), inspected for BIFF8 string continuation, record layouts,
  numeric/date interpretation and cached formulas. No xlrd runtime or whole
  source module is bundled. See `docs/research-xls.md`.
- striprtf v0.0.29 (BSD-3-Clause) and WordCraft's RTF module were consulted for
  format behavior. The RTF lexer and reader are independently written; neither
  the striprtf regex pipeline nor its source tables are included.
- odfpy was consulted for behavior; no odfpy source is copied or imported.
  The ODF implementation follows OASIS package and XML specifications using
  Python's standard library. See `docs/research-odf.md`.
