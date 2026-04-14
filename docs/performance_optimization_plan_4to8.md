# DocsFinder 성능 최적화 구현 플랜 (4~8번)

> 작성일: 2026-04-14  
> 선행 작업: 1~3번 완료 (벡터화 검색, DataFrame 디스크 캐시, 결과 트리 노드 캐싱)

---

## 개요

| # | 최적화 항목 | 대상 파일 | 예상 효과 |
|---|------------|-----------|-----------|
| 4 | ProcessPoolExecutor 재사용 | `search_worker.py` | 검색 시작 지연 1~3초 단축 |
| 5 | 결과 스트리밍 배치 표시 | `main_app.py` | 체감 검색 속도 대폭 개선 |
| 6 | Lazy import | `main.py`, `config.py`, `main_app.py` | 앱 시작 시간 30~50% 단축 |
| 7 | str() 중복 변환 제거 | `file_processor.py`, `main_app.py` | 검색 속도 10~20% 추가 개선 |
| 8 | QTreeView 가상화 | `main_app.py` (신규: `result_model.py`) | 만 건 이상 결과에서 UI 멈춤 방지 |

---

## 작업 4: ProcessPoolExecutor 재사용

### 현재 문제

`search_worker.py:172` — 매 검색마다 `ProcessPoolExecutor`를 새로 생성한다.

```python
# 현재 코드 (search_worker.py:172)
with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
    ...
```

프로세스 풀 생성 시 워커 프로세스를 fork/spawn하고, 각 워커에서 Python 인터프리터를 초기화하며, 모듈을 import하는 과정이 **1~3초** 소요된다. 특히 Windows에서는 `spawn` 방식이라 매번 전체 모듈을 다시 로드한다.

### 구현 방안

#### Step 1: 모듈 수준 풀 관리자 추가

`search_worker.py`에 모듈 레벨 풀 관리자를 추가하여, 앱 수명 동안 `ProcessPoolExecutor`를 재사용한다.

```python
# search_worker.py 상단에 추가

_shared_executor: Optional[ProcessPoolExecutor] = None
_shared_executor_workers: int = 0

def get_shared_executor(max_workers: int) -> ProcessPoolExecutor:
    """공유 ProcessPoolExecutor 반환. 워커 수 변경 시 재생성."""
    global _shared_executor, _shared_executor_workers
    if _shared_executor is None or _shared_executor_workers != max_workers:
        shutdown_shared_executor()
        _shared_executor = ProcessPoolExecutor(max_workers=max_workers)
        _shared_executor_workers = max_workers
    return _shared_executor

def shutdown_shared_executor():
    """공유 executor 종료 (앱 종료 시 호출)"""
    global _shared_executor
    if _shared_executor is not None:
        _shared_executor.shutdown(wait=False)
        _shared_executor = None
```

#### Step 2: ParallelSearchWorker.run() 수정

`with ProcessPoolExecutor(...)` 블록을 `get_shared_executor()` 호출로 교체한다.

```python
def run(self):
    try:
        self.initial_excel_processes = self.get_excel_processes()
        filtered_files = self.apply_file_and_path_filters(self.files)
        completed_files = 0
        total_files = len(filtered_files)

        tasks = [(...) for file_path in filtered_files]

        # 공유 executor 사용 (재생성 없음)
        executor = get_shared_executor(self.max_workers)
        self.executor = executor

        futures = {executor.submit(process_file, task): task for task in tasks}

        for future in as_completed(futures):
            if not self.is_running:
                for f in futures:
                    f.cancel()
                break

            # ... 기존 결과 처리 로직 동일 ...

    except Exception as e:
        self.error_occurred.emit("검색 오류", f"병렬 검색 중 예외 발생: {str(e)}")
    finally:
        self.kill_new_excel_processes()
        self.executor = None  # 참조만 해제 (shutdown 하지 않음)
        self.search_completed.emit()
```

