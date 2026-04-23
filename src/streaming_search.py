"""메모리 최적화를 위한 스트리밍 검색 모듈"""
import os
import pandas as pd
from typing import Iterator, Tuple, List, Optional, Generator
from pathlib import Path

from excel_utils import (
    read_csv_smart, read_excel_file_safe, is_large_file,
    ExcelProcessingError, FileFormatError
)
from constants import CHUNK_SIZE, LARGE_FILE_THRESHOLD, SUPPORTED_CSV_EXTENSIONS
from search_utils import (
    get_excluded_column_indices, should_skip_row_by_value
)


def stream_search_csv(file_path: str, search_text: str, exact_match: bool,
                     excluded_headers: List[str], excluded_if_not_empty: List[str],
                     case_sensitive: bool = False, chunk_size: int = CHUNK_SIZE) -> Generator[Tuple, None, None]:
    """CSV 파일 스트리밍 검색"""
    try:
        # 대용량 CSV 파일의 경우 청크 단위로 읽기
        if is_large_file(file_path):
            chunk_iterator = pd.read_csv(file_path, chunksize=chunk_size, na_filter=False)
            
            for chunk_idx, chunk in enumerate(chunk_iterator):
                if chunk.empty:
                    continue
                    
                # 첫 번째 청크에서 헤더 정보 설정
                if chunk_idx == 0:
                    header_row = chunk.columns
                    excluded_columns = get_excluded_column_indices(header_row, excluded_headers)
                    excluded_if_not_empty_columns = get_excluded_column_indices(header_row, excluded_if_not_empty)
                
                # 청크 내에서 검색
                sheet_name = Path(file_path).stem
                base_row_offset = chunk_idx * chunk_size  # CSV는 0-based 행 번호
                
                yield from _search_dataframe_chunk(
                    chunk, sheet_name, file_path, search_text, exact_match,
                    excluded_columns, excluded_if_not_empty_columns,
                    header_row, base_row_offset
                )
        else:
            # 작은 파일은 전체 로드
            df = read_csv_smart(file_path)
            if not df.empty:
                sheet_name = Path(file_path).stem
                header_row = df.columns
                excluded_columns = get_excluded_column_indices(header_row, excluded_headers)
                excluded_if_not_empty_columns = get_excluded_column_indices(header_row, excluded_if_not_empty)
                
                yield from _search_dataframe_chunk(
                    df, sheet_name, file_path, search_text, exact_match,
                    excluded_columns, excluded_if_not_empty_columns,
                    header_row, 0
                )
                
    except Exception as e:
        raise ExcelProcessingError(f"CSV 스트리밍 검색 실패: {str(e)}")


def stream_search_excel(file_path: str, search_text: str, exact_match: bool,
                       excluded_headers: List[str], excluded_if_not_empty: List[str],
                       case_sensitive: bool = False, chunk_size: int = CHUNK_SIZE) -> Generator[Tuple, None, None]:
    """Excel 파일 스트리밍 검색"""
    try:
        xl, sheet_names = read_excel_file_safe(file_path)
    except Exception as e:
        raise ExcelProcessingError(f"Excel 스트리밍 검색 실패: {str(e)}")

    try:
        for sheet_name in sheet_names:
            # 대용량 파일의 경우 스트리밍 처리
            if is_large_file(file_path):
                yield from _stream_search_excel_sheet(
                    xl, sheet_name, file_path, search_text, exact_match,
                    excluded_headers, excluded_if_not_empty, chunk_size
                )
            else:
                # 작은 파일은 전체 로드
                df = xl.parse(sheet_name, na_filter=False, header=None)
                if not df.empty:
                    header_row = df.iloc[0].values if len(df) > 0 else []
                    excluded_columns = get_excluded_column_indices(header_row, excluded_headers)
                    excluded_if_not_empty_columns = get_excluded_column_indices(header_row, excluded_if_not_empty)

                    yield from _search_dataframe_chunk(
                        df, sheet_name, file_path, search_text, exact_match,
                        excluded_columns, excluded_if_not_empty_columns,
                        header_row, 0
                    )
    except ExcelProcessingError:
        raise
    except Exception as e:
        raise ExcelProcessingError(f"Excel 스트리밍 검색 실패: {str(e)}")
    finally:
        try:
            xl.close()
        except Exception:
            pass


