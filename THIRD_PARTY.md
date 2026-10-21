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
