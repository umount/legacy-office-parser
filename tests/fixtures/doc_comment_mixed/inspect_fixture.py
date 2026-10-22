"""Independent mixed-range fixture evidence, including converter range loss.

Reuses only the earlier fixture's CFB/CLX/CHPX transport reader. XML ranges
are walked across host paragraphs and joined by annotation name, never by text.
"""
import importlib.util
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
OFFICE = '{urn:oasis:names:tc:opendocument:xmlns:office:1.0}'
T = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
D = '{http://purl.org/dc/elements/1.1/}'


def xml_comments(path):
    output, active = [], {}

    def text(value):
        for entry in active.values():
            entry['selection'] += value or ''

    def inline(node):
        text(node.text)
        for child in node:
            if child.tag == OFFICE + 'annotation':
                name = child.get(OFFICE + 'name')
                if name in active:
                    raise ValueError('duplicate fixture annotation name')
                entry = {'author': child.findtext(D + 'creator'),
                         'body': [''.join(p.itertext()) for p in child.findall(T + 'p')],
                         'selection': '' if name is not None else None}
                if name is not None:
                    active[name] = entry
                output.append(entry)
            elif child.tag == OFFICE + 'annotation-end':
                del active[child.get(OFFICE + 'name')]
            else:
                inline(child)
            text(child.tail)

    def blocks(node):
        for child in node:
            if child.tag == T + 'p':
                inline(child)
                text('\r')
            else:
                blocks(child)

    root = ET.parse(path).getroot()
    blocks(root.find(OFFICE + 'body').find(OFFICE + 'text'))
    if active:
        raise ValueError('unclosed fixture annotations')
    return output


def inspect(root=ROOT):
    helper = ROOT.parent / 'doc_comments/inspect_fixture.py'
    spec = importlib.util.spec_from_file_location('doc_comment_raw_fixture', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    module.xml_comments = xml_comments
    result = module.inspect()
    parts = {int(k): bytes.fromhex(v) for k, v in result['raw_parts_hex'].items()}
    meta, starts, limits = (parts[i] for i in (37, 42, 43))
    n = struct.unpack_from('<H', meta, 2)[0] if meta else 0
    main = result['main'].encode('utf-16le')
    ranges = {}
    for i in range(n):
        tag = struct.unpack_from('<I', meta, 6 + 12 * i + 4)[0]
        begin = struct.unpack_from('<I', starts, i * 4)[0]
        ibkl = struct.unpack_from('<H', starts, 4 * (n + 1) + i * 4)[0]
        end = struct.unpack_from('<I', limits, ibkl * 4)[0]
        ranges[tag] = (begin, end)
    for entry in result['comments']:
        begin, end = ranges.get(entry['tag'], (entry['source_cp'], entry['source_cp']))
        entry['selection_cps'] = [begin, end]
        entry['selection'] = main[begin * 2:end * 2].decode('utf-16le')
    return result


if __name__ == '__main__':
    print(json.dumps(inspect(), ensure_ascii=False, indent=2))