**핵심 차이**: `with` 블록 제거 → `finally`에서 `executor.shutdown()`을 호출하지 않고 참조만 해제.

#### Step 3: 앱 종료 시 정리

`main_app.py`의 `on_close_event()`에서 공유 executor를 종료한다.

```python
# main_app.py — on_close_event()에 추가
def on_close_event(self, event):
    self.save_settings()
    from search_worker import shutdown_shared_executor
    shutdown_shared_executor()
    event.accept()
```

#### Step 4: stop() 수정

검색 중지 시 executor를 shutdown하지 않고, 진행 중인 future만 취소한다.

```python
def stop(self):
    """검색 중지"""
    self.is_running = False
    self.kill_new_excel_processes()
    # executor는 shutdown하지 않음 — 다음 검색에서 재사용
```

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/search_worker.py` | `get_shared_executor()`, `shutdown_shared_executor()` 추가. `run()` 내 `with` 블록 제거. `stop()`에서 shutdown 제거. |
| `src/main_app.py` | `on_close_event()`에서 `shutdown_shared_executor()` 호출 추가 |

### 주의사항

- 워커 프로세스가 크래시하면 `BrokenProcessPool` 예외 발생 → `run()`에서 catch 후 풀 재생성
- `self.max_workers` 값이 변경되면 풀 재생성 (UI에서 워커 수 조정 시)
- 풀이 아직 이전 작업 처리 중일 때 새 검색 시작 시: `stop()`이 `is_running=False`로 이전 future 결과를 무시하므로 안전

---

## 작업 5: 결과 스트리밍 배치 표시

### 현재 문제

`search_worker.py:205-211` — 파일 하나의 모든 결과를 모아서 한번에 emit한다.

```python
# 현재 코드 (search_worker.py:205)
results, error_msgs = future.result()
for result in results:
    ...
    self.result_found.emit(file_path, sheet_name, row_idx, col_idx, value, header_data, row_data)
```

이 자체는 파일 단위로 스트리밍하고 있지만, **UI 측**에서 `add_result()`가 매 결과마다 호출되면서 QTreeWidget에 개별 삽입된다. 결과가 수천 건이면 매번 UI 갱신이 발생하여 심각한 지연이 발생한다.

### 구현 방안

#### Step 1: UI 업데이트 일시 중지/재개 메커니즘

QTreeWidget의 `setUpdatesEnabled(False)`를 사용하여 배치 삽입 시 repaint를 억제한다.

```python
# main_app.py — start_search()에 추가
self._result_buffer = []
self._result_batch_size = 100
self._batch_timer = QTimer()
self._batch_timer.setInterval(50)  # 50ms마다 배치 flush
self._batch_timer.timeout.connect(self._flush_result_buffer)
self._batch_timer.start()
```

#### Step 2: add_result()를 버퍼링으로 변경

기존 `add_result()` 시그널 연결을 버퍼 누적으로 변경한다.

```python
def _buffer_result(self, file_path, sheet_name, row, col, value, header_data, row_data):
    """결과를 버퍼에 누적"""
    self._result_buffer.append((file_path, sheet_name, row, col, value, header_data, row_data))
    # 버퍼가 배치 크기에 도달하면 즉시 flush
    if len(self._result_buffer) >= self._result_batch_size:
        self._flush_result_buffer()

def _flush_result_buffer(self):
    """버퍼에 쌓인 결과를 한 번에 트리에 추가"""
    if not self._result_buffer:
        return

    buffer = self._result_buffer
    self._result_buffer = []

    # UI 업데이트 일시 중지
    self.result_tree.setUpdatesEnabled(False)
    try:
        for args in buffer:
            self.add_result(*args)
    finally:
        # UI 업데이트 재개 (한 번만 repaint)
        self.result_tree.setUpdatesEnabled(True)
