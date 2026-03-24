"""UI 컴포넌트들을 분리한 모듈"""
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                            QComboBox, QLineEdit, QCheckBox, QPushButton, 
                            QSpinBox, QLabel, QTreeWidget, QTreeWidgetItem,
                            QTableWidget, QTableWidgetItem, QHeaderView,
                            QTextEdit)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
import multiprocessing as mp

from constants import DEFAULT_WORKER_COUNT, SUPPORTED_EXTENSIONS


class SearchOptionsWidget(QWidget):
    """검색 옵션 UI 컴포넌트"""
    
    search_requested = pyqtSignal()
    search_stopped = pyqtSignal()
    exception_settings_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_searching = False
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 검색 옵션 그룹박스
        search_group = QGroupBox('검색 옵션')
        options_layout = QVBoxLayout(search_group)
        
        # 검색 입력 및 모드 선택
        search_input_layout = QHBoxLayout()
        
        self.search_mode_combo = QComboBox()
        self.search_mode_combo.addItem('값 일치')
        self.search_mode_combo.addItem('값 포함')
        search_input_layout.addWidget(self.search_mode_combo)
        
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self.on_search_text_changed)
        search_input_layout.addWidget(self.search_input)
        
        options_layout.addLayout(search_input_layout)
        
        # 검색 예외 처리
        exception_layout = QHBoxLayout()
        
        self.apply_exception_checkbox = QCheckBox('검색 예외 처리 적용')
        self.apply_exception_checkbox.setChecked(True)
        exception_layout.addWidget(self.apply_exception_checkbox)
        
        self.exception_settings_btn = QPushButton('설정')
        self.exception_settings_btn.setFixedSize(50, 20)
        self.exception_settings_btn.setToolTip('검색 예외 처리 설정')
        self.exception_settings_btn.clicked.connect(self.exception_settings_requested.emit)
        exception_layout.addWidget(self.exception_settings_btn)
        exception_layout.addStretch()
        
        options_layout.addLayout(exception_layout)
        
        # 병렬 처리 옵션
        parallel_layout = QHBoxLayout()
        parallel_layout.addWidget(QLabel('병렬 처리 수:'))
        
        worker_container = QWidget()
        worker_layout = QHBoxLayout(worker_container)
        worker_layout.setContentsMargins(0, 0, 0, 0)
        worker_layout.setSpacing(5)
        
        self.worker_count = QSpinBox()
        self.worker_count.setMinimum(1)
        self.worker_count.setMaximum(mp.cpu_count())
        self.worker_count.setValue(min(DEFAULT_WORKER_COUNT, mp.cpu_count()))
        self.worker_count.setToolTip(f'사용 가능한 CPU 코어: {mp.cpu_count()}개')
        
        max_cpu_label = QLabel(f"(최대: {mp.cpu_count()})")
        
        worker_layout.addWidget(self.worker_count)
        worker_layout.addWidget(max_cpu_label)
        worker_layout.addStretch()
        
        parallel_layout.addWidget(worker_container, 1)
        options_layout.addLayout(parallel_layout)
        
        # 검색 버튼
        self.search_stop_btn = QPushButton('검색')
        self.search_stop_btn.clicked.connect(self.on_search_button_clicked)
        options_layout.addWidget(self.search_stop_btn)
        
        layout.addWidget(search_group)
        
    def on_search_text_changed(self):
        """검색 텍스트 변경 시 버튼 상태 업데이트"""
        if hasattr(self.parent(), 'update_search_button_state'):
            self.parent().update_search_button_state()
    
    def on_search_button_clicked(self):
        """검색/중지 버튼 클릭"""
        if self.is_searching:
            self.search_stopped.emit()
        else:
            self.search_requested.emit()
    
    def set_searching_state(self, is_searching: bool):
        """검색 상태 설정"""
        self.is_searching = is_searching
        if is_searching:
            self.search_stop_btn.setText('중지')
        else:
            self.search_stop_btn.setText('검색')
    
    def update_button_state(self, enabled: bool):
        """버튼 활성화 상태 업데이트"""
        if not self.is_searching:
            self.search_stop_btn.setEnabled(enabled)
    
    def get_search_text(self) -> str:
        return self.search_input.text()
    
    def is_exact_match(self) -> bool:
        return self.search_mode_combo.currentIndex() == 0
    
    def get_worker_count(self) -> int:
        return self.worker_count.value()
    
    def is_exception_applied(self) -> bool:
        return self.apply_exception_checkbox.isChecked()
    
    def set_search_mode(self, exact_match: bool):
        self.search_mode_combo.setCurrentIndex(0 if exact_match else 1)
    
    def set_worker_count(self, count: int):
        self.worker_count.setValue(count)
    
    def set_exception_applied(self, applied: bool):
        self.apply_exception_checkbox.setChecked(applied)


