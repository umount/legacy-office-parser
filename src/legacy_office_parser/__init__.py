"""Extract legacy Office, RTF and OpenDocument without an office runtime."""
from .api import parse, parse_doc, parse_ppt, parse_xls, parse_rtf, parse_odt, parse_ods, parse_odp
from .errors import (ParseError, InvalidDocumentError, UnsupportedFormatError,
                     EncryptedDocumentError, LimitExceededError)
from .limits import Limits
from .models import Document, Paragraph, Table, Cell, Slide, SlideComment, SpreadsheetCell, CellRange, Sheet, Note, NoteBodyRange, Comment, CommentBodyRange

__version__ = '0.19.0'
__all__ = ['parse_xls', 'parse_rtf', 'parse_odt', 'parse_ods', 'parse_odp',
           'SpreadsheetCell', 'CellRange', 'Sheet', 'parse', 'parse_doc', 'parse_ppt', 'Limits', 'Document', 'Paragraph',
           'Table', 'Cell', 'Slide', 'SlideComment', 'Note', 'NoteBodyRange', 'Comment', 'CommentBodyRange', 'ParseError', 'InvalidDocumentError',
           'UnsupportedFormatError', 'EncryptedDocumentError', 'LimitExceededError']
