"""PDF 파일 플러그인 (pdfminer.six 필요) - Extension Pack"""
import sys
import pandas as pd
from pathlib import Path
from typing import List, Tuple

_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin


class PdfPlugin(FormatPlugin):
    """PDF 파일(.pdf) 처리 플러그인 (pdfminer.six 필요)"""

    @property
    def plugin_id(self) -> str:
        return "pdf"

    @property
    def display_name(self) -> str:
        return "PDF"

    @property
    def required_packages(self) -> List[str]:
        return ["pdfminer"]

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.pdf',)

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        from pdfminer.high_level import extract_pages  # lazy import
        from pdfminer.layout import LTTextContainer

        file_stem = Path(file_path).stem
        rows = []

        for page_num, page_layout in enumerate(extract_pages(file_path), 1):
            for element in page_layout:
                if isinstance(element, LTTextContainer):
                    text = element.get_text().strip()
                    if text:
                        for line in text.splitlines():
                            line = line.strip()
                            if line:
                                rows.append((str(page_num), line))

        if not rows:
            return []

        headers = ['Page', 'Content']
        df = pd.DataFrame(rows, columns=range(2))
        return [(file_stem, headers, df)]
