# DocsFinder 성능 최적화 구현 플랜

> 작성일: 2026-04-13  
> 대상 파일: `src/file_processor.py`, `src/file_cache.py`, `src/main_app.py`, `src/search_utils.py`, `src/constants.py`

---

## 개요

DocsFinder의 3가지 핵심 병목을 해소하여 검색 성능과 UI 응답성을 대폭 개선한다.

| # | 최적화 항목 | 대상 파일 | 예상 효과 |
|---|------------|-----------|-----------|
| 1 | iterrows → 벡터화 검색 | `file_processor.py`, `search_utils.py` | 검색 10~50배 빠름 |
| 2 | DataFrame 디스크 캐시 (pickle) | `file_cache.py`, `file_processor.py`, `constants.py` | 재검색 시 파일 로딩 5~20배 빠름 |
| 3 | 결과 트리 노드 dict 캐싱 | `main_app.py` | UI 결과 추가 O(n)→O(1) |

---

## 작업 1: iterrows → 벡터화 검색

### 현재 문제

`file_processor.py:134-162` — `df.iterrows()`로 모든 셀을 순회하며 파이썬 레벨 루프에서 `str()` 변환 + 문자열 비교를 수행한다. pandas의 `iterrows()`는 각 행을 Series 객체로 변환하므로 매우 느리다.

```python
# 현재 코드 (느림)
for row_idx, row in df.iterrows():
    if should_skip_row_by_value(row, header_row, excluded_if_not_empty):
        continue
    for col_idx, value in enumerate(row):
        if col_idx < len(header_row) and should_exclude_column(...):
            continue
        str_value = str(value).strip()
        if _matches(str_value, search_text, exact_match, case_sensitive):
            ...
```

### 구현 방안

#### Step 1: 제외 컬럼 사전 계산 (Set)

`get_excluded_column_indices()`의 반환값을 **set**으로 변경하여 `col_idx in excluded_set` 검사를 O(1)로 만든다.

```python
excluded_col_set = set(get_excluded_column_indices(header_row, excluded_headers))
```

#### Step 2: 행 필터링 벡터화

`should_skip_row_by_value()`를 행 단위가 아닌 **DataFrame 전체에 대해 한 번에** 적용.

```python
def get_skip_row_mask(df, header_row, excluded_if_not_empty):
    """제외할 행의 boolean mask를 반환 (True = 건너뛸 행)"""
    if not excluded_if_not_empty:
        return pd.Series(False, index=df.index)
    
    skip_mask = pd.Series(False, index=df.index)
    for filter_setting in excluded_if_not_empty:
        parsed = parse_data_filter_setting(filter_setting)
        col_idx = _find_header_index(header_row, parsed['header'])
        if col_idx is None or col_idx >= len(df.columns):
            continue
        col = df.iloc[:, col_idx]
        if parsed['filter_type'] == 'any':
            skip_mask |= col.notna() & (col.astype(str).str.strip() != '')
        elif parsed['filter_type'] == 'specific':
            skip_mask |= (col.astype(str).str.strip() == parsed['specific_value'])
    return skip_mask
```

#### Step 3: 검색 매칭 벡터화

핵심: `df.astype(str)` → pandas `.str.contains()` / `.eq()`로 전체 DataFrame 검색.

```python
def _vectorized_search(df, search_text, exact_match, case_sensitive, excluded_col_set):
    """벡터화된 검색으로 매칭되는 (row_idx, col_idx) 위치 반환"""
    # 제외 컬럼 드롭
    search_cols = [i for i in range(len(df.columns)) if i not in excluded_col_set]
    df_subset = df.iloc[:, search_cols]
    
    # 전체를 문자열로 변환 (한 번만)
    df_str = df_subset.astype(str).apply(lambda col: col.str.strip())
    
    # NaN 문자열 제거
    nan_mask = df_str.apply(lambda col: col.str.lower() == 'nan')
    empty_mask = df_str == ''
    valid_mask = ~nan_mask & ~empty_mask
    
    # 검색 매칭
    search_trimmed = search_text.strip()
    if exact_match:
        if case_sensitive:
            match_mask = df_str.eq(search_trimmed) & valid_mask
        else:
            match_mask = df_str.apply(lambda col: col.str.lower()).eq(search_trimmed.lower()) & valid_mask
    else:
        if case_sensitive:
            match_mask = df_str.apply(lambda col: col.str.contains(search_trimmed, na=False, regex=False)) & valid_mask
        else:
            match_mask = df_str.apply(lambda col: col.str.contains(search_trimmed, case=False, na=False, regex=False)) & valid_mask
    
    # 매칭 위치 추출 — numpy로 빠르게
    import numpy as np
    rows, cols = np.where(match_mask.values)
    # cols는 df_subset 기준이므로 원래 인덱스로 변환
    original_cols = [search_cols[c] for c in cols]
    return list(zip(df.index[rows], original_cols))
```

