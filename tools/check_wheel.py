"""Smoke-check an installed distribution with the original public corpus."""
import argparse
from pathlib import Path

from legacy_office_parser import parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixtures', type=Path)
    args = parser.parse_args()
    cases = [('ordinary_table.doc', 'doc'), ('slides_notes.ppt', 'ppt'),
             ('extended/ordinary_table.rtf', 'rtf'), ('extended/ordinary_table.odt', 'odt'),
             ('extended/typed_sparse.xls', 'xls'), ('extended/typed_sparse.ods', 'ods'),
             ('extended/slides_notes.odp', 'odp')]
    for path, fmt in cases:
        doc = parse(args.fixtures / path)
        assert doc.format == fmt and doc.text, f'Installed {fmt} parser failed'
        if fmt in ('xls', 'ods'):
            assert len(doc.sheets) == 2
            assert any(c.is_formula and c.value == 25 for c in doc.sheets[0].cells)
        elif fmt in ('ppt', 'odp'):
            assert len(doc.slides) == 3 and doc.slides[2].notes
        else:
            assert any(b.kind == 'table' for b in doc.blocks)
    print('Installed wheel: all seven formats passed')


if __name__ == '__main__':
    main()
