"""Excel 파일 처리 유틸리티 모듈 (중복 코드 제거)"""
import os
import pandas as pd
import warnings
import tempfile
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Union

from constants import (SUPPORTED_EXCEL_EXTENSIONS, SUPPORTED_CSV_EXTENSIONS, 
                      CSV_ENCODINGS, CSV_SEPARATORS, LARGE_FILE_THRESHOLD)


class ExcelProcessingError(Exception):
    """Excel 파일 처리 관련 예외"""
    pass


class PermissionError(ExcelProcessingError):
    """파일 접근 권한 관련 예외"""
    pass


class FileFormatError(ExcelProcessingError):
    """파일 형식 관련 예외"""
    pass


def read_csv_smart(file_path: str) -> pd.DataFrame:
    """CSV 파일을 다양한 인코딩과 구분자로 시도하여 읽기"""
    
    for encoding in CSV_ENCODINGS:
        for sep in CSV_SEPARATORS:
            try:
                df = pd.read_csv(file_path, encoding=encoding, sep=sep, na_filter=False)
                # 성공적으로 읽혔고 데이터가 있으면 반환
                if not df.empty and len(df.columns) > 1:
                    return df
            except (UnicodeDecodeError, pd.errors.EmptyDataError, 
                   pd.errors.ParserError, OSError):
                continue
    
    # 모든 시도 실패 시 기본값으로 시도
    try:
        return pd.read_csv(file_path, na_filter=False)
    except Exception as e:
        # 최후의 수단: 텍스트 파일로 읽어서 DataFrame 생성
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            if lines:
                # 첫 번째 줄로 구분자 추정
                first_line = lines[0]
                sep = ',' if ',' in first_line else ';' if ';' in first_line else '\t'
                data = [line.strip().split(sep) for line in lines]
                return pd.DataFrame(data[1:], columns=data[0] if data else [])
        except Exception:
            pass
        
        raise FileFormatError(f"CSV 파일을 읽을 수 없습니다: {str(e)}")


def read_excel_file_safe(file_path: str) -> Tuple[pd.ExcelFile, List[str]]:
    """Excel 파일을 안전하게 읽기 (다단계 오류 처리)"""
    file_ext = Path(file_path).suffix.lower()
    
    if file_ext not in SUPPORTED_EXCEL_EXTENSIONS:
        raise FileFormatError(f"지원하지 않는 파일 형식: {file_ext}")
    
    # 1단계: 기본 방식으로 시도
    try:
        xl = pd.ExcelFile(file_path)
        return xl, xl.sheet_names
    except Exception as e1:
        # 권한 오류 확인
        if "Permission" in str(e1) or "denied" in str(e1).lower():
            raise PermissionError("파일이 다른 프로그램에서 사용 중이거나 접근 권한이 없습니다")
        
        # 2단계: 엔진 명시적 지정
        try:
            engine = 'xlrd' if file_ext == '.xls' else 'openpyxl'
            xl = pd.ExcelFile(file_path, engine=engine)
            return xl, xl.sheet_names
        except Exception as e2:
            # 3단계: 임시 파일로 복사 후 시도
            try:
                return _read_excel_with_temp_file(file_path, file_ext)
            except Exception as e3:
                # 모든 시도 실패
                error_msg = f"Excel 파일 열기 실패 - 원인1: {str(e1)}, 원인2: {str(e2)}, 원인3: {str(e3)}"
                raise ExcelProcessingError(error_msg)


def _read_excel_with_temp_file(file_path: str, file_ext: str) -> Tuple[pd.ExcelFile, List[str]]:
    """임시 파일로 복사 후 Excel 읽기"""
    temp_dir = tempfile.mkdtemp()
    temp_file = os.path.join(temp_dir, os.path.basename(file_path))

    try:
        shutil.copy2(file_path, temp_file)
        engine = 'xlrd' if file_ext == '.xls' else 'openpyxl'
        xl_temp = pd.ExcelFile(temp_file, engine=engine)
        try:
            sheet_names = xl_temp.sheet_names.copy()
        finally:
            try:
                xl_temp.close()
            except Exception:
                pass

        # 원본 파일로 ExcelFile 재생성 (임시 파일은 정리됨)
        xl_original = pd.ExcelFile(file_path, engine=engine)
        return xl_original, sheet_names

    finally:
        # 임시 디렉토리 정리
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


