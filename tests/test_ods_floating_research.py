"""Authored sheet-owned ordinary drawing text; research, not parser requirements."""
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

import pytest

from test_odf_inline_objects import p
from test_odf_passive_research import package, _READER_START, _READER_END


def fixture():
    sheets = []
    for owner in ('North', 'South'):
        drawings = []
        for index, kind in enumerate(('text-box', 'rect', 'ellipse', 'custom-shape')):
            label = owner + ' ' + kind
            body = p(label + ' paragraph') + '<text:list><text:list-item>' + p(label + ' list') + '</text:list-item></text:list>'
            attributes = (f'draw:name="{owner}-{kind}" svg:x="1cm" svg:y="{index * 3 + 1}cm" '
                          'svg:width="5cm" svg:height="2cm"')
            if kind == 'text-box':
                drawings.append('<draw:frame ' + attributes + '><draw:text-box>' + body + '</draw:text-box></draw:frame>')
            else:
                drawings.append(f'<draw:{kind} ' + attributes + '>' + body + f'</draw:{kind}>')
        sheets.append(f'<table:table table:name="{owner}"><table:shapes>' + ''.join(drawings) +
                      '</table:shapes><table:table-column/><table:table-row>'
                      '<table:table-cell office:value-type="string">' + p(owner + ' cell') +
                      '</table:table-cell></table:table-row></table:table>')
    return package('spreadsheet', ''.join(sheets))


def expected():
    return {owner: {'cell': owner + ' cell', 'drawings': [
        {'name': owner + '-' + kind,
         'text': f'{owner} {kind} paragraph\n{owner} {kind} list'}
        for kind in ('text-box', 'rect', 'ellipse', 'custom-shape')]}
        for owner in ('North', 'South')}


READER = _READER_START + r'''
        doc = desktop.loadComponentFromURL((root / 'floating.ods').as_uri(), '_blank', 0,
            (prop('Hidden', True), prop('ReadOnly', True),
             prop('MacroExecutionMode', NEVER_EXECUTE), prop('UpdateDocMode', NO_UPDATE)))
        if doc is None:
            raise RuntimeError('Authored ODS fixture failed to load')
        output = {}
        for index in range(doc.Sheets.Count):
            sheet = doc.Sheets.getByIndex(index)
            page = sheet.DrawPage
            output[sheet.Name] = {'cell': sheet.getCellRangeByName('A1').String,
                'drawings': [{'name': page.getByIndex(i).Name, 'text': page.getByIndex(i).String}
                             for i in range(page.Count)]}
        print(json.dumps(output, indent=2))
        doc.close(True)
        desktop.terminate()
''' + _READER_END


def write_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    data = fixture()
    (root / 'floating.ods').write_bytes(data)
    with ZipFile(BytesIO(data)) as z:
        (root / 'content.xml').write_bytes(z.read('content.xml'))
    (root / 'reader.py').write_text(READER)


def test_authored_fixture_has_no_links_or_objects():
    with ZipFile(BytesIO(fixture())) as z:
        content = z.read('content.xml')
    assert b'xlink:href=' not in content
    assert b'draw:object' not in content
    assert b'office:scripts' not in content


@pytest.mark.skipif(not os.environ.get('ODF13_SCHEMA'), reason='optional official ODF schema')
def test_official_schema(tmp_path):
    write_fixture(tmp_path)
    subprocess.run(['xmllint', '--nonet', '--noout', '--relaxng', os.environ['ODF13_SCHEMA'],
                    str(tmp_path / 'content.xml')], check=True, capture_output=True)


@pytest.mark.skipif(os.environ.get('ODS_FLOATING_LO') != '1', reason='optional independent Calc reader')
def test_independent_reader_text_and_owning_sheet(tmp_path):
    write_fixture(tmp_path)
    result = subprocess.run(['/usr/bin/python3', str(tmp_path / 'reader.py'), str(tmp_path)],
                            check=True, capture_output=True, text=True, timeout=45)
    assert json.loads(result.stdout) == expected()


if __name__ == '__main__':
    import sys
    write_fixture(Path(sys.argv[1]).resolve())
