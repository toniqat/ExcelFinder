"""TXT/LOG 파일 플러그인 (stdlib open)"""
import sys
import pandas as pd
from pathlib import Path
from typing import List, Tuple

_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin


class TxtPlugin(FormatPlugin):
    """텍스트/로그 파일(.txt, .log) 처리 플러그인"""

    @property
    def plugin_id(self) -> str:
        return "txt"

    @property
    def display_name(self) -> str:
        return "TXT/LOG"

    @property
    def is_builtin(self) -> bool:
        return True

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.txt', '.log')

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        lines = self._read_lines(file_path)
        if not lines:
            return []

        file_stem = Path(file_path).stem
        headers = ['Line', 'Content']
        data = [(str(i + 1), line) for i, line in enumerate(lines)]
        df = pd.DataFrame(data, columns=range(2))
        return [(file_stem, headers, df)]

    def _read_lines(self, file_path: str) -> List[str]:
        encodings = ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin1']
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc, errors='strict') as f:
                    return [line.rstrip('\n\r') for line in f]
            except (UnicodeDecodeError, LookupError):
                continue
        # 최후 수단
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return [line.rstrip('\n\r') for line in f]

    def supports_streaming(self, file_path: str) -> bool:
        return True

    def stream_file(self, file_path: str, chunk_size: int = 1000):
        lines = self._read_lines(file_path)
        file_stem = Path(file_path).stem
        headers = ['Line', 'Content']

        for start in range(0, max(1, len(lines)), chunk_size):
            chunk_lines = lines[start:start + chunk_size]
            data = [(str(start + i + 1), line) for i, line in enumerate(chunk_lines)]
            df = pd.DataFrame(data, columns=range(2))
            yield file_stem, headers, df
