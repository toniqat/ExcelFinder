@echo off
echo 디버그 모드로 ExcelFinder 실행
echo 검색 예외 처리 정보가 콘솔에 출력됩니다.
echo.

REM 디버그 모드 활성화
set EXCEL_FINDER_DEBUG=1

REM Python 실행
python main.py

REM 환경 변수 정리
set EXCEL_FINDER_DEBUG=

echo.
pause