def read_excel_sheet_safe(excel_file: pd.ExcelFile, sheet_name: str, 
                         large_file_mode: bool = False) -> pd.DataFrame:
    """Excel 시트를 안전하게 읽기"""
    try:
        if large_file_mode:
            # 대용량 파일 모드: 메모리 사용량 최소화
            return excel_file.parse(sheet_name, na_filter=False, dtype=str, header=None)
        else:
            return excel_file.parse(sheet_name, na_filter=False, header=None)

    except Exception as e:
        # fallback: pandas.read_excel 직접 사용
        try:
            file_path = excel_file.io
            return pd.read_excel(file_path, sheet_name=sheet_name,
                               na_filter=False, dtype=str if large_file_mode else None, header=None)
        except Exception:
            raise ExcelProcessingError(f"시트 '{sheet_name}' 읽기 실패: {str(e)}")


def get_file_sheets(file_path: str) -> List[str]:
    """파일의 시트 목록 반환"""
    file_ext = Path(file_path).suffix.lower()

    if file_ext in SUPPORTED_CSV_EXTENSIONS:
        # CSV/TSV는 단일 시트 (파일명 사용)
        return [Path(file_path).stem]
    elif file_ext in SUPPORTED_EXCEL_EXTENSIONS:
        try:
            xl, sheet_names = read_excel_file_safe(file_path)
            try:
                return sheet_names
            finally:
                try:
                    xl.close()
                except Exception:
                    pass
        except Exception as e:
            raise ExcelProcessingError(f"시트 목록 조회 실패: {str(e)}")
    else:
        raise FileFormatError(f"지원하지 않는 파일 형식: {file_ext}")


def is_large_file(file_path: str) -> bool:
    """대용량 파일 여부 확인"""
    try:
        return os.path.getsize(file_path) > LARGE_FILE_THRESHOLD
    except OSError:
        return False


def create_streaming_reader(file_path: str, sheet_name: str = None, 
                          chunk_size: int = 1000):
    """대용량 파일용 스트리밍 리더 생성"""
    file_ext = Path(file_path).suffix.lower()
    
    if file_ext in SUPPORTED_CSV_EXTENSIONS:
        # CSV 스트리밍 읽기
        return pd.read_csv(file_path, chunksize=chunk_size, na_filter=False)
    elif file_ext in SUPPORTED_EXCEL_EXTENSIONS:
        # Excel 스트리밍은 제한적이므로 청크로 분할
        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name, na_filter=False)
            
            # DataFrame을 청크로 분할
            for i in range(0, len(df), chunk_size):
                yield df.iloc[i:i + chunk_size]
                
        except Exception as e:
            raise ExcelProcessingError(f"스트리밍 읽기 실패: {str(e)}")
    else:
        raise FileFormatError(f"스트리밍을 지원하지 않는 파일 형식: {file_ext}")


def validate_file_access(file_path: str) -> bool:
    """파일 접근 가능성 검증"""
    try:
        if not os.path.exists(file_path):
            return False
            
        # 파일 크기 확인 (0 바이트 파일 제외)
        if os.path.getsize(file_path) == 0:
            return False
            
        # 읽기 권한 확인
        with open(file_path, 'rb') as f:
            f.read(1)  # 1바이트만 읽기 시도
            
        return True
    except (OSError, IOError, PermissionError):
        return False


def get_file_info(file_path: str) -> dict:
    """파일 정보 수집"""
    try:
        stat_info = os.stat(file_path)
        file_ext = Path(file_path).suffix.lower()
        
        return {
            'path': file_path,
            'size': stat_info.st_size,
            'modified': stat_info.st_mtime,
            'extension': file_ext,
            'is_large': stat_info.st_size > LARGE_FILE_THRESHOLD,
            'is_supported': file_ext in (SUPPORTED_EXCEL_EXTENSIONS + SUPPORTED_CSV_EXTENSIONS),
            'accessible': validate_file_access(file_path)
        }
    except Exception as e:
        return {
            'path': file_path,
            'error': str(e),
            'accessible': False
        }