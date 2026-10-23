# Original PPT master-object fixture

Authored from a new LibreOffice 7.4.7.2 Impress document, not a personal file.
The master has ordinary text `MASTER NOTICE / Привет 世界` and standard
placeholder shapes. Three slides have `Slide 1`, `Slide 2`, `Slide 3`; master
objects are enabled on slides 1 and 3 and disabled on slide 2.

Expected text is literal in `tests/test_ppt_master_text.py`. Independent UNO
readback confirmed ordinary/placeholder classification and inheritance flags.
See `docs/PPT.md` for generation steps and limitations.
No macro, external-resource or runtime office-application dependency is added.
