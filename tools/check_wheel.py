"""Smoke-check an installed distribution with the original public corpus."""
import argparse
from importlib.metadata import version
from pathlib import Path

from legacy_office_parser import __version__, parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixtures', type=Path)
    args = parser.parse_args()
    assert __version__ == version('legacy-office-parser'), 'Runtime and wheel versions differ'
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
    comments = parse(args.fixtures / 'doc_comments/authored.doc')
    assert [c.author for c in comments.comments] == ['Ada Fixture', 'Ben Fixture', 'Ada Fixture']
    assert [c.source_cp for c in comments.comments] == [20, 38, 61]
    assert all(c.anchor_path is not None for c in comments.comments)
    assert comments.comment_text.count('Shared comment.') == 2
    hidden = parse(args.fixtures / 'xls_hidden_sections/preserved.xls')
    assert any(c.value_type == 'number' and c.value is not None and c.text == ''
               for c in hidden.sheets[0].cells)
    assert any(c.value_type == 'string' and c.value and c.text == ''
               for c in hidden.sheets[0].cells)
    for name, expected in [('unicode', 'Grüße Ж 😀'), ('cp1251', 'Привет'), ('cp932', '日本')]:
        art = parse(args.fixtures / 'rtf_wordart_unicode' / (name + '.rtf'))
        assert art.textboxes == expected
        assert art.text.count(expected) == 1
    print('Installed wheel: seven formats, DOC comments, hidden XLS and Unicode WordArt passed')


if __name__ == '__main__':
    main()
