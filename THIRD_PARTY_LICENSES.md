# 제3자 라이브러리 라이센스 정보

ExcelFinder는 다음과 같은 오픈소스 라이브러리들을 사용합니다:

## 주요 라이브러리

### pandas (BSD-3-Clause License)
- **버전**: >= 1.0.0
- **용도**: 엑셀 파일 데이터 처리 및 분석
- **라이센스**: BSD-3-Clause
- **홈페이지**: https://pandas.pydata.org/
- **라이센스 전문**: https://github.com/pandas-dev/pandas/blob/main/LICENSE

### numpy (BSD-3-Clause License)
- **버전**: >= 1.18.0
- **용도**: 수치 계산 및 배열 처리
- **라이센스**: BSD-3-Clause
- **홈페이지**: https://numpy.org/
- **라이센스 전문**: https://github.com/numpy/numpy/blob/main/LICENSE.txt

### PyQt5 (GPL v3 License)
- **버전**: >= 5.15.0
- **용도**: GUI 사용자 인터페이스
- **라이센스**: GPL v3 (오픈소스 사용 시) / Commercial License (상용 사용 시)
- **홈페이지**: https://www.riverbankcomputing.com/software/pyqt/
- **라이센스 전문**: https://www.gnu.org/licenses/gpl-3.0.html
- **참고**: PyQt5는 GPL v3 라이센스로 배포되므로, 이를 사용하는 ExcelFinder도 GPL v3로 배포됩니다.

### xlrd (BSD-like License)
- **버전**: >= 1.2.0
- **용도**: Excel 97-2003 (.xls) 파일 읽기
- **라이센스**: BSD-like
- **홈페이지**: https://github.com/python-excel/xlrd
- **라이센스 전문**: https://github.com/python-excel/xlrd/blob/master/LICENSE

### openpyxl (MIT License)
- **버전**: >= 3.0.0
- **용도**: Excel 2010+ (.xlsx, .xlsm) 파일 읽기/쓰기
- **라이센스**: MIT
- **홈페이지**: https://openpyxl.readthedocs.io/
- **라이센스 전문**: https://github.com/theorchard/openpyxl/blob/master/LICENCE.rst

### pyxlsb (BSD-2-Clause License)
- **버전**: >= 1.0.0
- **용도**: Excel Binary (.xlsb) 파일 읽기
- **라이센스**: BSD-2-Clause
- **홈페이지**: https://github.com/wwwiiilll/pyxlsb
- **라이센스 전문**: https://github.com/wwwiiilll/pyxlsb/blob/master/LICENSE

### pywin32 (PSF-2.0 License)
- **버전**: >= 300 (Windows 전용)
- **용도**: Windows API 접근
- **라이센스**: Python Software Foundation License 2.0
- **홈페이지**: https://github.com/mhammond/pywin32
- **라이센스 전문**: https://github.com/mhammond/pywin32/blob/main/LICENSE.txt

## 빌드 도구

### PyInstaller (GPL v2 License)
- **버전**: >= 4.0
- **용도**: Python 애플리케이션을 실행 파일로 패키징
- **라이센스**: GPL v2
- **홈페이지**: https://pyinstaller.org/
- **라이센스 전문**: https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt

## 라이센스 호환성

ExcelFinder는 GPL v3 라이센스로 배포됩니다. 이는 다음과 같은 이유 때문입니다:

1. **PyQt5**: GPL v3 라이센스를 사용하므로, 이를 사용하는 애플리케이션도 GPL v3로 배포되어야 합니다.
2. **PyInstaller**: GPL v2 라이센스이며, GPL v3와 호환됩니다.
3. **기타 라이브러리들**: BSD, MIT, PSF 라이센스들은 모두 GPL v3와 호환됩니다.

## 라이센스 전문

각 라이브러리의 라이센스 전문은 위에 제공된 링크에서 확인할 수 있습니다. 모든 라이브러리는 해당 라이센스 조건에 따라 사용됩니다.

## 기여 및 수정

ExcelFinder를 수정하거나 재배포하는 경우, GPL v3 라이센스 조건을 준수해야 합니다:

- 소스코드를 공개해야 합니다
- 동일한 GPL v3 라이센스로 배포해야 합니다
- 수정 사항을 명시해야 합니다
- 라이센스 및 저작권 고지를 유지해야 합니다

자세한 내용은 LICENSE 파일과 https://www.gnu.org/licenses/gpl-3.0.html 을 참조하세요.
