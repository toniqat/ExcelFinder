@echo off
echo ========================================
echo      DocsFinder Build Script v3.0
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
echo [3/5] Building DocsFinder application...
venv\Scripts\pyinstaller.exe excel_finder.spec

:: Check if build was successful
if not exist "dist\DocsFinder\DocsFinder.exe" (
    echo.
    echo ERROR: Build failed! DocsFinder.exe not found.
    pause
    exit /b 1
)

:: Copy config and icon folders to root level (outside _internal)
echo [4/5] Moving config and icon folders to root level...
if exist "dist\DocsFinder\_internal\config\" (
    xcopy "dist\DocsFinder\_internal\config" "dist\DocsFinder\config\" /E /I /Y >nul
    echo ✓ Config folder copied to root
) else (
    echo ✗ Config folder not found in _internal!
)

if exist "dist\DocsFinder\_internal\icon\" (
    xcopy "dist\DocsFinder\_internal\icon" "dist\DocsFinder\icon\" /E /I /Y >nul
    echo ✓ Icon folder copied to root
) else (
    echo ✗ Icon folder not found in _internal!
)

if exist "dist\DocsFinder\_internal\plugins\" (
    xcopy "dist\DocsFinder\_internal\plugins" "dist\DocsFinder\plugins\" /E /I /Y >nul
    echo ✓ Plugins folder copied to root
) else (
    echo ✗ Plugins folder not found in _internal!
)

:: Verify folder structure
echo [5/5] Verifying build structure...
if exist "dist\DocsFinder\config\" (
    echo ✓ Config folder found in root
) else (
    echo ✗ Config folder missing!
)

if exist "dist\DocsFinder\icon\" (
    echo ✓ Icon folder found in root
) else (
    echo ✗ Icon folder missing!
)

if exist "dist\DocsFinder\plugins\" (
    echo ✓ Plugins folder found in root
) else (
    echo ✗ Plugins folder missing!
)

if exist "dist\DocsFinder\_internal\" (
    echo ✓ Internal files found
) else (
    echo ✗ Internal files missing!
)

echo.
echo ========================================
echo Build completed successfully!
echo.
echo Output location: dist\DocsFinder\
echo Executable: dist\DocsFinder\DocsFinder.exe
echo ========================================
echo.
pause