import os
import sys
import json
import pandas as pd
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                            QPushButton, QLabel, QLineEdit, QFileDialog, QListWidget,
                            QRadioButton, QGroupBox, QHeaderView, QMessageBox, QProgressBar,
                            QTextEdit, QSpinBox, QToolBar, QAction, QCheckBox, QStatusBar,
                            QComboBox, QSplitter, QTreeWidget, QTreeWidgetItem, QMenu,
                            QStyledItemDelegate, QApplication, QStyle, QWidgetAction)
from PyQt5.QtCore import Qt, QEvent, pyqtSignal, QSize, QProcess
from PyQt5.QtGui import QIcon, QTextDocument, QBrush, QColor, QTextCharFormat, QPainter
import multiprocessing as mp
import subprocess
import stat

from search_worker import ParallelSearchWorker
from sheet_viewer import SheetViewer
from search_exception_dialog_improved import SearchExceptionDialogImproved
from plugin_registry import get_plugin_registry

class ResultTreeDelegate(QStyledItemDelegate):
    """결과 트리 전용 델리게이트: 'Name' 컬럼 HTML 렌더링 + 파일 그룹 구분선"""

    SEPARATOR_COLOR = QColor('#CCCCCC')
    SEPARATOR_MARGIN = 8   # px above and below the divider line (total 16px)
    BASE_ROW_HEIGHT = 22   # px for normal rows

    def _is_separator_row(self, index):
        """파일 그룹 구분선이 필요한 행 여부 (최상위 노드 중 첫 번째 제외)"""
        return not index.parent().isValid() and index.row() > 0

    def _content_rect(self, option, index):
        """실제 콘텐츠를 그려야 할 rect 반환 — 구분선 행은 separator margin 아래 상단 정렬"""
        rect = option.rect
        if self._is_separator_row(index):
            # Pin content to just below the separator margin so no gap appears
            # between the file-group label and its child items.
            from PyQt5.QtCore import QRect
            content_top = rect.top() + self.SEPARATOR_MARGIN
            return QRect(rect.left(), content_top, rect.width(), self.BASE_ROW_HEIGHT)
        return rect

    def paint(self, painter, option, index):
        # 최상위(파일) 노드의 두 번째 이후 행 위에 구분선 그리기
        if self._is_separator_row(index) and index.column() == 0:
            tree = self.parent()
            if tree:
                viewport_width = tree.viewport().width()
                painter.save()
                painter.setClipping(False)
                pen = painter.pen()
                pen.setColor(self.SEPARATOR_COLOR)
                pen.setWidth(1)
                painter.setPen(pen)
                y = option.rect.top() + self.SEPARATOR_MARGIN
                painter.drawLine(0, y, viewport_width, y)
                painter.restore()

        # 'Name' 컬럼(0)의 HTML 렌더링
        if index.column() == 0:
            text = index.data(Qt.DisplayRole)
            if text and '<span' in str(text):
                content_rect = self._content_rect(option, index)

                # Draw selection/hover background over the full row first
                opt = option.__class__(option)
                self.initStyleOption(opt, index)
                opt.text = ''
                widget = opt.widget
                style = widget.style() if widget else QApplication.style()
                style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)

                doc = QTextDocument()
                doc.setHtml(str(text))
                doc.setTextWidth(-1)  # No word wrap — render as single line

                painter.save()
                painter.setClipRect(content_rect)
                painter.translate(content_rect.topLeft())
                doc.drawContents(painter)
                painter.restore()

                # Draw ellipsis overlay if content overflows the column width
                if doc.idealWidth() > content_rect.width():
                    fm = painter.fontMetrics()
                    ellipsis_w = fm.horizontalAdvance('...')
                    ell_rect = content_rect.__class__(
                        content_rect.right() - ellipsis_w,
                        content_rect.top(),
                        ellipsis_w,
                        content_rect.height(),
                    )
                    palette = opt.palette
                    if int(option.state) & QStyle.State_Selected:
                        bg = palette.color(palette.Highlight)
                        fg = palette.color(palette.HighlightedText)
                    else:
                        bg = palette.color(palette.Base)
                        fg = palette.color(palette.Text)
                    painter.fillRect(ell_rect, bg)
                    painter.setPen(fg)
                    painter.drawText(ell_rect, Qt.AlignVCenter | Qt.AlignLeft, '...')
                return

        # Non-HTML columns — use content_rect for separator rows to avoid divider overlap
        if self._is_separator_row(index):
            content_rect = self._content_rect(option, index)
            adjusted_option = option.__class__(option)
            adjusted_option.rect = content_rect
            super().paint(painter, adjusted_option, index)
            return

        super().paint(painter, option, index)

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        # File-group separator rows: base height + margin above line + margin below line
        if self._is_separator_row(index):
            return QSize(hint.width(), self.BASE_ROW_HEIGHT + self.SEPARATOR_MARGIN)
        return QSize(hint.width(), self.BASE_ROW_HEIGHT)

class FormatItemWidget(QWidget):
    """드롭다운 한 행: [QCheckBox]  [아이콘 16×16]  [확장자 텍스트]"""

    def __init__(self, icon, ext: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 12, 3)
        layout.setSpacing(6)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        layout.addWidget(self.checkbox)

        icon_label = QLabel()
        icon_label.setFixedSize(16, 16)
        icon_label.setPixmap(icon.pixmap(16, 16))
        icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(icon_label)

        text_label = QLabel(ext)
        text_label.setMinimumWidth(55)
        text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(text_label)

        layout.addStretch()

    def mousePressEvent(self, event):
        """아이콘·텍스트 클릭도 체크박스 토글로 전달"""
        self.checkbox.setChecked(not self.checkbox.isChecked())

    def mouseReleaseEvent(self, event):
        """이벤트를 소비해 QMenu 레벨까지 전파되지 않도록 함"""
        event.accept()


class PersistentCheckMenu(QMenu):
    """QWidgetAction 행 클릭 시 닫히지 않는 QMenu 서브클래스.
    Escape 키 또는 메뉴 외부 클릭 시에만 닫힘."""

    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action is None:
            super().mouseReleaseEvent(event)
        elif isinstance(action, QWidgetAction):
            # 위젯이 이미 이벤트를 처리함 — 메뉴를 닫지 않음
            pass
        elif action.isCheckable():
            action.setChecked(not action.isChecked())
        else:
            super().mouseReleaseEvent(event)


