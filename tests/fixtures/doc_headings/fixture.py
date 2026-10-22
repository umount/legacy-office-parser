"""Original heading specimen and independent, fixture-only binary/XML probes.

No production parser imports. Run this file to recreate authored.docx, then use
LibreOffice to export authored.doc and read it back as readback/authored.docx.
"""

from pathlib import Path
import struct
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import olefile

ROOT = Path(__file__).parent
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EXPECTED = {
    "Heading one specimen": 1,
    "Heading two specimen": 2,
    "Ordinary body specimen": None,
    "Inherited heading specimen": 1,
    "Direct body override specimen": None,
    "Custom body style specimen": None,
    "Direct outline three specimen": 3,
    "Cell heading specimen": 2,
    "Header heading specimen": 2,
}


def source_bytes():
    from io import BytesIO

    def p(text, style="Normal", outline=None):
        direct = "" if outline is None else f'<w:outlineLvl w:val="{outline}"/>'
        return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{direct}</w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'

    def style(ident, name, base=None, outline=None):
        based = "" if base is None else f'<w:basedOn w:val="{base}"/>'
        props = "" if outline is None else f'<w:pPr><w:outlineLvl w:val="{outline}"/></w:pPr>'
        return f'<w:style w:type="paragraph" w:styleId="{ident}"><w:name w:val="{name}"/>{based}{props}</w:style>'

    body = p("Heading one specimen", "Heading1") + p("Heading two specimen", "Heading2")
    body += p("Ordinary body specimen") + p("Inherited heading specimen", "Inherited")
    body += p("Direct body override specimen", "Inherited", 9)
    body += p("Custom body style specimen", "CustomBody") + p(
        "Direct outline three specimen", outline=2
    )
    body += (
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="6000"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:w="6000" w:type="dxa"/></w:tcPr>'
        + p("Cell heading specimen", "Heading2")
        + "</w:tc></w:tr></w:tbl>"
    )
    body += '<w:p/><w:sectPr><w:headerReference w:type="default" r:id="header"/></w:sectPr>'
    styles = (
        style("Normal", "Normal")
        + style("Heading1", "heading 1", "Normal", 0)
        + style("Heading2", "heading 2", "Normal", 1)
    )
    styles += style("Inherited", "Research inherited", "Heading1") + style(
        "CustomBody", "Research body child", "Heading1", 9
    )
    types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
    for name, kind in [("document", "document.main"), ("styles", "styles"), ("header1", "header")]:
        types += f'<Override PartName="/word/{name}.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>'
    relns = "http://schemas.openxmlformats.org/package/2006/relationships"
    files = {
        "[Content_Types].xml": types + "</Types>",
        "_rels/.rels": f'<Relationships xmlns="{relns}"><Relationship Id="main" Type="{R}/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}</w:body></w:document>',
        "word/styles.xml": f'<w:styles xmlns:w="{W}">{styles}</w:styles>',
        "word/header1.xml": f'<w:hdr xmlns:w="{W}">{p("Header heading specimen", "Heading2")}</w:hdr>',
        "word/_rels/document.xml.rels": f'<Relationships xmlns="{relns}"><Relationship Id="styles" Type="{R}/styles" Target="styles.xml"/><Relationship Id="header" Type="{R}/header" Target="header1.xml"/></Relationships>',
    }
    out = BytesIO()
    with ZipFile(out, "w") as z:
        for name, text in files.items():
            info = ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            z.writestr(info, text.encode())
    return out.getvalue()


def xml_levels(path):
    """Read explicit/inherited OOXML outlines, independently of production."""
    ns = {"w": W}
    attr = "{" + W + "}val"
    with ZipFile(path) as z:
        styles = {s.get("{" + W + "}styleId"): s for s in ET.fromstring(z.read("word/styles.xml"))}

        def level(props, seen=()):
            if props is None:
                return None
            own = props.find("w:outlineLvl", ns)
            if own is not None:
                value = int(own.get(attr))
                return value + 1 if value < 9 else None
            ref = props.find("w:pStyle", ns)
            ident = ref.get(attr) if ref is not None else None
            return inherited(ident, seen)

        def inherited(ident, seen):
            if ident is None:
                return None
            assert ident not in seen
            s = styles[ident]
            props = s.find("w:pPr", ns)
            if props is not None and props.find("w:outlineLvl", ns) is not None:
                return level(props)
            base = s.find("w:basedOn", ns)
            return inherited(base.get(attr) if base is not None else None, (*seen, ident))

        result = {}
        for name in z.namelist():
            if (
                name == "word/document.xml"
                or name.startswith("word/header")
                and name.endswith(".xml")
            ):
                for p in ET.fromstring(z.read(name)).iter("{" + W + "}p"):
                    text = "".join(t.text or "" for t in p.iter("{" + W + "}t"))
                    if text:
                        assert text not in result
                        result[text] = level(p.find("w:pPr", ns))
        return result


