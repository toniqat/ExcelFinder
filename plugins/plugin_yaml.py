"""YAML 파일 플러그인 (pyyaml 필요) - Extension Pack"""
import sys
import pandas as pd
from pathlib import Path
from typing import List, Tuple

_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin, _flatten_dict, _flatten_value


def _yaml_to_sections(data, file_stem: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
    """YAML 데이터를 (sheet_name, headers, df) 목록으로 변환 (JSON 플러그인과 동일 로직)"""
    def _records_to_df(records: list, sheet_name: str):
        if not records:
            return None
        if isinstance(records[0], dict):
            flat_records = [_flatten_dict(r) for r in records]
            df = pd.DataFrame(flat_records)
        else:
            df = pd.DataFrame({'Value': [_flatten_value(v) for v in records]})
        headers = list(df.columns)
        # 헤더 행을 row 0으로 포함 (Excel 플러그인과 동일한 방식)
        header_df = pd.DataFrame([headers], columns=df.columns)
        df_ri = pd.concat([header_df, df], ignore_index=True)
        df_ri.columns = range(len(df_ri.columns))
        return sheet_name, headers, df_ri

    if isinstance(data, list):
        result = _records_to_df(data, file_stem)
        return [result] if result else []

    if isinstance(data, dict):
        sections = []
        list_keys = {k: v for k, v in data.items() if isinstance(v, list)}
        scalar_keys = {k: v for k, v in data.items() if not isinstance(v, list)}

        for key, records in list_keys.items():
            result = _records_to_df(records, str(key))
            if result:
                sections.append(result)

        if scalar_keys:
            flat = _flatten_dict(scalar_keys)
            df = pd.DataFrame([flat])
            headers = list(df.columns)
            header_df = pd.DataFrame([headers], columns=df.columns)
            df_ri = pd.concat([header_df, df], ignore_index=True)
            df_ri.columns = range(len(df_ri.columns))
            sections.append((file_stem, headers, df_ri))

        if not sections:
            flat = _flatten_dict(data)
            df = pd.DataFrame([flat])
            headers = list(df.columns)
            header_df = pd.DataFrame([headers], columns=df.columns)
            df_ri = pd.concat([header_df, df], ignore_index=True)
            df_ri.columns = range(len(df_ri.columns))
            sections.append((file_stem, headers, df_ri))

        return sections

    headers = ['Value']
    df = pd.DataFrame({'Value': [_flatten_value(data)]})
    header_df = pd.DataFrame([headers], columns=df.columns)
    df_ri = pd.concat([header_df, df], ignore_index=True)
    df_ri.columns = range(len(df_ri.columns))
    return [(file_stem, headers, df_ri)]


class YamlPlugin(FormatPlugin):
    """YAML 파일(.yaml, .yml) 처리 플러그인 (pyyaml 필요)"""

    @property
    def plugin_id(self) -> str:
        return "yaml"

    @property
    def display_name(self) -> str:
        return "YAML"

    @property
    def required_packages(self) -> List[str]:
        return ["yaml"]

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.yaml', '.yml')

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        import yaml  # lazy import

        encodings = ['utf-8', 'utf-8-sig', 'cp949', 'latin1']
        data = None
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    data = yaml.safe_load(f)
                break
            except (UnicodeDecodeError, yaml.YAMLError):
                continue

        if data is None:
            raise ValueError(f"YAML 파일을 읽을 수 없습니다: {file_path}")

        return _yaml_to_sections(data, Path(file_path).stem)
