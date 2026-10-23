"""Smoke-check an installed distribution with the original public corpus."""
import argparse
from importlib.metadata import version
from pathlib import Path

from legacy_office_parser import __version__, normalize_text, parse


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
    inline = parse(args.fixtures / 'odp_inline_objects/inline.odp')
    assert inline.slides[0].text == 'Object before\nObject cell\nObject after'
    assert inline.textboxes == ''
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
    ranges = parse(args.fixtures / 'doc_comment_selections/authored.doc')
    assert [(c.selection_start, c.selection_end) for c in ranges.comments] == [(8, 22), (50, 61)]
    assert ranges.text.count('Across empty paragraph.') == 1
    sections = parse(args.fixtures / 'doc_comment_sections/authored.doc')
    assert [(c.selection_start, c.selection_end) for c in sections.comments] == [(8, 21)]
    assert sections.comments[0].author == 'Ada Section'

    labels = parse(args.fixtures / 'xls_text_sections/preserved.xls')
    assert any(c.value == 'retained' and c.text == 'Name: retained'
               for c in labels.sheets[0].cells)
    replies = parse(args.fixtures / 'doc_comment_replies/authored.doc')
    assert [(c.reply_depth, c.parent_ordinal) for c in replies.comments] == [(0, None), (1, 1), (2, 2)]
    assert replies.text.count('Shared comment.') == 2
    literals = parse(args.fixtures / 'xls_text_literals/preserved.xls')
    assert any(c.value == 'retained' and c.text != c.value
               for c in literals.sheets[0].cells)
    headings = parse(args.fixtures / 'doc_headings/authored.doc')
    main = {b.text: b.heading_level for b in headings.blocks if b.kind == 'paragraph'}
    assert main['Heading one specimen'] == 1 and main['Heading two specimen'] == 2
    assert main['Inherited heading specimen'] == 1
    assert main['Direct outline three specimen'] == 3
    assert main['Direct body override specimen'] is None
    table = next(b for b in headings.blocks if b.kind == 'table')
    assert table.rows[0][0].blocks[0].heading_level == 2
    assert any(b.kind == 'paragraph' and b.heading_level == 2
               for b in headings.story_blocks['headers_footers'])
    for filename in ('authored.odt', 'explicit.rtf'):
        document = parse(args.fixtures / 'paragraph_headings' / filename)
        levels = {b.text: b.heading_level for b in document.blocks if b.kind == 'paragraph'}
        assert levels['Heading one specimen'] == 1
        assert levels['Heading two specimen'] == 2
        assert levels['Direct body override specimen'] is None
        table = next(b for b in document.blocks if b.kind == 'table')
        assert table.rows[0][0].blocks[0].heading_level == 2
        assert any(b.kind == 'paragraph' and b.heading_level == 2
                   for b in document.story_blocks['headers_footers'])
    terminated = parse(br'{\rtf1 Original}' + b'\0')
    assert terminated.text == 'Original'
    assert terminated.warnings == ['A single terminal NUL after the RTF root was ignored.']
    controls = parse(b'{\\rtf1 A\x00B}')
    assert controls.text == 'A\x00B'
    normalized = normalize_text(controls)
    assert normalized.text == 'AB' and controls.text == 'A\x00B'
    assert normalized.diagnostics[-1].code == 'text_normalized'
    note = parse(br'{\rtf1 Body{\footnote first\par second}}')
    assert len(note.notes) == 1 and note.notes[0].source_cp is None
    assert note.notes[0].body.block_end == 2
    assert [p.text for p in note.story_blocks['footnotes']] == ['first', 'second']
    header = next(a for a in headings.auxiliary_stories
                  if a.source == 'header' and a.kind == 'header' and a.variant == 'odd')
    assert (header.ordinal, header.section) == (8, 1)
    assert headings.story_blocks[header.story][header.block_start].text == 'Header heading specimen'
    from legacy_office_parser._xls_formats import render_number
    assert render_number(1 / 3, '# ?/?') == ' 1/3'
    assert render_number(1.23, '0.##') == '1.23'
    assert render_number(1.0, '0.##') is None
    assert render_number(1.0, 'General') == '1'
    soft = parse(br'{\rtf1 co\-operate\u8203?word}')
    assert normalize_text(soft).text == 'cooperate\u200bword'
    assert normalize_text(soft, drop_soft_hyphens=False).text == soft.text
    print('Installed wheel: seven formats and DOC/XLS/RTF feature regressions passed')


if __name__ == '__main__':
    main()