#### Step 4: process_file 함수 리팩토링

벡터화된 함수들을 통합하여 `process_file()` 내 검색 루프를 대체.

```python
# 행 필터 마스크 생성
skip_mask = get_skip_row_mask(df, header_row, excluded_if_not_empty)
df_filtered = df[~skip_mask]

# 벡터화 검색
matches = _vectorized_search(df_filtered, search_text, exact_match, case_sensitive, excluded_col_set)

# 결과 생성
for row_idx, col_idx in matches:
    str_value = str(df_filtered.at[row_idx, df_filtered.columns[col_idx]]).strip()
    header_data = [str(h) if h is not None else "" for h in header_row]
    row_data = [str(v) if v is not None else "" for v in df_filtered.loc[row_idx]]
    results.append((file_path, sheet_name, row_idx, col_idx, str_value, header_data, row_data))
```

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/file_processor.py` | `_vectorized_search()`, `get_skip_row_mask()` 추가. `process_file()` 내 검색 루프 교체 |
| `src/search_utils.py` | `_find_header_index()` 헬퍼 추가 |

### 주의사항

- 스트리밍 모드(대용량 파일)도 청크 단위로 동일한 벡터화 적용
- `header_data`, `row_data` 생성은 매칭된 행에 대해서만 수행 (불필요한 str 변환 방지)
- 기존 `_matches()` 함수는 호환성을 위해 유지하되, 주 검색 경로에서는 사용하지 않음

---

## 작업 2: DataFrame 디스크 캐시 (pickle)

### 현재 문제

`file_cache.py`는 **메타데이터만** 캐시한다 (시트명, 파일 해시 등). 실제 DataFrame 데이터는 캐시하지 않아 매 검색마다 Excel 파일을 다시 파싱한다. Excel 파싱(`pd.read_excel`)은 매우 느린 I/O 작업이다.

### 구현 방안

#### Step 1: DataFrame 캐시 저장/로드

pickle 형식으로 DataFrame을 디스크에 캐시한다. parquet 대비 추가 의존성 없고 모든 데이터 타입을 보존한다.

```python
# file_cache.py에 추가
import pickle

class DataFrameCache:
    """DataFrame 디스크 캐시"""
    
    def __init__(self, cache_dir=None):
        if cache_dir is None:
            project_root = Path(__file__).parent.parent
            cache_dir = project_root / "config" / "cache" / "dataframes"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _cache_key(self, file_path):
        """파일 경로 기반 캐시 키 생성"""
        norm = os.path.normpath(file_path)
        return hashlib.md5(norm.encode()).hexdigest()
    
    def get(self, file_path):
        """캐시된 DataFrame 목록 반환. 없거나 만료되면 None."""
        cache_path = self.cache_dir / f"{self._cache_key(file_path)}.pkl"
        if not cache_path.exists():
            return None
        try:
            mtime = os.path.getmtime(file_path)
            size = os.path.getsize(file_path)
            with open(cache_path, 'rb') as f:
                cached = pickle.load(f)
            if cached['mtime'] == mtime and cached['size'] == size:
                return cached['sections']  # [(sheet_name, headers, df), ...]
        except Exception:
            pass
        return None
    
    def set(self, file_path, sections):
        """DataFrame 목록을 캐시에 저장"""
        cache_path = self.cache_dir / f"{self._cache_key(file_path)}.pkl"
        try:
            data = {
                'mtime': os.path.getmtime(file_path),
                'size': os.path.getsize(file_path),
                'sections': sections,
            }
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            pass
    
    def clear(self):
        """전체 캐시 삭제"""
        import shutil
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def cleanup(self, max_entries=200):
        """오래된 캐시 파일 정리"""
        files = sorted(self.cache_dir.glob("*.pkl"), key=lambda p: p.stat().st_mtime)
        if len(files) > max_entries:
            for f in files[:len(files) - max_entries]:
                f.unlink(missing_ok=True)
```

#### Step 2: file_processor.py에서 캐시 활용

```python
from file_cache import get_df_cache

# process_file() 내:
df_cache = get_df_cache()
cached_sections = df_cache.get(file_path)

if cached_sections is not None:
    section_iter = iter(cached_sections)
else:
    sections = plugin.read_file(file_path)
    # 캐시에 저장 (스트리밍이 아닌 경우만)
    if not use_streaming:
        df_cache.set(file_path, sections)
    section_iter = iter(sections)
