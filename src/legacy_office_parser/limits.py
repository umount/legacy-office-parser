from dataclasses import dataclass, fields
import sys

@dataclass(frozen=True, slots=True)
class Limits:
    max_file_bytes: int = 64 * 1024 * 1024
    max_stream_bytes: int = 64 * 1024 * 1024
    max_text_chars: int = 10_000_000
    max_records: int = 200_000
    max_depth: int = 32
    max_cells: int = 100_000
    max_slides: int = 10_000
    max_sheets: int = 256
    max_rows: int = 1_048_576
    max_columns: int = 16_384
    max_archive_entries: int = 4096
    max_uncompressed_bytes: int = 128 * 1024 * 1024

    def __post_init__(self):
        for f in fields(self):
            v = getattr(self, f.name)
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise ValueError(f'{f.name} must be a positive integer')

        for name in ('max_file_bytes', 'max_stream_bytes'):
            if getattr(self, name) >= sys.maxsize:
                raise ValueError(f'{name} must be less than sys.maxsize')