```

#### Step 3: 시그널 연결 변경

```python
# 기존:
self.search_worker.result_found.connect(self.add_result)
# 변경:
self.search_worker.result_found.connect(self._buffer_result)
```

#### Step 4: 검색 완료 시 잔여 버퍼 flush

```python
def search_finished(self):
    # 남은 버퍼 flush
    self._flush_result_buffer()
    self._batch_timer.stop()
    # 기존 로직 계속...
```

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/main_app.py` | `_buffer_result()`, `_flush_result_buffer()` 추가. `start_search()`에서 타이머 초기화. 시그널 연결을 `_buffer_result`로 변경. `search_finished()`에서 잔여 flush. |

### 주의사항

- `setUpdatesEnabled(False)` 중에는 스크롤이나 클릭이 일시적으로 무반응 → 50ms 간격이면 체감되지 않음
- 배치 크기(100)와 타이머 간격(50ms)은 성능 테스트 후 조정 가능
- 검색 중지(`stop()`) 시에도 `_batch_timer.stop()` + 잔여 flush 필요

---

## 작업 6: Lazy Import

### 현재 문제

앱 시작 시 **모든 모듈이 순차적으로 import**된다:

1. `main.py:16` — `import config` → **pandas를 즉시 로드** (`config.py:3`: `import pandas as pd`)
2. `main.py:24` — `from PyQt5.QtWidgets import QApplication` → PyQt5 전체 로드
3. `main.py:53` — `from main_app import ExcelSearchApp` → 나머지 모든 모듈 연쇄 로드
4. `main_app.py:4` — `import pandas as pd` → 이미 로드됨이지만 import 시점에 확인
5. `main_app.py:13-14` — `import multiprocessing, subprocess` → 시작 시 불필요

특히 **pandas**는 import에 약 1~2초가 걸리며, `config.py`에서 앱 시작 즉시 로드된다.

### 구현 방안

#### Step 1: config.py에서 pandas 지연 로드

`config.py`에서 `import pandas`를 제거하고 설정을 함수로 감싼다.

```python
# config.py — 변경 후
import warnings
import logging

# 모든 경고 메시지 억제 설정
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.CRITICAL)

def configure_pandas():
    """pandas import 후 설정 적용 — 첫 검색 시 호출"""
    import pandas as pd
    pd.options.mode.chained_assignment = None
    pd.options.mode.use_inf_as_na = True

class NullWriter:
    def write(self, s):
        pass
    def flush(self):
        pass
```

#### Step 2: pandas 설정 호출 시점 이동

`main_app.py`의 `_initialize_step_by_step()`에서 pandas 설정을 로딩 단계에 배치한다.

```python
# main_app.py — _initialize_step_by_step()의 경고 처리 단계
# 3단계: 경고 메시지 설정
if self.loading_dialog:
    self.loading_dialog.update_progress(88, "경고 처리 설정 중...", "pandas 및 라이브러리 설정")
from config import configure_pandas
configure_pandas()
```

#### Step 3: main_app.py 상단 import 정리

`import pandas as pd`를 상단에서 제거하고, 실제 사용하는 곳에서만 import한다.

```python
# main_app.py 상단
# 삭제: import pandas as pd
# 삭제: import multiprocessing as mp  (사용처 없으면)
# 삭제: import subprocess  (사용처에서 lazy import)
```

실제 pandas를 사용하는 메서드들 (`main_app.py` 내에서 `pd.` 를 사용하는 곳)에 로컬 import 추가:

```python
def some_method_using_pandas(self):
    import pandas as pd
    # ...
```

#### Step 4: multiprocessing freeze_support 최적화

```python
# main.py — multiprocessing import를 함수 내부로 이동
def initialize_application():
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # Windows 멀티프로세싱 설정 — 함수 내부에서만 import
    import multiprocessing as mp
    mp.freeze_support()
    # ...
```

