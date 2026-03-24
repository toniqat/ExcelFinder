import sys
import os
import time

# src 폴더를 Python 경로에 추가
src_path = os.path.join(os.path.dirname(__file__), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# 현재 디렉토리도 추가 (개발 환경에서 필요할 수 있음)
current_dir = os.path.dirname(__file__)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 설정 모듈 import (경고 억제 포함)
import config

# 표준 출력 및 표준 에러 리다이렉션 (모든 경고 메시지 숨기기)
sys.stderr = config.NullWriter()
sys.stdout = config.NullWriter()

def initialize_application():
    """애플리케이션 초기화 및 로딩 화면 관리"""
    from PyQt5.QtWidgets import QApplication
    import multiprocessing as mp

    # 애플리케이션 생성
    app = QApplication(sys.argv)

    # Windows 멀티프로세싱 설정
    mp.freeze_support()

    # 플러그인 사전 탐색 (부모 프로세스)
    from plugin_registry import get_plugin_registry
    get_plugin_registry().discover()

    # 초기화 시작 시간 측정
    start_time = time.time()

    # loading_dialog import 시도
    try:
        from loading_dialog import LoadingDialog
        loading_dialog = LoadingDialog()
        loading_dialog.show()
        loading_dialog.update_progress(20, "기본 라이브러리 로딩 완료", "PyQt5 컴포넌트")
    except ImportError:
        loading_dialog = None

    if loading_dialog:
        loading_dialog.update_progress(40, "멀티프로세싱 초기화 완료", "병렬 처리 준비")

    # 메인 애플리케이션 모듈 import
    from main_app import ExcelSearchApp
    if loading_dialog:
        loading_dialog.update_progress(60, "메인 애플리케이션 모듈 로딩 완료", "ExcelSearchApp 클래스")

    # 메인 창 초기화
    if loading_dialog:
        loading_dialog.update_progress(80, "메인 창 초기화 중...")

    window = ExcelSearchApp(loading_dialog)

    if loading_dialog:
        loading_dialog.update_progress(95, "UI 컴포넌트 준비 완료", "메인 창 생성")
        loading_dialog.update_progress(100, "준비 완료!", "애플리케이션 시작")
        loading_dialog.close_when_ready()

    # 메인 창 표시
    window.show()

    return app, window

if __name__ == '__main__':
    # 애플리케이션 초기화
    app, window = initialize_application()
    
    # 애플리케이션 실행
    sys.exit(app.exec_())