```

#### Step 3: 캐시 크기 관리 상수

```python
# constants.py에 추가
MAX_DF_CACHE_ENTRIES = 200      # DataFrame 캐시 최대 파일 수
DF_CACHE_DIR = "dataframes"     # 캐시 서브디렉토리명
```

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/file_cache.py` | `DataFrameCache` 클래스 추가, `get_df_cache()` 전역 접근자 추가 |
| `src/file_processor.py` | 캐시 조회/저장 로직 통합 |
| `src/constants.py` | 캐시 관련 상수 추가 |

### 주의사항

- pickle은 **신뢰할 수 있는 로컬 파일만** 역직렬화하므로 보안 문제 없음
- 대용량 파일(>50MB)은 캐시하지 않음 (디스크 공간 절약)
- 파일 수정시간(mtime) + 크기(size) 조합으로 캐시 유효성 검증 (해시 불필요)
- 멀티프로세스 환경에서 동시 쓰기 충돌 방지: 임시 파일 → rename 패턴 사용

---

## 작업 3: 결과 트리 노드 dict 캐싱

### 현재 문제

`main_app.py:1709-1713` — `add_result()`가 호출될 때마다 파일 노드를 찾기 위해 트리의 **모든 최상위 아이템을 순회**한다. 시트 노드도 마찬가지로 해당 파일의 **모든 자식을 순회**한다.

```python
# 현재 코드 — O(n) 탐색
for i in range(self.result_tree.topLevelItemCount()):
    candidate = self.result_tree.topLevelItem(i)
    node_data = candidate.data(0, Qt.UserRole)
    if isinstance(node_data, dict) and node_data.get('file_path') == file_path:
        file_node = candidate
        break
```

검색 결과가 수천 건이면 파일/시트 노드 탐색만으로도 심각한 지연이 발생한다.

### 구현 방안

#### Step 1: 노드 캐시 딕셔너리 추가

```python
# start_search() 내 결과 트리 초기화 시점에 함께 초기화
self.result_tree.clear()
self._file_node_cache = {}    # {file_path: QTreeWidgetItem}
self._sheet_node_cache = {}   # {(file_path, sheet_name): QTreeWidgetItem}
```

#### Step 2: add_result() 내 노드 조회 변경

```python
def add_result(self, file_path, sheet_name, row, col, value, header_data, row_data):
    if not hasattr(self, 'excel_icon'):
        self.init_icons()

    file_ext = os.path.splitext(file_path)[1].lower()
    show_intermediate = file_ext in self._FORMATS_WITH_INTERMEDIATE

    # ── Level 1: 파일 노드 — O(1) 조회 ─────────────────────────
    file_node = self._file_node_cache.get(file_path)
    if file_node is None:
        file_name = os.path.basename(file_path)
        file_node = QTreeWidgetItem(self.result_tree)
        file_node.setData(0, Qt.UserRole, {'type': 'file', 'file_path': file_path})
        file_node.setText(0, file_name)
        file_node.setIcon(0, self._get_file_icon(file_ext))
        file_node.setExpanded(True)
        self._file_node_cache[file_path] = file_node

    # ── Level 2: 시트 노드 — O(1) 조회 ─────────────────────────
    if show_intermediate:
        cache_key = (file_path, sheet_name)
        sheet_node = self._sheet_node_cache.get(cache_key)
        if sheet_node is None:
            sheet_node = QTreeWidgetItem(file_node)
            sheet_node.setData(0, Qt.UserRole, {'type': 'sheet', 'sheet_name': sheet_name})
            sheet_node.setText(0, sheet_name)
            sheet_node.setExpanded(True)
            self._sheet_node_cache[cache_key] = sheet_node
        result_parent = sheet_node
    else:
        result_parent = file_node

    # 이하 결과 노드 생성은 기존과 동일...
```

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/main_app.py` | `_file_node_cache`, `_sheet_node_cache` 추가. `add_result()` 내 노드 조회를 dict lookup으로 교체. `start_search()`에서 캐시 초기화. |

### 주의사항

- `result_tree.clear()` 호출 시 캐시 dict도 반드시 초기화
- 캐시 키는 file_path 원본 문자열 사용 (normalize 불필요 — 동일 검색 세션 내에서는 경로가 동일)

---

## 구현 순서

```
작업 3 (결과 트리 캐싱)     ← 가장 간단, 먼저 완료
    ↓
작업 1 (벡터화 검색)         ← 핵심 성능 개선
    ↓
작업 2 (DataFrame 디스크 캐시) ← 재검색 성능 개선
```

작업 3은 독립적이므로 먼저 완료하고, 작업 1과 2는 `file_processor.py`를 공유하므로 순차적으로 진행한다.
