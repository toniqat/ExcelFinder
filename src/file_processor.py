import os
import pandas as pd
from pathlib import Path
from typing import List, Tuple, Optional

from excel_utils import is_large_file
from file_cache import get_file_cache
from search_utils import (
    get_excluded_column_indices,
    should_skip_row_by_value, debug_exclusion_info, should_exclude_column
)
from plugin_registry import get_plugin_registry


def _should_exclude_by_filter(text, filter_string):
    """필터 문자열에 따라 텍스트를 제외해야 하는지 확인"""
    if not filter_string:
        return False

    parts = filter_string.split('|')
    if len(parts) < 2:
        return parts[0] in text

    keyword = parts[0]
    match_type = parts[1]

    if match_type == 'exact':
        return keyword == text
    else:
        return keyword in text


def _matches(str_value: str, search_text: str, exact_match: bool, case_sensitive: bool) -> bool:
    """검색 조건에 따라 값이 일치하는지 확인"""
    search_text_trimmed = str(search_text).strip()
    if exact_match:
        if case_sensitive:
            return search_text_trimmed == str_value
        return search_text_trimmed.lower() == str_value.lower()
    else:
        if case_sensitive:
            return search_text_trimmed in str_value
        return search_text_trimmed.lower() in str_value.lower()


def process_file(args) -> Tuple[List, List]:
    """
    개별 파일을 처리하는 함수 (멀티프로세싱용)
    args: (file_path, search_text, exact_match, excluded_headers, excluded_if_not_empty,
           case_sensitive, excluded_paths, excluded_files, excluded_sheets)

    Returns:
        Tuple[List, List]: (검색 결과 리스트, 오류 메시지 리스트)
    """
    (file_path, search_text, exact_match, excluded_headers, excluded_if_not_empty,
     case_sensitive, excluded_paths, excluded_files, excluded_sheets) = args

    results = []
    error_msgs = []

    try:
        file_ext = Path(file_path).suffix.lower()

        # 플러그인 레지스트리에서 파서 조회 (child process: lazy discover)
        registry = get_plugin_registry()
        if not registry._discovered:
            registry.discover()
            # 플러그인 로드 실패는 파일 단위 오류가 아니므로 error_msgs에 추가하지 않음.
            # 메인 프로세스 시작 시 이미 보고됨.

        plugin = registry.get_parser(file_ext)
        if plugin is None:
            error_msgs.append((file_path, f"지원하지 않는 파일 형식: {file_ext}"))
            return results, error_msgs

        # 캐시 확인 (Excel 플러그인만 의미 있음)
        cache = get_file_cache()
        cached_metadata = cache.get_metadata(file_path)

        # 캐시된 시트 정보가 있으면 메타데이터 재사용 (Excel 전용)
        # 실제 파일 읽기는 플러그인에서 처리

        # 스트리밍 vs 전체 로드 결정
        use_streaming = (plugin.supports_streaming(file_path) and
                         is_large_file(file_path))

        if use_streaming:
            section_iter = plugin.stream_file(file_path)
        else:
            try:
                sections = plugin.read_file(file_path)
            except PermissionError:
                error_msgs.append((file_path, "PermissionError: 이미 열고 있는 파일을 닫은 후 시도해주세요"))
                return results, error_msgs
            except Exception as e:
                error_msgs.append((file_path, f"파일 열기 실패: {str(e)}"))
                return results, error_msgs

            # 캐시 갱신 (시트 이름 저장)
            if sections and not cached_metadata:
                sheet_names = [s[0] for s in sections]
                cache.set_metadata(file_path, sheet_names)

            section_iter = iter(sections)

        # 통합 검색 루프 — 모든 포맷에 동일하게 적용
        for sheet_name, headers, df in section_iter:
            # 시트 필터링
            should_exclude_sheet = any(
                _should_exclude_by_filter(sheet_name, f) for f in excluded_sheets
            )
            if should_exclude_sheet:
                continue

            if df.empty:
                continue

            # 헤더 행 결정
            # Excel 플러그인: df는 header=None (첫 행이 데이터에 포함됨)
            # 기타 플러그인: headers 리스트가 별도로 제공됨
            header_row = headers if headers else []

            # 값이 있으면 제외할 열 인덱스 계산
            excluded_if_not_empty_columns = get_excluded_column_indices(
                header_row, excluded_if_not_empty
            )

            if os.getenv('EXCEL_FINDER_DEBUG') == '1':
                debug_info = debug_exclusion_info(header_row, excluded_headers, excluded_if_not_empty)
                print(f"\n[DEBUG] {os.path.basename(file_path)} 시트 {sheet_name} 제외 처리:")
                print(f"  제외될 컬럼: {debug_info['excluded_columns']}")
                print(f"  값 있으면 제외될 컬럼: {debug_info['excluded_if_not_empty_columns']}")

            for row_idx, row in df.iterrows():
                # 행 필터링 (excluded_if_not_empty)
                if should_skip_row_by_value(row, header_row, excluded_if_not_empty):
                    if os.getenv('EXCEL_FINDER_DEBUG') == '1':
                        print(f"    [DEBUG] 행 {row_idx} 스킵 (데이터 필터 조건)")
                    continue

                for col_idx, value in enumerate(row):
                    # 열 필터링 (excluded_headers)
                    if col_idx < len(header_row) and should_exclude_column(
                            header_row[col_idx], excluded_headers):
                        continue

                    if value is None:
                        continue

                    try:
                        str_value = str(value).strip()
                    except (ValueError, TypeError, AttributeError):
                        continue

                    if not str_value or str_value.lower() == 'nan':
                        continue

                    if _matches(str_value, search_text, exact_match, case_sensitive):
                        header_data = [str(h) if h is not None else "" for h in header_row]
                        row_data = [str(v) if v is not None else "" for v in row]
                        results.append((file_path, sheet_name, row_idx, col_idx,
                                        str_value, header_data, row_data))

    except Exception as e:
        error_msgs.append((file_path, f"파일 처리 중 예기치 못한 오류: {str(e)}"))

    return results, error_msgs
