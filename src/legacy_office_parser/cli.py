"""Local extraction CLI. Diagnostics never include the document's contents."""
import argparse
import json
import sys
from .api import parse, parse_doc, parse_ppt, parse_xls, parse_rtf, parse_odt, parse_ods, parse_odp
from .errors import ParseError
from .limits import Limits
from .normalization import normalize_text

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Extract DOC/XLS/PPT/RTF/ODT/ODS/ODP text and structure')
    parser.add_argument('file')
    parser.add_argument('--format', choices=['auto', 'doc', 'xls', 'ppt', 'rtf', 'odt', 'ods', 'odp'], default='auto')
    parser.add_argument('--json', action='store_true', help='write structured JSON')
    parser.add_argument('--normalize-text', action='store_true', help='normalize display line breaks and controls')
    parser.add_argument('--nfc', action='store_true', help='normalize display text including Unicode NFC')
    parser.add_argument('--strict', action='store_true', help='exit 3 if extraction has warnings')
    parser.add_argument('--max-file-bytes', type=int, default=Limits().max_file_bytes)
    args = parser.parse_args(argv)
    try:
        limits = Limits(max_file_bytes=args.max_file_bytes)
        reader = {'auto': parse, 'doc': parse_doc, 'ppt': parse_ppt, 'xls': parse_xls,
                  'rtf': parse_rtf, 'odt': parse_odt, 'ods': parse_ods, 'odp': parse_odp}[args.format]
        doc = reader(args.file, limits=limits)
        if args.normalize_text or args.nfc:
            doc = normalize_text(doc, unicode_form='NFC' if args.nfc else None, limits=limits)
        print(json.dumps(doc.to_dict(), ensure_ascii=False, allow_nan=False) if args.json else doc.text)
        for warning in doc.warnings:
            print('warning: ' + warning, file=sys.stderr)
        return 3 if args.strict and doc.warnings else 0
    except ParseError as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(type(exc).__name__ + ': unable to read input or invalid options', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
