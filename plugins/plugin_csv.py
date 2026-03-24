"""CSV/TSV 파일 플러그인 - 기존 excel_utils.read_csv_smart() 래퍼"""
import sys
import pandas as pd
from pathlib import Path
from typing import List, Tuple

_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin


class CsvPlugin(FormatPlugin):
    """CSV/TSV 파일(.csv, .tsv) 처리 플러그인"""

    @property
    def plugin_id(self) -> str:
        return "csv"

    @property
    def display_name(self) -> str:
        return "CSV/TSV"

    @property
    def is_builtin(self) -> bool:
        return True

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.csv', '.tsv')

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        """CSV/TSV 파일 읽기.

        sheet_name = 파일명(확장자 제외)
        headers = DataFrame 컬럼 이름 리스트 (CSV 첫 행)
        df = 헤더 행을 row 0으로 포함한 RangeIndex DataFrame (Excel 플러그인과 동일)
        """
        from excel_utils import read_csv_smart

        df = read_csv_smart(file_path)
        sheet_name = Path(file_path).stem
        headers = [str(col) for col in df.columns]
        # 헤더 행을 row 0으로 포함 (Excel 플러그인과 동일한 방식)
        header_df = pd.DataFrame([headers], columns=df.columns)
        df_full = pd.concat([header_df, df], ignore_index=True)
        df_full.columns = range(len(df_full.columns))
        return [(sheet_name, headers, df_full)]

    def supports_streaming(self, file_path: str) -> bool:
        return True

    def stream_file(self, file_path: str, chunk_size: int = 1000):
        from excel_utils import read_csv_smart

        df = read_csv_smart(file_path)
        sheet_name = Path(file_path).stem
        headers = [str(col) for col in df.columns]
        # 헤더 행을 row 0으로 포함 (Excel 플러그인과 동일한 방식)
        header_df = pd.DataFrame([headers], columns=df.columns)
        df_full = pd.concat([header_df, df], ignore_index=True)
        df_full.columns = range(len(df_full.columns))

        for i in range(0, max(1, len(df_full)), chunk_size):
            chunk = df_full.iloc[i:i + chunk_size]
            yield sheet_name, headers, chunk
