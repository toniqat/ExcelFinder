"""JSON 파일 플러그인 (stdlib json)"""
import json
import sys
import pandas as pd
from pathlib import Path
from typing import List, Tuple

_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin, _flatten_dict, _flatten_value


def _find_line_numbers(raw_text: str, data: list) -> list:
    """JSON 배열의 각 요소 시작 줄 번호(1-based)를 반환합니다.
    파싱 실패 시 순차 번호(1, 2, 3, ...)로 폴백."""
    if not raw_text or not data:
        return list(range(1, len(data) + 1))
    try:
        decoder = json.JSONDecoder()
        bracket_pos = raw_text.index('[')
        pos = bracket_pos + 1
        line_numbers = []
        for _ in data:
            while pos < len(raw_text) and raw_text[pos] in ' \t\n\r,':
                pos += 1
            if pos >= len(raw_text):
                break
            line_numbers.append(raw_text[:pos].count('\n') + 1)
            _, end = decoder.raw_decode(raw_text, pos)
            pos = end
        while len(line_numbers) < len(data):
            line_numbers.append(len(line_numbers) + 1)
        return line_numbers
    except Exception:
        return list(range(1, len(data) + 1))


def _json_to_sections(data, file_stem: str, raw_text: str = None) -> List[Tuple[str, List[str], pd.DataFrame]]:
    """JSON 데이터를 (sheet_name, headers, df) 목록으로 변환"""

    def _records_to_df(records: list, sheet_name: str, line_numbers: list = None):
        if not records:
            return None
        # 딕셔너리 목록: 평탄화
        if isinstance(records[0], dict):
            flat_records = [_flatten_dict(r) for r in records]
            df = pd.DataFrame(flat_records)
        else:
            # 단순 값 목록
            df = pd.DataFrame({'Value': [_flatten_value(v) for v in records]})
        if line_numbers is not None:
            df.insert(0, 'LineNo', [str(ln) for ln in line_numbers[:len(df)]])
        headers = list(df.columns)
        # 헤더 행을 row 0으로 포함 (Excel 플러그인과 동일한 방식)
        header_df = pd.DataFrame([headers], columns=df.columns)
        df_ri = pd.concat([header_df, df], ignore_index=True)
        df_ri.columns = range(len(df_ri.columns))
        return sheet_name, headers, df_ri

    # Case 1: 최상위가 리스트 → 단일 시트
    if isinstance(data, list):
        line_numbers = _find_line_numbers(raw_text, data) if raw_text else list(range(1, len(data) + 1))
        result = _records_to_df(data, file_stem, line_numbers)
        return [result] if result else []

    # Case 2: 최상위가 딕셔너리
    if isinstance(data, dict):
        sections = []
        # 값이 리스트인 키는 별도 시트로
        list_keys = {k: v for k, v in data.items() if isinstance(v, list)}
        scalar_keys = {k: v for k, v in data.items() if not isinstance(v, list)}

        for key, records in list_keys.items():
            # 서브리스트는 순차 번호 사용 (폴백)
            line_numbers = list(range(1, len(records) + 1))
            result = _records_to_df(records, str(key), line_numbers)
            if result:
                sections.append(result)

        # 스칼라 키들은 하나의 시트로
        if scalar_keys:
            flat = _flatten_dict(scalar_keys)
            df = pd.DataFrame([flat])
            df.insert(0, 'LineNo', ['1'])
            headers = list(df.columns)
            header_df = pd.DataFrame([headers], columns=df.columns)
            df_ri = pd.concat([header_df, df], ignore_index=True)
            df_ri.columns = range(len(df_ri.columns))
            sections.append((file_stem, headers, df_ri))

        if not sections:
            # 전체를 평탄화
            flat = _flatten_dict(data)
            df = pd.DataFrame([flat])
            df.insert(0, 'LineNo', ['1'])
            headers = list(df.columns)
            header_df = pd.DataFrame([headers], columns=df.columns)
            df_ri = pd.concat([header_df, df], ignore_index=True)
            df_ri.columns = range(len(df_ri.columns))
            sections.append((file_stem, headers, df_ri))

        return sections

    # Case 3: 단순 값
    headers = ['LineNo', 'Value']
    df = pd.DataFrame({'LineNo': ['1'], 'Value': [_flatten_value(data)]})
    header_df = pd.DataFrame([headers], columns=df.columns)
    df_ri = pd.concat([header_df, df], ignore_index=True)
    df_ri.columns = range(len(df_ri.columns))
    return [(file_stem, headers, df_ri)]


class JsonPlugin(FormatPlugin):
    """JSON 파일(.json) 처리 플러그인"""

    @property
    def plugin_id(self) -> str:
        return "json"

    @property
    def display_name(self) -> str:
        return "JSON"

    @property
    def is_builtin(self) -> bool:
        return True

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.json',)

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        encodings = ['utf-8', 'utf-8-sig', 'cp949', 'latin1']
        data = None
        raw_text = None
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    raw_text = f.read()
                data = json.loads(raw_text)
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                raw_text = None
                continue

        if data is None:
            raise ValueError(f"JSON 파일을 읽을 수 없습니다: {file_path}")

        return _json_to_sections(data, Path(file_path).stem, raw_text)
