# 검색 준비 단계 성능 개선 계획

## 현황 분석

검색 버튼을 누른 후 실제 파일 처리가 시작되기까지 다음 단계들이 순차적으로 실행된다.

```
[검색 버튼 클릭]
    │
    ├── (메인 스레드) collect_excel_files() → os.walk() 동기 실행
    │
    ├── (QThread 시작)
    │       ├── get_excel_processes() → psutil.process_iter() 전체 프로세스 스캔
    │       ├── apply_file_and_path_filters() → os.path.split() 반복
    │       ├── get_shared_executor() → 첫 검색 시 ProcessPoolExecutor 신규 생성
    │       └── executor.submit() × N → 태스크 튜플 피클링 + 큐 전송
    │
    └── (자식 프로세스 첫 실행)
            ├── 모듈 임포트 (Windows: 공유 메모리 없음)
            ├── registry.discover() → plugins/ 디렉터리 glob + importlib 동적 로딩
            ├── get_file_cache() → file_cache.json 디스크 로드 + is_valid() × N
            └── get_df_cache() 초기화
```

### 병목 요약

| # | 위치 | 원인 | 스레드 | 예상 지연 |
|---|------|------|--------|-----------|
| A | `main_app.py:1754` | `os.walk()` 메인 스레드 동기 실행 | 메인(UI 블로킹) | 파일 수에 비례 |
| B | `search_worker.py:181` | `psutil.process_iter()` 전체 OS 프로세스 순회 | QThread | 100~500ms |
| C | `search_worker.py:18~21` | 첫 검색 시 `ProcessPoolExecutor` 신규 생성 + 워커 스폰 | QThread | 200~800ms |
| D | `search_worker.py:190` | 매 파일마다 필터 리스트 포함 태스크 튜플 피클링 | QThread | 파일 수에 비례 |
| E | `file_processor.py:154~156` | 자식 프로세스 최초 실행 시 플러그인 디스커버리 | 자식 프로세스 | 300ms~1s (워커 수만큼) |
| F | `file_cache.py:144~151` | 캐시 로드 시 모든 항목에 `is_valid()` (= `os.stat()` × N) 호출 | 자식 프로세스 | 파일 캐시 항목 수에 비례 |

---

## 개선 계획

### Step 1. `collect_excel_files()` 를 백그라운드 스레드로 이동

**대상 파일:** `src/main_app.py:1693-1695`, `1748-1766`

**문제:**  
`start_search()` 내에서 `collect_excel_files()` 가 메인 스레드에서 동기적으로 호출된다.  
대용량 폴더 구조를 탐색할 때 `os.walk()` 가 UI를 블로킹하여 애플리케이션이 멈춘 것처럼 보인다.

**개선 방법:**
1. `QThread` 또는 `QRunnable` 기반의 `FileCollectorWorker` 클래스 생성
2. `collect_excel_files()` 로직을 해당 워커로 이동
3. 수집 완료 시그널 발생 → 수집된 파일 목록을 받아 `ParallelSearchWorker` 시작
4. 수집 중에는 상태 바에 "파일 목록 수집 중..." 표시

**기대 효과:** UI 블로킹 제거, 사용자에게 즉각적인 반응 제공

---

### Step 2. 앱 시작 시 `ProcessPoolExecutor` 워커 프리워밍

**대상 파일:** `src/search_worker.py:15-22`, `src/main_app.py` (앱 초기화 구간)

**문제:**  
`get_shared_executor()` 는 풀을 재사용하지만 Windows 에서는 첫 `submit()` 호출 시까지  
실제 자식 프로세스가 스폰되지 않는다. 첫 번째 검색 시에만 발생하는 지연이다.

**개선 방법:**
1. `LoadingDialog` 가 닫힌 직후(앱 초기화 완료 시점)에 `get_shared_executor()` 를 호출하여 풀 사전 생성
2. no-op 태스크(`lambda: None` 또는 전용 `_warmup()` 함수)를 워커 수만큼 제출하여 모든 자식 프로세스를 즉시 스폰
3. 워밍업은 백그라운드에서 진행하며 완료를 기다리지 않음

**기대 효과:** 첫 번째 검색의 ProcessPool 생성 비용(200~800ms) 제거

---

### Step 3. 자식 프로세스 초기화 시 플러그인 디스커버리 사전 실행

**대상 파일:** `src/file_processor.py:153-156`, `src/search_worker.py:20`

**문제:**  
자식 프로세스에서 `process_file()` 이 처음 호출될 때 `registry.discover()` 가 실행된다.  
플러그인 파일을 glob + `importlib` 로 동적 로딩하는 작업이 워커 수만큼 중복 발생한다.

**개선 방법:**
1. `ProcessPoolExecutor` 생성 시 `initializer` 인자로 초기화 함수 지정

   ```python
   def _worker_initializer():
       from plugin_registry import get_plugin_registry
       from file_cache import get_file_cache, get_df_cache
       registry = get_plugin_registry()
       registry.discover()
       get_file_cache()
       get_df_cache()

   ProcessPoolExecutor(max_workers=n, initializer=_worker_initializer)
   ```

2. `process_file()` 내의 `registry.discover()` 조건 분기 제거