이 부분은 현재 코드에서 이미 함수 내부에 있으므로 변경 불필요.

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/config.py` | `import pandas` 제거. `configure_pandas()` 함수로 분리 |
| `src/main_app.py` | 상단 `import pandas as pd` 제거. 사용처에 로컬 import. `_initialize_step_by_step()`에서 `configure_pandas()` 호출 |
| `main.py` | 변경 없음 (이미 함수 내부 import) |

### 주의사항

- `main_app.py`에서 `pd.`를 사용하는 모든 위치를 grep으로 찾아서 로컬 import로 교체해야 함
- pandas가 처음 import될 때 약간의 지연이 발생 → 로딩 화면 단계에서 미리 import하여 사용자에게 보여줌
- `config.py`를 import하는 다른 파일(`file_processor.py` 등)에는 영향 없음 (worker 프로세스에서 pandas는 별도로 import됨)

### 효과 측정

```python
# 시작 시간 비교 (main.py에서 측정)
import time
t0 = time.time()
# ... initialization ...
print(f"Startup: {time.time() - t0:.2f}s")
```

pandas import가 앱 시작 크리티컬 패스에서 빠지면 **체감 시작 시간 30~50% 단축**.

---

## 작업 7: str() 중복 변환 제거

### 현재 문제

동일한 값에 대해 `str()` 변환이 여러 지점에서 반복된다:

1. **검색 시** (`file_processor.py:232-234`) — 벡터화 검색에서 `df.astype(str)` 수행 후, 결과 생성 시 다시 `str(value).strip()`
2. **결과 저장 시** (`file_processor.py:234`) — `row_data = [str(v) ... for v in df_filtered.loc[row_idx]]`
3. **UI 표시 시** (`main_app.py:1754`) — `str_value = str(value)` 재변환

또한 `header_data`가 동일 시트의 모든 결과에 대해 **매번 동일한 리스트를 새로 생성**한다.

```python
# 현재: 매 결과마다 header_data를 새로 생성 (이미 작업1에서 루프 밖으로 이동 완료)
header_data = [str(h) if h is not None else "" for h in header_row]
```

작업 1에서 `header_data`는 이미 시트별로 한 번만 생성하도록 수정됨. 추가 개선 여지:

### 구현 방안

#### Step 1: 결과 생성 시 str() 재변환 제거

벡터화 검색 함수 `_vectorized_search()`는 이미 내부에서 `df.astype(str).str.strip()` 처리된 문자열 DataFrame을 생성한다. 이 **문자열 DataFrame을 반환**하여 결과 생성 시 재변환을 제거한다.

```python
def _vectorized_search(df, search_text, exact_match, case_sensitive, excluded_col_set):
    """반환: (matches, df_str_full)
    - matches: [(row_idx, col_idx), ...]
    - df_str_full: 전체 DataFrame의 str 변환 결과 (결과 생성 시 재사용)
    """
    # ... 기존 로직 ...
    
    # 전체 DataFrame의 str 버전도 함께 생성 (결과 추출용)
    df_str_full = df.astype(str)
    for col in df_str_full.columns:
        df_str_full[col] = df_str_full[col].str.strip()
    
    # 검색은 excluded_col 제외한 subset에서만 수행
    # ... 기존 매칭 로직 ...
    
    return matches, df_str_full
```

#### Step 2: 결과 생성 루프에서 df_str_full 재사용

```python
# process_file() 내:
matches, df_str = _vectorized_search(
    df_filtered, search_text, exact_match, case_sensitive, excluded_col_set
)

header_data = [str(h) if h is not None else "" for h in header_row]
for row_idx, col_idx in matches:
    try:
        # str() 재변환 없이 이미 변환된 값 사용
        str_value = df_str.iat[
            df_str.index.get_loc(row_idx), col_idx
        ]
        row_data = df_str.loc[row_idx].tolist()
        results.append((file_path, sheet_name, row_idx, col_idx,
                        str_value, header_data, row_data))
    except (KeyError, IndexError):
        continue
