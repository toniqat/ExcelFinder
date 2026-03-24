@echo off
echo ========================================
echo      ExcelFinder Build Script v3.0
echo ========================================
echo.

:: Check if virtual environment exists
if not exist "venv\" (
    echo ERROR: Virtual environment not found!
    echo Please run: python -m venv venv
    echo Then: venv\Scripts\activate
    echo Then: pip install -r requirements.txt
    pause
    exit /b 1
)

:: Activate virtual environment
echo [1/4] Activating virtual environment...
call venv\Scripts\activate.bat

:: Clean previous builds
echo [2/4] Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
if exist src\__pycache__ rmdir /s /q src\__pycache__

:: Build application
echo [3/5] Building ExcelFinder application...
pyinstaller excel_finder.spec

:: Check if build was successful
if not exist "dist\ExcelFinder\ExcelFinder.exe" (
    echo.
    echo ERROR: Build failed! ExcelFinder.exe not found.
    pause
    exit /b 1
)

:: Copy config and icon folders to root level (outside _internal)
echo [4/5] Moving config and icon folders to root level...
if exist "dist\ExcelFinder\_internal\config\" (
    xcopy "dist\ExcelFinder\_internal\config" "dist\ExcelFinder\config\" /E /I /Y >nul
    echo ✓ Config folder copied to root
) else (
    echo ✗ Config folder not found in _internal!
)

if exist "dist\ExcelFinder\_internal\icon\" (
    xcopy "dist\ExcelFinder\_internal\icon" "dist\ExcelFinder\icon\" /E /I /Y >nul
    echo ✓ Icon folder copied to root
) else (
    echo ✗ Icon folder not found in _internal!
)

:: Verify folder structure
echo [5/5] Verifying build structure...
if exist "dist\ExcelFinder\config\" (
    echo ✓ Config folder found in root
) else (
    echo ✗ Config folder missing!
)

if exist "dist\ExcelFinder\icon\" (
    echo ✓ Icon folder found in root
) else (
    echo ✗ Icon folder missing!
)

if exist "dist\ExcelFinder\_internal\" (
    echo ✓ Internal files found
) else (
    echo ✗ Internal files missing!
)

echo.
echo ========================================
echo Build completed successfully!
echo.
echo Output location: dist\ExcelFinder\
echo Executable: dist\ExcelFinder\ExcelFinder.exe
echo ========================================
echo.
pause