**기대 효과:**  
- 플러그인 디스커버리가 프로세스당 1회로 제한 (이전: 태스크 첫 실행마다)
- `FileCache` JSON 로드도 프로세스 초기화 시 1회만 실행

---

### Step 4. `psutil.process_iter()` 호출 최적화

**대상 파일:** `src/search_worker.py:64-73`, `178-181`

**문제:**  
`run()` 시작 시 `self.get_excel_processes()` 를 호출하여 OS 전체 프로세스 목록을 순회한다.  
시스템에 실행 중인 프로세스가 많을수록 시간이 길어지며, Excel 을 사용하지 않는 경우에도 매번 실행된다.

**개선 방법:**

옵션 A (권장 — 조건부 실행):  
Excel 관련 기능(파일 잠금 처리)이 실제로 필요한 경우에만 실행.  
Excel `.xls*` 파일이 검색 대상에 포함된 경우에만 `get_excel_processes()` 호출.

```python
has_excel_files = any(f.lower().endswith(('.xls', '.xlsx', '.xlsm')) for f in filtered_files)
if has_excel_files:
    self.initial_excel_processes = self.get_excel_processes()
```

옵션 B (보조 — 캐싱):  
이전 스캔 결과를 5초간 캐싱하여 연속 검색 시 재사용.

**기대 효과:** Excel 파일이 없는 검색에서 100~500ms 단축

---

### Step 5. 태스크 피클링 크기 축소

**대상 파일:** `src/search_worker.py:190`, `src/file_processor.py:138-139`

**문제:**  
매 파일마다 생성되는 태스크 튜플에 `excluded_headers`, `excluded_if_not_empty`, `excluded_paths`,  
`excluded_files`, `excluded_sheets` 5개 리스트가 반복 포함된다.  
이 데이터는 검색 전체에 걸쳐 동일하므로 파일 수만큼 중복 직렬화된다.

**개선 방법:**  
Step 3 의 `initializer` 를 활용하여 공유 필터 설정을 프로세스 전역 변수로 주입.

```python
def _worker_initializer(filter_config: dict):
    global _FILTER_CONFIG
    _FILTER_CONFIG = filter_config
    # 플러그인·캐시 초기화 ...

# 태스크 튜플을 (file_path, search_text, exact_match, case_sensitive) 만으로 축소
tasks = [(fp, search_text, exact_match, case_sensitive) for fp in filtered_files]
```

**기대 효과:**  
태스크 튜플 크기 감소 → 피클링 시간 단축 (파일 100개 기준 약 30~50% 직렬화 비용 절감)

---

### Step 6. `FileCache.load_cache()` 지연 유효성 검사

**대상 파일:** `src/file_cache.py:137-154`

**문제:**  
`load_cache()` 가 캐시 JSON 을 로드할 때 모든 항목에 대해 `is_valid()` 를 즉시 호출한다.  
`is_valid()` 는 `os.path.getsize()` + `os.path.getmtime()` 을 실행하므로 캐시 항목이 많을수록 I/O 가 증가한다.

**개선 방법:**
1. `load_cache()` 에서 유효성 검사를 제거하고 일단 모든 항목을 메모리에 로드
2. `get_metadata()` 에서 첫 조회 시점에 `is_valid()` 호출 (현재 동작과 동일)
3. 앱 종료 시 또는 주기적 백그라운드 스레드에서 `clear_invalid_cache()` 실행

```python
def load_cache(self):
    # is_valid() 체크 없이 모든 항목 로드 (지연 검증)
    for cache_key, metadata_dict in data.items():
        try:
            self._cache[cache_key] = FileMetadata(**metadata_dict)
        except Exception:
            continue
```

**기대 효과:** 캐시 항목 1,000개 기준 로드 시간 약 50~70% 단축

---

## 구현 우선순위

| 우선순위 | Step | 난이도 | 예상 효과 | 사이드 이펙트 위험 |
|----------|------|--------|-----------|-------------------|
| 1 | Step 2 — ProcessPool 프리워밍 | 낮음 | 첫 검색 체감 개선 최대 | 낮음 |
| 2 | Step 3 — Worker initializer | 중간 | 자식 프로세스 초기화 비용 제거 | 중간 (프로세스 재시작 시 재초기화 필요) |
| 3 | Step 1 — 파일 수집 비동기화 | 중간 | UI 블로킹 완전 제거 | 중간 (검색 흐름 리팩터링 필요) |
| 4 | Step 4 — psutil 조건부 실행 | 낮음 | 빠른 개선 | 낮음 |
| 5 | Step 5 — 태스크 피클링 축소 | 중간 | 파일 많을수록 효과 증가 | 중간 (Step 3 선행 필요) |
| 6 | Step 6 — 캐시 지연 검증 | 낮음 | 반복 검색 초기화 단축 | 낮음 |

---

## 참고: 단계별 적용 후 예상 타임라인

```
현재:
[클릭] ──300ms UI 블로킹── [QThread 시작] ──700ms 준비── [파일 처리 시작]

Step 1+2+3 적용 후:
[클릭] ──즉시 반응── [백그라운드 수집] ──100ms 준비── [파일 처리 시작]
         (이미 워커 대기 중)
```

총 준비 시간 예상 단축: **약 70~85%** (환경에 따라 다름)
