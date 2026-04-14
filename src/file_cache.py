"""파일 메타데이터 캐싱 모듈"""
import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from threading import Lock

import pickle
import tempfile
from constants import MAX_CACHE_SIZE, LARGE_FILE_THRESHOLD, MAX_DF_CACHE_ENTRIES, DF_CACHE_DIR, DF_CACHE_MAX_FILE_SIZE


@dataclass
class FileMetadata:
    """파일 메타데이터"""
    file_path: str
    file_size: int
    last_modified: float
    sheet_names: List[str]
    cached_time: float
    file_hash: str
    plugin_id: str = ""  # 처리한 플러그인 ID (캐시 무효화용)
    
    def is_valid(self) -> bool:
        """캐시가 유효한지 확인"""
        try:
            if not os.path.exists(self.file_path):
                return False
                
            current_size = os.path.getsize(self.file_path)
            current_modified = os.path.getmtime(self.file_path)
            
            return (self.file_size == current_size and 
                   self.last_modified == current_modified)
        except OSError:
            return False
    
    def is_large_file(self) -> bool:
        """대용량 파일 여부 확인"""
        return self.file_size > LARGE_FILE_THRESHOLD


class FileCache:
    """파일 메타데이터 캐시 관리 클래스"""
    
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            project_root = Path(__file__).parent.parent
            cache_dir = project_root / "config" / "cache"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.cache_file = self.cache_dir / "file_cache.json"
        self._cache: Dict[str, FileMetadata] = {}
        self._lock = Lock()
        
        self.load_cache()
    
    def get_file_hash(self, file_path: str) -> str:
        """파일의 해시값 계산 (처음 1KB만 사용)"""
        try:
            with open(file_path, 'rb') as f:
                # 대용량 파일의 경우 처음 1KB만 읽어서 해시 계산
                chunk = f.read(1024)
                return hashlib.md5(chunk).hexdigest()
        except Exception:
            return ""
    
    def get_metadata(self, file_path: str) -> Optional[FileMetadata]:
        """파일 메타데이터 조회"""
        with self._lock:
            cache_key = os.path.normpath(file_path)
            
            if cache_key in self._cache:
                metadata = self._cache[cache_key]
                if metadata.is_valid():
                    return metadata
                else:
                    # 캐시가 무효하면 제거
                    del self._cache[cache_key]
            
            return None
    
    def set_metadata(self, file_path: str, sheet_names: List[str]) -> FileMetadata:
        """파일 메타데이터 캐시에 저장"""
        try:
            file_stats = os.stat(file_path)
            file_hash = self.get_file_hash(file_path)
            
            metadata = FileMetadata(
                file_path=file_path,
                file_size=file_stats.st_size,
                last_modified=file_stats.st_mtime,
                sheet_names=sheet_names,
                cached_time=datetime.now().timestamp(),
                file_hash=file_hash
            )
            
            with self._lock:
                cache_key = os.path.normpath(file_path)
                self._cache[cache_key] = metadata
                
                # 캐시 크기 제한
                if len(self._cache) > MAX_CACHE_SIZE:
                    self._cleanup_old_entries()
                
                # 주기적으로 캐시 저장
                if len(self._cache) % 10 == 0:
                    self._save_cache_async()
            
            return metadata
            
        except Exception as e:
            print(f"메타데이터 캐시 저장 실패 {file_path}: {e}")
            return None
    
    def _cleanup_old_entries(self):
        """오래된 캐시 항목 정리"""
        # 가장 오래된 항목부터 제거
        sorted_items = sorted(
            self._cache.items(), 
            key=lambda x: x[1].cached_time
        )
        
        # 최대 크기의 80%까지 줄임
        target_size = int(MAX_CACHE_SIZE * 0.8)
        items_to_remove = len(sorted_items) - target_size
        
        for i in range(items_to_remove):
            cache_key = sorted_items[i][0]
            del self._cache[cache_key]
    
    def load_cache(self):
        """캐시 파일에서 로드"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    for cache_key, metadata_dict in data.items():
                        try:
                            metadata = FileMetadata(**metadata_dict)
                            # 유효한 캐시만 로드
                            if metadata.is_valid():
                                self._cache[cache_key] = metadata
                        except Exception:
                            continue
                            
        except Exception as e:
            print(f"캐시 로드 실패: {e}")
    
    def save_cache(self):
        """캐시를 파일에 저장"""
        try:
            with self._lock:
                # 유효한 캐시만 저장
                valid_cache = {}
                for cache_key, metadata in self._cache.items():
                    if metadata.is_valid():
                        valid_cache[cache_key] = asdict(metadata)
                
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(valid_cache, f, indent=2)
                    
        except Exception as e:
            print(f"캐시 저장 실패: {e}")
    
    def _save_cache_async(self):
        """비동기로 캐시 저장"""
        import threading
        threading.Thread(target=self.save_cache, daemon=True).start()
    
    def clear_invalid_cache(self):
        """무효한 캐시 항목 정리"""
        with self._lock:
            invalid_keys = []
            for cache_key, metadata in self._cache.items():
                if not metadata.is_valid():
                    invalid_keys.append(cache_key)
            
            for key in invalid_keys:
                del self._cache[key]
    
    def get_cache_stats(self) -> Dict:
        """캐시 통계 정보"""
        with self._lock:
            total_files = len(self._cache)
            large_files = sum(1 for m in self._cache.values() if m.is_large_file())
            total_size = sum(m.file_size for m in self._cache.values())
            
            return {
                'total_files': total_files,
                'large_files': large_files,
                'total_cached_size': total_size,
                'cache_hit_potential': f"{(total_files / MAX_CACHE_SIZE * 100):.1f}%" if total_files > 0 else "0%"
            }


class DataFrameCache:
    """DataFrame 디스크 캐시 — pickle 형식으로 파싱된 DataFrame을 저장하여 재검색 시 로딩 속도 향상"""

    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            project_root = Path(__file__).parent.parent
            cache_dir = project_root / "config" / "cache" / DF_CACHE_DIR
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _cache_key(self, file_path: str) -> str:
        """파일 경로 기반 캐시 키 생성"""
        norm = os.path.normpath(file_path)
        return hashlib.md5(norm.encode()).hexdigest()

    def get(self, file_path: str):
        """캐시된 섹션 목록 반환. 없거나 만료되면 None.

        Returns:
            list of (sheet_name, headers, DataFrame) 또는 None
        """
        cache_path = self.cache_dir / f"{self._cache_key(file_path)}.pkl"
        if not cache_path.exists():
            return None
        try:
            mtime = os.path.getmtime(file_path)
            size = os.path.getsize(file_path)
            with open(cache_path, 'rb') as f:
                cached = pickle.load(f)
            if cached['mtime'] == mtime and cached['size'] == size:
                return cached['sections']
        except Exception:
            # 캐시 파일이 손상된 경우 삭제
            try:
                cache_path.unlink(missing_ok=True)
            except Exception:
                pass
        return None

    def set(self, file_path: str, sections):
        """섹션 목록을 캐시에 저장.

        대용량 파일(>50MB)은 캐시하지 않는다.
        임시 파일 → rename 패턴으로 멀티프로세스 안전성 확보.
        """
        try:
            file_size = os.path.getsize(file_path)
            if file_size > DF_CACHE_MAX_FILE_SIZE:
                return

            cache_path = self.cache_dir / f"{self._cache_key(file_path)}.pkl"
            data = {
                'mtime': os.path.getmtime(file_path),
                'size': file_size,
                'sections': sections,
            }

            # 임시 파일에 먼저 쓰고 rename (원자적 교체)
            fd, tmp_path = tempfile.mkstemp(dir=str(self.cache_dir), suffix='.tmp')
            try:
                with os.fdopen(fd, 'wb') as f:
                    pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
                # Windows에서는 대상이 존재하면 rename 실패하므로 먼저 제거
                if cache_path.exists():
                    cache_path.unlink()
                os.rename(tmp_path, str(cache_path))
            except Exception:
                # 실패 시 임시 파일 정리
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except Exception:
            pass

    def cleanup(self, max_entries: int = None):
        """오래된 캐시 파일 정리"""
        if max_entries is None:
            max_entries = MAX_DF_CACHE_ENTRIES
        try:
            files = sorted(self.cache_dir.glob("*.pkl"),
                           key=lambda p: p.stat().st_mtime)
            if len(files) > max_entries:
                for f in files[:len(files) - max_entries]:
                    f.unlink(missing_ok=True)
        except Exception:
            pass

    def clear(self):
        """전체 DataFrame 캐시 삭제"""
        import shutil
        try:
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


# 전역 캐시 인스턴스
_file_cache: Optional[FileCache] = None
_df_cache: Optional[DataFrameCache] = None

def get_file_cache() -> FileCache:
    """전역 파일 캐시 인스턴스 반환"""
    global _file_cache
    if _file_cache is None:
        _file_cache = FileCache()
    return _file_cache


def get_df_cache() -> DataFrameCache:
    """전역 DataFrame 캐시 인스턴스 반환"""
    global _df_cache
    if _df_cache is None:
        _df_cache = DataFrameCache()
    return _df_cache