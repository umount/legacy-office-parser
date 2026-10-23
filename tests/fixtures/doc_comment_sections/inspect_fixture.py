"""Original section/bookmark evidence; no production parser imports."""
import importlib.util
import json
from pathlib import Path
import struct

import olefile

ROOT = Path(__file__).resolve().parent


def inspect(root=ROOT):
    # Reuse the earlier fixture-only CLX/CHPX/bookmark and XML readers. That
    # probe explicitly distinguishes an absent annotation-end from a range.
    path = ROOT.parent / 'doc_comment_mixed/inspect_fixture.py'
    spec = importlib.util.spec_from_file_location('section_fixture_raw', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.inspect(root)
    with olefile.OleFileIO(root / 'authored.doc') as compound:
        word = compound.openstream('WordDocument').read()
        name = '1Table' if struct.unpack_from('<H', word, 10)[0] & 0x200 else '0Table'
        table = compound.openstream(name).read()
    start, size = struct.unpack_from('<II', word, 154 + 6 * 8)
    plc = table[start:start + size]
    assert len(plc) >= 4 and (len(plc) - 4) % 16 == 0
    count = (len(plc) - 4) // 16
    cps = list(struct.unpack_from('<' + 'I' * (count + 1), plc))
    main = result['main'].encode('utf-16le')
    assert cps[0] == 0 and all(a < b for a, b in zip(cps, cps[1:]))
    assert all(0 < cp < len(main) // 2 and main[(cp-1)*2:cp*2] == b'\x0c\0'
               for cp in cps[1:-1])
    assert cps[-1] >= len(main) // 2
    result['section_cps'] = cps
    result['section_plc_hex'] = plc.hex()
    return result


if __name__ == '__main__':
    print(json.dumps(inspect(), ensure_ascii=False, indent=2))
