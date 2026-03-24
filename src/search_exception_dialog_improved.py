"""개선된 검색 예외 처리 다이얼로그"""
import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                            QPushButton, QTableWidget, QTableWidgetItem, QGroupBox, QMessageBox,
                            QDialogButtonBox, QFormLayout, QHeaderView, QComboBox, QRadioButton,
                            QTextEdit, QButtonGroup, QSizePolicy)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon


class UnifiedFilterDialog(QDialog):
    """통합 필터 입력을 위한 다이얼로그"""
    def __init__(self, parent=None, title="필터 추가", edit_data=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(300, 300, 600, 450)

        # Help 버튼 제거
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        # 폼 레이아웃
        form_layout = QFormLayout()

        # 검색 제외 방법 (Type)
        self.exclusion_type_combo = QComboBox()

        # 아이콘 경로 설정
        icon_base_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icon')

        # 아이콘과 함께 아이템 추가
        self.exclusion_type_combo.addItem(QIcon(os.path.join(icon_base_path, 'folder.svg')), "경로 제외", "exclude_path")
        self.exclusion_type_combo.addItem(QIcon(os.path.join(icon_base_path, 'ms-excel.svg')), "파일 제외", "exclude_file")
        self.exclusion_type_combo.addItem(QIcon(os.path.join(icon_base_path, 'sheet.svg')), "시트 제외", "exclude_sheet")
        self.exclusion_type_combo.addItem(QIcon(os.path.join(icon_base_path, 'column.svg')), "열 제외", "exclude_column")
        self.exclusion_type_combo.addItem(QIcon(os.path.join(icon_base_path, 'row.svg')), "행 제외", "exclude_row")
        self.exclusion_type_combo.currentTextChanged.connect(self.on_exclusion_type_changed)
        form_layout.addRow("필터 방식:", self.exclusion_type_combo)

        # 키워드 (경로/파일/시트/헤더 이름)
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("필터할 키워드를 입력하세요")
        self.keyword_label = QLabel("키워드:")
        form_layout.addRow(self.keyword_label, self.keyword_input)

        # 추가 키워드 (행 제외일 때만 사용)
        self.additional_keyword_input = QLineEdit()
        self.additional_keyword_input.setPlaceholderText("특정 값을 입력하세요 (행 제외에서만 사용)")
        self.additional_keyword_input.setEnabled(False)  # 초기에는 비활성화
        self.additional_keyword_label = QLabel("추가 키워드:")
        form_layout.addRow(self.additional_keyword_label, self.additional_keyword_input)

        # 키워드 매치 방식
        self.match_type_combo = QComboBox()
        self.match_type_combo.addItem("정확히 일치", "exact")
        self.match_type_combo.addItem("부분 포함", "contains")
        form_layout.addRow("검색 방식:", self.match_type_combo)

        # 메모 입력 (여러 줄)
        self.memo_input = QTextEdit()
        self.memo_input.setMinimumHeight(100)
        self.memo_input.setPlaceholderText("선택사항")
        form_layout.addRow("설명:", self.memo_input)

        layout.addLayout(form_layout)

        # 기존 데이터로 초기화 (편집 모드)
        if edit_data:
            exclusion_type = edit_data.get('exclusion_type', 'exclude_column')
            index = self.exclusion_type_combo.findData(exclusion_type)
            if index >= 0:
                self.exclusion_type_combo.setCurrentIndex(index)

            self.keyword_input.setText(edit_data.get('keyword', ''))
            self.additional_keyword_input.setText(edit_data.get('additional_keyword', ''))

            match_type = edit_data.get('match_type', 'exact')
            index = self.match_type_combo.findData(match_type)
            if index >= 0:
                self.match_type_combo.setCurrentIndex(index)

            self.memo_input.setPlainText(edit_data.get('memo', ''))
            self.on_exclusion_type_changed()  # UI 상태 업데이트

        # 버튼
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # 적응형 레이아웃 설정
        layout.setStretchFactor(form_layout, 1)

        # 초기 필터 타입에 따른 라벨 설정
        self.on_exclusion_type_changed()

    def on_exclusion_type_changed(self):
        """제외 방법 변경 시 UI 업데이트"""
        exclusion_type = self.exclusion_type_combo.currentData()
        is_exclude_row = (exclusion_type == 'exclude_row')
        self.additional_keyword_input.setEnabled(is_exclude_row)

        # 키워드 라벨 텍스트 업데이트
        keyword_labels = {
            'exclude_path': "제외할 폴더명:",
            'exclude_file': "제외할 파일명:",
            'exclude_sheet': "제외할 시트명:",
            'exclude_column': "제외할 열 이름:",
            'exclude_row': "참고할 열 이름:"
        }
        self.keyword_label.setText(keyword_labels.get(exclusion_type, "키워드:"))

        # 추가 키워드 라벨 텍스트 업데이트
        if is_exclude_row:
            self.additional_keyword_label.setText("제외 참고값:")
        else:
            self.additional_keyword_label.setText("추가 키워드:")

        # Keyword 필드 플레이스홀더 업데이트
        keyword_placeholders = {
            'exclude_path': "검색에서 제외할 폴더 이름을 입력하세요",
            'exclude_file': "검색에서 제외할 파일 이름을 입력하세요",
            'exclude_sheet': "검색에서 제외할 시트 이름을 입력하세요",
            'exclude_column': "검색에서 제외할 열 이름을 입력하세요",
            'exclude_row': "검색에서 제외할 열 이름을 입력하세요"
        }
        self.keyword_input.setPlaceholderText(keyword_placeholders.get(exclusion_type, "제외할 키워드를 입력하세요"))

        # Additional Keyword 필드의 플레이스홀더 업데이트
        if is_exclude_row:
            self.additional_keyword_input.setPlaceholderText("검색에서 제외할 추가 키워드를 입력하세요")
        else:
            self.additional_keyword_input.setPlaceholderText("행 제외에서만 사용됩니다")

    def get_filter_info(self):
        """필터 정보 반환"""
        return {
            'exclusion_type': self.exclusion_type_combo.currentData(),
            'keyword': self.keyword_input.text().strip(),
            'additional_keyword': self.additional_keyword_input.text().strip(),
            'match_type': self.match_type_combo.currentData(),
            'memo': self.memo_input.toPlainText().strip()
        }


class SearchExceptionDialogImproved(QDialog):
    def __init__(self, parent=None, excluded_headers=None, excluded_if_not_empty=None,
                 excluded_paths=None, excluded_files=None, excluded_sheets=None):
        super().__init__(parent)
        self.parent = parent
        self.excluded_headers = excluded_headers or []
        self.excluded_if_not_empty = excluded_if_not_empty or []
        self.excluded_paths = excluded_paths or []
        self.excluded_files = excluded_files or []
        self.excluded_sheets = excluded_sheets or []

        # Help 버튼 제거
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('필터 설정')
        self.setGeometry(300, 300, 1100, 600)  # 크기 조정
        self.setMinimumSize(800, 500)  # 최소 크기 설정

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)  # 여백 설정

        # === 통합 필터 그룹 ===
        unified_filter_group = QGroupBox('필터 설정')
        unified_filter_layout = QVBoxLayout(unified_filter_group)

        # 통합 테이블 (새로운 헤더 구조)
        self.unified_filter_table = QTableWidget(0, 5)
        self.unified_filter_table.setHorizontalHeaderLabels([
            '필터 방식',
            '키워드',
            '추가 키워드',
            '검색 방식',
            '설명'
        ])
        # 적응형 열 크기 조정 설정
        header = self.unified_filter_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)      # 필터 방식 - 고정 크기
        header.setSectionResizeMode(1, QHeaderView.Interactive) # 키워드 - 사용자 조정 가능
        header.setSectionResizeMode(2, QHeaderView.Interactive) # 추가 키워드 - 사용자 조정 가능
        header.setSectionResizeMode(3, QHeaderView.Fixed)      # 검색 방식 - 고정 크기
        header.setSectionResizeMode(4, QHeaderView.Stretch)    # 설명 - 확장 가능

        # 고정 크기 열의 기본 너비 설정
        self.unified_filter_table.setColumnWidth(0, 120)  # 필터 방식
        self.unified_filter_table.setColumnWidth(1, 150)  # 키워드
        self.unified_filter_table.setColumnWidth(2, 120)  # 추가 키워드
        self.unified_filter_table.setColumnWidth(3, 100)  # 검색 방식
        # 설명 열은 Stretch 모드로 자동 확장

        self.unified_filter_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.unified_filter_table.setEditTriggers(QTableWidget.NoEditTriggers)

        # 테이블 크기 정책 설정 (다이얼로그 크기에 맞춰 확장)
        self.unified_filter_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 기존 필터 목록을 통합 테이블로 로드
        self._load_existing_filters()

        unified_filter_layout.addWidget(self.unified_filter_table)

        # 버튼 영역
        buttons_layout = QHBoxLayout()
        add_btn = QPushButton('추가')
        add_btn.clicked.connect(self.add_filter_dialog)

        self.edit_btn = QPushButton('편집')
        self.edit_btn.clicked.connect(self.edit_filter_dialog)
        self.edit_btn.setEnabled(False)

        self.remove_btn = QPushButton('선택 항목 삭제')
        self.remove_btn.clicked.connect(self.remove_filter)
        self.remove_btn.setEnabled(False)

        buttons_layout.addWidget(add_btn)
        buttons_layout.addWidget(self.edit_btn)
        buttons_layout.addWidget(self.remove_btn)
        unified_filter_layout.addLayout(buttons_layout)

        # 테이블 선택 이벤트 연결
        self.unified_filter_table.itemSelectionChanged.connect(self.on_filter_selection_changed)

        # 메인 레이아웃에 추가
        layout.addWidget(unified_filter_group)

        # 하단 버튼
        bottom_layout = QHBoxLayout()
        close_btn = QPushButton('닫기')
        close_btn.clicked.connect(self.accept)
        bottom_layout.addStretch()
        bottom_layout.addWidget(close_btn)
        layout.addLayout(bottom_layout)

    def _load_existing_filters(self):
        """기존 필터들을 통합 테이블로 로드"""
        # 경로 필터들 추가
        for path_filter in self.excluded_paths:
            path_data = self._parse_generic_setting(path_filter)
            unified_data = {
                'exclusion_type': 'exclude_path',
                'keyword': path_data['keyword'],
                'additional_keyword': '',
                'match_type': path_data['match_type'],
                'memo': path_data['memo']
            }
            self._add_filter_to_unified_table(unified_data)

        # 파일 필터들 추가
        for file_filter in self.excluded_files:
            file_data = self._parse_generic_setting(file_filter)
            unified_data = {
                'exclusion_type': 'exclude_file',
                'keyword': file_data['keyword'],
                'additional_keyword': '',
                'match_type': file_data['match_type'],
                'memo': file_data['memo']
            }
            self._add_filter_to_unified_table(unified_data)

        # 시트 필터들 추가
        for sheet_filter in self.excluded_sheets:
            sheet_data = self._parse_generic_setting(sheet_filter)
            unified_data = {
                'exclusion_type': 'exclude_sheet',
                'keyword': sheet_data['keyword'],
                'additional_keyword': '',
                'match_type': sheet_data['match_type'],
                'memo': sheet_data['memo']
            }
            self._add_filter_to_unified_table(unified_data)

        # 기존 헤더 필터들을 변환하여 추가
        for header in self.excluded_headers:
            header_data = self._parse_header_setting(header)
            unified_data = {
                'exclusion_type': 'exclude_column',
                'keyword': header_data['header'],
                'additional_keyword': '',  # 열 제외에서는 사용하지 않음
                'match_type': header_data['match_type'],
                'memo': header_data['memo']
            }
            self._add_filter_to_unified_table(unified_data)

        # 기존 데이터 필터들을 변환하여 추가
        for data_filter in self.excluded_if_not_empty:
            data_filter_data = self._parse_data_filter_setting(data_filter)
            # 데이터 필터의 filter_type에 따라 match_type 결정
            match_type = 'exact' if data_filter_data['filter_type'] == 'specific' else 'contains'
            unified_data = {
                'exclusion_type': 'exclude_row',
                'keyword': data_filter_data['header'],
                'additional_keyword': data_filter_data['specific_value'],
                'match_type': match_type,
                'memo': data_filter_data['memo']
            }
            self._add_filter_to_unified_table(unified_data)

    def _add_filter_to_unified_table(self, filter_data):
        """통합 테이블에 필터 추가"""
        row = self.unified_filter_table.rowCount()
        self.unified_filter_table.insertRow(row)

        # 아이콘 경로 설정
        icon_base_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icon')

        # Type with icon
        type_text_map = {
            'exclude_path': "경로 제외",
            'exclude_file': "파일 제외",
            'exclude_sheet': "시트 제외",
            'exclude_column': "열 제외",
            'exclude_row': "행 제외"
        }
        type_icon_map = {
            'exclude_path': 'folder.svg',
            'exclude_file': 'ms-excel.svg',
            'exclude_sheet': 'sheet.svg',
            'exclude_column': 'column.svg',
            'exclude_row': 'row.svg'
        }

        type_text = type_text_map.get(filter_data['exclusion_type'], "Unknown")
        type_item = QTableWidgetItem(type_text)

        # 아이콘 설정
        icon_filename = type_icon_map.get(filter_data['exclusion_type'])
        if icon_filename:
            icon_path = os.path.join(icon_base_path, icon_filename)
            if os.path.exists(icon_path):
                type_item.setIcon(QIcon(icon_path))

        self.unified_filter_table.setItem(row, 0, type_item)

        # Keyword
        self.unified_filter_table.setItem(row, 1, QTableWidgetItem(filter_data['keyword']))

        # Additional Keyword (행 제외에서만 사용)
        additional_keyword = filter_data['additional_keyword'] if filter_data['exclusion_type'] == 'exclude_row' else ""
        self.unified_filter_table.setItem(row, 2, QTableWidgetItem(additional_keyword))

        # Keyword Match
        match_text = "정확히 일치" if filter_data['match_type'] == 'exact' else "부분 포함"
        self.unified_filter_table.setItem(row, 3, QTableWidgetItem(match_text))

        # Memo
        self.unified_filter_table.setItem(row, 4, QTableWidgetItem(filter_data['memo']))

    def add_filter_dialog(self):
        """필터 추가 다이얼로그"""
        dialog = UnifiedFilterDialog(self, "필터 추가")
        if dialog.exec_():
            filter_info = dialog.get_filter_info()
            if filter_info['keyword']:
                # 중복 확인
                if not self._is_filter_duplicate(filter_info['keyword'], filter_info['exclusion_type']):
                    self._add_filter_to_unified_table(filter_info)
                    self.save_settings()
                else:
                    QMessageBox.warning(self, '중복 항목', f"'{filter_info['keyword']}'는 이미 목록에 있습니다.")

    def edit_filter_dialog(self):
        """필터 편집 다이얼로그"""
        selected_rows = self._get_selected_rows(self.unified_filter_table)
        if not selected_rows:
            return

        row = min(selected_rows)

        # 현재 값 가져오기
        type_text = self.unified_filter_table.item(row, 0).text()
        type_data_map = {
            "경로 제외": 'exclude_path',
            "파일 제외": 'exclude_file',
            "시트 제외": 'exclude_sheet',
            "열 제외": 'exclude_column',
            "행 제외": 'exclude_row'
        }
        current_data = {
            'exclusion_type': type_data_map.get(type_text, 'exclude_column'),
            'keyword': self.unified_filter_table.item(row, 1).text(),
            'additional_keyword': self.unified_filter_table.item(row, 2).text(),
            'match_type': 'exact' if self.unified_filter_table.item(row, 3).text() == "정확히 일치" else 'contains',
            'memo': self.unified_filter_table.item(row, 4).text()
        }

        dialog = UnifiedFilterDialog(self, "필터 편집", current_data)
        if dialog.exec_():
            filter_info = dialog.get_filter_info()
            if filter_info['keyword']:
                # 다른 행과 중복 확인 (현재 행 제외)
                if not self._is_filter_duplicate(filter_info['keyword'], filter_info['exclusion_type'], exclude_row=row):
                    # 테이블 업데이트
                    # 아이콘 경로 설정
                    icon_base_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icon')

                    type_text_map = {
                        'exclude_path': "경로 제외",
                        'exclude_file': "파일 제외",
                        'exclude_sheet': "시트 제외",
                        'exclude_column': "열 제외",
                        'exclude_row': "행 제외"
                    }
                    type_icon_map = {
                        'exclude_path': 'folder.svg',
                        'exclude_file': 'ms-excel.svg',
                        'exclude_sheet': 'sheet.svg',
                        'exclude_column': 'column.svg',
                        'exclude_row': 'row.svg'
                    }

                    type_text = type_text_map.get(filter_info['exclusion_type'], "Unknown")
                    type_item = QTableWidgetItem(type_text)

                    # 아이콘 설정
                    icon_filename = type_icon_map.get(filter_info['exclusion_type'])
                    if icon_filename:
                        icon_path = os.path.join(icon_base_path, icon_filename)
                        if os.path.exists(icon_path):
                            type_item.setIcon(QIcon(icon_path))

                    self.unified_filter_table.setItem(row, 0, type_item)
                    self.unified_filter_table.setItem(row, 1, QTableWidgetItem(filter_info['keyword']))

                    additional_keyword = filter_info['additional_keyword'] if filter_info['exclusion_type'] == 'exclude_row' else ""
                    self.unified_filter_table.setItem(row, 2, QTableWidgetItem(additional_keyword))

                    match_text = "정확히 일치" if filter_info['match_type'] == 'exact' else "부분 포함"
                    self.unified_filter_table.setItem(row, 3, QTableWidgetItem(match_text))
                    self.unified_filter_table.setItem(row, 4, QTableWidgetItem(filter_info['memo']))
                    self.save_settings()
                else:
                    QMessageBox.warning(self, '중복 항목', f"'{filter_info['keyword']}'는 이미 목록에 있습니다.")

    def remove_filter(self):
        """선택한 필터 삭제"""
        selected_rows = self._get_selected_rows(self.unified_filter_table)
        if not selected_rows:
            return

        for row in sorted(selected_rows, reverse=True):
            self.unified_filter_table.removeRow(row)

        self.save_settings()

    def on_filter_selection_changed(self):
        """필터 테이블 선택 변경 이벤트"""
        selected_items = self.unified_filter_table.selectedItems()
        has_selection = len(selected_items) > 0

        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _is_filter_duplicate(self, keyword, exclusion_type, exclude_row=None):
        """필터 중복 확인"""
        type_data_map = {
            "경로 제외": 'exclude_path',
            "파일 제외": 'exclude_file',
            "시트 제외": 'exclude_sheet',
            "열 제외": 'exclude_column',
            "행 제외": 'exclude_row'
        }

        for row in range(self.unified_filter_table.rowCount()):
            if exclude_row is not None and row == exclude_row:
                continue
            keyword_item = self.unified_filter_table.item(row, 1)
            type_item = self.unified_filter_table.item(row, 0)
            if keyword_item and type_item:
                existing_type = type_data_map.get(type_item.text(), 'exclude_column')
                if keyword_item.text() == keyword and existing_type == exclusion_type:
                    return True
        return False

    def _parse_generic_setting(self, setting_string):
        """경로/파일/시트 설정 문자열 파싱"""
        # 형식: "keyword|match_type|메모: memo_text"
        if "|" in setting_string:
            parts = setting_string.split("|", 2)
            keyword = parts[0].strip()
            match_type = parts[1].strip() if len(parts) > 1 else 'exact'
            memo_part = parts[2].strip() if len(parts) > 2 else ''

            if memo_part.startswith('메모: '):
                memo = memo_part[3:].strip()  # "메모: " 제거 후 공백 제거
            else:
                memo = memo_part.strip()  # 공백 제거
        else:
            # 기본 형식 (키워드만)
            keyword = setting_string.strip()
            match_type = 'exact'
            memo = ""

        return {
            'keyword': keyword,
            'match_type': match_type,
            'memo': memo
        }

    def _parse_header_setting(self, header_setting):
        """헤더 설정 문자열 파싱"""
        # 새로운 형식: "header_name|match_type|메모: memo_text"
        # 기존 형식: "header_name (메모: memo_text)" 또는 "header_name"
        
        if "|" in header_setting:
            # 새로운 형식
            parts = header_setting.split("|", 2)
            header = parts[0].strip()
            match_type = parts[1].strip() if len(parts) > 1 else 'exact'
            memo_part = parts[2].strip() if len(parts) > 2 else ''

            if memo_part.startswith('메모: '):
                memo = memo_part[3:].strip()  # "메모: " 제거 후 공백 제거
            else:
                memo = memo_part.strip()  # 공백 제거
        else:
            # 기존 형식 (호환성)
            if " (메모: " in header_setting:
                header, memo_part = header_setting.split(" (메모: ", 1)
                memo = memo_part.rstrip(")").strip()  # 공백 제거
            else:
                header = header_setting.strip()
                memo = ""
            match_type = 'exact'  # 기본값
        
        return {
            'header': header,
            'match_type': match_type,
            'memo': memo
        }
    
    def _parse_data_filter_setting(self, filter_setting):
        """데이터 필터 설정 문자열 파싱"""
        # 새로운 형식: "header_name|filter_type|specific_value|메모: memo_text"
        # 기존 형식: "header_name (메모: memo_text)" 또는 "header_name"
        
        if "|" in filter_setting:
            # 새로운 형식
            parts = filter_setting.split("|", 3)
            header = parts[0].strip()
            filter_type = parts[1].strip() if len(parts) > 1 else 'any'
            specific_value = parts[2].strip() if len(parts) > 2 else ''
            memo_part = parts[3].strip() if len(parts) > 3 else ''

            if memo_part.startswith('메모: '):
                memo = memo_part[3:].strip()  # "메모: " 제거 후 공백 제거
            else:
                memo = memo_part.strip()  # 공백 제거
        else:
            # 기존 형식 (호환성)
            if " (메모: " in filter_setting:
                header, memo_part = filter_setting.split(" (메모: ", 1)
                memo = memo_part.rstrip(")").strip()  # 공백 제거
            else:
                header = filter_setting.strip()
                memo = ""
            filter_type = 'any'  # 기본값
            specific_value = ''
        
        return {
            'header': header,
            'filter_type': filter_type,
            'specific_value': specific_value,
            'memo': memo
        }
    
    def _get_selected_rows(self, table):
        """선택된 행 번호 목록 반환"""
        selected_rows = set()
        for item in table.selectedItems():
            selected_rows.add(item.row())
        return selected_rows

    def get_unified_filters(self):
        """통합 테이블에서 필터 목록을 분리하여 반환"""
        path_filters = []
        file_filters = []
        sheet_filters = []
        header_filters = []
        data_filters = []

        for row in range(self.unified_filter_table.rowCount()):
            type_item = self.unified_filter_table.item(row, 0)
            keyword_item = self.unified_filter_table.item(row, 1)
            additional_keyword_item = self.unified_filter_table.item(row, 2)
            match_item = self.unified_filter_table.item(row, 3)
            memo_item = self.unified_filter_table.item(row, 4)

            if not type_item or not keyword_item:
                continue

            exclusion_type = type_item.text()
            keyword = keyword_item.text()
            additional_keyword = additional_keyword_item.text() if additional_keyword_item else ""
            match_type = 'exact' if match_item.text() == "정확히 일치" else 'contains'
            memo = memo_item.text() if memo_item else ""

            # 일반적인 필터 형식 (경로/파일/시트용)
            filter_string = f"{keyword}|{match_type}"
            if memo:
                filter_string += f"|메모: {memo}"

            if exclusion_type == "경로 제외":
                path_filters.append(filter_string)

            elif exclusion_type == "파일 제외":
                file_filters.append(filter_string)

            elif exclusion_type == "시트 제외":
                sheet_filters.append(filter_string)

            elif exclusion_type == "열 제외":
                header_filters.append(filter_string)

            elif exclusion_type == "행 제외":
                # 데이터 필터 형식으로 변환
                # match_type에 따라 filter_type 결정
                filter_type = 'specific' if match_type == 'exact' and additional_keyword else 'any'
                data_filter_string = f"{keyword}|{filter_type}|{additional_keyword}"
                if memo:
                    data_filter_string += f"|메모: {memo}"
                data_filters.append(data_filter_string)

        return path_filters, file_filters, sheet_filters, header_filters, data_filters
    
    def save_settings(self):
        """설정 저장"""
        # 통합 테이블의 내용을 분리하여 설정 업데이트
        path_filters, file_filters, sheet_filters, header_filters, data_filters = self.get_unified_filters()
        self.excluded_paths = path_filters
        self.excluded_files = file_filters
        self.excluded_sheets = sheet_filters
        self.excluded_headers = header_filters
        self.excluded_if_not_empty = data_filters

        # 부모 객체가 있고 save_settings 메서드가 있으면 호출
        if self.parent and hasattr(self.parent, 'save_settings'):
            # 기존 필터들 업데이트
            self.parent.excluded_headers = self.excluded_headers
            self.parent.excluded_if_not_empty = self.excluded_if_not_empty

            # 새로운 필터들 추가 (부모에 속성이 있는 경우만)
            if hasattr(self.parent, 'excluded_paths'):
                self.parent.excluded_paths = self.excluded_paths
            if hasattr(self.parent, 'excluded_files'):
                self.parent.excluded_files = self.excluded_files
            if hasattr(self.parent, 'excluded_sheets'):
                self.parent.excluded_sheets = self.excluded_sheets

            self.parent.save_settings()
    
    def closeEvent(self, event):
        """다이얼로그가 닫힐 때 호출되는 이벤트 핸들러"""
        # 설정 저장
        self.save_settings()
        
        # 기본 closeEvent 처리
        super().closeEvent(event)