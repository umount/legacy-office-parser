from dataclasses import dataclass, fields

@dataclass(frozen=True, slots=True)
class Limits:
    max_file_bytes: int = 64 * 1024 * 1024
    max_stream_bytes: int = 64 * 1024 * 1024
    max_text_chars: int = 10_000_000
    max_records: int = 200_000
    max_depth: int = 32
    max_cells: int = 100_000
    max_slides: int = 10_000

    def __post_init__(self):
        for f in fields(self):
            v = getattr(self, f.name)
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise ValueError(f'{f.name} must be a positive integer')