```

#### Step 3: UI 측 불필요한 str() 제거

`main_app.py`의 `add_result()`에서 이미 문자열인 `value`에 대해 `str(value)` 재변환을 제거한다.

```python
# main_app.py — add_result() 내
# 기존:
str_value = str(value)
# 변경:
str_value = value  # file_processor에서 이미 str 변환 완료
```

#### Step 4: highlight_keyword_in_text()에서 re.compile 캐싱

`main_app.py:1680-1689` — 매 결과마다 `re.escape()` + `re.sub()`이 호출된다.

```python
# 변경: 검색 시작 시 패턴 한 번만 컴파일
def start_search(self):
    # ... 기존 코드 ...
    self._highlight_pattern = re.compile(
        f'({re.escape(search_text)})', flags=re.IGNORECASE
    )

def highlight_keyword_in_text(self, text, keyword):
    if not keyword or not text:
        return text
    if hasattr(self, '_highlight_pattern'):
        return self._highlight_pattern.sub(
            r'<span style="background-color: yellow;">\1</span>', text
        )
    return text
```

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/file_processor.py` | `_vectorized_search()` 반환값에 `df_str_full` 추가. 결과 생성 시 재변환 제거 |
| `src/main_app.py` | `add_result()` 내 `str(value)` 제거. `highlight_keyword_in_text()`에 `re.compile` 캐싱 |

### 주의사항

- `df_str_full`은 추가 메모리 사용 → 시트 하나 처리 후 GC 대상이므로 큰 문제 없음
- `row_data = df_str.loc[row_idx].tolist()`가 원본과 동일한 형태인지 확인 필요 (None 값 처리 차이)
- None 값은 `astype(str)`에 의해 `"None"`으로 변환됨 → 기존 코드에서도 `str(None)` = `"None"`이므로 동일

---

## 작업 8: QTreeView 가상화 (Virtual Scrolling)

### 현재 문제

`QTreeWidget`은 모든 아이템을 메모리에 생성하고 보유한다.

```python
# 현재: QTreeWidget (모든 노드 메모리 상주)
self.result_tree = QTreeWidget()
```

검색 결과가 10,000건 이상이면:
- `QTreeWidgetItem` 10,000개 + 파일/시트 노드 수백 개 생성
- 각 아이템에 `setText()`, `setData()`, `setIcon()` 호출 → 대량 메모리 + 시간 소모
- 스크롤 시 모든 아이템이 paint 대상에 포함될 수 있음

### 구현 방안

`QTreeWidget` → `QTreeView` + 커스텀 `QAbstractItemModel`로 전환한다. 이 모델은 **보이는 행만 렌더링**하는 가상 스크롤을 자동으로 제공한다.

#### Step 1: ResultTreeModel 클래스 작성 (신규 파일)

`src/result_model.py` — 트리 구조 데이터 모델

