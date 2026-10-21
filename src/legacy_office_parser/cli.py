"""Local extraction CLI. Diagnostics never include the document's contents."""
import argparse
import json
import sys
from .api import parse, parse_doc, parse_ppt
from .errors import ParseError
from .limits import Limits

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Extract binary DOC/PPT text and structure')
    parser.add_argument('file')
    parser.add_argument('--format', choices=['auto', 'doc', 'ppt'], default='auto')
    parser.add_argument('--json', action='store_true', help='write structured JSON')
    parser.add_argument('--strict', action='store_true', help='exit 3 if extraction has warnings')
    parser.add_argument('--max-file-bytes', type=int, default=Limits().max_file_bytes)
    args = parser.parse_args(argv)
    try:
        limits = Limits(max_file_bytes=args.max_file_bytes)
        doc = {'auto': parse, 'doc': parse_doc, 'ppt': parse_ppt}[args.format](args.file, limits=limits)
        print(json.dumps(doc.to_dict(), ensure_ascii=False) if args.json else doc.text)
        for warning in doc.warnings:
            print('warning: ' + warning, file=sys.stderr)
        return 3 if args.strict and doc.warnings else 0
    except ParseError as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(type(exc).__name__ + ': unable to read input or invalid options', file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0

if __name__ == '__main__':
    raise SystemExit(main())
