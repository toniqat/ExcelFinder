"""XML 파일 플러그인 (stdlib xml.etree)"""
import sys
import pandas as pd
from pathlib import Path
from typing import List, Tuple
import xml.etree.ElementTree as ET

_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin, _flatten_value


def _element_to_dict(element: ET.Element) -> dict:
    """XML 요소를 딕셔너리로 변환"""
    result = {}
    # 속성 추가
    result.update(element.attrib)
    # 자식 요소 추가
    for child in element:
        tag = child.tag.split('}')[-1]  # 네임스페이스 제거
        child_dict = _element_to_dict(child)
        if tag in result:
            # 중복 태그는 리스트로
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(child_dict if child_dict else (child.text or ""))
        else:
            result[tag] = child_dict if child_dict else (child.text or "")
    # 텍스트 내용
    if element.text and element.text.strip():
        if not result:
            return {'_text': element.text.strip()}
        result['_text'] = element.text.strip()
    return result


def _find_repeated_elements(root: ET.Element):
    """반복되는 자식 요소 태그와 요소 목록 찾기"""
    from collections import Counter
    tag_counts = Counter(child.tag.split('}')[-1] for child in root)
    # 2회 이상 반복되는 태그 우선
    for tag, count in tag_counts.most_common():
        if count >= 2:
            elements = [c for c in root if c.tag.split('}')[-1] == tag]
            return tag, elements
    # 반복 없으면 모든 자식
    return None, list(root)


class XmlPlugin(FormatPlugin):
    """XML 파일(.xml) 처리 플러그인"""

    @property
    def plugin_id(self) -> str:
        return "xml"

    @property
    def display_name(self) -> str:
        return "XML"

    @property
    def is_builtin(self) -> bool:
        return True

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.xml',)

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        tree = ET.parse(file_path)
        root = tree.getroot()
        file_stem = Path(file_path).stem

        tag, elements = _find_repeated_elements(root)

        records = []
        for el in elements:
            d = _element_to_dict(el)
            # 평탄화
            flat = {}
            for k, v in d.items():
                flat[k] = _flatten_value(v)
            records.append(flat)

        if not records:
            # 루트 자체를 하나의 레코드로
            d = _element_to_dict(root)
            records = [{k: _flatten_value(v) for k, v in d.items()}]

        df = pd.DataFrame(records)
        if df.empty:
            return []

        headers = list(df.columns)
        # 헤더 행을 row 0으로 포함 (Excel 플러그인과 동일한 방식)
        header_df = pd.DataFrame([headers], columns=df.columns)
        df_with_header = pd.concat([header_df, df], ignore_index=True)
        df_with_header.columns = range(len(df_with_header.columns))
        return [(file_stem, headers, df_with_header)]