def _stream_search_excel_sheet(xl: pd.ExcelFile, sheet_name: str, file_path: str,
                              search_text: str, exact_match: bool,
                              excluded_headers: List[str], excluded_if_not_empty: List[str],
                              chunk_size: int) -> Generator[Tuple, None, None]:
    """Excel 시트 스트리밍 검색"""
    try:
        # 시트의 첫 번째 행을 읽어서 헤더 정보 추출
        temp_df = xl.parse(sheet_name, nrows=1, header=None)  # 첫 번째 행만 읽기
        header_row = temp_df.iloc[0].values if len(temp_df) > 0 else []
        
        excluded_columns = get_excluded_column_indices(header_row, excluded_headers)
        excluded_if_not_empty_columns = get_excluded_column_indices(header_row, excluded_if_not_empty)
        
        # 청크 단위로 시트 읽기
        row_offset = 0
        while True:
            try:
                chunk = xl.parse(
                    sheet_name,
                    skiprows=row_offset,
                    nrows=chunk_size,
                    header=None,
                    na_filter=False
                )
                
                if chunk.empty:
                    break

                yield from _search_dataframe_chunk(
                    chunk, sheet_name, file_path, search_text, exact_match,
                    excluded_columns, excluded_if_not_empty_columns,
                    header_row, row_offset
                )
                
                row_offset += chunk_size
                
                # 청크가 요청한 크기보다 작으면 마지막 청크
                if len(chunk) < chunk_size:
                    break
                    
            except Exception as e:
                # 더 이상 읽을 데이터가 없거나 오류 발생
                break
                
    except Exception as e:
        raise ExcelProcessingError(f"Excel 시트 스트리밍 검색 실패: {str(e)}")


# 함수가 search_utils.py로 이동되어 중복 제거


def _search_dataframe_chunk(df: pd.DataFrame, sheet_name: str, file_path: str,
                           search_text: str, exact_match: bool,
                           excluded_columns: List[int], excluded_if_not_empty_columns: List[int],
                           header_row, row_offset: int) -> Generator[Tuple, None, None]:
    """DataFrame 청크에서 검색 수행"""
    
    for df_row_idx, row in df.iterrows():
        # 실제 행 인덱스 계산
        actual_row_idx = row_offset + df_row_idx if isinstance(df_row_idx, int) else df_row_idx
        
        # 값이 있으면 제외할 열 확인 (개선된 유틸리티 사용)
        if should_skip_row_by_value(row, excluded_if_not_empty_columns):
            continue
        
        # 행에서 검색
        for col_idx, value in enumerate(row):
            # 제외할 열 건너뛰기
            if col_idx in excluded_columns:
                continue
            
            # 값 검색
            if value is not None:
                try:
                    str_value = str(value)
                except (ValueError, TypeError, AttributeError):
                    continue
                
                # 검색 조건 확인
                match_found = False
                if exact_match:
                    if case_sensitive:
                        match_found = str(search_text) == str_value
                    else:
                        match_found = str(search_text).lower() == str_value.lower()
                else:
                    if case_sensitive:
                        match_found = str(search_text) in str_value
                    else:
                        match_found = str(search_text).lower() in str_value.lower()
                
                if match_found:
                    # 헤더 행과 현재 행의 데이터 저장
                    header_data = [str(val) if val is not None else "" for val in header_row]
                    row_data = [str(val) if val is not None else "" for val in row]
                    
                    # 열 헤더 정보
                    col_header = str(col_idx + 1)  # 기본값은 열 번호 (1-based)
                    if col_idx < len(header_row):
                        col_header = f"{header_row[col_idx]} ({col_idx + 1})"
                    
                    yield (file_path, sheet_name, actual_row_idx, col_idx, str_value, 
                          header_data, row_data)


def should_use_streaming(file_path: str) -> bool:
    """스트리밍 검색을 사용해야 하는지 판단"""
    return is_large_file(file_path)


def get_optimal_chunk_size(file_path: str) -> int:
    """파일 크기에 따른 최적 청크 크기 반환"""
    try:
        file_size = os.path.getsize(file_path)
        
        if file_size < LARGE_FILE_THRESHOLD:
            return CHUNK_SIZE  # 기본 청크 크기
        elif file_size < 100 * 1024 * 1024:  # 100MB 미만
            return CHUNK_SIZE // 2  # 작은 청크
        else:  # 100MB 이상
            return CHUNK_SIZE // 4  # 더 작은 청크
            
    except OSError:
        return CHUNK_SIZE