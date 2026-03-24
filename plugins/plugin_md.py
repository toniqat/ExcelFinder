"""Markdown 파일 플러그인 (stdlib re)"""
import re
import sys
import pandas as pd
from pathlib import Path
from typing import List, Tuple

_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin

_TABLE_ROW_RE = re.compile(r'^\|(.+)\|$')
_SEPARATOR_RE = re.compile(r'^\|[\s\-|:]+\|$')


def _parse_md_tables(lines: List[str], file_stem: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
    """Markdown 파일에서 테이블 파싱"""
    sections = []
    i = 0
    table_idx = 0

    while i < len(lines):
        line = lines[i].strip()
        if _TABLE_ROW_RE.match(line):
            # 헤더 행
            header_line = line
            # 다음 줄이 구분자인지 확인
            if i + 1 < len(lines) and _SEPARATOR_RE.match(lines[i + 1].strip()):
                headers = [cell.strip() for cell in header_line.strip('|').split('|')]
                i += 2  # 헤더 + 구분자 건너뜀
                # 데이터 행 수집
                rows = []
                while i < len(lines) and _TABLE_ROW_RE.match(lines[i].strip()):
                    cells = [cell.strip() for cell in lines[i].strip().strip('|').split('|')]
                    # 헤더 수에 맞게 패딩/트런케이션
                    while len(cells) < len(headers):
                        cells.append("")
                    rows.append(cells[:len(headers)])
                    i += 1

                if rows:
                    table_idx += 1
                    sheet_name = f"Table_{table_idx}"
                    # 헤더 행을 row 0으로 포함 (Excel 플러그인과 동일한 방식)
                    all_rows = [headers] + rows
                    df = pd.DataFrame(all_rows, columns=range(len(headers)))
                    sections.append((sheet_name, headers, df))
                continue
        i += 1

    return sections


class MdPlugin(FormatPlugin):
    """Markdown 파일(.md) 처리 플러그인"""

    @property
    def plugin_id(self) -> str:
        return "md"

    @property
    def display_name(self) -> str:
        return "Markdown"

    @property
    def is_builtin(self) -> bool:
        return True

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.md',)

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        encodings = ['utf-8', 'utf-8-sig', 'cp949', 'latin1']
        lines = None
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc, errors='strict') as f:
                    lines = [line.rstrip('\n\r') for line in f]
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if lines is None:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = [line.rstrip('\n\r') for line in f]

        file_stem = Path(file_path).stem
        sections = _parse_md_tables(lines, file_stem)

        # 테이블이 없으면 텍스트 전체를 라인 단위로
        if not sections:
            headers = ['Line', 'Content']
            data = [(str(i + 1), line) for i, line in enumerate(lines)]
            df = pd.DataFrame(data, columns=range(2))
            sections = [(file_stem, headers, df)]

        return sections
