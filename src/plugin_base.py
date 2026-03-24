"""플러그인 시스템 기반 클래스 모듈"""
import importlib.util
import pandas as pd
from abc import ABC, abstractmethod
from typing import List, Tuple, Generator, Optional


class PluginLoadError(Exception):
    """플러그인 로드 실패 예외"""
    pass


def _flatten_value(value) -> str:
    """값을 문자열로 변환"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " | ".join(str(v) for v in value)
    if isinstance(value, dict):
        return " | ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _flatten_dict(d: dict, prefix: str = "") -> dict:
    """중첩 딕셔너리를 평탄화"""
    result = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            result.update(_flatten_dict(value, full_key))
        else:
            result[full_key] = _flatten_value(value)
    return result


class FormatPlugin(ABC):
    """파일 형식 플러그인 기반 클래스 (ABC)"""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """고유 플러그인 ID (예: 'json', 'excel')"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """사용자에게 표시되는 이름 (예: 'JSON', 'Excel')"""
        ...

    @property
    def is_builtin(self) -> bool:
        """기본 내장 플러그인 여부"""
        return False

    @property
    def required_packages(self) -> List[str]:
        """필요한 패키지 목록"""
        return []

    @abstractmethod
    def supported_extensions(self) -> Tuple[str, ...]:
        """지원하는 파일 확장자 튜플 (소문자, 점 포함 예: ('.json',))"""
        ...

    @abstractmethod
    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        """파일을 읽어 (sheet_name, headers, dataframe) 튜플 목록 반환.

        DataFrame은 RangeIndex 컬럼(0, 1, 2...)을 사용.
        headers는 별도 List[str]로 제공.
        이는 기존 Excel 처리 방식과 동일한 계약을 유지함.
        """
        ...

    def supports_streaming(self, file_path: str) -> bool:
        """스트리밍 지원 여부"""
        return False

    def stream_file(self, file_path: str, chunk_size: int = 1000) -> Generator:
        """파일을 청크 단위로 스트리밍.
        기본 구현: read_file() 호출 후 청크 단위로 분할."""
        sections = self.read_file(file_path)
        for sheet_name, headers, df in sections:
            for i in range(0, max(1, len(df)), chunk_size):
                chunk = df.iloc[i:i + chunk_size]
                yield sheet_name, headers, chunk

    def get_metadata(self, file_path: str) -> dict:
        """파일 메타데이터 반환 (시트 이름 목록 등)"""
        try:
            sections = self.read_file(file_path)
            return {'sheet_names': [s[0] for s in sections]}
        except Exception:
            return {'sheet_names': []}

    def check_dependencies(self) -> Tuple[bool, List[str]]:
        """의존 패키지 설치 여부 확인 (side-effect 없는 importlib 사용).
        Returns: (all_ok, missing_packages)"""
        missing = []
        for pkg in self.required_packages:
            spec = importlib.util.find_spec(pkg)
            if spec is None:
                missing.append(pkg)
        return len(missing) == 0, missing