def operations(data):
    """Fixture-only SPRM framing; reject truncation and unsupported huge operands."""
    pos = 0
    out = []
    while pos < len(data):
        if data[pos:] == b"\0":
            break
        op = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        size = (1, 1, 2, 4, 2, 2, None, 3)[op >> 13]
        if size is None:
            if op in (0xD608, 0xD606):
                size = struct.unpack_from("<H", data, pos)[0] - 1
                pos += 2
            else:
                size = data[pos]
                pos += 1
        arg = data[pos : pos + size]
        assert len(arg) == size
        out.append((op, arg))
        pos += size
    return out


def binary(path):
    """Independent STSH, CLX and PAPX FKP read; no extraction implementation."""

    def u16(b, p=0):
        return struct.unpack_from("<H", b, p)[0]

    def u32(b, p=0):
        return struct.unpack_from("<I", b, p)[0]

    with olefile.OleFileIO(path) as ole:
        word = ole.openstream("WordDocument").read()
        table = ole.openstream("1Table" if u16(word, 10) & 0x200 else "0Table").read()

    def part(i):
        at, size = struct.unpack_from("<II", word, 154 + 8 * i)
        return table[at : at + size]

    stsh = part(1)
    size = u16(stsh)
    count = u16(stsh, 2)
    base_size = u16(stsh, 4)
    at = 2 + size
    styles = {}
    for i in range(count):
        n = u16(stsh, at)
        raw = stsh[at + 2 : at + 2 + n]
        at += n + 2
        if not n:
            continue
        name_units = u16(raw, base_size)
        name = raw[base_size + 2 : base_size + 2 + name_units * 2].decode("utf-16le")
        q = base_size + 4 + name_units * 2
        groups = []
        for _ in range(u16(raw, 4) & 15):
            n = u16(raw, q)
            groups.append(raw[q + 2 : q + 2 + n])
            q += 2 + n + (n & 1)
        kind = u16(raw, 2) & 15
        styles[i] = {
            "sti": u16(raw) & 0xFFF,
            "base": u16(raw, 2) >> 4,
            "name": name,
            "kind": kind,
            "ops": operations(groups[0][2:]) if kind == 1 else [],
        }
    clx = part(33)
    at = 0
    while clx[at] == 1:
        at += 3 + u16(clx, at + 1)
    assert clx[at] == 2
    plc = clx[at + 5 : at + 5 + u32(clx, at + 1)]
    n = (len(plc) - 4) // 12
    pieces = []
    for i in range(n):
        cp, end = u32(plc, i * 4), u32(plc, (i + 1) * 4)
        encoded = u32(plc, 4 * (n + 1) + i * 8 + 2)
        width = 1 if encoded & 0x40000000 else 2
        fc = (encoded & 0x3FFFFFFF) // (2 if width == 1 else 1)
        raw = word[fc : fc + (end - cp) * width]
        # This authored specimen is ASCII: character offsets equal source CPs.
        assert all(ord(ch) < 128 for ch in raw.decode("cp1252" if width == 1 else "utf-16le"))
        pieces.append((cp, end, fc, width, raw.decode("cp1252" if width == 1 else "utf-16le")))
    runs = []
    plc = part(13)
    n = (len(plc) - 4) // 8
    for i in range(n):
        pn = u32(plc, 4 * (n + 1 + i)) & 0x3FFFFF
        page = word[pn * 512 : (pn + 1) * 512]
        count = page[511]
        for j in range(count):
            off = 2 * page[4 * (count + 1) + 13 * j]
            if not off:
                style, group = 0, b""
            else:
                size = page[off]
                begin, length = (off + 1, size * 2 - 1) if size else (off + 2, page[off + 1] * 2)
                raw = page[begin : begin + length]
                style, group = u16(raw), raw[2:]
            runs.append((u32(page, 4 * j), u32(page, 4 * (j + 1)), style, group))
    # Probe only the named, nonempty specimen paragraphs. This is not a
    # validator for every unused FKP run or empty terminal paragraph.
    paras = {}
    text = ""
    for cp, end, fc, width, value in pieces:
        for j, char in enumerate(value):
            if char in "\r\x07":
                if text:
                    matches = [
                        (s, operations(group)) for a, b, s, group in runs if a <= fc + j * width < b
                    ]
                    assert len(matches) == 1, (text, matches)
                    paras[text] = matches[0]
                text = ""
            else:
                text += char
    return styles, paras


if __name__ == "__main__":
    (ROOT / "authored.docx").write_bytes(source_bytes())
