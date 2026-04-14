import warnings
import logging

# 모든 경고 메시지 억제 설정
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.CRITICAL)

def configure_pandas():
    """pandas import 후 설정 적용 — 첫 검색 시 또는 로딩 단계에서 호출"""
    import pandas as pd
    pd.options.mode.chained_assignment = None
    pd.options.mode.use_inf_as_na = True

# 표준 출력 리다이렉션 클래스
class NullWriter:
    def write(self, s):
        pass
    def flush(self):
        pass
