# 애플리케이션 시작 속도 최적화 가이드

엑셀 파일 검색 도구가 시작될 때 느리게 로드되는 이유와 이를 개선하기 위한 방법을 설명합니다.

## 느린 시작 속도의 주요 원인

1. **대형 라이브러리 로딩**:
   - pandas, numpy, PyQt5 등 대형 라이브러리를 시작 시 모두 로드
   - 이러한 라이브러리는 크기가 크고 초기화 시간이 오래 걸림

2. **PyQt5 초기화**:
   - GUI 프레임워크 초기화에 시간이 소요됨
   - 많은 UI 컴포넌트를 한 번에 생성하는 경우 더 느려짐

3. **경고 억제 로직**:
   - 다양한 경고를 억제하기 위한 코드가 시작 시간에 영향을 줄 수 있음

4. **멀티프로세싱 설정**:
   - 멀티프로세싱 인프라 설정에 시간이 소요됨

5. **PyInstaller 압축 해제** (실행 파일 사용 시):
   - PyInstaller로 빌드된 실행 파일은 실행 전 모든 라이브러리를 임시 디렉토리에 압축 해제해야 함
   - 이 과정이 상당한 시간을 소요할 수 있음

## 시작 속도 개선 방법

### 1. 지연 임포트 (Lazy Import) 사용

현재 코드는 시작 시 모든 라이브러리를 임포트합니다. 대신 필요할 때만 임포트하도록 변경할 수 있습니다.

```python
# 변경 전 (시작 시 임포트)
import pandas as pd
import numpy as np
from PyQt5.QtWidgets import QApplication, QMainWindow, ...

# 변경 후 (필요할 때만 임포트)
def process_file(args):
    import pandas as pd
    import numpy as np
    # 함수 내용...
```

### 2. UI 컴포넌트 생성 최적화

UI 컴포넌트를 필요할 때만 생성하거나, 백그라운드에서 점진적으로 생성하도록 변경할 수 있습니다.

```python
# 스플래시 화면 추가
class SplashScreen(QSplashScreen):
    def __init__(self):
        super().__init__(QPixmap("splash.png"))
        
# 메인 애플리케이션에서 사용
splash = SplashScreen()
splash.show()
app.processEvents()  # 이벤트 처리하여 스플래시 화면 표시

# UI 초기화 (시간이 오래 걸리는 작업)
window = ExcelSearchApp()

# 초기화 완료 후 스플래시 화면 닫기
splash.finish(window)
window.show()
```

### 3. 멀티프로세싱 지연 초기화

멀티프로세싱 관련 설정을 애플리케이션 시작 시가 아닌 실제 검색 시작 시에만 초기화하도록 변경할 수 있습니다.

### 4. PyInstaller 최적화 옵션

PyInstaller로 빌드할 때 다음 옵션을 사용하여 시작 속도를 개선할 수 있습니다:

```python
# build_exe.py 수정
cmd = [
    "pyinstaller",
    "--name=DocsFinder",
    "--onefile",  # 단일 파일 대신 디렉토리 모드 사용 시 더 빠름
    "--windowed",
    "--noupx",    # UPX 압축 비활성화로 압축 해제 시간 단축
    # 기타 옵션...
]
```

또는 `--onedir` 옵션을 사용하여 단일 디렉토리로 빌드하면 시작 속도가 크게 향상됩니다 (단, 배포는 더 복잡해짐).

### 5. 스플래시 화면 추가

애플리케이션이 로딩 중임을 사용자에게 알리기 위해 스플래시 화면을 추가할 수 있습니다. 이는 실제 시작 시간을 단축하지는 않지만, 사용자 경험을 개선합니다.

## 구현 예시: 스플래시 화면 추가

main.py 파일을 다음과 같이 수정하여 스플래시 화면을 추가할 수 있습니다:

```python
import sys
import multiprocessing as mp
from PyQt5.QtWidgets import QApplication, QSplashScreen
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
from main_app import ExcelSearchApp
import config

if __name__ == '__main__':
    # Windows에서 멀티프로세싱 시작 방법 설정
    mp.freeze_support()
    
    # 표준 출력 리다이렉션
    null_writer = config.NullWriter()
    
    # 애플리케이션 시작
    app = QApplication(sys.argv)
    
    # 스플래시 화면 표시 (이미지가 없는 경우 텍스트만 표시)
    splash = QSplashScreen()
    splash.showMessage("엑셀 파일 검색 도구 로딩 중...", Qt.AlignCenter, Qt.white)
    splash.show()
    app.processEvents()  # 이벤트 처리하여 스플래시 화면 표시
    
    # 메인 창 초기화 (시간이 오래 걸리는 작업)
    window = ExcelSearchApp()
    
    # 초기화 완료 후 스플래시 화면 닫고 메인 창 표시
    splash.finish(window)
    window.show()
    
    sys.exit(app.exec_())
```

이 변경으로 애플리케이션이 로딩 중임을 사용자에게 알려 사용자 경험을 개선할 수 있습니다.
