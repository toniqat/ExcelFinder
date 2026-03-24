import time
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QProgressBar, QTextEdit, QApplication)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon
import os

class LoadingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.progress_value = 0
        self.start_time = time.time()
        self.min_display_time = 0.5  # 최소 500ms 표시
        
    def init_ui(self):
        self.setWindowTitle('ExcelFinder 시작 중...')
        self.setFixedSize(400, 200)
        self.setWindowFlags((Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowStaysOnTopHint) & ~Qt.WindowContextHelpButtonHint)
        self.setModal(True)
        
        # 윈도우 아이콘 설정
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # 메인 레이아웃
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 제목
        title_label = QLabel('ExcelFinder v3.1')
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 현재 작업 표시
        self.status_label = QLabel('초기화 중...')
        
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 진행률 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)
        
        # 완료된 작업 목록
        self.completed_tasks = QTextEdit()
        self.completed_tasks.setMaximumHeight(60)
        self.completed_tasks.setReadOnly(True)
        self.completed_tasks.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-size: 9pt;
                padding: 5px;
            }
        """)
        layout.addWidget(self.completed_tasks)
        
        self.setLayout(layout)
        
        # 화면 중앙에 위치
        self.center_on_screen()
    
    def center_on_screen(self):
        """화면 중앙에 다이얼로그 위치시키기"""
        screen = QApplication.desktop().screenGeometry()
        size = self.geometry()
        self.move(
            (screen.width() - size.width()) // 2,
            (screen.height() - size.height()) // 2
        )
    
    def update_progress(self, value, status_text, completed_task=None):
        """진행률과 상태 업데이트"""
        self.progress_value = value
        self.progress_bar.setValue(value)
        self.status_label.setText(status_text)
        
        if completed_task:
            current_text = self.completed_tasks.toPlainText()
            if current_text:
                new_text = current_text + f"\n✓ {completed_task}"
            else:
                new_text = f"✓ {completed_task}"
            self.completed_tasks.setPlainText(new_text)
            
            # 스크롤을 맨 아래로
            scrollbar = self.completed_tasks.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        
        # UI 업데이트 강제 실행
        QApplication.processEvents()
    
    def should_close(self):
        """로딩 화면을 닫을 수 있는지 확인"""
        elapsed_time = time.time() - self.start_time
        return elapsed_time >= self.min_display_time and self.progress_value >= 100
    
    def close_when_ready(self):
        """준비되면 창 닫기"""
        if self.should_close():
            self.accept()
        else:
            # 최소 표시 시간이 지날 때까지 대기
            remaining_time = max(0, self.min_display_time - (time.time() - self.start_time))
            if remaining_time > 0:
                QTimer.singleShot(int(remaining_time * 1000), self.accept)
            else:
                self.accept()