```python
# src/result_model.py
from PyQt5.QtCore import QAbstractItemModel, QModelIndex, Qt
from PyQt5.QtGui import QIcon

class ResultNode:
    """트리 노드 데이터 컨테이너"""
    __slots__ = ('parent', 'children', 'data', 'row')
    
    def __init__(self, data: dict, parent=None):
        self.parent = parent
        self.children = []
        self.data = data  # {'type': 'file'|'sheet'|'result', ...}
        self.row = 0
    
    def append_child(self, child):
        child.row = len(self.children)
        child.parent = self
        self.children.append(child)
        return child


class ResultTreeModel(QAbstractItemModel):
    """검색 결과 트리 모델 — 가상 스크롤 지원"""
    
    COLUMNS = ['Name', 'Number', 'Type']
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = ResultNode({'type': 'root'})
        self._file_cache = {}    # {file_path: ResultNode}
        self._sheet_cache = {}   # {(file_path, sheet_name): ResultNode}
    
    # ── QAbstractItemModel 필수 구현 ──────────────────────────────
    
    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else self._root
        if row < len(parent_node.children):
            return self.createIndex(row, column, parent_node.children[row])
        return QModelIndex()
    
    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        parent_node = node.parent
        if parent_node is None or parent_node is self._root:
            return QModelIndex()
        return self.createIndex(parent_node.row, 0, parent_node)
    
    def rowCount(self, parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self._root
        return len(node.children)
    
    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)
    
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        col = index.column()
        
        if role == Qt.DisplayRole:
            return node.data.get(f'col_{col}', '')
        elif role == Qt.UserRole:
            return node.data
        elif role == Qt.TextAlignmentRole and col == 1:
            return Qt.AlignCenter
        return None
    
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None
    
    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable
    
    # ── 데이터 조작 API ──────────────────────────────────────────
    
    def clear(self):
        """모든 결과 초기화"""
        self.beginResetModel()
        self._root.children.clear()
        self._file_cache.clear()
        self._sheet_cache.clear()
        self.endResetModel()
    
    def add_result(self, file_path, sheet_name, row, col, value,
                   header_data, row_data, file_ext, show_intermediate,
                   col_header, display_number, display_type, highlighted_text=None):
        """검색 결과 추가 — O(1) 노드 조회"""
        
        # ── 파일 노드 ──
        file_node = self._file_cache.get(file_path)
        if file_node is None:
            import os
            file_name = os.path.basename(file_path)
            file_node = ResultNode({
                'type': 'file', 'file_path': file_path,
                'col_0': file_name, 'col_1': '', 'col_2': ''
            })
            parent = self._root
            pos = len(parent.children)
            self.beginInsertRows(QModelIndex(), pos, pos)
            parent.append_child(file_node)
            self.endInsertRows()
            self._file_cache[file_path] = file_node
        
        # ── 시트 노드 (조건부) ──
        if show_intermediate:
            cache_key = (file_path, sheet_name)
            sheet_node = self._sheet_cache.get(cache_key)
            if sheet_node is None:
                sheet_node = ResultNode({
                    'type': 'sheet', 'sheet_name': sheet_name,
                    'col_0': sheet_name, 'col_1': '', 'col_2': ''
                })
                parent_index = self.createIndex(file_node.row, 0, file_node)
                pos = len(file_node.children)
                self.beginInsertRows(parent_index, pos, pos)
                file_node.append_child(sheet_node)
                self.endInsertRows()
                self._sheet_cache[cache_key] = sheet_node
            result_parent = sheet_node
        else:
            result_parent = file_node
        
        # ── 결과 노드 ──
        result_node = ResultNode({
            'type': 'result',
            'file_path': file_path,
            'sheet_name': sheet_name,
            'row': row,
            'col_header': col_header,
            'col_0': highlighted_text or str(value),
            'col_1': display_number,
            'col_2': display_type,
            'original_text': str(value),
        })
        
        if result_parent is file_node:
            parent_index = self.createIndex(file_node.row, 0, file_node)
        else:
            parent_index = self.createIndex(result_parent.row, 0, result_parent)
        pos = len(result_parent.children)
        self.beginInsertRows(parent_index, pos, pos)
        result_parent.append_child(result_node)
        self.endInsertRows()
    
    def get_total_result_count(self):
        """전체 결과(leaf) 노드 수 반환"""
        count = 0
        for file_node in self._root.children:
            for child in file_node.children:
                if child.data.get('type') == 'sheet':
                    count += len(child.children)
                elif child.data.get('type') == 'result':
                    count += 1
        return count
```

#### Step 2: main_app.py에서 QTreeWidget → QTreeView 교체

```python
# init_ui() 내:
from result_model import ResultTreeModel

self.result_model = ResultTreeModel(self)
self.result_tree = QTreeView()
self.result_tree.setModel(self.result_model)
self.result_tree.setHeaderHidden(False)
self.result_tree.setRootIsDecorated(True)
self.result_tree.setUniformRowHeights(True)  # 성능 핵심: 모든 행 높이 동일
self.result_tree.setAnimated(False)  # 애니메이션 비활성화 (성능)
self.result_tree.setItemDelegate(ResultTreeDelegate(self.result_tree))
```

