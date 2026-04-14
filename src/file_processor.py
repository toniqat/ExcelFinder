import os
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional

from excel_utils import is_large_file
from file_cache import get_file_cache, get_df_cache
from search_utils import (
    get_excluded_column_indices,
    should_skip_row_by_value, debug_exclusion_info, should_exclude_column,
    parse_data_filter_setting, find_header_index
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
    """검색 조건에 따라 값이 일치하는지 확인 (호환용 — 스트리밍 폴백)"""
    search_text_trimmed = str(search_text).strip()
    if exact_match:
        if case_sensitive:
            return search_text_trimmed == str_value
        return search_text_trimmed.lower() == str_value.lower()
    else:
        if case_sensitive:
            return search_text_trimmed in str_value
        return search_text_trimmed.lower() in str_value.lower()


def _get_skip_row_mask(df, header_row, excluded_if_not_empty):
    """제외할 행의 boolean mask를 반환 (True = 건너뛸 행).
    벡터화된 연산으로 행 단위 루프를 제거한다."""
    if not excluded_if_not_empty:
        return pd.Series(False, index=df.index)

    skip_mask = pd.Series(False, index=df.index)
    for filter_setting in excluded_if_not_empty:
        parsed = parse_data_filter_setting(filter_setting)
        col_idx = find_header_index(header_row, parsed['header'])
        if col_idx is None or col_idx >= len(df.columns):
            continue
        col = df.iloc[:, col_idx]
        if parsed['filter_type'] == 'any':
            # 어떠한 값이건 있을 때 → 해당 행 제외
            col_str = col.astype(str).str.strip()
            skip_mask = skip_mask | (col.notna() & (col_str != '') & (col_str.str.lower() != 'nan'))
        elif parsed['filter_type'] == 'specific':
            # 지정한 값이 있을 때만
            skip_mask = skip_mask | (col.astype(str).str.strip() == parsed['specific_value'])
    return skip_mask


def _vectorized_search(df, search_text, exact_match, case_sensitive, excluded_col_set):
    """벡터화된 검색으로 매칭되는 (row_idx, col_idx) 위치 리스트와 전체 str DataFrame을 반환.

    pandas str 연산을 사용하여 셀 단위 파이썬 루프를 완전히 제거한다.

    Returns:
        (matches, df_str_full)
        - matches: [(row_idx, col_idx), ...]
        - df_str_full: 전체 DataFrame의 str 변환 결과 (결과 생성 시 재사용)
    """
    # 전체 DataFrame의 str 버전 생성 (결과 추출용으로 재사용)
    df_str_full = df.astype(str)
    for col in df_str_full.columns:
        df_str_full[col] = df_str_full[col].str.strip()

    if df.empty:
        return [], df_str_full

    # 검색 대상 컬럼만 선택
    all_cols = list(range(len(df.columns)))
    search_cols = [i for i in all_cols if i not in excluded_col_set]
    if not search_cols:
        return [], df_str_full

    df_str = df_str_full.iloc[:, search_cols]

    # NaN 문자열 및 빈 문자열 마스크
    valid_mask = pd.DataFrame(True, index=df_str.index, columns=df_str.columns)
    for col in df_str.columns:
        valid_mask[col] = (df_str[col] != '') & (df_str[col].str.lower() != 'nan')

    # 검색 매칭
    search_trimmed = search_text.strip()
    if exact_match:
        if case_sensitive:
            match_mask = df_str.eq(search_trimmed) & valid_mask
        else:
            search_lower = search_trimmed.lower()
            match_mask = pd.DataFrame(False, index=df_str.index, columns=df_str.columns)
            for col in df_str.columns:
                match_mask[col] = (df_str[col].str.lower() == search_lower) & valid_mask[col]
    else:
        if case_sensitive:
            match_mask = pd.DataFrame(False, index=df_str.index, columns=df_str.columns)
            for col in df_str.columns:
                match_mask[col] = df_str[col].str.contains(search_trimmed, na=False, regex=False) & valid_mask[col]
        else:
            match_mask = pd.DataFrame(False, index=df_str.index, columns=df_str.columns)
            for col in df_str.columns:
                match_mask[col] = df_str[col].str.contains(search_trimmed, case=False, na=False, regex=False) & valid_mask[col]

    # 매칭 위치 추출 — numpy로 빠르게
    rows, cols = np.where(match_mask.values)
    # cols는 df_str(subset) 기준이므로 원래 인덱스로 변환
    original_cols = [search_cols[c] for c in cols]
    return list(zip(df.index[rows].tolist(), original_cols)), df_str_full


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

        # ── 파일 이름 매칭 ──────────────────────────────────────
        file_basename = os.path.basename(file_path)
        if _matches(file_basename, search_text, exact_match, case_sensitive):
            # row=-1 은 파일 이름 매칭을 나타냄
            results.append((file_path, '', -1, -1, file_basename, None, None))

        # 플러그인 레지스트리에서 파서 조회 (child process: lazy discover)
        registry = get_plugin_registry()
        if not registry._discovered:
            registry.discover()

        plugin = registry.get_parser(file_ext)
        if plugin is None:
            error_msgs.append((file_path, f"지원하지 않는 파일 형식: {file_ext}"))
            return results, error_msgs

        # 캐시 확인
        cache = get_file_cache()
        cached_metadata = cache.get_metadata(file_path)
        df_cache = get_df_cache()

        # 스트리밍 vs 전체 로드 결정
        use_streaming = (plugin.supports_streaming(file_path) and
                         is_large_file(file_path))

        if use_streaming:
            section_iter = plugin.stream_file(file_path)
        else:
            # DataFrame 디스크 캐시 조회 (pickle)
            cached_sections = df_cache.get(file_path)
            if cached_sections is not None:
                sections = cached_sections
            else:
                try:
                    sections = plugin.read_file(file_path)
                except PermissionError:
                    error_msgs.append((file_path, "PermissionError: 이미 열고 있는 파일을 닫은 후 시도해주세요"))
                    return results, error_msgs
                except Exception as e:
                    error_msgs.append((file_path, f"파일 열기 실패: {str(e)}"))
                    return results, error_msgs

                # DataFrame 캐시에 저장
                df_cache.set(file_path, sections)

            # 메타데이터 캐시 갱신 (시트 이름 저장)
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

            # ── 시트 이름 매칭 ──────────────────────────────────
            if _matches(sheet_name, search_text, exact_match, case_sensitive):
                # row=-2 는 시트 이름 매칭을 나타냄
                results.append((file_path, sheet_name, -2, -1, sheet_name, None, None))

            if df.empty:
                continue

            # 헤더 행 결정
            header_row = headers if headers else []

            # 제외 컬럼 인덱스를 set으로 사전 계산 (O(1) lookup)
            excluded_col_set = set(get_excluded_column_indices(
                header_row, excluded_headers
            ))

            if os.getenv('EXCEL_FINDER_DEBUG') == '1':
                debug_info = debug_exclusion_info(header_row, excluded_headers, excluded_if_not_empty)
                print(f"\n[DEBUG] {os.path.basename(file_path)} 시트 {sheet_name} 제외 처리:")
                print(f"  제외될 컬럼: {debug_info['excluded_columns']}")
                print(f"  값 있으면 제외될 컬럼: {debug_info['excluded_if_not_empty_columns']}")

            # ── 벡터화 검색 ──────────────────────────────────────────
            # 1) 행 필터 마스크 생성 (벡터화)
            skip_mask = _get_skip_row_mask(df, header_row, excluded_if_not_empty)
            df_filtered = df[~skip_mask]

            if df_filtered.empty:
                continue

            # 2) 벡터화 검색 수행 (df_str도 함께 반환하여 재변환 제거)
            matches, df_str = _vectorized_search(
                df_filtered, search_text, exact_match, case_sensitive, excluded_col_set
            )

            # 3) 결과 생성 — 이미 변환된 df_str 재사용 (str() 재변환 없음)
            header_data = [str(h) if h is not None else "" for h in header_row]
            for row_idx, col_idx in matches:
                try:
                    str_value = df_str.iat[
                        df_str.index.get_loc(row_idx), col_idx
                    ]
                    row_data = df_str.loc[row_idx].tolist()
                    results.append((file_path, sheet_name, row_idx, col_idx,
                                    str_value, header_data, row_data))
                except (KeyError, IndexError):
                    continue

    except Exception as e:
        error_msgs.append((file_path, f"파일 처리 중 예기치 못한 오류: {str(e)}"))

    return results, error_msgs
