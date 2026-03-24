"""애플리케이션 설정 관리 모듈"""
import os
import json
import multiprocessing as mp
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from pathlib import Path

from constants import DEFAULT_WORKER_COUNT


@dataclass
class AppSettings:
    """애플리케이션 설정을 관리하는 데이터 클래스"""
    
    # 기본 설정
    last_directory: str = ""
    search_mode_exact: bool = True
    worker_count: int = field(default_factory=lambda: min(DEFAULT_WORKER_COUNT, mp.cpu_count()))
    
    # 검색 예외 처리 설정
    excluded_headers: List[str] = field(default_factory=list)
    excluded_if_not_empty: List[str] = field(default_factory=list)
    apply_exception: bool = True
    
    # UI 설정
    expanded_paths: List[str] = field(default_factory=list)
    window_geometry: Optional[str] = None
    splitter_state: Optional[str] = None

    # 플러그인 설정 (빈 리스트 = 모든 플러그인 활성화)
    enabled_plugins: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """초기화 후 유효성 검사"""
        self.worker_count = max(1, min(self.worker_count, mp.cpu_count()))


class SettingsManager:
    """설정 파일 관리 클래스"""
    
    def __init__(self, settings_dir: str = None):
        if settings_dir is None:
            # 기본 설정 디렉토리: 프로젝트 루트/config
            project_root = Path(__file__).parent.parent
            settings_dir = project_root / "config"
        
        self.settings_dir = Path(settings_dir)
        self.settings_dir.mkdir(exist_ok=True)
        
        # 새로운 JSON 설정 파일
        self.json_settings_file = self.settings_dir / "app_settings.json"
        # 기존 텍스트 설정 파일 (마이그레이션용)
        self.legacy_settings_file = self.settings_dir / "excel_finder_settings.txt"
        
    def load_settings(self) -> AppSettings:
        """설정 로드 (JSON -> 레거시 순서로 시도)"""
        # 1. JSON 파일에서 로드 시도
        if self.json_settings_file.exists():
            try:
                with open(self.json_settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return AppSettings(**data)
            except Exception as e:
                print(f"JSON 설정 로드 실패: {e}")
        
        # 2. 레거시 텍스트 파일에서 로드 시도
        if self.legacy_settings_file.exists():
            try:
                settings = self._load_legacy_settings()
                # 로드 성공 시 JSON으로 저장
                self.save_settings(settings)
                return settings
            except Exception as e:
                print(f"레거시 설정 로드 실패: {e}")
        
        # 3. 기본 설정 반환
        return AppSettings()
    
    def save_settings(self, settings: AppSettings) -> None:
        """설정을 JSON 파일로 저장"""
        try:
            with open(self.json_settings_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(settings), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"설정 저장 실패: {e}")
    
    def _load_legacy_settings(self) -> AppSettings:
        """레거시 텍스트 설정 파일 로드"""
        settings = AppSettings()
        
        try:
            with open(self.legacy_settings_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # 각 설정값 파싱
                    if key == 'last_directory' and os.path.isdir(value):
                        settings.last_directory = value
                    elif key == 'search_mode_exact':
                        settings.search_mode_exact = value.lower() == 'true'
                    elif key == 'worker_count':
                        try:
                            count = int(value)
                            if 1 <= count <= mp.cpu_count():
                                settings.worker_count = count
                        except ValueError:
                            pass
                    elif key == 'excluded_headers':
                        settings.excluded_headers = value.split('|') if value else []
                    elif key == 'excluded_if_not_empty':
                        settings.excluded_if_not_empty = value.split('|') if value else []
                    elif key == 'apply_exception':
                        settings.apply_exception = value.lower() == 'true'
                    elif key == 'expanded_paths':
                        settings.expanded_paths = value.split('|') if value else []
        
        except Exception as e:
            print(f"레거시 설정 파일 읽기 오류: {e}")
        
        return settings
    
    def migrate_legacy_settings(self) -> bool:
        """레거시 설정을 새 형식으로 마이그레이션"""
        if not self.legacy_settings_file.exists():
            return False
        
        try:
            settings = self._load_legacy_settings()
            self.save_settings(settings)
            
            # 백업 생성 후 원본 삭제
            backup_file = self.legacy_settings_file.with_suffix('.txt.backup')
            self.legacy_settings_file.rename(backup_file)
            
            print(f"설정 마이그레이션 완료: {backup_file}")
            return True
        
        except Exception as e:
            print(f"설정 마이그레이션 실패: {e}")
            return False