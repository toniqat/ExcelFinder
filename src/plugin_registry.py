"""플러그인 레지스트리 모듈 - 플러그인 탐색, 등록, 조회"""
import os
import sys
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from plugin_base import FormatPlugin, PluginLoadError


def _get_plugins_dir() -> Path:
    """플러그인 디렉토리 경로 반환 (PyInstaller 번들 호환)"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 번들: 실행 파일 옆 plugins/ 폴더
        base = Path(sys.executable).parent
    else:
        # 개발 환경: 프로젝트 루트 plugins/ 폴더
        base = Path(__file__).parent.parent
    return base / "plugins"


class PluginRegistry:
    """파일 형식 플러그인 레지스트리"""

    def __init__(self):
        self._ext_map: Dict[str, FormatPlugin] = {}  # ext -> plugin
        self._plugins: List[FormatPlugin] = []        # 등록된 플러그인 목록
        self._errors: Dict[str, str] = {}             # plugin_id -> 오류 메시지
        self._discovered = False

    def discover(self, plugins_dir: Path = None) -> None:
        """플러그인 디렉토리에서 플러그인 탐색 및 등록"""
        if self._discovered:
            return
        self._discovered = True

        if plugins_dir is None:
            plugins_dir = _get_plugins_dir()

        if not plugins_dir.exists():
            return

        # plugin_*.py 파일 탐색
        plugin_files = sorted(plugins_dir.glob("plugin_*.py"))

        for plugin_file in plugin_files:
            try:
                self._load_plugin_file(plugin_file)
            except Exception as e:
                plugin_id = plugin_file.stem
                self._errors[plugin_id] = str(e)

    def _load_plugin_file(self, plugin_file: Path) -> None:
        """단일 플러그인 파일 로드"""
        module_name = f"plugins.{plugin_file.stem}"

        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if spec is None:
            raise PluginLoadError(f"모듈 스펙 생성 실패: {plugin_file}")

        module = importlib.util.module_from_spec(spec)
        # Python 공식 권장 패턴: exec_module 전에 sys.modules에 등록해야
        # 재진입 import(플러그인이 자기 자신을 참조하는 경우)를 방지할 수 있음
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            # 로드 실패 시 sys.modules에서 제거
            sys.modules.pop(module_name, None)
            raise

        # 모듈에서 FormatPlugin 서브클래스 찾기
        found_class = False  # 클래스를 찾았는가 (deps 실패 포함)
        found_any = False    # 성공적으로 등록되었는가
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and
                    issubclass(attr, FormatPlugin) and
                    attr is not FormatPlugin):
                found_class = True
                try:
                    instance = attr()
                    ok, missing = instance.check_dependencies()
                    if ok:
                        self.register(instance)
                        found_any = True
                    else:
                        self._errors[instance.plugin_id] = (
                            f"필요 패키지 없음: {', '.join(missing)}"
                        )
                except Exception as e:
                    self._errors[attr_name] = str(e)

        if not found_class:
            self._errors[plugin_file.stem] = "FormatPlugin 서브클래스를 찾을 수 없음"

    def register(self, plugin: FormatPlugin) -> None:
        """플러그인 등록. 동일 확장자는 나중 등록이 우선."""
        # 이미 등록된 플러그인이면 업데이트
        existing = next((p for p in self._plugins if p.plugin_id == plugin.plugin_id), None)
        if existing:
            self._plugins.remove(existing)
            # 기존 확장자 매핑 제거
            for ext, p in list(self._ext_map.items()):
                if p is existing:
                    del self._ext_map[ext]

        self._plugins.append(plugin)
        for ext in plugin.supported_extensions():
            self._ext_map[ext.lower()] = plugin

    def get_parser(self, file_ext: str) -> Optional[FormatPlugin]:
        """확장자에 맞는 플러그인 반환"""
        return self._ext_map.get(file_ext.lower())

    def all_supported_extensions(self) -> Tuple[str, ...]:
        """모든 지원 확장자 튜플"""
        return tuple(sorted(self._ext_map.keys()))

    def all_plugins(self) -> List[FormatPlugin]:
        """등록된 모든 플러그인 목록"""
        return list(self._plugins)

    def load_errors(self) -> Dict[str, str]:
        """로드 실패한 플러그인 오류 정보"""
        return dict(self._errors)

    def reset(self) -> None:
        """레지스트리 초기화 (테스트용)"""
        self._ext_map.clear()
        self._plugins.clear()
        self._errors.clear()
        self._discovered = False


# 전역 싱글톤
_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """전역 플러그인 레지스트리 싱글톤 반환"""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry
