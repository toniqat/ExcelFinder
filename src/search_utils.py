"""검색 예외 처리 유틸리티 모듈"""
from typing import List, Set, Dict, Tuple


def extract_header_name_from_setting(header_setting: str) -> str:
    """설정에서 헤더 이름만 추출 (메모 부분 제거)
    
    Args:
        header_setting: "헤더명" 또는 "헤더명 (메모: 설명)" 또는 "헤더명|match_type|메모: 설명" 형태의 문자열
        
    Returns:
        헤더명만 추출된 문자열
    """
    # 새로운 형식: "header|match_type|메모: memo"
    if "|" in header_setting:
        return header_setting.split("|", 1)[0]
    # 기존 형식: "header (메모: memo)"
    elif " (메모: " in header_setting:
        return header_setting.split(" (메모: ", 1)[0]
    return header_setting


def parse_header_filter_setting(header_setting: str) -> Dict[str, str]:
    """헤더 필터 설정 파싱
    
    Args:
        header_setting: 헤더 필터 설정 문자열
        
    Returns:
        {'header': str, 'match_type': str, 'memo': str}
    """
    if "|" in header_setting:
        # 새로운 형식: "header|match_type|메모: memo"
        parts = header_setting.split("|", 2)
        header = parts[0]
        match_type = parts[1] if len(parts) > 1 else 'exact'
        memo_part = parts[2] if len(parts) > 2 else ''
        
        if memo_part.startswith('메모: '):
            memo = memo_part[3:]  # "메모: " 제거
        else:
            memo = memo_part
    else:
        # 기존 형식 (호환성)
        if " (메모: " in header_setting:
            header, memo_part = header_setting.split(" (메모: ", 1)
            memo = memo_part.rstrip(")")
        else:
            header = header_setting
            memo = ""
        match_type = 'exact'  # 기본값
    
    return {
        'header': header,
        'match_type': match_type,
        'memo': memo
    }


def parse_data_filter_setting(filter_setting: str) -> Dict[str, str]:
    """데이터 필터 설정 파싱
    
    Args:
        filter_setting: 데이터 필터 설정 문자열
        
    Returns:
        {'header': str, 'filter_type': str, 'specific_value': str, 'memo': str}
    """
    if "|" in filter_setting:
        # 새로운 형식: "header|filter_type|specific_value|메모: memo"
        parts = filter_setting.split("|", 3)
        header = parts[0]
        filter_type = parts[1] if len(parts) > 1 else 'any'
        specific_value = parts[2] if len(parts) > 2 else ''
        memo_part = parts[3] if len(parts) > 3 else ''
        
        if memo_part.startswith('메모: '):
            memo = memo_part[3:]  # "메모: " 제거
        else:
            memo = memo_part
    else:
        # 기존 형식 (호환성)
        if " (메모: " in filter_setting:
            header, memo_part = filter_setting.split(" (메모: ", 1)
            memo = memo_part.rstrip(")")
        else:
            header = filter_setting
            memo = ""
        filter_type = 'any'  # 기본값
        specific_value = ''
    
    return {
        'header': header,
        'filter_type': filter_type,
        'specific_value': specific_value,
        'memo': memo
    }


def get_clean_excluded_headers(excluded_headers: List[str]) -> Set[str]:
    """메모가 제거된 순수 헤더 이름 집합 반환"""
    return {extract_header_name_from_setting(header) for header in excluded_headers}


def should_exclude_column(header_value: str, excluded_headers: List[str]) -> bool:
    """컬럼이 제외되어야 하는지 확인 (개선된 버전 - 매칭 방식 고려)
    
    Args:
        header_value: 검사할 헤더 값
        excluded_headers: 제외할 헤더 설정 목록
        
    Returns:
        제외해야 하면 True, 아니면 False
    """
    if not excluded_headers:
        return False
    
    header_str = str(header_value)
    
    # 중복 헤더 처리 (.1, .2 등의 접미사 제거)
    base_header = header_str
    if '.' in header_str:
        parts = header_str.rsplit('.', 1)
        if len(parts) == 2 and parts[1].isdigit():
            base_header = parts[0]
    
    # 각 헤더 필터 설정 확인
    for header_setting in excluded_headers:
        parsed = parse_header_filter_setting(header_setting)
        target_header = parsed['header']
        match_type = parsed['match_type']
        
        if match_type == 'exact':
            # 정확히 일치
            if base_header == target_header or header_str == target_header:
                return True
        elif match_type == 'contains':
            # 키워드 포함
            if target_header.lower() in base_header.lower() or target_header.lower() in header_str.lower():
                return True
    
    return False