class DirectoryTreeWidget(QWidget):
    """디렉토리 트리 UI 컴포넌트"""
    
    selection_changed = pyqtSignal()
    parent_folder_requested = pyqtSignal()
    folder_selection_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder_icon = None
        self.excel_icon = None
        self.init_ui()
        self.init_icons()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        dirs_group = QGroupBox('검색할 폴더 및 파일 선택 (Excel, CSV)')
        dirs_layout = QVBoxLayout(dirs_group)
        
        # 폴더 선택 영역
        folder_select_layout = QHBoxLayout()
        
        self.parent_folder_btn = QPushButton('↑')
        self.parent_folder_btn.setToolTip('상위 폴더로 이동')
        self.parent_folder_btn.setFixedWidth(30)
        self.parent_folder_btn.clicked.connect(self.parent_folder_requested.emit)
        folder_select_layout.addWidget(self.parent_folder_btn)
        
        self.root_folder_edit = QLineEdit()
        self.root_folder_edit.setReadOnly(True)
        self.root_folder_edit.setPlaceholderText('루트 폴더를 선택하세요')
        
        self.select_folder_btn = QPushButton('폴더 선택...')
        self.select_folder_btn.clicked.connect(self.folder_selection_requested.emit)
        
        folder_select_layout.addWidget(self.root_folder_edit)
        folder_select_layout.addWidget(self.select_folder_btn)
        dirs_layout.addLayout(folder_select_layout)
        
        # 디렉토리 트리
        self.dir_tree = QTreeWidget()
        self.dir_tree.setHeaderLabels(['폴더'])
        self.dir_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.dir_tree.itemExpanded.connect(self.on_item_expanded)
        self.dir_tree.itemClicked.connect(self.on_item_clicked)
        dirs_layout.addWidget(self.dir_tree)
        
        layout.addWidget(dirs_group)
    
    def init_icons(self):
        """아이콘 초기화"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        folder_icon_path = os.path.join(project_root, "icon", "folder.png")
        excel_icon_path = os.path.join(project_root, "icon", "excel.png")
        
        if os.path.exists(folder_icon_path):
            self.folder_icon = QIcon(folder_icon_path)
        if os.path.exists(excel_icon_path):
            self.excel_icon = QIcon(excel_icon_path)
    
    def on_item_expanded(self, item):
        """트리 아이템 확장 이벤트"""
        if hasattr(self.parent(), 'load_subdirectories'):
            self.parent().load_subdirectories(item)
    
    def on_item_clicked(self, item, column):
        """트리 아이템 클릭 이벤트"""
        self.selection_changed.emit()
    
    def get_selected_items(self):
        return self.dir_tree.selectedItems()
    
    def clear(self):
        self.dir_tree.clear()
    
    def set_root_folder_text(self, text: str):
        self.root_folder_edit.setText(text)
    
    def get_root_folder_text(self) -> str:
        return self.root_folder_edit.text()
    
    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.dir_tree.setEnabled(enabled)


class SearchResultsWidget(QWidget):
    """검색 결과 UI 컴포넌트"""
    
    result_double_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        results_group = QGroupBox('검색 결과')
        results_layout = QVBoxLayout(results_group)
        
        self.result_table = QTableWidget(0, 5)
        self.result_table.setHorizontalHeaderLabels(['파일', '시트', '행', '열', '값'])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.doubleClicked.connect(self.result_double_clicked.emit)
        results_layout.addWidget(self.result_table)
        
        layout.addWidget(results_group)
    
    def add_result(self, file_path: str, sheet_name: str, row: int, col: str, value: str):
        """검색 결과 추가"""
        row_count = self.result_table.rowCount()
        self.result_table.insertRow(row_count)
        
        file_name = os.path.basename(file_path)
        file_item = QTableWidgetItem(file_name)
        file_item.setData(Qt.UserRole, file_path)
        
        self.result_table.setItem(row_count, 0, file_item)
        self.result_table.setItem(row_count, 1, QTableWidgetItem(sheet_name))
        self.result_table.setItem(row_count, 2, QTableWidgetItem(str(row)))
        self.result_table.setItem(row_count, 3, QTableWidgetItem(col))
        self.result_table.setItem(row_count, 4, QTableWidgetItem(value))
    
    def clear_results(self):
        self.result_table.setRowCount(0)
    
    def get_current_row_data(self):
        """현재 선택된 행의 데이터 반환"""
        current_row = self.result_table.currentRow()
        if current_row >= 0:
            file_item = self.result_table.item(current_row, 0)
            file_path = file_item.data(Qt.UserRole)
            sheet_name = self.result_table.item(current_row, 1).text()
            excel_row = int(self.result_table.item(current_row, 2).text())
            return file_path, sheet_name, excel_row
        return None, None, None
    
    def get_result_count(self) -> int:
        return self.result_table.rowCount()


class LogWidget(QWidget):
    """로그 표시 UI 컴포넌트"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        log_group = QGroupBox('로그')
        log_layout = QVBoxLayout(log_group)
        
        self.error_log = QTextEdit()
        self.error_log.setReadOnly(True)
        log_layout.addWidget(self.error_log)
        
        layout.addWidget(log_group)
    
    def append_log(self, message: str):
        """로그 메시지 추가"""
        self.error_log.append(message)
    
    def clear_log(self):
        """로그 지우기"""
        self.error_log.clear()