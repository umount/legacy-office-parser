"""Read this original fixture's raw records; not a general parser or test suite.

Uses olefile only for CFB transport. No legacy_office_parser imports. Prints JSON
for review; source FODT and LibreOffice readback are inspected independently.
"""
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import olefile

ROOT = Path(__file__).resolve().parent


def u16(data, offset=0):
    return struct.unpack_from('<H', data, offset)[0]


def u32(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]


def xml_comments(path):
    ns = {'o': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
          't': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
          'd': 'http://purl.org/dc/elements/1.1/'}
    root = ET.parse(path).getroot()
    output = []
    for p in root.findall('.//t:p', ns):
        # Fixture host paragraphs use text/spans only outside annotations.
        cursor = len(p.text or '')
        active = {}
        def visit(parent):
            nonlocal cursor
            for child in parent:
                if child.tag == '{' + ns['o'] + '}annotation':
                    entry = {'author': child.findtext('d:creator', namespaces=ns),
                             'paragraphs': [''.join(x.itertext())
                                            for x in child.findall('t:p', ns)],
                             'host_prefix_chars': cursor, 'range_chars': None}
                    output.append(entry)
                    active[child.get('{' + ns['o'] + '}name')] = entry
                elif child.tag == '{' + ns['o'] + '}annotation-end':
                    entry = active[child.get('{' + ns['o'] + '}name')]
                    entry['range_chars'] = cursor - entry['host_prefix_chars']
                else:
                    cursor += len(child.text or '')
                    visit(child)
                cursor += len(child.tail or '')
        visit(p)
    return output


def inspect():
    with olefile.OleFileIO(ROOT / 'authored.doc') as compound:
        word = compound.openstream('WordDocument').read()
        table = compound.openstream('1Table' if u16(word, 10) & 0x200 else '0Table').read()
    at = 32
    at += 2 + 2 * u16(word, at)
    lw = at + 2
    counts = [u32(word, lw + 4 * i) for i in (3, 4, 5, 7, 8, 9, 10)]
    at += 2 + 4 * u16(word, at)
    pair_count = u16(word, at)
    pairs = at + 2

    def part(index):
        if index >= pair_count:
            return b''
        offset, size = struct.unpack_from('<II', word, pairs + 8 * index)
        return table[offset:offset + size]

    clx = part(33)
    at = 0
    while clx[at] == 1:
        at += 3 + u16(clx, at + 1)
    if clx[at] != 2:
        raise ValueError('fixture CLX has no piece table')
    plc = clx[at + 5:at + 5 + u32(clx, at + 1)]
    n = (len(plc) - 4) // 12
    cps = struct.unpack_from('<' + 'I' * (n + 1), plc)
    units = bytearray()
    piece_locations = []
    for i in range(n):
        fc = u32(plc, 4 * (n + 1) + 8 * i + 2)
        width = 1 if fc & 0x40000000 else 2
        offset = (fc & 0x3fffffff) // (2 if width == 1 else 1)
        piece_locations.append((cps[i], cps[i + 1], offset, width))
        chunk = word[offset:offset + (cps[i + 1] - cps[i]) * width]
        if width == 1:
            # This fixture does not need the MS-DOC non-ASCII compressed map.
            chunk = chunk.decode('ascii').encode('utf-16le')
        units.extend(chunk)
    main = bytes(units[:counts[0] * 2])
    start = sum(counts[:3])
    story = bytes(units[start * 2:(start + counts[3]) * 2])
    refs, texts = part(4), part(5)
    n = (len(refs) - 4) // 34
    text_cps = struct.unpack('<' + 'I' * (len(texts) // 4), texts)
    owners = []
    owner_bytes = part(36)
    at = 0
    while at < len(owner_bytes):
        length = u16(owner_bytes, at)
        owners.append(owner_bytes[at + 2:at + 2 + length * 2].decode('utf-16le'))
        at += 2 + length * 2
    entries = []
    for i in range(n):
        record = refs[4 * (n + 1) + 30 * i:4 * (n + 1) + 30 * (i + 1)]
        cp = u32(refs, i * 4)
        entries.append({'source_cp': cp, 'source_unit': u16(main, cp * 2),
                        'initials': record[2:2 + u16(record) * 2].decode('utf-16le'),
                        'owner_index': u16(record, 20), 'tag': u32(record, 26),
                        'body_cps': text_cps[i:i + 2],
                        'body': story[text_cps[i] * 2:text_cps[i + 1] * 2].decode('utf-16le')})
    # Independently inspect direct CHPX at each reference/body marker.
    markers = [entry['source_cp'] for entry in entries] + [start + c for c in text_cps[:-2]]
    bte = part(12)
    pages = (len(bte) - 4) // 8
    marker_chpx = []
    for cp in markers:
        piece = next(p for p in piece_locations if p[0] <= cp < p[1])
        fc = piece[2] + (cp - piece[0]) * piece[3]
        found = []
        for i in range(pages):
            if not u32(bte, i * 4) <= fc < u32(bte, (i + 1) * 4):
                continue
            page = u32(bte, (pages + 1) * 4 + i * 4) & 0x3fffff
            fkp = word[page * 512:(page + 1) * 512]
            runs = fkp[511]
            for j in range(runs):
                if u32(fkp, j * 4) <= fc < u32(fkp, (j + 1) * 4):
                    offset = fkp[(runs + 1) * 4 + j] * 2
                    grp = fkp[offset + 1:offset + 1 + fkp[offset]] if offset else b''
                    found.append(grp.hex())
        marker_chpx.append({'cp': cp, 'direct_chpx_hex': found})
    return {'story_counts': counts, 'main': main.decode('utf-16le'),
            'comment_story': story.decode('utf-16le'), 'owners': owners,
            'reference_sentinel': u32(refs, n * 4), 'text_cps': text_cps,
            'comments': entries, 'marker_chpx': marker_chpx,
            'raw_parts_hex': {str(i): part(i).hex() for i in (4, 5, 36, 37, 42, 43, 112)},
            'source_xml': xml_comments(ROOT / 'authored.fodt'),
            'lo_readback_xml': xml_comments(ROOT / 'readback/authored.fodt')}


if __name__ == '__main__':
    print(json.dumps(inspect(), ensure_ascii=False, indent=2))