def should_skip_row_by_value(row_data, header_row, excluded_if_not_empty: List[str]) -> bool:
    """값이 있는 컬럼 때문에 행을 건너뛸지 확인 (개선된 버전 - 필터 방식 고려)
    
    Args:
        row_data: 행 데이터
        header_row: 헤더 행 데이터
        excluded_if_not_empty: 데이터 필터 설정 목록
        
    Returns:
        행을 건너뛸 경우 True, 아니면 False
    """
    if not excluded_if_not_empty:
        return False
    
    # 각 데이터 필터 설정 확인
    for filter_setting in excluded_if_not_empty:
        parsed = parse_data_filter_setting(filter_setting)
        target_header = parsed['header']
        filter_type = parsed['filter_type']
        specific_value = parsed['specific_value']
        
        # 해당 헤더의 컬럼 인덱스 찾기
        col_idx = None
        for i, header_value in enumerate(header_row):
            header_str = str(header_value)
            # 중복 헤더 처리
            base_header = header_str
            if '.' in header_str:
                parts = header_str.rsplit('.', 1)
                if len(parts) == 2 and parts[1].isdigit():
                    base_header = parts[0]
            
            if base_header == target_header or header_str == target_header:
                col_idx = i
                break
        
        if col_idx is not None and col_idx < len(row_data):
            value = row_data.iloc[col_idx] if hasattr(row_data, 'iloc') else row_data[col_idx]
            
            if filter_type == 'any':
                # 어떠한 값이건 있을 때
                if value is not None and str(value).strip():
                    return True
            elif filter_type == 'specific':
                # 지정한 값이 있을 때만
                if value is not None and str(value).strip() == specific_value:
                    return True
    
    return False


def find_header_index(header_row, target_header: str):
    """헤더 행에서 대상 헤더의 컬럼 인덱스를 찾아 반환. 없으면 None."""
    for i, header_value in enumerate(header_row):
        header_str = str(header_value)
        base_header = header_str
        if '.' in header_str:
            parts = header_str.rsplit('.', 1)
            if len(parts) == 2 and parts[1].isdigit():
                base_header = parts[0]
        if base_header == target_header or header_str == target_header:
            return i
    return None


def get_excluded_column_indices(header_row, excluded_headers: List[str]) -> List[int]:
    """제외할 컬럼의 인덱스 목록 반환
    
    Args:
        header_row: 헤더 행 데이터
        excluded_headers: 제외할 헤더 설정 목록 (메모 포함 가능)
        
    Returns:
        제외할 컬럼의 인덱스 목록
    """
    if not excluded_headers:
        return []
    
    excluded_columns = []
    
    for col_idx, header_value in enumerate(header_row):
        if should_exclude_column(header_value, excluded_headers):
            excluded_columns.append(col_idx)
    
    return excluded_columns


def debug_exclusion_info(header_row, excluded_headers: List[str], 
                        excluded_if_not_empty: List[str]) -> dict:
    """디버깅용 제외 정보 반환"""
    excluded_headers_clean = get_clean_excluded_headers(excluded_headers)
    excluded_if_not_empty_clean = get_clean_excluded_headers(excluded_if_not_empty)
    
    excluded_col_indices = get_excluded_column_indices(header_row, excluded_headers)
    excluded_if_not_empty_indices = get_excluded_column_indices(header_row, excluded_if_not_empty)
    
    return {
        'original_excluded_headers': excluded_headers,
        'clean_excluded_headers': list(excluded_headers_clean),
        'original_excluded_if_not_empty': excluded_if_not_empty,
        'clean_excluded_if_not_empty': list(excluded_if_not_empty_clean),
        'header_row': list(header_row),
        'excluded_column_indices': excluded_col_indices,
        'excluded_if_not_empty_indices': excluded_if_not_empty_indices,
        'excluded_columns': [header_row[i] for i in excluded_col_indices if i < len(header_row)],
        'excluded_if_not_empty_columns': [header_row[i] for i in excluded_if_not_empty_indices if i < len(header_row)]
    }