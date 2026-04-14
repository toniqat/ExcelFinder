from PyQt5.QtCore import QThread, pyqtSignal
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed, BrokenExecutor
from typing import List, Tuple, Optional
import psutil
import os

from file_processor import process_file
from streaming_search import should_use_streaming, get_optimal_chunk_size

# ── 공유 ProcessPoolExecutor 관리 ──────────────────────────────
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
    global _shared_executor, _shared_executor_workers
    if _shared_executor is not None:
        _shared_executor.shutdown(wait=False)
        _shared_executor = None
        _shared_executor_workers = 0

class ParallelSearchWorker(QThread):
    """병렬 검색 작업을 백그라운드에서 실행하는 스레드"""
    result_found = pyqtSignal(str, str, int, int, str, object, object)  # 파일, 시트, 행, 열, 값, 헤더 데이터, 행 데이터
    progress_update = pyqtSignal(int)
    error_occurred = pyqtSignal(str, str)  # 파일, 오류 메시지
    search_completed = pyqtSignal()
    current_file_changed = pyqtSignal(str)  # 현재 처리 중인 파일 경로
    
    def __init__(self, files: List[str], search_text: str, exact_match: bool,
                 max_workers: Optional[int] = None, excluded_headers: Optional[List[str]] = None,
                 excluded_if_not_empty: Optional[List[str]] = None, case_sensitive: bool = False,
                 excluded_paths: Optional[List[str]] = None, excluded_files: Optional[List[str]] = None,
                 excluded_sheets: Optional[List[str]] = None):
        super().__init__()
        self.files = files
        self.search_text = search_text
        self.exact_match = exact_match
        self.case_sensitive = case_sensitive
        self.is_running = True
        # 기본값: CPU 코어 수의 반 (최소 2)
        self.max_workers = max_workers if max_workers else max(2, mp.cpu_count() // 2)
        self.excluded_headers = excluded_headers or []
        self.excluded_if_not_empty = excluded_if_not_empty or []
        self.excluded_paths = excluded_paths or []
        self.excluded_files = excluded_files or []
        self.excluded_sheets = excluded_sheets or []

        self.last_progress = 0
        self.executor = None
        self.started_processes = set()  # 시작된 프로세스 추적
        self.initial_excel_processes = set()  # 검색 시작 전 Excel 프로세스

    def get_excel_processes(self):
        """현재 실행 중인 Excel 프로세스 목록 반환"""
        excel_processes = set()
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and 'excel' in proc.info['name'].lower():
                    excel_processes.add(proc.info['pid'])
        except Exception:
            pass  # 프로세스 접근 오류 무시
        return excel_processes

    def kill_new_excel_processes(self):
        """검색 시작 후 생성된 Excel 프로세스만 종료"""
        try:
            current_excel_processes = self.get_excel_processes()
            new_processes = current_excel_processes - self.initial_excel_processes

            for pid in new_processes:
                try:
                    proc = psutil.Process(pid)
                    proc.terminate()
                    # 3초 후에도 종료되지 않으면 강제 종료
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass  # 프로세스가 이미 종료되었거나 접근 권한 없음
        except Exception as e:
            print(f"Excel 프로세스 정리 중 오류: {str(e)}")

    def apply_file_and_path_filters(self, files):
        """파일 및 경로 필터링 적용"""
        filtered_files = []

        for file_path in files:
            should_exclude = False

            # 경로 필터링 확인 - 경로 내의 각 폴더명을 개별적으로 확인
            for excluded_path_filter in self.excluded_paths:
                if self._should_exclude_by_path_filter(file_path, excluded_path_filter):
                    should_exclude = True
                    break

            # 파일 필터링 확인
            if not should_exclude:
                file_name = os.path.basename(file_path)
                for excluded_file_filter in self.excluded_files:
                    if self._should_exclude_by_filter(file_name, excluded_file_filter):
                        should_exclude = True
                        break

            if not should_exclude:
                filtered_files.append(file_path)

        return filtered_files

    def _should_exclude_by_filter(self, text, filter_string):
        """필터 문자열에 따라 텍스트를 제외해야 하는지 확인"""
        if not filter_string:
            return False

        # 필터 문자열 파싱: "keyword|match_type" 또는 "keyword|match_type|메모: memo"
        parts = filter_string.split('|')
        if len(parts) < 2:
            # 구형 형식이거나 잘못된 형식인 경우 부분 일치로 처리
            return parts[0] in text

        keyword = parts[0]
        match_type = parts[1]

        if match_type == 'exact':
            return keyword == text
        else:  # 'contains' 또는 기타
            return keyword in text

    def _should_exclude_by_path_filter(self, file_path, filter_string):
        """경로 필터 문자열에 따라 파일 경로의 폴더들을 확인하여 제외해야 하는지 판단"""
        if not filter_string:
            return False

        # 필터 문자열 파싱: "keyword|match_type" 또는 "keyword|match_type|메모: memo"
        parts = filter_string.split('|')
        if len(parts) < 2:
            # 구형 형식이거나 잘못된 형식인 경우 부분 일치로 처리
            keyword = parts[0]
            match_type = 'contains'
        else:
            keyword = parts[0]
            match_type = parts[1]

        # 파일 경로에서 폴더 부분만 추출 (파일명 제외)
        dir_path = os.path.dirname(file_path)

        # 경로를 개별 폴더명으로 분리
        path_parts = []
        while dir_path:
            dir_path, folder_name = os.path.split(dir_path)
            if folder_name:
                path_parts.append(folder_name)
            else:
                break

        # 각 폴더명에 대해 필터 조건 확인
        for folder_name in path_parts:
            if match_type == 'exact':
                if keyword == folder_name:
                    return True
            else:  # 'contains' 또는 기타
                if keyword in folder_name:
                    return True

        return False

    def run(self):
        try:
            # 검색 시작 전 Excel 프로세스 목록 저장
            self.initial_excel_processes = self.get_excel_processes()

            # 파일 및 경로 필터링 적용
            filtered_files = self.apply_file_and_path_filters(self.files)

            completed_files = 0
            total_files = len(filtered_files)

            # 작업 목록 생성 (검색 예외 처리 목록 포함)
            tasks = [(file_path, self.search_text, self.exact_match, self.excluded_headers, self.excluded_if_not_empty, self.case_sensitive, self.excluded_paths, self.excluded_files, self.excluded_sheets) for file_path in filtered_files]

            # 공유 executor 사용 (재생성 없음)
            try:
                executor = get_shared_executor(self.max_workers)
            except BrokenExecutor:
                # 이전 워커 크래시 시 풀 재생성
                shutdown_shared_executor()
                executor = get_shared_executor(self.max_workers)
            self.executor = executor

            # 모든 작업을 시작
            futures = {executor.submit(process_file, task): task for task in tasks}

            # 완료된 작업을 처리
            for future in as_completed(futures):
                if not self.is_running:
                    # 즉시 종료 - 대기 중인 작업 취소
                    for f in futures:
                        f.cancel()
                    break

                # 현재 처리 중인 파일 정보 업데이트
                current_task = futures[future]
                current_file_path = current_task[0]  # 첫 번째 요소가 파일 경로
                self.current_file_changed.emit(current_file_path)

                # 대용량 파일 처리 상태 확인
                if should_use_streaming(current_file_path):
                    # 대용량 파일에 대한 특별 처리 시간 추가 고려
                    pass

                try:
                    results, error_msgs = future.result()
                except BrokenExecutor:
                    # 워커 크래시 시 풀 재생성 후 계속
                    shutdown_shared_executor()
                    self.error_occurred.emit(current_file_path, "워커 프로세스 크래시 — 풀 재생성됨")
                    continue

                # 결과 처리
                for result in results:
                    if len(result) == 7:  # 새로운 형식 (header_data, row_data 포함)
                        file_path, sheet_name, row_idx, col_idx, value, header_data, row_data = result
                        self.result_found.emit(file_path, sheet_name, row_idx, col_idx, value, header_data, row_data)
                    else:  # 이전 형식 (header_data, row_data 없음)
                        file_path, sheet_name, row_idx, col_idx, value = result
                        self.result_found.emit(file_path, sheet_name, row_idx, col_idx, value, None, None)

                # 오류 처리
                for file_path, error_msg in error_msgs:
                    self.error_occurred.emit(file_path, error_msg)

                # 진행 상황 업데이트 (즉시 업데이트)
                completed_files += 1
                progress = int(completed_files / total_files * 100)
                self.progress_update.emit(progress)
            
        except Exception as e:
            self.error_occurred.emit("검색 오류", f"병렬 검색 중 예외 발생: {str(e)}")
        finally:
            # Excel 프로세스 정리 (검색 도중 생성된 것만)
            self.kill_new_excel_processes()
            self.executor = None
            self.search_completed.emit()

    def stop(self):
        """검색 중지"""
        self.is_running = False

        # 즉시 Excel 프로세스 정리
        self.kill_new_excel_processes()
        # executor는 shutdown하지 않음 — 다음 검색에서 재사용