class ExcelSearchApp(QMainWindow):
    def __init__(self, loading_dialog=None):
        super().__init__()
        self.loading_dialog = loading_dialog
        
        # 기본 속성 초기화
        self.files = []
        self.search_worker = None
        self.file_sheet_data = {}  # {file_path: {sheet_name: dataframe}}
        self.cached_row_data = {}  # 검색 결과에 대한 캐시된 행 데이터 저장 {(file_path, sheet_name, row_idx): (header_data, row_data)}
        self.actual_root_path = ""  # 실제 루트 폴더 경로 (간소화된 표시와 별도로 저장)
        
        # 설정 파일 경로 (config 폴더로 이동)
        self.settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "excel_finder_settings.txt")

        # 필터 설정 JSON 파일 경로
        self.filter_settings_file = self._get_filter_config_path()
        
        # 단계별 초기화
        self._initialize_step_by_step()
    
    def _initialize_step_by_step(self):
        """단계별 초기화 (로딩 화면과 연동)"""
        # 1단계: UI 초기화
        if self.loading_dialog:
            self.loading_dialog.update_progress(82, "UI 컴포넌트 생성 중...")
        self.init_ui()
        
        # 2단계: 설정 로드
        if self.loading_dialog:
            self.loading_dialog.update_progress(85, "설정 파일 로딩 중...")
        self.load_settings()
        
        # 3단계: 경고 메시지 설정 (config.py에서 이미 처리됨)
        if self.loading_dialog:
            self.loading_dialog.update_progress(88, "경고 처리 설정 중...", "pandas 및 라이브러리 설정")
        
        # 4단계: 이벤트 핸들러 연결
        if self.loading_dialog:
            self.loading_dialog.update_progress(91, "이벤트 핸들러 연결 중...")
        self.search_input.textChanged.connect(self.update_search_button_state)
        self.closeEvent = self.on_close_event
        
        # 5단계: 검색 버튼 상태 초기화
        if self.loading_dialog:
            self.loading_dialog.update_progress(94, "UI 상태 초기화 중...")
        self.update_search_button_state()
        self.update_selection_status()  # 초기 선택 상태 설정
        
        # 6단계: 플러그인 탐색 및 형식 필터 구성
        if self.loading_dialog:
            self.loading_dialog.update_progress(95, "플러그인 탐색 중...", "파일 형식 플러그인")
        get_plugin_registry().discover()
        self._populate_format_filter()

        # 플러그인 로드 오류를 error_log에 기록 (의존 패키지 미설치 등)
        load_errors = get_plugin_registry().load_errors()
        if load_errors:
            for pid, err in load_errors.items():
                self.error_log.append(
                    f"<div style='color:#e67e22; margin-top:2px;'>"
                    f"[플러그인 로드 실패] <b>{pid}</b>: {err}</div>"
                )

        # 7단계: 마지막 사용 폴더 복원
        if self.loading_dialog:
            self.loading_dialog.update_progress(97, "마지막 설정 복원 중...", "폴더 정보 로딩")
        self.load_drives()
    
    def on_close_event(self, event):
        """애플리케이션 종료 시 설정 저장"""
        self.save_settings()
        event.accept()
    
    def load_settings(self):
        """애플리케이션 설정 로드"""
        # 기본값 설정
        self.last_directory = ""
        self.search_mode_exact = True
        self.worker_count_value = min(4, mp.cpu_count())
        self.saved_files = []
        self.excluded_headers = []
        self.excluded_if_not_empty = []
        self.excluded_paths = []  # 경로 제외 필터
        self.excluded_files = []  # 파일 제외 필터
        self.excluded_sheets = []  # 시트 제외 필터
        self.apply_exception = True  # 검색 예외 처리 적용 기본값
        self.case_sensitive = False  # 대소문자 구분 기본값
        self.expanded_paths = []  # TreeWidget의 확장된 경로 저장
        
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = {}
                    for line in f:
                        line = line.strip()
                        if line and '=' in line:
                            key, value = line.split('=', 1)
                            settings[key.strip()] = value.strip()
                    
                    # 마지막 디렉토리 로드
                    if 'last_directory' in settings:
                        directory = settings['last_directory']
                        if os.path.isdir(directory):
                            self.last_directory = directory
                    
                    # 검색 모드 로드
                    if 'search_mode_exact' in settings:
                        self.search_mode_exact = settings['search_mode_exact'].lower() == 'true'
                        self.search_mode_btn.setChecked(self.search_mode_exact)
                    
                    # 병렬 처리 수 로드
                    if 'worker_count' in settings:
                        try:
                            count = int(settings['worker_count'])
                            if 1 <= count <= mp.cpu_count():
                                self.worker_count_value = count
                                self.worker_count.setValue(count)
                        except ValueError:
                            pass
                    
                    # 필터 설정은 별도 JSON 파일에서 로드되므로 여기서는 제외
                    
                    # 검색 예외 처리 적용 여부 로드 (항상 활성)
                    if 'apply_exception' in settings:
                        self.apply_exception = settings['apply_exception'].lower() == 'true'
                    else:
                        self.apply_exception = True  # 기본값: 항상 적용

                    # 대소문자 구분 설정 로드
                    if 'case_sensitive' in settings:
                        self.case_sensitive = settings['case_sensitive'].lower() == 'true'
                        self.case_sensitive_btn.setChecked(self.case_sensitive)
                        
                    # TreeWidget의 확장된 경로 로드
                    if 'expanded_paths' in settings:
                        self.expanded_paths = settings['expanded_paths'].split('|') if settings['expanded_paths'] else []

                    # 검색 키워드 로드
                    if 'search_keyword' in settings:
                        self.search_input.setText(settings['search_keyword'])

                    # 필터 활성화 상태 로드
                    if 'filter_enabled' in settings:
                        self.filter_enabled_btn.setChecked(settings['filter_enabled'].lower() == 'true')

                    # 형식 필터 상태 로드 (_populate_format_filter 에서 적용됨)
                    if 'format_extensions' in settings:
                        val = settings['format_extensions'].strip()
                        self._saved_format_extensions = set(e.strip().lower() for e in val.split(',') if e.strip())
                    else:
                        self._saved_format_extensions = None  # None = 전체 선택(기본값)
                    # 이전 세션에서 알려진 모든 확장자 (새 플러그인 구분용)
                    if 'format_extensions_known' in settings:
                        val_known = settings['format_extensions_known'].strip()
                        self._saved_all_known_extensions = set(e.strip().lower() for e in val_known.split(',') if e.strip())
                    else:
                        self._saved_all_known_extensions = None

                    # 컬럼 넓이 로드
                    if 'column_widths' in settings:
                        try:
                            widths = [int(w) for w in settings['column_widths'].split(',')]
                            if len(widths) == 3:  # 3개 컬럼
                                for i, width in enumerate(widths):
                                    self.result_tree.setColumnWidth(i, width)
                            else:
                                self.set_default_column_widths()  # 컬럼 수 불일치 시 기본값
                        except ValueError:
                            self.set_default_column_widths()  # 파싱 실패 시 기본값 설정
                    else:
                        self.set_default_column_widths()  # 설정이 없으면 기본값 설정
            else:
                # 설정 파일이 없는 경우 (첫 실행) 기본값 설정
                self.set_default_column_widths()
        except Exception as e:
            print(f"설정 로드 중 오류: {e}")
            # 오류 발생 시에도 기본 컬럼 넓이 설정
            self.set_default_column_widths()

        # JSON 형식의 필터 설정 로드 (기존 텍스트 설정을 덮어씀)
        self._load_filters_from_json()
    
    def save_settings(self):
        """애플리케이션 설정 저장"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                # 마지막 디렉토리 저장
                f.write(f"last_directory={self.last_directory}\n")
                
                # 검색 모드 저장
                f.write(f"search_mode_exact={self.search_mode_btn.isChecked()}\n")
                
                # 병렬 처리 수 저장
                f.write(f"worker_count={self.worker_count.value()}\n")
                
                # 필터 설정은 별도 JSON 파일로 저장되므로 여기서는 제외
                
                # 검색 예외 처리 적용 여부 저장 (항상 활성)
                f.write(f"apply_exception=True\n")

                # 대소문자 구분 설정 저장
                f.write(f"case_sensitive={self.case_sensitive_btn.isChecked()}\n")

                # TreeWidget의 확장된 경로 저장
                expanded_paths = self.get_expanded_paths()
                f.write(f"expanded_paths={('|').join(expanded_paths)}\n")

                # 검색 키워드 저장
                f.write(f"search_keyword={self.search_input.text()}\n")

                # 필터 활성화 상태 저장
                f.write(f"filter_enabled={self.filter_enabled_btn.isChecked()}\n")

                # 형식 필터 상태 저장 (체크된 것 + 이 세션에서 알려진 모든 확장자)
                checked_exts = ','.join(sorted(ext for ext, a in self._format_actions.items() if a.isChecked()))
                f.write(f"format_extensions={checked_exts}\n")
                all_known_exts = ','.join(sorted(self._format_actions.keys()))
                f.write(f"format_extensions_known={all_known_exts}\n")

                # 컬럼 넓이 저장
                column_widths = []
                for i in range(5):  # 5개 컬럼
                    column_widths.append(str(self.result_tree.columnWidth(i)))
                f.write(f"column_widths={','.join(column_widths)}\n")

            # JSON 형식으로 필터 설정 저장
            self._save_filters_to_json()

        except Exception as e:
            print(f"설정 저장 중 오류: {e}")

    def set_default_column_widths(self):
        """기본 컬럼 넓이 설정"""
        self.result_tree.setColumnWidth(0, 300)  # Name (파일명/시트명/검색값)
        self.result_tree.setColumnWidth(1, 60)   # 행 번호
        self.result_tree.setColumnWidth(2, 140)  # 열명 (열번호)

    def get_expanded_paths(self):
        """TreeWidget에서 확장된 모든 경로를 가져옴"""
        expanded_paths = []
        
        def traverse_tree(item, current_path):
            if item.isExpanded():
                expanded_paths.append(current_path)
            
            for i in range(item.childCount()):
                child = item.child(i)
                # 상대 경로 구성 (루트 폴더 기준)
                child_path = os.path.join(current_path, child.text(0))
                traverse_tree(child, child_path)
        
        # 루트 아이템 순회
        for i in range(self.dir_tree.topLevelItemCount()):
            root_item = self.dir_tree.topLevelItem(i)
            # 루트 아이템의 경우 상대 경로 사용 (실제 경로가 아닌 표시 이름)
            root_path = root_item.text(0)
            traverse_tree(root_item, root_path)
        
        return expanded_paths

    def simplify_path_display(self, full_path):
        """경로 표시를 간소화 (상위 경로는 ...으로 표시)"""
        if not full_path:
            return full_path

        # 경로를 분리
        parts = full_path.replace('\\', '/').split('/')

        # 최소 2개 이상의 경로 부분이 있을 때만 간소화
        if len(parts) >= 3:
            # 마지막 폴더와 그 상위 폴더만 표시
            simplified = f"...\\{parts[-2]}\\{parts[-1]}"
            return simplified
        else:
            return full_path

    def init_ui(self):
        # 메인 윈도우 설정
        self.setWindowTitle('ExcelFinder v3.1')
        self.setGeometry(100, 100, 1200, 700)
        
        # 윈도우 아이콘 설정 (icon 폴더는 루트에 있음)
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # 상태 바 추가
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        
        # 상태 바에 진행 상황 표시를 위한 위젯 생성 (검색 시에만 표시)
        self.status_label = QLabel("선택된 항목이 없습니다.")
        self.status_progress_bar = QProgressBar()
        self.status_progress_bar.setFixedWidth(200)
        self.status_progress_bar.setVisible(False)  # 초기에는 숨김
        
        # 상태 바에 위젯 추가
        self.statusBar.addWidget(self.status_label, 1)  # 1은 stretch factor
        self.statusBar.addPermanentWidget(self.status_progress_bar)
        
        # 중앙 위젯 설정
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 상단 영역 (검색 옵션 + 디렉토리 트리 + 검색 결과)
        top_splitter = QSplitter(Qt.Horizontal)
        
        # 좌측 영역 (검색 옵션 + 디렉토리 트리)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 검색 옵션 영역 (좌측 상단)
        search_options = QGroupBox('검색 옵션')
        options_layout = QVBoxLayout(search_options)
        
        # 첫 번째 행: 옵션 버튼들 - 검색 입력 필드
        first_line_layout = QHBoxLayout()

        # 필터 활성화/비활성화 아이콘 버튼
        self.filter_enabled_btn = QPushButton()
        self.filter_enabled_btn.setIconSize(QSize(20, 20))
        self.filter_enabled_btn.setCheckable(True)
        self.filter_enabled_btn.setChecked(False)  # 기본값: 필터 비활성화
        self.filter_enabled_btn.setToolTip('필터 적용')
        self.filter_enabled_btn.setFixedSize(24, 24)

        # 상태에 따른 아이콘 설정
        self._update_filter_icon()
        self.filter_enabled_btn.toggled.connect(self._update_filter_icon)
        self.filter_enabled_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                border-radius: 2px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 2px;
            }
            QPushButton:checked {
                background-color: rgba(0, 0, 0, 0.1);
                border-radius: 2px;
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 0.15);
                border-radius: 2px;
            }
            QPushButton:checked:pressed {
                background-color: rgba(0, 0, 0, 0.2);
                border-radius: 2px;
            }
        """)
        # 검색 모드 아이콘 버튼 (일치/포함 토글)
        self.search_mode_btn = QPushButton()
        match_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "match.svg")
        if os.path.exists(match_icon_path):
            self.search_mode_btn.setIcon(QIcon(match_icon_path))
        self.search_mode_btn.setIconSize(QSize(20, 20))
        self.search_mode_btn.setCheckable(True)
        self.search_mode_btn.setChecked(True)  # 기본값: 일치 모드
        self.search_mode_btn.setToolTip('일치/포함')
        self.search_mode_btn.setFixedSize(24, 24)
        self.search_mode_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                border-radius: 2px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 2px;
            }
            QPushButton:checked {
                background-color: rgba(0, 0, 0, 0.1);
                border-radius: 2px;
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 0.15);
                border-radius: 2px;
            }
            QPushButton:checked:pressed {
                background-color: rgba(0, 0, 0, 0.2);
                border-radius: 2px;
            }
        """)
        # 대소문자 구분 아이콘 버튼
        self.case_sensitive_btn = QPushButton()
        self.case_sensitive_btn.setIconSize(QSize(20, 20))
        self.case_sensitive_btn.setCheckable(True)
        self.case_sensitive_btn.setChecked(False)  # 기본값: 대소문자 구분 안함
        self.case_sensitive_btn.setToolTip('대소문자 구분')
        self.case_sensitive_btn.setFixedSize(24, 24)

        # 상태에 따른 아이콘 설정
        self._update_case_sensitive_icon()
        self.case_sensitive_btn.toggled.connect(self._update_case_sensitive_icon)
        self.case_sensitive_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                border-radius: 2px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 2px;
            }
            QPushButton:checked {
                background-color: rgba(0, 0, 0, 0.1);
                border-radius: 2px;
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 0.15);
                border-radius: 2px;
            }
            QPushButton:checked:pressed {
                background-color: rgba(0, 0, 0, 0.2);
                border-radius: 2px;
            }
        """)
        # 검색 입력 필드 (오른쪽에 배치)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색할 키워드를 입력하세요")

        # 파일 형식 필터 드롭다운 버튼 (검색 입력 왼쪽)
        self.format_filter_btn = QPushButton("형식 ▾")
        self.format_filter_btn.setToolTip("검색할 파일 형식 선택")
        self.format_filter_btn.setFixedHeight(24)
        self.format_filter_btn.clicked.connect(self._show_format_menu)
        self._format_menu = PersistentCheckMenu(self)
        self._format_actions = {}  # ext -> QAction

        first_line_layout.addWidget(self.format_filter_btn)
        first_line_layout.addWidget(self.search_input)

        options_layout.addLayout(first_line_layout)

        # 두 번째 행: 필터 설정 버튼 + 옵션 버튼들
        second_line_layout = QHBoxLayout()

        # 필터 설정 표준 버튼 (아이콘 + 텍스트)
        self.filter_settings_btn = QPushButton("필터 설정")
        filter_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "filter.svg")
        if os.path.exists(filter_icon_path):
            self.filter_settings_btn.setIcon(QIcon(filter_icon_path))
        self.filter_settings_btn.setIconSize(QSize(20, 20))
        self.filter_settings_btn.clicked.connect(self.show_search_exception_dialog)

        second_line_layout.addWidget(self.filter_settings_btn)
        second_line_layout.addWidget(self.filter_enabled_btn)
        second_line_layout.addWidget(self.search_mode_btn)
        second_line_layout.addWidget(self.case_sensitive_btn)
        second_line_layout.addStretch()

        options_layout.addLayout(second_line_layout)

        # 병렬 처리 옵션 추가 (세 번째 행)
        parallel_options = QHBoxLayout()
        parallel_options.addWidget(QLabel('병렬 처리 수:'))

        # 병렬 처리 수 입력 위젯과 최대 CPU 수 표시를 포함하는 컨테이너
        worker_container = QWidget()
        worker_layout = QHBoxLayout(worker_container)
        worker_layout.setContentsMargins(0, 0, 0, 0)
        worker_layout.setSpacing(5)

        self.worker_count = QSpinBox()
        self.worker_count.setMinimum(1)
        self.worker_count.setMaximum(mp.cpu_count())
        self.worker_count.setValue(min(4, mp.cpu_count()))  # 기본값: 최대 4개, CPU 코어 수를 넘지 않음
        self.worker_count.setToolTip(f'사용 가능한 CPU 코어: {mp.cpu_count()}개')

        # 최대 CPU 수 표시 레이블
        max_cpu_label = QLabel(f"(최대: {mp.cpu_count()})")

        worker_layout.addWidget(self.worker_count)
        worker_layout.addWidget(max_cpu_label)
        worker_layout.addStretch()  # 스트레치를 추가하여 너비에 따라 조정되도록 함

        parallel_options.addWidget(worker_container, 1)  # 스트레치 팩터 1 추가
        options_layout.addLayout(parallel_options)

        # 검색 버튼 (최하단)
        self.search_stop_btn = QPushButton('검색')
        self.search_stop_btn.clicked.connect(self.toggle_search)
        options_layout.addWidget(self.search_stop_btn)

        left_layout.addWidget(search_options)
        
        # 디렉토리 트리 영역 (좌측 하단)
        dirs_group = QGroupBox('검색 범위 지정')
        dirs_layout = QVBoxLayout(dirs_group)
        
        # 폴더 선택 버튼 영역
        folder_select_layout = QHBoxLayout()

        # 상위 폴더로 이동 아이콘 버튼
        self.parent_folder_btn = QPushButton()
        up_arrow_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "up-arrow.svg")
        if os.path.exists(up_arrow_icon_path):
            self.parent_folder_btn.setIcon(QIcon(up_arrow_icon_path))
        self.parent_folder_btn.setIconSize(QSize(14, 14))
        self.parent_folder_btn.setToolTip('상위 폴더로 이동')
        self.parent_folder_btn.setFixedSize(20, 20)
        self.parent_folder_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                border-radius: 2px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 2px;
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 0.15);
                border-radius: 2px;
            }
        """)
        self.parent_folder_btn.clicked.connect(self.navigate_to_parent_folder)
        folder_select_layout.addWidget(self.parent_folder_btn)

        # 폴더 검색 아이콘 버튼
        self.select_folder_btn = QPushButton()
        search_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "search.svg")
        if os.path.exists(search_icon_path):
            self.select_folder_btn.setIcon(QIcon(search_icon_path))
        self.select_folder_btn.setIconSize(QSize(14, 14))
        self.select_folder_btn.setToolTip('폴더 선택')
        self.select_folder_btn.setFixedSize(20, 20)
        self.select_folder_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                border-radius: 2px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 2px;
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 0.15);
                border-radius: 2px;
            }
        """)
        self.select_folder_btn.clicked.connect(self.select_root_folder)
        folder_select_layout.addWidget(self.select_folder_btn)

        # 폴더 경로 입력 필드
        self.root_folder_edit = QLineEdit()
        self.root_folder_edit.setReadOnly(True)
        self.root_folder_edit.setPlaceholderText('루트 폴더를 선택하세요')
        folder_select_layout.addWidget(self.root_folder_edit)

        # 선택된 폴더를 루트로 사용 아이콘 버튼
        self.use_selected_folder_btn = QPushButton()
        check_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "check.svg")
        if os.path.exists(check_icon_path):
            self.use_selected_folder_btn.setIcon(QIcon(check_icon_path))
        self.use_selected_folder_btn.setIconSize(QSize(14, 14))
        self.use_selected_folder_btn.setToolTip('선택된 폴더를 루트로 사용')
        self.use_selected_folder_btn.setFixedSize(20, 20)
        self.use_selected_folder_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                border-radius: 2px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 2px;
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 0.15);
                border-radius: 2px;
            }
        """)
        self.use_selected_folder_btn.clicked.connect(self.use_selected_folder_as_root)
        folder_select_layout.addWidget(self.use_selected_folder_btn)

        dirs_layout.addLayout(folder_select_layout)
        
        # 디렉토리 트리 위젯 (다중 선택 가능)
        self.dir_tree = QTreeWidget()
        self.dir_tree.setHeaderLabels(['폴더'])
        self.dir_tree.setHeaderHidden(True)  # 헤더 숨기기
        self.dir_tree.setSelectionMode(QTreeWidget.ExtendedSelection)  # 다중 선택 모드 설정
        self.dir_tree.setContextMenuPolicy(Qt.CustomContextMenu)  # 사용자 정의 컨텍스트 메뉴
        self.dir_tree.customContextMenuRequested.connect(self.show_tree_context_menu)  # 컨텍스트 메뉴 연결
        self.dir_tree.itemExpanded.connect(self.on_item_expanded)
        self.dir_tree.itemClicked.connect(self.on_item_clicked)
        self.dir_tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.dir_tree.itemSelectionChanged.connect(self.update_selection_status)
        dirs_layout.addWidget(self.dir_tree)


        # 디렉토리 트리 영역을 좌측 영역에 추가
        left_layout.addWidget(dirs_group)
        
        # 우측 영역 (검색 결과)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        results_group = QGroupBox('검색 결과')
        results_layout = QVBoxLayout(results_group)
        
        self.result_tree = QTreeWidget()
        self.result_tree.setColumnCount(3)
        self.result_tree.setHeaderLabels(['이름', '번호', '타입'])

        # 전체 트리에 델리게이트 적용 (HTML 렌더링 + 파일 그룹 구분선)
        result_tree_delegate = ResultTreeDelegate(self.result_tree)
        self.result_tree.setItemDelegate(result_tree_delegate)

        # 컬럼 넓이를 사용자가 수동으로 조절할 수 있게 설정
        self.result_tree.header().setSectionResizeMode(QHeaderView.Interactive)
        self.result_tree.header().setStretchLastSection(True)
        self.result_tree.header().setMinimumSectionSize(20)

        self.result_tree.setUniformRowHeights(False)  # Allow separator rows to have extra height for divider margins
        self.result_tree.setWordWrap(False)           # Disable word wrap at the view level
        self.result_tree.setTextElideMode(Qt.ElideRight)  # Elide non-HTML columns at right

        self.result_tree.setSelectionBehavior(QTreeWidget.SelectRows)
        self.result_tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        self.result_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.result_tree.customContextMenuRequested.connect(self.show_results_context_menu)
        self.result_tree.itemDoubleClicked.connect(self.show_sheet_data)
        results_layout.addWidget(self.result_tree)

        # 기본 컬럼 넓이는 설정 로드 후에 처리됨 (load_settings에서 처리)
        
        right_layout.addWidget(results_group)
        
        # 스플리터에 좌/우 위젯 추가
        top_splitter.addWidget(left_widget)
        top_splitter.addWidget(right_widget)
        top_splitter.setStretchFactor(0, 1)  # 좌측 영역 스트레치 팩터
        top_splitter.setStretchFactor(1, 3)  # 우측 영역 스트레치 팩터

        # 패널이 사라지지 않도록 최소 크기 설정 및 접기 방지
        top_splitter.setSizes([200, 600])  # 초기 크기 설정
        left_widget.setMinimumWidth(150)    # 좌측 패널 최소 너비
        right_widget.setMinimumWidth(300)   # 우측 패널 최소 너비
        top_splitter.setCollapsible(0, False)  # 좌측 패널 접기 방지
        top_splitter.setCollapsible(1, False)  # 우측 패널 접기 방지
        
        # 로그 영역 추가
        log_group = QGroupBox('로그')
        log_layout = QVBoxLayout(log_group)
        self.error_log = QTextEdit()
        self.error_log.setReadOnly(True)
        log_layout.addWidget(self.error_log)

        # 상단 영역과 로그 영역 사이에 수직 스플리터 추가
        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(log_group)
        main_splitter.setStretchFactor(0, 3)  # 상단 영역 스트레치 팩터
        main_splitter.setStretchFactor(1, 1)  # 로그 영역 스트레치 팩터

        # 패널이 사라지지 않도록 최소 크기 설정 및 접기 방지
        main_splitter.setSizes([400, 100])  # 초기 크기 설정
        top_splitter.setMinimumHeight(250)   # 상단 패널 최소 높이
        log_group.setMinimumHeight(80)       # 로그 패널 최소 높이

        # 메인 레이아웃에 스플리터 추가
        main_layout.addWidget(main_splitter)
    
    def show_search_exception_dialog(self):
        """검색 예외 처리 다이얼로그 표시"""
        dialog = SearchExceptionDialogImproved(self, self.excluded_headers, self.excluded_if_not_empty,
                                              self.excluded_paths, self.excluded_files, self.excluded_sheets)
        dialog.show()

    # ── 파일 형식 필터 드롭다운 ─────────────────────────────────────────────

    def _populate_format_filter(self):
        """플러그인 레지스트리 기반으로 형식 필터 메뉴 구성 (discover() 후 호출)"""
        self._format_menu.clear()
        self._format_actions.clear()

        plugins = get_plugin_registry().all_plugins()
        if not plugins:
            return

        if not hasattr(self, 'folder_icon'):
            self.init_icons()

        # ── "전체 선택" 행 (QWidgetAction, 아이콘 없음) ──────────────────────
        sa_widget = QWidget()
        sa_layout = QHBoxLayout(sa_widget)
        sa_layout.setContentsMargins(6, 3, 12, 3)
        sa_layout.setSpacing(6)
        self._select_all_checkbox = QCheckBox("전체 선택")
        self._select_all_checkbox.setChecked(True)
        sa_layout.addWidget(self._select_all_checkbox)
        sa_layout.addStretch()
        sa_wa = QWidgetAction(self._format_menu)
        sa_wa.setDefaultWidget(sa_widget)
        self._format_menu.addAction(sa_wa)
        self._format_menu.addSeparator()

        # ── 저장된 형식 복원 ──────────────────────────────────────────────────
        saved = getattr(self, '_saved_format_extensions', None)
        saved_known = getattr(self, '_saved_all_known_extensions', None)

        for plugin in plugins:
            for ext in sorted(plugin.supported_extensions()):
                item_widget = FormatItemWidget(self._get_file_icon(ext), ext)
                cb = item_widget.checkbox

                if saved is not None and saved_known is not None:
                    cb.setChecked(ext.lower() in saved if ext.lower() in saved_known else True)
                elif saved is not None:
                    cb.setChecked(ext.lower() in saved)
                else:
                    cb.setChecked(True)

                cb.stateChanged.connect(lambda _state, a=cb: self._on_format_action_toggled(a))

                wa = QWidgetAction(self._format_menu)
                wa.setDefaultWidget(item_widget)
                self._format_menu.addAction(wa)
                self._format_actions[ext.lower()] = cb

        # 전체 선택 상태 동기화
        self._sync_select_all_action(self._select_all_checkbox)
        self._select_all_checkbox.stateChanged.connect(
            lambda state: self._toggle_all_formats(state == Qt.Checked)
        )
        self._update_format_btn_label()

    def _show_format_menu(self):
        """형식 필터 메뉴 표시"""
        btn = self.format_filter_btn
        self._format_menu.exec_(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _on_format_action_toggled(self, changed_action):
        """개별 형식 체크 변경 시 '전체 선택' 상태 동기화"""
        if hasattr(self, '_select_all_checkbox'):
            self._sync_select_all_action(self._select_all_checkbox)
        self._update_format_btn_label()

    def _toggle_all_formats(self, checked):
        """전체 선택/해제"""
        for action in self._format_actions.values():
            action.blockSignals(True)
            action.setChecked(checked)
            action.blockSignals(False)
        self._update_format_btn_label()

    def _sync_select_all_action(self, select_all_action):
        """모든 형식이 체크됐으면 전체선택도 체크"""
        all_checked = all(a.isChecked() for a in self._format_actions.values())
        select_all_action.blockSignals(True)
        select_all_action.setChecked(all_checked)
        select_all_action.blockSignals(False)

    def _update_format_btn_label(self):
        """선택된 형식을 버튼 레이블에 반영"""
        if not self._format_actions:
            self.format_filter_btn.setText("형식 ▾")
            return
        checked_set = {ext for ext, cb in self._format_actions.items() if cb.isChecked()}
        if len(checked_set) == len(self._format_actions):
            self.format_filter_btn.setText("전체 ▾")
        elif not checked_set:
            self.format_filter_btn.setText("없음 ▾")
        else:
            # 메뉴 등록 순서(삽입 순) 기준으로 첫 번째 체크된 확장자 사용
            first = next(ext for ext in self._format_actions if ext in checked_set)
            extra = len(checked_set) - 1
            label = f"{first} +{extra}" if extra > 0 else first
            self.format_filter_btn.setText(f"{label} ▾")

    def _get_active_extensions(self):
        """현재 체크된 확장자 튜플 반환. 비어 있으면 모든 지원 형식 반환."""
        if not self._format_actions:
            return get_plugin_registry().all_supported_extensions()
        checked = tuple(ext for ext, a in self._format_actions.items() if a.isChecked())
        return checked if checked else get_plugin_registry().all_supported_extensions()

    # ── 끝 ─────────────────────────────────────────────────────────────────

    def update_selection_status(self):
        """선택된 항목 상태 업데이트 (상태 바에 표시)"""
        selected_items = self.dir_tree.selectedItems()
        count = len(selected_items)

        if count == 0:
            self.status_label.setText("선택된 항목이 없습니다.")
        elif count == 1:
            item = selected_items[0]
            item_text = item.text(0)

            # 파일인지 폴더인지 확인
            item_data = item.data(0, Qt.UserRole)
            if item_data and item_data.get('is_file'):
                # 파일인 경우
                file_name = os.path.splitext(item_text)[0]
                file_ext = os.path.splitext(item_text)[1]
                self.status_label.setText(f" {file_name}{file_ext} 선택됨")
            else:
                # 폴더인 경우
                self.status_label.setText(f" {item_text} 선택됨")
        else:
            # 다중 선택의 경우
            first_item = selected_items[0]
            first_text = first_item.text(0)

            # 첫 번째 항목이 파일인지 폴더인지 확인
            item_data = first_item.data(0, Qt.UserRole)
            if item_data and item_data.get('is_file'):
                # 파일인 경우
                file_name = os.path.splitext(first_text)[0]
                file_ext = os.path.splitext(first_text)[1]
                self.status_label.setText(f" {file_name}{file_ext} 외 {count-1}개 선택됨")
            else:
                # 폴더인 경우
                self.status_label.setText(f" {first_text} 외 {count-1}개 선택됨")
    
    def update_search_button_state(self):
        """검색 버튼 활성화/비활성화 상태 업데이트"""
        # 검색 중이 아닐 때만 버튼 상태 업데이트
        if not hasattr(self, 'is_searching') or not self.is_searching:
            # 검색 버튼은 항상 활성화 (키워드와 파일/폴더 선택은 버튼 클릭 시 확인)
            self.search_stop_btn.setEnabled(True)
            self.search_stop_btn.setText('검색')
    
    def select_root_folder(self):
        """루트 폴더 선택 다이얼로그"""
        # 마지막으로 사용한 디렉토리가 있으면 해당 위치에서 시작
        start_directory = self.last_directory if self.last_directory else ""
        
        folder = QFileDialog.getExistingDirectory(self, '루트 폴더 선택', start_directory)
        if folder:
            # 선택한 폴더 경로 저장
            self.last_directory = folder
            self.actual_root_path = folder
            self.root_folder_edit.setText(self.simplify_path_display(folder))

            # 디렉토리 트리 업데이트
            self.load_directory_tree(folder)
    
    def load_drives(self):
        """초기 상태에서 드라이브 목록 로드 (이제 사용하지 않음)"""
        # 마지막으로 사용한 디렉토리가 있으면 해당 디렉토리 로드
        if self.last_directory and os.path.isdir(self.last_directory):
            self.actual_root_path = self.last_directory
            self.root_folder_edit.setText(self.simplify_path_display(self.last_directory))
            self.load_directory_tree(self.last_directory)
    
    def load_directory_tree(self, root_folder):
        """지정된 루트 폴더의 디렉토리 트리 로드"""
        if not os.path.isdir(root_folder):
            return
            
        self.dir_tree.clear()
        
        # 루트 폴더를 트리에 추가
        root_name = os.path.basename(root_folder) or root_folder  # 루트 폴더 이름 (없으면 전체 경로)
        root_item = QTreeWidgetItem(self.dir_tree, [root_name])
        root_item.setData(0, Qt.UserRole, {'path': root_folder, 'is_file': False})
        
        # 하위 폴더 로드
        self.load_subdirectories(root_item)
        
        # 루트 아이템 확장
        root_item.setExpanded(True)
        
        # 저장된 확장 상태 복원
        self.restore_expanded_state()
    
    def restore_expanded_state(self):
        """저장된 확장 상태를 복원"""
        if not self.expanded_paths:
            return
            
        # 확장할 경로 목록을 순회
        for path in self.expanded_paths:
            # 경로 분할
            parts = path.split(os.sep)
            if not parts:
                continue
                
            # 루트 아이템 찾기
            root_item = None
            for i in range(self.dir_tree.topLevelItemCount()):
                item = self.dir_tree.topLevelItem(i)
                if item.text(0) == parts[0]:
                    root_item = item
                    break
                    
            if not root_item:
                continue
                
            # 경로를 따라 아이템 확장
            current_item = root_item
            current_path = parts[0]
            
            # 루트 아이템 확장 (하위 폴더 로드)
            if not current_item.isExpanded():
                self.load_subdirectories(current_item)
                current_item.setExpanded(True)
                
            # 나머지 경로 확장
            for i in range(1, len(parts)):
                found = False
                for j in range(current_item.childCount()):
                    child = current_item.child(j)
                    if child.text(0) == parts[i]:
                        current_item = child
                        current_path = os.path.join(current_path, parts[i])
                        
                        # 하위 폴더 로드 및 확장
                        if not current_item.isExpanded():
                            self.load_subdirectories(current_item)
                            current_item.setExpanded(True)
                            
                        found = True
                        break
                        
                if not found:
                    break
    
    def on_item_expanded(self, item):
        """트리 아이템이 확장될 때 호출되는 이벤트 핸들러"""
        self.load_subdirectories(item)
    
    def on_item_clicked(self, item, column):
        """트리 아이템이 클릭될 때 호출되는 이벤트 핸들러"""
        # 아이템이 파일인지 폴더인지 확인
        item_data = item.data(0, Qt.UserRole)
        is_file = item_data.get('is_file', False) if isinstance(item_data, dict) else False
        
        if not is_file:
            # 폴더인 경우 선택된 디렉토리 경로 저장
            self.last_directory = self.get_full_path(item)
        
        # 검색 버튼 상태 업데이트 (파일이든 폴더든 선택 가능)
        self.update_search_button_state()

    def on_item_double_clicked(self, item, column):
        """트리 아이템이 더블클릭될 때 호출되는 이벤트 핸들러 - 파일인 경우 열기"""
        try:
            # 아이템이 파일인지 확인
            item_data = item.data(0, Qt.UserRole)
            is_file = item_data.get('is_file', False) if isinstance(item_data, dict) else False

            if is_file:
                # 파일인 경우 파일 열기
                item_path = self.get_full_path(item)
                self.safe_open_file_or_folder(item_path)
        except Exception as e:
            QMessageBox.critical(self, '오류', f'파일을 열 수 없습니다: {str(e)}')

    def get_full_path(self, item):
        """트리 아이템의 전체 경로 반환"""
        # 루트 아이템인 경우 (부모가 없는 경우)
        if item.parent() is None:
            # 루트 폴더 경로 반환 (UserRole에 저장된 전체 경로)
            item_data = item.data(0, Qt.UserRole)
            return item_data.get('path') if isinstance(item_data, dict) else item_data
        
        # 하위 아이템인 경우
        path_parts = []
        current_item = item
        
        # 아이템 계층 구조를 따라 올라가면서 경로 구성
        while current_item is not None:
            if current_item.parent() is None:
                # 루트 아이템에 도달하면 UserRole에 저장된 전체 경로 사용
                root_data = current_item.data(0, Qt.UserRole)
                root_path = root_data.get('path') if isinstance(root_data, dict) else root_data
                return os.path.join(root_path, *reversed(path_parts))
            else:
                # 중간 아이템은 이름만 사용
                path_parts.append(current_item.text(0))
            
            current_item = current_item.parent()
        
        # 여기까지 오면 오류 (루트 아이템을 찾지 못한 경우)
        return ""
    
    def init_icons(self):
        """아이콘 초기화"""
        icon_base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon")

        self.folder_icon = QIcon(os.path.join(icon_base, "folder.svg"))
        self.excel_icon = QIcon(os.path.join(icon_base, "ms-excel.svg"))
        self.csv_icon = QIcon(os.path.join(icon_base, "csv.svg"))
        self.sheet_icon = QIcon(os.path.join(icon_base, "sheet.svg"))
        self.result_icon = QIcon(os.path.join(icon_base, "row.svg"))
        self.word_icon = QIcon(os.path.join(icon_base, "ms-word.svg"))
        self.ppt_icon = QIcon(os.path.join(icon_base, "ms-ppt.svg"))
        self.json_icon = QIcon(os.path.join(icon_base, "json.svg"))
        self.pdf_icon = QIcon(os.path.join(icon_base, "pdf.svg"))
        self.xml_icon = QIcon(os.path.join(icon_base, "xml.svg"))
        self.yaml_icon = QIcon(os.path.join(icon_base, "yaml.svg"))
        self.md_icon = QIcon(os.path.join(icon_base, "md.svg"))
        self.txt_icon = QIcon(os.path.join(icon_base, "txt.svg"))
        self.hwp_icon = QIcon(os.path.join(icon_base, "hwp.svg"))

    def _get_file_icon(self, file_ext: str) -> QIcon:
        """파일 확장자에 맞는 아이콘 반환"""
        if not hasattr(self, 'folder_icon'):
            self.init_icons()
        ext = file_ext.lower()
        if ext in ('.csv', '.tsv'):
            return self.csv_icon
        if ext in ('.doc', '.docx'):
            return self.word_icon
        if ext in ('.ppt', '.pptx'):
            return self.ppt_icon
        if ext == '.json':
            return self.json_icon
        if ext == '.pdf':
            return self.pdf_icon
        if ext == '.xml':
            return self.xml_icon
        if ext in ('.yaml', '.yml'):
            return self.yaml_icon
        if ext == '.md':
            return self.md_icon
        if ext in ('.txt', '.log'):
            return self.txt_icon
        if ext in ('.hwp', '.hwpx'):
            return self.hwp_icon
        return self.excel_icon

    def show_extension_manager(self):
        """Extension Manager 다이얼로그 표시"""
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                                     QTableWidgetItem, QDialogButtonBox, QLabel)
        from PyQt5.QtCore import Qt

        registry = get_plugin_registry()
        plugins = registry.all_plugins()
        errors = registry.load_errors()

        dlg = QDialog(self)
        dlg.setWindowTitle("Extension Manager — 파일 형식 플러그인")
        dlg.resize(600, 400)
        layout = QVBoxLayout(dlg)

        info = QLabel("설치된 플러그인 목록입니다. Extension Pack 플러그인은 별도 패키지 설치가 필요합니다.")
        info.setWordWrap(True)
        layout.addWidget(info)

        table = QTableWidget(len(plugins) + len(errors), 4)
        table.setHorizontalHeaderLabels(["플러그인", "유형", "지원 확장자", "상태"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)

        row = 0
        for plugin in plugins:
            table.setItem(row, 0, QTableWidgetItem(plugin.display_name))
            table.setItem(row, 1, QTableWidgetItem("내장" if plugin.is_builtin else "Extension Pack"))
            table.setItem(row, 2, QTableWidgetItem(", ".join(plugin.supported_extensions())))
            status_item = QTableWidgetItem("✔ 활성")
            status_item.setForeground(QColor('#27ae60'))
            table.setItem(row, 3, status_item)
            row += 1

        for plugin_id, error_msg in errors.items():
            table.setItem(row, 0, QTableWidgetItem(plugin_id))
            table.setItem(row, 1, QTableWidgetItem("—"))
            table.setItem(row, 2, QTableWidgetItem("—"))
            status_item = QTableWidgetItem(f"✘ {error_msg}")
            status_item.setForeground(QColor('#e74c3c'))
            table.setItem(row, 3, status_item)
            row += 1

        layout.addWidget(table)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)

        dlg.exec_()

    def load_subdirectories(self, parent_item):
        """지정된 부모 아이템 아래에 하위 디렉토리와 엑셀 파일 로드"""
        # 아이콘이 초기화되지 않았으면 초기화
        if not hasattr(self, 'folder_icon'):
            self.init_icons()
            
        # 전체 경로 가져오기
        dir_path = self.get_full_path(parent_item)
        
        # 기존 더미 아이템 제거
        while parent_item.childCount() > 0:
            parent_item.removeChild(parent_item.child(0))
        
        try:
            # 디렉토리와 엑셀 파일 목록 가져오기
            subdirs = []
            excel_files = []
            
            supported_exts = get_plugin_registry().all_supported_extensions()
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_dir() and not entry.name.startswith('.'):
                        subdirs.append(entry.name)
                    elif entry.is_file() and entry.name.lower().endswith(supported_exts):
                        excel_files.append(entry.name)
            
            # 디렉토리 정렬하여 트리에 추가
            subdirs.sort()
            for subdir in subdirs:
                dir_item = QTreeWidgetItem(parent_item, [subdir])
                dir_item.setData(0, Qt.UserRole, {'path': os.path.join(dir_path, subdir), 'is_file': False})
                dir_item.setIcon(0, self.folder_icon)  # 폴더 아이콘 설정
                
                # 하위 폴더가 있는지 확인하여 더미 아이템 추가
                try:
                    has_subdirs_or_excel = False
                    subdir_path = os.path.join(dir_path, subdir)
                    with os.scandir(subdir_path) as entries:
                        for entry in entries:
                            if entry.is_dir() and not entry.name.startswith('.'):
                                has_subdirs_or_excel = True
                                break
                            elif entry.is_file() and entry.name.lower().endswith(supported_exts):
                                has_subdirs_or_excel = True
                                break
                    
                    if has_subdirs_or_excel:
                        dummy_item = QTreeWidgetItem(dir_item, ["로딩 중..."])
                except (PermissionError, OSError):
                    # 접근 권한이 없는 경우 더미 아이템 추가
                    dummy_item = QTreeWidgetItem(dir_item, ["로딩 중..."])
            
            # 엑셀/CSV 파일 정렬하여 트리에 추가
            excel_files.sort()
            for excel_file in excel_files:
                file_item = QTreeWidgetItem(parent_item, [excel_file])
                file_item.setData(0, Qt.UserRole, {'path': os.path.join(dir_path, excel_file), 'is_file': True})

                # 파일 확장자에 따라 아이콘 설정
                file_ext = os.path.splitext(excel_file)[1].lower()
                file_item.setIcon(0, self._get_file_icon(file_ext))
                
        
        except (PermissionError, OSError) as e:
            # 접근 권한이 없는 경우 오류 메시지 표시
            error_item = QTreeWidgetItem(parent_item, [f"접근 권한 없음: {str(e)}"])
    
    def navigate_to_parent_folder(self):
        """상위 폴더로 이동"""
        # 실제 루트 폴더 경로 가져오기
        current_folder = self.actual_root_path

        if not current_folder or not os.path.isdir(current_folder):
            return

        # 상위 폴더 경로 계산
        parent_folder = os.path.dirname(current_folder)

        # 상위 폴더가 유효한 경로인지 확인
        if parent_folder and os.path.isdir(parent_folder):
            # 상위 폴더로 이동
            self.last_directory = parent_folder
            self.actual_root_path = parent_folder
            self.root_folder_edit.setText(self.simplify_path_display(parent_folder))
            self.load_directory_tree(parent_folder)

    def use_selected_folder_as_root(self):
        """선택된 폴더를 루트 폴더로 설정"""
        selected_items = self.dir_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, '경고', '폴더를 선택하세요.')
            return

        # 첫 번째 선택된 항목 가져오기
        selected_item = selected_items[0]

        # 아이템이 폴더인지 확인
        item_data = selected_item.data(0, Qt.UserRole)
        is_file = item_data.get('is_file', False) if isinstance(item_data, dict) else False

        if is_file:
            QMessageBox.warning(self, '경고', '폴더를 선택하세요. 파일은 루트로 설정할 수 없습니다.')
            return

        # 선택된 폴더의 전체 경로 가져오기
        selected_folder_path = self.get_full_path(selected_item)

        if selected_folder_path and os.path.isdir(selected_folder_path):
            # 선택된 폴더를 새 루트로 설정
            self.last_directory = selected_folder_path
            self.actual_root_path = selected_folder_path
            self.root_folder_edit.setText(self.simplify_path_display(selected_folder_path))
            self.load_directory_tree(selected_folder_path)
        else:
            QMessageBox.warning(self, '경고', '유효하지 않은 폴더입니다.')
    
    def refresh_directory_tree(self):
        """디렉토리 트리 새로고침"""
        # 현재 확장된 경로 저장
        self.expanded_paths = self.get_expanded_paths()
        
        # 현재 선택된 루트 폴더가 있으면 다시 로드
        root_folder = self.root_folder_edit.text()
        if root_folder and os.path.isdir(root_folder):
            self.load_directory_tree(root_folder)
        else:
            # 루트 폴더가 없으면 트리 초기화
            self.dir_tree.clear()
    
    def toggle_search(self):
        """검색 시작/중지 토글"""
        if hasattr(self, 'is_searching') and self.is_searching:
            self.stop_search()
        else:
            self.start_search()
    
    def start_search(self):
        """검색 시작"""
        search_text = self.search_input.text()
        self.current_search_text = search_text  # 현재 검색어 저장
        if not search_text:
            QMessageBox.warning(self, '경고', '검색할 키워드를 입력해주세요.')
            self.search_input.setFocus()  # 입력 커서를 검색 입력 필드로 이동
            return
            
        # 선택된 아이템 확인
        selected_items = self.dir_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, '경고', '검색할 폴더 또는 파일을 선택해주세요.')
            return
        
        # 오류 로그 초기화
        self.error_log.clear()
        
        # 검색 상태 설정
        self.is_searching = True
        
        # UI 상태 업데이트
        self.search_stop_btn.setText('중지')
        self.dir_tree.setEnabled(False)
        
        # 결과 트리 초기화
        self.result_tree.clear()
        
        # 상태 바에 진행 상황 표시
        self.status_progress_bar.setValue(0)
        self.status_progress_bar.setVisible(True)
        self.status_label.setText("검색 준비 중...")
        
        # 선택된 폴더와 엑셀 파일 분리
        selected_dirs = []
        selected_excel_files = []
        
        for item in selected_items:
            path = self.get_full_path(item)
            item_data = item.data(0, Qt.UserRole)
            is_file = item_data.get('is_file', False) if isinstance(item_data, dict) else False
            
            if is_file:
                # 활성화된 형식 파일인지 확인
                if path.lower().endswith(self._get_active_extensions()):
                    selected_excel_files.append(path)
            else:
                # 폴더인 경우
                if os.path.isdir(path):
                    selected_dirs.append(path)
        
        # 중복 검색 방지: 상위 폴더가 이미 선택된 경우 하위 폴더 제외
        filtered_dirs = self.filter_nested_directories(selected_dirs)
        
        # 로그에 선택된 폴더 기록
        if filtered_dirs:
            self.error_log.append("<div style='color:#2980b9; font-weight:bold; margin-top:5px; padding-top:5px;'>선택된 검색 폴더:</div>")
            for dir_path in filtered_dirs:
                self.error_log.append(f"<div style='color:#2980b9; margin-left:10px;'>{dir_path}</div>")
        
        # 로그에 선택된 파일 기록
        if selected_excel_files:
            self.error_log.append("<div style='color:#9b59b6; font-weight:bold; margin-top:5px; padding-top:5px;'>선택된 파일:</div>")
            for file_path in selected_excel_files:
                file_name = os.path.basename(file_path)
                self.error_log.append(f"<div style='color:#9b59b6; margin-left:10px;'>{file_name}</div>")
        
        self.error_log.append("<div style='margin-bottom:10px;'></div>")
        
        # 검색할 엑셀 파일 목록 초기화
        self.files = []
        
        # 선택된 엑셀 파일 추가
        for file_path in selected_excel_files:
            if file_path not in self.files:
                self.files.append(file_path)
        
        # 선택된 디렉토리에서 엑셀 파일 목록 수집
        for dir_path in filtered_dirs:
            self.collect_excel_files(dir_path)
        
        if not self.files:
            QMessageBox.warning(self, '경고', '선택한 폴더에 검색 가능한 파일이 없거나, 파일을 선택하지 않았습니다.\n형식 필터에서 검색할 파일 형식이 선택되어 있는지 확인하세요.')
            self.search_finished()
            return
        
        # 검색 스레드 시작
        exact_match = self.search_mode_btn.isChecked()  # True: 값 일치, False: 값 포함
        
        # 검색 예외 처리 적용 여부 확인 (필터 버튼 상태에 따라)
        apply_exception = self.filter_enabled_btn.isChecked()
        
        # 검색 예외 처리를 적용하지 않는 경우 빈 리스트 전달
        excluded_headers = self.excluded_headers if apply_exception else []
        excluded_if_not_empty = self.excluded_if_not_empty if apply_exception else []
        excluded_paths = self.excluded_paths if apply_exception else []
        excluded_files = self.excluded_files if apply_exception else []
        excluded_sheets = self.excluded_sheets if apply_exception else []

        # 병렬 처리 스레드 사용
        worker_count = self.worker_count.value()
        self.search_worker = ParallelSearchWorker(
            self.files,
            search_text,
            exact_match,
            worker_count,
            excluded_headers,
            excluded_if_not_empty,
            self.case_sensitive_btn.isChecked(),
            excluded_paths,
            excluded_files,
            excluded_sheets
        )
        self.search_worker.result_found.connect(self.add_result)
        self.search_worker.progress_update.connect(self.update_progress)
        self.search_worker.error_occurred.connect(self.log_error)
        self.search_worker.search_completed.connect(self.search_finished)
        
        # 현재 처리 중인 파일 정보 연결 (search_worker.py에 구현 필요)
        if hasattr(self.search_worker, 'current_file_changed'):
            self.search_worker.current_file_changed.connect(self.update_current_file)
        
        self.search_worker.start()
    
    def collect_excel_files(self, directory):
        """지정된 디렉토리에서 모든 엑셀 파일을 수집"""
        try:
            excel_count = 0
            
            supported_exts = self._get_active_extensions()
            for root, _, files in os.walk(directory):
                for file in files:
                    if file.lower().endswith(supported_exts):
                        file_path = os.path.join(root, file)
                        if file_path not in self.files:
                            self.files.append(file_path)
                            excel_count += 1
            
            # 검색 폴더와 발견된 파일 수만 로그에 기록 (여백 추가)
            self.error_log.append(f"<div style='color:#27ae60; margin-top:3px; padding-top:3px;'>검색 폴더: {directory} - 파일 {excel_count}개 발견</div>")
            
        except Exception as e:
            self.log_error(directory, f"디렉토리 검색 중 오류: {str(e)}")
    
    def update_current_file(self, file_path):
        """현재 처리 중인 파일 정보 업데이트"""
        if file_path:
            display_path = self.format_file_path_for_display(file_path)
            self.status_label.setText(f"처리 중: {display_path}")
    
    def format_file_path_for_display(self, file_path):
        """파일 경로를 간략하게 표시 (상위 폴더까지만)"""
        # 파일명과 확장자 추출
        filename = os.path.basename(file_path)
        
        # 경로에서 디렉토리 부분만 추출
        directory = os.path.dirname(file_path)
        
        if directory:
            # 디렉토리가 있는 경우 마지막 폴더명만 추출
            parent_dir = os.path.basename(directory)
            
            if parent_dir:
                # 상위 폴더가 있는 경우 ".../상위폴더/파일명" 형식으로 반환
                return f".../{parent_dir}/{filename}"
            else:
                # 상위 폴더가 없는 경우 파일명만 반환
                return filename
        else:
            # 디렉토리가 없는 경우 파일명만 반환
            return filename
    
    def log_error(self, file_path, error_msg):
        """오류 로그에 메시지 추가 (간략한 형식)"""
        # 파일 경로 간략화
        display_path = self.format_file_path_for_display(file_path)
        
        # 오류 유형에 따른 표시 메시지 결정
        if "PermissionError" in error_msg or "Permission denied" in error_msg or "파일에 액세스할 수 없습니다" in error_msg:
            display_msg = "Permission Denied: 이미 열고 있는 엑셀 테이블을 닫은 후 시도해주세요"
            msg_color = "#e67e22"
        elif "지원하지 않는 파일 형식" in error_msg:
            ext_part = error_msg.split("지원하지 않는 파일 형식:")[-1].strip()
            display_msg = f"지원하지 않는 파일 형식: {ext_part}"
            msg_color = "#7f8c8d"
        elif "[플러그인 로드 실패]" in error_msg:
            detail = error_msg.split("[플러그인 로드 실패]")[-1].strip()
            display_msg = f"플러그인 미설치: {detail}"
            msg_color = "#e67e22"
        elif "파일 열기 실패:" in error_msg:
            detail = error_msg.split("파일 열기 실패:")[-1].strip()
            display_msg = f"열기 실패: {detail}"
            msg_color = "#e74c3c"
        elif "파일 처리 중 예기치 못한 오류:" in error_msg:
            detail = error_msg.split("파일 처리 중 예기치 못한 오류:")[-1].strip()
            display_msg = f"처리 오류: {detail}"
            msg_color = "#e74c3c"
        else:
            display_msg = f"오류: {error_msg}"
            msg_color = "#e74c3c"

        formatted_msg = f"<div style='margin-top:3px; padding-top:3px; margin-bottom:5px;'>"
        formatted_msg += f"<span style='font-weight:bold;color:#e74c3c;'>{display_path}</span>: "
        formatted_msg += f"<span style='color:{msg_color};'>{display_msg}</span>"
        formatted_msg += f"</div>"
        
        # 오류 로그에 추가
        self.error_log.append(formatted_msg)
        
        # 로그 파일에는 상세 정보 기록 (디버깅용) - logs 폴더는 루트에 있음
        try:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "excel_errors.log")
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"시간: {pd.Timestamp.now()}\n")
                f.write(f"파일: {file_path}\n")
                f.write(error_msg)
                f.write(f"\n{'='*50}\n")
        except Exception:
            # 로그 파일 저장 실패 시 무시 (UI에는 이미 표시됨)
            pass
        
    def stop_search(self):
        """검색 중지"""
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.stop()
            # 워커 스레드가 완전히 종료될 때까지 대기 (최대 5초)
            self.search_worker.wait(5000)
    
    def search_finished(self):
        """검색 완료"""
        # 검색 상태 해제
        self.is_searching = False
        
        # UI 상태 복원
        self.search_stop_btn.setText('검색')
        self.update_search_button_state()
        self.dir_tree.setEnabled(True)
        
        # 상태 바 업데이트
        self.status_progress_bar.setVisible(False)
        self.status_label.setText("준비")
        
        # 검색 결과 메시지 표시 (leaf 노드 수 계산)
        result_count = 0
        for i in range(self.result_tree.topLevelItemCount()):
            file_node = self.result_tree.topLevelItem(i)
            for j in range(file_node.childCount()):
                result_count += file_node.child(j).childCount()
        QMessageBox.information(self, '검색 완료', f'총 {result_count}개의 결과를 찾았습니다.')

    def column_number_to_letter(self, col_num):
        """열 번호를 Excel 열 문자로 변환 (1=A, 2=B, ..., 27=AA)"""
        result = ""
        while col_num > 0:
            col_num -= 1  # 0-based로 변환
            result = chr(ord('A') + col_num % 26) + result
            col_num //= 26
        return result

    def column_letter_to_number(self, col_letter):
        """Excel 열 문자를 번호로 변환 (A=1, B=2, ..., AA=27)"""
        result = 0
        for char in col_letter.upper():
            result = result * 26 + (ord(char) - ord('A') + 1)
        return result

    def highlight_keyword_in_text(self, text, keyword):
        """텍스트 내에서 키워드를 HTML로 하이라이트"""
        if not keyword or not text:
            return text

        import re
        # 대소문자 무시하고 검색어를 찾아서 하이라이트
        pattern = re.escape(keyword)
        highlighted = re.sub(
            f'({pattern})',
            r'<span style="background-color: yellow;">\1</span>',
            text,
            flags=re.IGNORECASE
        )
        return highlighted

    # 중간 계층(시트/섹션)을 표시할 확장자 집합 — Excel만 시트 레벨 유지
    _FORMATS_WITH_INTERMEDIATE = frozenset({'.xlsx', '.xls', '.xlsm'})

    # Number 컬럼: col 0에 위치 정보(페이지/슬라이드 번호/줄 번호)가 저장된 포맷
    _FORMATS_WITH_POSITION_IN_COL0 = frozenset({'.pdf', '.pptx', '.json', '.txt', '.log'})

    def add_result(self, file_path, sheet_name, row, col, value, header_data, row_data):
        """검색 결과를 트리에 추가.
        Excel: 파일 > 시트 > 결과 (3단계)
        그 외: 파일 > 결과 (2단계, 중간 섹션 생략)
        """
        # 아이콘이 초기화되지 않았으면 초기화
        if not hasattr(self, 'excel_icon'):
            self.init_icons()

        file_ext = os.path.splitext(file_path)[1].lower()
        show_intermediate = file_ext in self._FORMATS_WITH_INTERMEDIATE

        # ── Level 1: 파일 노드 ───────────────────────────────────────────
        file_node = None
        for i in range(self.result_tree.topLevelItemCount()):
            candidate = self.result_tree.topLevelItem(i)
            node_data = candidate.data(0, Qt.UserRole)
            if isinstance(node_data, dict) and node_data.get('file_path') == file_path:
                file_node = candidate
                break

        if file_node is None:
            file_name = os.path.basename(file_path)
            file_node = QTreeWidgetItem(self.result_tree)
            file_node.setData(0, Qt.UserRole, {'type': 'file', 'file_path': file_path})
            file_node.setText(0, file_name)
            file_node.setIcon(0, self._get_file_icon(file_ext))
            file_node.setExpanded(True)

        # ── Level 2 (조건부): 시트/섹션 노드 ────────────────────────────
        if show_intermediate:
            sheet_node = None
            for i in range(file_node.childCount()):
                candidate = file_node.child(i)
                node_data = candidate.data(0, Qt.UserRole)
                if isinstance(node_data, dict) and node_data.get('sheet_name') == sheet_name:
                    sheet_node = candidate
                    break

            if sheet_node is None:
                sheet_node = QTreeWidgetItem(file_node)
                sheet_node.setData(0, Qt.UserRole, {'type': 'sheet', 'sheet_name': sheet_name})
                sheet_node.setText(0, sheet_name)
                sheet_node.setExpanded(True)

            result_parent = sheet_node
        else:
            result_parent = file_node

        # ── Level 3 (또는 Level 2): 결과 노드 ────────────────────────────
        col_letter = self.column_number_to_letter(col + 1)
        col_header = col_letter
        if header_data is not None and col < len(header_data):
            col_header = f"{header_data[col]} ({col_letter})"

        result_node = QTreeWidgetItem(result_parent)

        # 검색값 (하이라이트 적용) — 'Name' 컬럼(0)에 표시
        search_keyword = getattr(self, 'current_search_text', '')
        str_value = str(value)
        if search_keyword and search_keyword.lower() in str_value.lower():
            highlighted = self.highlight_keyword_in_text(str_value, search_keyword)
            result_node.setText(0, highlighted)
            result_node.setData(0, Qt.UserRole + 1, str_value)  # 원본 텍스트 저장
        else:
            result_node.setText(0, str_value)

        # ── Number 컬럼: 포맷별 위치 식별자 ─────────────────────────────
        # PDF/PPTX: row_data[0]에 페이지/슬라이드 번호가 저장됨 → 추출하여 표시
        if file_ext in self._FORMATS_WITH_POSITION_IN_COL0 and row_data and len(row_data) > 0:
            display_number = str(row_data[0])
        else:
            display_number = str(row)
        result_node.setText(1, display_number)
        result_node.setTextAlignment(1, Qt.AlignCenter)

        # ── Type 컬럼: 포맷별 의미있는 식별자 ───────────────────────────
        if file_ext in ('.docx', '.doc'):
            # DOCX: 테이블 결과는 열 헤더, 단락 결과는 'DOCX'
            display_type = col_header if sheet_name.startswith('Table_') else 'DOCX'
        elif file_ext == '.md':
            # Markdown: 테이블 결과는 열 헤더, 일반 텍스트 결과는 'Markdown'
            display_type = col_header if sheet_name.startswith('Table_') else 'Markdown'
        elif file_ext in ('.txt', '.log'):
            display_type = 'TXT'
        elif file_ext == '.pdf':
            display_type = 'PDF'
        elif file_ext == '.pptx':
            # PPTX: 슬라이드 제목(col 1)을 Type으로 표시
            display_type = row_data[1] if row_data and len(row_data) > 1 else 'PPTX'
        elif file_ext in ('.hwp', '.hwx'):
            display_type = 'HWP'
        elif file_ext in ('.json', '.yaml', '.yml', '.xml'):
            # 구조화 포맷: 괄호(열 문자) 없이 헤더 이름만 표시
            if header_data is not None and col < len(header_data):
                display_type = str(header_data[col])
            else:
                display_type = col_letter
        else:
            # Excel, CSV 등: 열 헤더 (열 문자 포함)
            display_type = col_header
        result_node.setText(2, display_type)

        # show_sheet_data에 필요한 데이터 저장
        result_node.setData(0, Qt.UserRole, {
            'type': 'result',
            'file_path': file_path,
            'sheet_name': sheet_name,
            'row': row,
            'col_header': col_header,
        })

        # 헤더/행 데이터 캐시
        if header_data is not None and row_data is not None:
            self.cached_row_data[(file_path, sheet_name, row)] = (header_data, row_data)
        
    def show_sheet_data(self, item, column):
        """선택한 결과 노드의 행 데이터를 새 창에 표시"""
        if item is None:
            return

        item_data = item.data(0, Qt.UserRole)
        if not isinstance(item_data, dict) or item_data.get('type') != 'result':
            return

        file_path = item_data['file_path']
        sheet_name = item_data['sheet_name']
        excel_row = item_data['row']
        col_header = item_data['col_header']

        # 열 헤더에서 열 인덱스 추출 (예: "Header (A)" -> A -> 0)
        col_index = None
        if '(' in col_header and ')' in col_header:
            col_letter = col_header.split('(')[-1].split(')')[0]
            col_index = self.column_letter_to_number(col_letter) - 1  # 0-based

        search_keyword = getattr(self, 'current_search_text', '')
        cached_data = self.cached_row_data.get((file_path, sheet_name, excel_row))

        viewer = SheetViewer(file_path, sheet_name, excel_row, self, cached_data,
                           highlight_col=col_index, search_keyword=search_keyword)
        viewer.exec_()
        
    def filter_nested_directories(self, directories):
        """중복 검색 방지: 상위 폴더가 이미 선택된 경우 하위 폴더 제외"""
        if not directories:
            return []
            
        # 경로를 정규화하고 정렬 (긴 경로가 먼저 오도록)
        normalized_dirs = [os.path.normpath(d) for d in directories]
        sorted_dirs = sorted(normalized_dirs, key=len, reverse=True)
        
        # 필터링된 디렉토리 목록
        filtered_dirs = []
        
        for dir_path in sorted_dirs:
            # 이미 추가된 디렉토리의 하위 디렉토리인지 확인
            is_subdirectory = False
            for parent_dir in filtered_dirs:
                # 현재 경로가 이미 추가된 경로의 하위 디렉토리인지 확인
                if dir_path.startswith(parent_dir + os.sep) or dir_path == parent_dir:
                    is_subdirectory = True
                    break
            
            # 하위 디렉토리가 아니면 추가
            if not is_subdirectory:
                filtered_dirs.append(dir_path)
        
        return filtered_dirs
    
    def update_progress(self, value):
        """진행 상황 업데이트"""
        self.status_progress_bar.setValue(value)
    
    def _parse_header_filters_from_settings(self, settings_string):
        """설정 문자열에서 헤더 필터 목록 파싱 (손상된 데이터도 복구)"""
        if not settings_string:
            return []
        
        # 새로운 구분자가 있는지 확인
        if '^^^' in settings_string:
            # 새로운 형식: 필터들이 ^^^로 구분됨
            return settings_string.split('^^^')
        
        # 손상된 데이터인 경우 정리
        if settings_string.count('|') > 10:  # 너무 많은 파이프는 손상된 데이터
            # 기본 헤더들만 추출하여 복구
            parts = settings_string.split('|')
            clean_headers = []
            for part in parts:
                if part and part not in ['exact', 'contains', 'any', 'specific', ''] and not part.startswith('메모:'):
                    if len(part) < 50:  # 너무 긴 텍스트는 제외
                        clean_headers.append(f"{part}|exact")
            return clean_headers[:3]  # 최대 3개만 유지
        
        filters = []
        parts = settings_string.split('|')
        
        # 올바른 새 형식인지 확인
        if len(parts) >= 3:
            i = 0
            while i + 2 < len(parts):
                header = parts[i]
                match_type = parts[i + 1]
                memo_part = parts[i + 2]
                
                # 유효한 형식인지 확인
                if header and match_type in ['exact', 'contains']:
                    filter_string = f"{header}|{match_type}"
                    if memo_part and (memo_part.startswith('메모:') or memo_part):
                        if not memo_part.startswith('메모:'):
                            memo_part = f"메모: {memo_part}"
                        filter_string += f"|{memo_part}"
                    filters.append(filter_string)
                    i += 3
                else:
                    # 잘못된 형식이면 기존 형식으로 처리
                    break
            
            # 필터가 성공적으로 파싱되었으면 반환
            if filters:
                return filters
        
        # 기존 형식으로 처리
        for part in parts:
            if part and part.strip() and part not in ['exact', 'contains', 'any', 'specific']:
                # 기존 메모 형식 확인
                if " (메모: " in part:
                    header, memo_part = part.split(" (메모: ", 1)
                    memo = memo_part.rstrip(")")
                    filters.append(f"{header}|exact|메모: {memo}")
                else:
                    filters.append(f"{part}|exact")
        
        return filters
    
    def _parse_data_filters_from_settings(self, settings_string):
        """설정 문자열에서 데이터 필터 목록 파싱 (손상된 데이터도 복구)"""
        if not settings_string:
            return []
        
        # 새로운 구분자가 있는지 확인
        if '^^^' in settings_string:
            # 새로운 형식: 필터들이 ^^^로 구분됨
            return settings_string.split('^^^')
        
        # 손상된 데이터인 경우 정리
        if settings_string.count('|') > 15:  # 너무 많은 파이프는 손상된 데이터
            # 기본 헤더들만 추출하여 복구
            parts = settings_string.split('|')
            clean_filters = []
            for part in parts:
                if part and part not in ['exact', 'contains', 'any', 'specific', ''] and not part.startswith('메모:'):
                    if len(part) < 50:  # 너무 긴 텍스트는 제외
                        clean_filters.append(f"{part}|any|")
            return clean_filters[:3]  # 최대 3개만 유지
        
        filters = []
        parts = settings_string.split('|')
        
        # 올바른 새 형식인지 확인 (3개 또는 4개 부분)
        if len(parts) >= 3:
            i = 0
            while i + 2 < len(parts):
                header = parts[i]
                filter_type = parts[i + 1]
                specific_value = parts[i + 2]
                memo_part = parts[i + 3] if i + 3 < len(parts) else ""
                
                # 유효한 형식인지 확인
                if header and filter_type in ['any', 'specific']:
                    filter_string = f"{header}|{filter_type}|{specific_value}"
                    if memo_part and (memo_part.startswith('메모:') or memo_part):
                        if not memo_part.startswith('메모:'):
                            memo_part = f"메모: {memo_part}"
                        filter_string += f"|{memo_part}"
                        i += 4  # 메모가 있으면 4개씩 증가
                    else:
                        i += 3  # 메모가 없으면 3개씩 증가
                    
                    filters.append(filter_string)
                else:
                    # 잘못된 형식이면 기존 형식으로 처리
                    break
            
            # 필터가 성공적으로 파싱되었으면 반환
            if filters:
                return filters
        
        # 기존 형식으로 처리
        for part in parts:
            if part and part.strip() and part not in ['exact', 'contains', 'any', 'specific']:
                # 기존 메모 형식 확인
                if " (메모: " in part:
                    header, memo_part = part.split(" (메모: ", 1)
                    memo = memo_part.rstrip(")")
                    filters.append(f"{header}|any||메모: {memo}")
                else:
                    filters.append(f"{part}|any|")
        
        return filters
    
    def _format_header_filters_for_settings(self, filters):
        """헤더 필터 목록을 설정 문자열로 변환"""
        if not filters:
            return ""
        # 필터 간 구분을 위해 특수 구분자 사용
        return '^^^'.join(filters)
    
    def _format_data_filters_for_settings(self, filters):
        """데이터 필터 목록을 설정 문자열로 변환"""
        if not filters:
            return ""
        # 필터 간 구분을 위해 특수 구분자 사용
        return '^^^'.join(filters)

    def _format_simple_filters_for_settings(self, filters):
        """단순 필터 목록을 설정 문자열로 변환 (경로, 파일, 시트)"""
        if not filters:
            return ""
        return '^^^'.join(filters)

    def _parse_simple_filters_from_settings(self, settings_string):
        """설정 문자열에서 단순 필터 목록 파싱 (경로, 파일, 시트)"""
        if not settings_string:
            return []
        return settings_string.split('^^^')

    def _get_filter_config_path(self):
        """필터 설정 JSON 파일 경로 결정"""
        # 현재 실행 파일의 위치 확인
        if getattr(sys, 'frozen', False):
            # PyInstaller로 빌드된 실행 파일인 경우
            app_dir = os.path.dirname(sys.executable)
        else:
            # 개발 환경인 경우
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # config 폴더 경로
        config_dir = os.path.join(app_dir, "config")

        # config 폴더가 없으면 생성
        os.makedirs(config_dir, exist_ok=True)

        return os.path.join(config_dir, "filter.json")

    def _save_filters_to_json(self):
        """필터 설정을 JSON 형식으로 저장"""
        filters_list = []

        # 경로 제외 필터 변환
        for filter_string in self.excluded_paths:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_path")
            if filter_obj:
                filters_list.append(filter_obj)

        # 파일 제외 필터 변환
        for filter_string in self.excluded_files:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_file")
            if filter_obj:
                filters_list.append(filter_obj)

        # 시트 제외 필터 변환
        for filter_string in self.excluded_sheets:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_sheet")
            if filter_obj:
                filters_list.append(filter_obj)

        # 헤더 제외 필터 변환
        for filter_string in self.excluded_headers:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_column")
            if filter_obj:
                filters_list.append(filter_obj)

        # 데이터 필터 변환
        for filter_string in self.excluded_if_not_empty:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_row")
            if filter_obj:
                filters_list.append(filter_obj)

        filters_data = {
            "version": "3.0",
            "filters": filters_list,
            "last_updated": pd.Timestamp.now().isoformat()
        }

        try:
            with open(self.filter_settings_file, 'w', encoding='utf-8') as f:
                json.dump(filters_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"필터 설정 저장 중 오류: {str(e)}")

    def _parse_filter_string_to_object(self, filter_string, filter_type):
        """필터 문자열을 JSON 객체로 변환"""
        if not filter_string:
            return None

        # 파싱 로직: "keyword|match_type|메모: memo" 또는 "header|filter_type|value|메모: memo"
        parts = filter_string.split("|")

        filter_obj = {
            "filterType": filter_type,
            "keyword": "",
            "extra": "",
            "exact": True,
            "memo": ""
        }

        if len(parts) >= 1:
            filter_obj["keyword"] = parts[0].strip()

        if len(parts) >= 2:
            match_type = parts[1].strip()
            filter_obj["exact"] = (match_type == "exact")

        # 행 제외의 경우 extra 필드 처리
        if filter_type == "exclude_row" and len(parts) >= 3:
            filter_obj["extra"] = parts[2].strip()
            memo_part = parts[3].strip() if len(parts) > 3 else ""
        else:
            memo_part = parts[2].strip() if len(parts) > 2 else ""

        # 메모 처리
        if memo_part.startswith('메모: '):
            filter_obj["memo"] = memo_part[3:].strip()
        elif memo_part:
            filter_obj["memo"] = memo_part.strip()

        return filter_obj

    def _load_filters_from_json(self):
        """JSON 파일에서 필터 설정 로드"""
        if not os.path.exists(self.filter_settings_file):
            return

        try:
            with open(self.filter_settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            version = data.get("version", "1.0")

            if version in ["2.0", "3.0"]:
                # 새로운 개별 필터 형식 (버전 2.0 및 3.0)
                self._load_individual_filters(data.get("filters", []))
            else:
                # 기존 그룹화된 형식 (버전 1.0 호환)
                filters = data.get("filters", {})
                self.excluded_paths = filters.get("excluded_paths", [])
                self.excluded_files = filters.get("excluded_files", [])
                self.excluded_sheets = filters.get("excluded_sheets", [])
                self.excluded_headers = filters.get("excluded_headers", [])
                self.excluded_if_not_empty = filters.get("excluded_if_not_empty", [])

        except Exception as e:
            print(f"필터 설정 로드 중 오류: {str(e)}")

    def _load_individual_filters(self, filters_list):
        """개별 필터 형식에서 기존 형식으로 변환하여 로드"""
        # 기존 필터 리스트 초기화
        self.excluded_paths = []
        self.excluded_files = []
        self.excluded_sheets = []
        self.excluded_headers = []
        self.excluded_if_not_empty = []

        for filter_obj in filters_list:
            filter_string = self._convert_object_to_filter_string(filter_obj)
            if not filter_string:
                continue

            filter_type = filter_obj.get("filterType", "")

            if filter_type == "exclude_path":
                self.excluded_paths.append(filter_string)
            elif filter_type == "exclude_file":
                self.excluded_files.append(filter_string)
            elif filter_type == "exclude_sheet":
                self.excluded_sheets.append(filter_string)
            elif filter_type == "exclude_column":
                self.excluded_headers.append(filter_string)
            elif filter_type == "exclude_row":
                self.excluded_if_not_empty.append(filter_string)

    def _convert_object_to_filter_string(self, filter_obj):
        """JSON 필터 객체를 필터 문자열로 변환"""
        keyword = filter_obj.get("keyword", "")
        extra = filter_obj.get("extra", "")
        exact = filter_obj.get("exact", True)
        memo = filter_obj.get("memo", "")
        filter_type = filter_obj.get("filterType", "")

        if not keyword:
            return None

        # 매치 타입 결정
        match_type = "exact" if exact else "contains"

        # 필터 문자열 구성
        if filter_type == "exclude_row" and extra:
            # 행 제외: "header|filter_type|value|메모: memo"
            filter_string = f"{keyword}|specific|{extra}"
        else:
            # 기타: "keyword|match_type|메모: memo"
            filter_string = f"{keyword}|{match_type}"

        # 메모 추가
        if memo:
            filter_string += f"|메모: {memo}"

        return filter_string

    def export_filters_to_file(self, file_path):
        """필터 설정을 지정된 파일로 내보내기 (다른 사용자와 공유용)"""
        filters_list = []

        # 모든 필터를 개별 객체로 변환
        for filter_string in self.excluded_paths:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_path")
            if filter_obj:
                filters_list.append(filter_obj)

        for filter_string in self.excluded_files:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_file")
            if filter_obj:
                filters_list.append(filter_obj)

        for filter_string in self.excluded_sheets:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_sheet")
            if filter_obj:
                filters_list.append(filter_obj)

        for filter_string in self.excluded_headers:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_column")
            if filter_obj:
                filters_list.append(filter_obj)

        for filter_string in self.excluded_if_not_empty:
            filter_obj = self._parse_filter_string_to_object(filter_string, "exclude_row")
            if filter_obj:
                filters_list.append(filter_obj)

        filters_data = {
            "version": "3.0",
            "filters": filters_list,
            "exported_at": pd.Timestamp.now().isoformat(),
            "exported_from": "ExcelFinder"
        }

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(filters_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"필터 내보내기 중 오류: {str(e)}")
            return False

    def import_filters_from_file(self, file_path):
        """파일에서 필터 설정 가져오기"""
        if not os.path.exists(file_path):
            return False

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            version = data.get("version", "1.0")

            if version in ["2.0", "3.0"]:
                # 새로운 개별 필터 형식 (버전 2.0 및 3.0)
                self._load_individual_filters(data.get("filters", []))
            else:
                # 기존 그룹화된 형식 (버전 1.0 호환)
                filters = data.get("filters", {})
                self.excluded_paths = filters.get("excluded_paths", [])
                self.excluded_files = filters.get("excluded_files", [])
                self.excluded_sheets = filters.get("excluded_sheets", [])
                self.excluded_headers = filters.get("excluded_headers", [])
                self.excluded_if_not_empty = filters.get("excluded_if_not_empty", [])

            # 설정 저장
            self._save_filters_to_json()
            return True
        except Exception as e:
            print(f"필터 가져오기 중 오류: {str(e)}")
            return False

    def _update_case_sensitive_icon(self):
        """대소문자 구분 버튼 아이콘 업데이트"""
        icon_name = "case.svg" if self.case_sensitive_btn.isChecked() else "case-off.svg"
        case_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", icon_name)
        if os.path.exists(case_icon_path):
            self.case_sensitive_btn.setIcon(QIcon(case_icon_path))

    def _update_filter_icon(self):
        """필터 버튼 아이콘 업데이트"""
        icon_name = "filter.svg" if self.filter_enabled_btn.isChecked() else "filter-off.svg"
        filter_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", icon_name)
        if os.path.exists(filter_icon_path):
            self.filter_enabled_btn.setIcon(QIcon(filter_icon_path))

    def show_tree_context_menu(self, position):
        """TreeWidget 컨텍스트 메뉴 표시"""
        try:
            item = self.dir_tree.itemAt(position)
            if not item:
                return

            # 메뉴 생성
            context_menu = QMenu(self)

            # 아이템 데이터 가져오기
            item_data = item.data(0, Qt.UserRole)
            is_file = item_data.get('is_file', False) if isinstance(item_data, dict) else False
            item_path = self.get_full_path(item)

            # 경로 정보 추출
            item_name = os.path.basename(item_path)
            parent_folder = os.path.dirname(item_path)
            parent_folder_name = os.path.basename(parent_folder)

            if is_file:
                # 파일인 경우의 메뉴 옵션들
                file_name, file_ext = os.path.splitext(item_name)

                # 1. Open File ({File Name}.{Extension})
                open_action = QAction(f"파일 열기", self)
                file_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "ms-excel.svg")
                if os.path.exists(file_icon_path):
                    open_action.setIcon(QIcon(file_icon_path))
                open_action.triggered.connect(lambda: self.safe_open_file_or_folder(item_path))
                context_menu.addAction(open_action)

                # 2. Open after disabling Read-Only
                open_without_readonly_action = QAction("읽기 전용 해제 후 파일 열기", self)
                open_without_readonly_action.triggered.connect(lambda: self.safe_open_file_without_readonly(item_path))
                context_menu.addAction(open_without_readonly_action)

                # 3. Open location ({Folder Name}) in File Explorer
                open_location_action = QAction(f"탐색기에서 파일 경로 ({parent_folder_name}) 열기", self)
                folder_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "folder.svg")
                if os.path.exists(folder_icon_path):
                    open_location_action.setIcon(QIcon(folder_icon_path))
                open_location_action.triggered.connect(lambda: self.safe_open_file_location(item_path))
                context_menu.addAction(open_location_action)

            else:
                # 폴더인 경우의 메뉴 옵션들
                # 경로 표시 생성 (...\{Parent Folder Name}\{Folder Name})
                folder_display_path = f"...\\{parent_folder_name}\\{item_name}" if parent_folder_name else item_name

                # 1. Open folder (...\{Parent Folder Name}\{Folder Name}) in File Explorer
                open_action = QAction(f"탐색기에서 폴더 ({folder_display_path}) 열기", self)
                # 아이콘 설정
                folder_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "folder.svg")
                if os.path.exists(folder_icon_path):
                    open_action.setIcon(QIcon(folder_icon_path))
                open_action.triggered.connect(lambda: self.safe_open_file_or_folder(item_path))
                context_menu.addAction(open_action)

                # 2. Open folder location (...\{Parent Folder Name}) in File Explorer
                if parent_folder_name:
                    grandparent_folder = os.path.dirname(parent_folder)
                    grandparent_folder_name = os.path.basename(grandparent_folder)
                    parent_display_path = f"...\\{grandparent_folder_name}\\{parent_folder_name}" if grandparent_folder_name else parent_folder_name

                    open_parent_action = QAction(f"탐색기에서 파일 위치 ({parent_display_path}) 열기", self)
                    open_parent_action.triggered.connect(lambda: self.safe_open_file_or_folder(parent_folder))
                    context_menu.addAction(open_parent_action)

            # 구분선 추가
            context_menu.addSeparator()

            # 공통 네비게이션 옵션들
            # View Top-Level Path
            if self.actual_root_path:
                root_name = os.path.basename(self.actual_root_path)
                root_parent = os.path.dirname(self.actual_root_path)
                root_parent_name = os.path.basename(root_parent)
                root_display_path = f"...\\{root_parent_name}\\{root_name}" if root_parent_name else root_name

                view_top_level_action = QAction(f"최상위 경로 ({root_display_path}) 선택", self)
                view_top_level_action.triggered.connect(lambda: self.select_top_level_path())
                context_menu.addAction(view_top_level_action)

                # View Previous Path (상위 폴더로 이동)
                if root_parent and os.path.isdir(root_parent):
                    previous_display_path = f"...\\{os.path.basename(os.path.dirname(root_parent))}\\{root_parent_name}" if os.path.basename(os.path.dirname(root_parent)) else root_parent_name

                    view_previous_action = QAction(f"이전 경로 ({previous_display_path}) 확인", self)
                    # 아이콘 설정
                    up_arrow_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "up-arrow.svg")
                    if os.path.exists(up_arrow_icon_path):
                        view_previous_action.setIcon(QIcon(up_arrow_icon_path))
                    view_previous_action.triggered.connect(self.safe_navigate_to_parent_folder)
                    context_menu.addAction(view_previous_action)

            # Set This Folder as Top-Level Path (폴더인 경우에만)
            if not is_file:
                set_root_action = QAction("이 폴더를 최상위 경로로 설정", self)
                # 아이콘 설정
                check_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "check.svg")
                if os.path.exists(check_icon_path):
                    set_root_action.setIcon(QIcon(check_icon_path))
                set_root_action.triggered.connect(lambda: self.safe_set_folder_as_root(item_path))
                context_menu.addAction(set_root_action)

            # 메뉴 표시
            context_menu.exec_(self.dir_tree.mapToGlobal(position))

        except Exception as e:
            # 컨텍스트 메뉴 오류를 조용히 처리
            print(f"Context menu error: {str(e)}")
            import traceback
            traceback.print_exc()

            # 간단한 대체 메뉴라도 표시하려고 시도
            try:
                simple_menu = QMenu(self)
                simple_action = QAction("탐색기에서 열기", self)
                if hasattr(self, 'dir_tree') and hasattr(self.dir_tree, 'itemAt'):
                    item = self.dir_tree.itemAt(position)
                    if item:
                        item_path = self.get_full_path(item)
                        simple_action.triggered.connect(lambda: self.safe_open_file_or_folder(item_path))
                simple_menu.addAction(simple_action)
                simple_menu.exec_(self.dir_tree.mapToGlobal(position))
            except Exception:
                pass  # 모든 시도가 실패하면 조용히 무시

    def open_file_or_folder(self, path):
        """파일 또는 폴더 열기"""
        try:
            if os.path.exists(path):
                if os.name == 'nt':  # Windows
                    os.startfile(path)
                elif os.name == 'posix':  # macOS/Linux
                    subprocess.call(['open' if os.uname().sysname == 'Darwin' else 'xdg-open', path])
            else:
                QMessageBox.warning(self, '경고', f'경로를 찾을 수 없습니다: {path}')
        except Exception as e:
            QMessageBox.critical(self, '오류', f'파일/폴더를 열 수 없습니다: {str(e)}')

    def open_file_location(self, file_path):
        """파일 위치를 File Explorer에서 열기"""
        print(f"DEBUG: open_file_location called with: {file_path}")  # Debug logging

        try:
            if not os.path.exists(file_path):
                QMessageBox.warning(self, '경고', f'파일을 찾을 수 없습니다: {file_path}')
                return

            if os.name == 'nt':  # Windows
                # 가장 간단하고 안정적인 방법 사용 - subprocess.Popen with detach
                normalized_path = os.path.normpath(file_path)
                print(f"DEBUG: Normalized path: {normalized_path}")

                try:
                    print("DEBUG: Using subprocess.Popen for explorer /select...")
                    # Popen을 사용하여 단일 인스턴스만 실행하고 즉시 반환
                    process = subprocess.Popen(
                        ['explorer', '/select,', normalized_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL
                    )
                    print(f"DEBUG: Process started with PID: {process.pid}")
                    # 프로세스를 시작한 후 즉시 반환 (기다리지 않음)

                except Exception as e:
                    print(f"DEBUG: Popen failed: {e}")
                    # 실패시에만 폴더 열기
                    folder_path = os.path.dirname(normalized_path)
                    if os.path.exists(folder_path):
                        print(f"DEBUG: Fallback - opening folder: {folder_path}")
                        try:
                            os.startfile(folder_path)
                        except Exception as fallback_error:
                            print(f"DEBUG: Fallback also failed: {fallback_error}")
                            QMessageBox.critical(self, '오류', f'파일 위치를 열 수 없습니다: {str(e)}')

            elif os.name == 'posix':  # macOS/Linux
                if os.uname().sysname == 'Darwin':  # macOS
                    subprocess.call(['open', '-R', file_path])
                else:  # Linux
                    folder_path = os.path.dirname(file_path)
                    subprocess.call(['xdg-open', folder_path])

        except Exception as e:
            print(f"DEBUG: Outer exception: {e}")
            QMessageBox.critical(self, '오류', f'파일 위치를 열 수 없습니다: {str(e)}')

    def show_results_context_menu(self, position):
        """검색 결과 트리 컨텍스트 메뉴 표시"""
        try:
            item = self.result_tree.itemAt(position)
            if not item:
                return

            item_data = item.data(0, Qt.UserRole)
            if not isinstance(item_data, dict):
                return

            # 결과 노드에서 파일 경로 추출
            node_type = item_data.get('type')
            if node_type == 'result':
                file_path = item_data['file_path']
            elif node_type == 'file':
                file_path = item_data['file_path']
            elif node_type == 'sheet':
                # 부모(파일 노드)에서 file_path 가져오기
                parent = item.parent()
                if parent is None:
                    return
                parent_data = parent.data(0, Qt.UserRole)
                if not isinstance(parent_data, dict):
                    return
                file_path = parent_data.get('file_path')
            else:
                return

            if not file_path:
                return

            # 메뉴 생성
            context_menu = QMenu(self)

            # 아이콘 기본 경로
            icon_base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon")

            # 1. Open in File Explorer (파일 자체 열기)
            open_file_action = QAction("파일 열기", self)
            excel_icon_path = os.path.join(icon_base_path, "ms-excel.svg")
            if os.path.exists(excel_icon_path):
                open_file_action.setIcon(QIcon(excel_icon_path))
            open_file_action.triggered.connect(lambda: self.safe_open_file_or_folder(file_path))
            context_menu.addAction(open_file_action)

            # 2. Open in File Explorer after disabling Read-Only
            open_without_readonly_action = QAction("읽기 전용 해제 후 파일 열기", self)
            open_without_readonly_action.triggered.connect(lambda: self.safe_open_file_without_readonly(file_path))
            context_menu.addAction(open_without_readonly_action)

            # 3. Open file location (파일이 있는 폴더 열기)
            # 파일의 상위 폴더 경로 표시 형식으로 변경
            parent_folder = os.path.dirname(file_path)
            parent_folder_name = os.path.basename(parent_folder)
            grandparent_folder = os.path.dirname(parent_folder)
            grandparent_folder_name = os.path.basename(grandparent_folder)
            parent_display_path = f"...\\{grandparent_folder_name}\\{parent_folder_name}" if grandparent_folder_name else parent_folder_name

            open_file_location_action = QAction(f"탐색기에서 파일 위치 ({parent_display_path}) 열기", self)
            folder_icon_path = os.path.join(icon_base_path, "folder.svg")
            if os.path.exists(folder_icon_path):
                open_file_location_action.setIcon(QIcon(folder_icon_path))
            open_file_location_action.triggered.connect(lambda: self.safe_open_file_location(file_path))
            context_menu.addAction(open_file_location_action)

            # 메뉴 표시
            context_menu.exec_(self.result_tree.mapToGlobal(position))

        except Exception as e:
            print(f"Results context menu error: {str(e)}")
            # 조용히 오류 처리

    def open_file_without_readonly(self, file_path):
        """파일을 읽기 전용 없이 열기"""
        try:
            if not os.path.exists(file_path):
                QMessageBox.warning(self, '경고', f'파일을 찾을 수 없습니다: {file_path}')
                return

            # 현재 파일 권한 확인
            current_permissions = os.stat(file_path).st_mode

            # 읽기 전용인지 확인 (쓰기 권한이 없는지 확인)
            is_readonly = not (current_permissions & stat.S_IWRITE)

            if is_readonly:
                try:
                    # 읽기 전용 속성 해제 (쓰기 권한 추가)
                    new_permissions = current_permissions | stat.S_IWRITE
                    os.chmod(file_path, new_permissions)

                    # 성공 메시지
                    file_name = os.path.basename(file_path)
                    self.status_label.setText(f"'{file_name}' 읽기 전용 속성이 해제되었습니다.")

                except PermissionError:
                    QMessageBox.warning(self, '경고',
                                      f'파일의 읽기 전용 속성을 해제할 권한이 없습니다:\n{os.path.basename(file_path)}\n\n관리자 권한으로 실행하거나 파일 소유자에게 문의하세요.')
                    return
                except Exception as e:
                    QMessageBox.critical(self, '오류',
                                       f'파일 권한 변경 중 오류가 발생했습니다:\n{str(e)}')
                    return

            # 읽기 전용 속성 해제 후 파일 열기
            # 파일 확장자 확인
            file_ext = os.path.splitext(file_path)[1].lower()

            if file_ext in ['.xlsx', '.xls', '.xlsm']:
                # Excel 파일인 경우
                if os.name == 'nt':  # Windows
                    # Excel로 직접 열기
                    subprocess.Popen([file_path], shell=True)
                else:
                    # 다른 OS의 경우 기본 프로그램으로 열기
                    self.open_file_or_folder(file_path)
            else:
                # 다른 파일 형식의 경우 기본 프로그램으로 열기
                self.open_file_or_folder(file_path)

        except Exception as e:
            QMessageBox.critical(self, '오류', f'파일을 열 수 없습니다: {str(e)}')

    def set_folder_as_root(self, folder_path):
        """폴더를 루트 경로로 설정"""
        try:
            if os.path.exists(folder_path) and os.path.isdir(folder_path):
                # 선택된 폴더를 새 루트로 설정
                self.last_directory = folder_path
                self.actual_root_path = folder_path
                self.root_folder_edit.setText(self.simplify_path_display(folder_path))
                self.load_directory_tree(folder_path)

                # 성공 메시지 표시
                folder_name = os.path.basename(folder_path)
                self.status_label.setText(f"루트 경로가 '{folder_name}'로 설정되었습니다.")
            else:
                QMessageBox.warning(self, '경고', f'유효하지 않은 폴더입니다: {folder_path}')
        except Exception as e:
            QMessageBox.critical(self, '오류', f'폴더를 루트로 설정할 수 없습니다: {str(e)}')

    def select_top_level_path(self):
        """TreeWidget에서 최상위 경로를 선택하고 확장"""
        if not self.actual_root_path:
            return

        # 최상위 아이템 찾기
        root = self.dir_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            # 최상위 아이템을 선택하고 확장
            self.dir_tree.clearSelection()
            self.dir_tree.setCurrentItem(item)
            item.setSelected(True)
            self.dir_tree.expandItem(item)
            # 스크롤하여 선택된 아이템을 표시
            self.dir_tree.scrollToItem(item)
            break

    # Safe wrapper methods to prevent crashes
    def safe_open_file_or_folder(self, path):
        """안전한 파일/폴더 열기"""
        try:
            self.open_file_or_folder(path)
        except Exception as e:
            QMessageBox.critical(self, '오류', f'파일/폴더를 열 수 없습니다: {str(e)}')

    def safe_open_file_location(self, file_path):
        """안전한 파일 위치 열기"""
        print(f"DEBUG: safe_open_file_location called with: {file_path}")  # Debug logging
        try:
            self.open_file_location(file_path)
        except Exception as e:
            print(f"DEBUG: Exception in safe_open_file_location: {e}")
            QMessageBox.critical(self, '오류', f'파일 위치를 열 수 없습니다: {str(e)}')

    def safe_open_file_without_readonly(self, file_path):
        """안전한 읽기 전용 해제 후 파일 열기"""
        try:
            self.open_file_without_readonly(file_path)
        except Exception as e:
            QMessageBox.critical(self, '오류', f'파일을 열 수 없습니다: {str(e)}')

    def safe_set_folder_as_root(self, folder_path):
        """안전한 루트 폴더 설정"""
        try:
            self.set_folder_as_root(folder_path)
        except Exception as e:
            QMessageBox.critical(self, '오류', f'폴더를 루트로 설정할 수 없습니다: {str(e)}')

    def safe_navigate_to_parent_folder(self):
        """안전한 상위 폴더 이동"""
        try:
            self.navigate_to_parent_folder()
        except Exception as e:
            QMessageBox.critical(self, '오류', f'상위 폴더로 이동할 수 없습니다: {str(e)}')