#### Step 3: add_result() 수정

기존 `QTreeWidgetItem` 직접 생성 → `ResultTreeModel.add_result()` 호출로 변경.

```python
def add_result(self, file_path, sheet_name, row, col, value, header_data, row_data):
    # ... col_header, display_number, display_type 계산 로직은 기존과 동일 ...
    
    self.result_model.add_result(
        file_path, sheet_name, row, col, value,
        header_data, row_data, file_ext, show_intermediate,
        col_header, display_number, display_type, highlighted_text
    )
    
    # 행 데이터 캐시
    if header_data is not None and row_data is not None:
        self.cached_row_data[(file_path, sheet_name, row)] = (header_data, row_data)
```

#### Step 4: search_finished()에서 결과 카운트 변경

```python
def search_finished(self):
    # ...
    result_count = self.result_model.get_total_result_count()
    QMessageBox.information(self, '검색 완료', f'총 {result_count}개의 결과를 찾았습니다.')
```

#### Step 5: ResultTreeDelegate 수정

`QTreeView`용 delegate는 `QTreeWidgetItem` 대신 `QModelIndex`에서 데이터를 읽도록 수정해야 한다.

```python
class ResultTreeDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        node_data = index.data(Qt.UserRole)
        if node_data is None:
            super().paint(painter, option, index)
            return
        # ... 기존 렌더링 로직을 index 기반으로 변환 ...
```

#### Step 6: show_sheet_data() 수정

`QTreeWidgetItem.data()` → `QModelIndex.data()` 접근으로 변경.

```python
def show_sheet_data(self, index):
    """선택한 결과 노드의 행 데이터를 새 창에 표시"""
    if not index.isValid():
        return
    node_data = index.data(Qt.UserRole)
    # ...
```

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/result_model.py` | **신규** — `ResultNode`, `ResultTreeModel` 클래스 |
| `src/main_app.py` | `QTreeWidget` → `QTreeView` + `ResultTreeModel`. `add_result()`, `search_finished()`, `show_sheet_data()`, `init_ui()` 수정. `ResultTreeDelegate` 수정 |

### 주의사항

- **가장 큰 변경**: UI 전반에 걸쳐 `QTreeWidgetItem` API → `QModelIndex` API로 변환 필요
- `result_tree.clear()` → `result_model.clear()`로 변경
- `result_tree.topLevelItemCount()` → `result_model.rowCount()` 등 모든 접근자 변경
- `setUniformRowHeights(True)`가 성능의 핵심 — 이게 없으면 모든 행의 높이를 개별 계산
- `ResultTreeDelegate`의 구분선 로직(`_is_separator_row`)은 `index.parent().isValid()`로 동일하게 동작
- 단계적 전환 권장: 먼저 4~7번 완료 후 8번 진행 (8번은 대규모 리팩토링)

---

## 구현 순서 및 의존성

```
작업 4 (Executor 재사용) ──────┐
                               ├── 독립 (병렬 가능)
작업 6 (Lazy import)  ─────────┘

        ↓

작업 7 (str() 중복 제거)       ← file_processor.py 작업 1 기반 수정

        ↓

작업 5 (배치 표시)             ← main_app.py의 add_result() 연결 변경

        ↓

작업 8 (QTreeView 가상화)      ← 가장 큰 변경, 마지막에 수행
```

### 권장 우선순위

| 순서 | 작업 | 이유 |
|------|------|------|
| 1 | 4 + 6 (병렬) | 독립적이며 리스크 낮음. 체감 효과 즉시 확인 가능 |
| 2 | 7 | 작업 1의 벡터화 검색 위에 추가 최적화 |
| 3 | 5 | UI 응답성 개선. add_result() 시그널 연결만 변경 |
| 4 | 8 | 대규모 리팩토링. 결과 만 건 이상일 때만 체감 |
