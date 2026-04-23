"""Excel 파일 플러그인 (.xlsx, .xls, .xlsm) - 기존 excel_utils.py 래퍼"""
import sys
import os
import pandas as pd
from pathlib import Path
from typing import List, Tuple

# src 경로 추가 (child process 환경 대응)
_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin


class ExcelPlugin(FormatPlugin):
    """Excel 파일(.xlsx, .xls, .xlsm) 처리 플러그인"""

    @property
    def plugin_id(self) -> str:
        return "excel"

    @property
    def display_name(self) -> str:
        return "Excel"

    @property
    def is_builtin(self) -> bool:
        return True

    @property
    def required_packages(self) -> List[str]:
        return ["openpyxl"]

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.xlsx', '.xls', '.xlsm')

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        """Excel 파일을 시트별로 읽어 (sheet_name, headers, df) 목록 반환.

        headers = 첫 번째 행 값 리스트
        df = 모든 행 포함 (header=None, RangeIndex 컬럼)
        이 계약은 기존 file_processor.py 의 동작과 동일.
        """
        from excel_utils import read_excel_file_safe, read_excel_sheet_safe
        from excel_utils import is_large_file

        large_file_mode = is_large_file(file_path)
        xl, sheet_names = read_excel_file_safe(file_path)

        try:
            results = []
            for sheet_name in sheet_names:
                df = read_excel_sheet_safe(xl, sheet_name, large_file_mode)
                if df.empty:
                    continue
                header_row = list(df.iloc[0].values) if len(df) > 0 else []
                headers = [str(h) if h is not None else "" for h in header_row]
                results.append((sheet_name, headers, df))
        finally:
            try:
                xl.close()
            except Exception:
                pass

        return results

    def supports_streaming(self, file_path: str) -> bool:
        return True

    def stream_file(self, file_path: str, chunk_size: int = 1000):
        """ExcelFile 객체를 유지하며 시트별로 스트리밍"""
        from excel_utils import read_excel_file_safe, read_excel_sheet_safe
        from excel_utils import is_large_file

        large_file_mode = is_large_file(file_path)
        xl, sheet_names = read_excel_file_safe(file_path)

        try:
            for sheet_name in sheet_names:
                df = read_excel_sheet_safe(xl, sheet_name, large_file_mode)
                if df.empty:
                    continue
                header_row = list(df.iloc[0].values) if len(df) > 0 else []
                headers = [str(h) if h is not None else "" for h in header_row]

                for i in range(0, max(1, len(df)), chunk_size):
                    chunk = df.iloc[i:i + chunk_size]
                    yield sheet_name, headers, chunk
        finally:
            try:
                xl.close()
            except Exception:
                pass

    def get_metadata(self, file_path: str) -> dict:
        from excel_utils import read_excel_file_safe
        try:
            xl, sheet_names = read_excel_file_safe(file_path)
            try:
                return {'sheet_names': sheet_names}
            finally:
                try:
                    xl.close()
                except Exception:
                    pass
        except Exception:
            return {'sheet_names': []}
