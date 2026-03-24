"""HWP 파일 플러그인 (olefile 필요) - Extension Pack"""
import sys
import pandas as pd
from pathlib import Path
from typing import List, Tuple

_src = Path(__file__).parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from plugin_base import FormatPlugin


class HwpPlugin(FormatPlugin):
    """한글 문서(.hwp) 처리 플러그인 (olefile 필요)"""

    @property
    def plugin_id(self) -> str:
        return "hwp"

    @property
    def display_name(self) -> str:
        return "한글 (HWP)"

    @property
    def required_packages(self) -> List[str]:
        return ["olefile"]

    def supported_extensions(self) -> Tuple[str, ...]:
        return ('.hwp', '.hwx')

    def _read_hwx(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        """HWX (Hancom Word XML) 파일 파싱"""
        import xml.etree.ElementTree as ET

        file_stem = Path(file_path).stem
        paragraphs = []

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            # HWX XML에서 텍스트 노드 추출 (네임스페이스 무시)
            for elem in root.iter():
                text = (elem.text or '').strip()
                if text:
                    paragraphs.append(text)
                tail = (elem.tail or '').strip()
                if tail:
                    paragraphs.append(tail)
        except ET.ParseError as e:
            raise ValueError(f"HWX XML 파싱 실패: {file_path} — {e}")

        if not paragraphs:
            return []

        headers = ['Content']
        df = pd.DataFrame([(p,) for p in paragraphs], columns=range(1))
        return [(file_stem, headers, df)]

    def read_file(self, file_path: str) -> List[Tuple[str, List[str], pd.DataFrame]]:
        if Path(file_path).suffix.lower() == '.hwx':
            return self._read_hwx(file_path)

        import olefile  # lazy import

        file_stem = Path(file_path).stem

        if not olefile.isOleFile(file_path):
            raise ValueError(f"유효하지 않은 HWP 파일: {file_path}")

        ole = olefile.OleFileIO(file_path)
        paragraphs = []

        try:
            # HWP BodyText 스트림에서 텍스트 추출
            if ole.exists('BodyText'):
                # 섹션 스트림 탐색
                entries = ole.listdir()
                section_streams = [e for e in entries
                                   if len(e) >= 2 and e[0] == 'BodyText'
                                   and e[1].startswith('Section')]
                section_streams.sort(key=lambda x: x[1])

                for stream_path in section_streams:
                    try:
                        data = ole.openstream(stream_path).read()
                        text = self._extract_text_from_section(data)
                        paragraphs.extend(text)
                    except Exception:
                        continue
        finally:
            ole.close()

        if not paragraphs:
            return []

        headers = ['Content']
        df = pd.DataFrame([(p,) for p in paragraphs], columns=range(1))
        return [(file_stem, headers, df)]

    def _extract_text_from_section(self, data: bytes) -> List[str]:
        """HWP 섹션 바이너리 데이터에서 텍스트 추출"""
        # HWP5 레코드 파싱 (간략화된 구현)
        # 레코드 태그 67 = HWPTAG_PARA_TEXT
        PARA_TEXT_TAG = 67
        paragraphs = []
        i = 0

        while i + 4 <= len(data):
            header = int.from_bytes(data[i:i+4], 'little')
            tag_id = header & 0x3FF
            level = (header >> 10) & 0x3FF
            size = (header >> 20) & 0xFFF

            if size == 0xFFF:
                # 확장 크기
                if i + 8 > len(data):
                    break
                size = int.from_bytes(data[i+4:i+8], 'little')
                i += 8
            else:
                i += 4

            if i + size > len(data):
                break

            if tag_id == PARA_TEXT_TAG:
                chunk = data[i:i+size]
                try:
                    # UTF-16LE 디코딩
                    text = chunk.decode('utf-16-le', errors='replace')
                    # 제어 문자 제거 (0x0000~0x001F 범위, 일반 공백 제외)
                    text = ''.join(c if ord(c) >= 0x20 or c in '\t' else '' for c in text)
                    text = text.strip()
                    if text:
                        paragraphs.append(text)
                except Exception:
                    pass

            i += size

        return paragraphs
