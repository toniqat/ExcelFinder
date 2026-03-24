import warnings
import logging
import pandas as pd

# 모든 경고 메시지 억제 설정
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.CRITICAL)

# pandas 설정 최적화
pd.options.mode.chained_assignment = None
pd.options.mode.use_inf_as_na = True

# 표준 출력 리다이렉션 클래스
class NullWriter:
    def write(self, s):
        pass
    def flush(self):
        pass
