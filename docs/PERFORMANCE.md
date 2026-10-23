# Performance checks

```sh
python tools/check_performance.py --profile large --repeats 3 --libreoffice /usr/bin/libreoffice
```

The tool generates original synthetic text documents, sheets and slides, checks
literal content/structure through the public API and reports elapsed time and
process peak RSS. `--profile small` gives a quick probe. Without LibreOffice,
binary DOC/XLS/PPT generation is skipped; the parser itself never needs it.

Use this for suspected performance changes, not every edit. Peak RSS includes
the Python process, and conversion time includes office startup, so these are
not isolated algorithm benchmarks. Historical measurements remain in Git history.
