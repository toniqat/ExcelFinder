from PyQt5.QtCore import QAbstractItemModel, QModelIndex, Qt
from PyQt5.QtGui import QIcon
import os


class ResultNode:
    """트리 노드 데이터 컨테이너"""
    __slots__ = ('parent', 'children', 'data', 'row')

    def __init__(self, data: dict, parent=None):
        self.parent = parent
        self.children = []
        self.data = data  # {'type': 'file'|'sheet'|'result', ...}
        self.row = 0

    def append_child(self, child):
        child.row = len(self.children)
        child.parent = self
        self.children.append(child)
        return child


class ResultTreeModel(QAbstractItemModel):
    """검색 결과 트리 모델 - 가상 스크롤 지원"""

    COLUMNS = ['이름', '번호', '타입']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = ResultNode({'type': 'root'})
        self._file_cache = {}    # {file_path: ResultNode}
        self._sheet_cache = {}   # {(file_path, sheet_name): ResultNode}
        self._icon_resolver = None  # callable(file_ext) -> QIcon

    def set_icon_resolver(self, resolver):
        """파일 확장자로 아이콘을 반환하는 콜백 설정: resolver(file_ext) -> QIcon"""
        self._icon_resolver = resolver

    # -- QAbstractItemModel 필수 구현 --

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else self._root
        if row < len(parent_node.children):
            return self.createIndex(row, column, parent_node.children[row])
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        parent_node = node.parent
        if parent_node is None or parent_node is self._root:
            return QModelIndex()
        return self.createIndex(parent_node.row, 0, parent_node)

    def rowCount(self, parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self._root
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        col = index.column()

        if role == Qt.DisplayRole:
            return node.data.get(f'col_{col}', '')
        elif role == Qt.DecorationRole:
            if col == 0 and node.data.get('type') == 'file' and self._icon_resolver:
                file_ext = node.data.get('file_ext', '')
                if file_ext:
                    return self._icon_resolver(file_ext)
            return None
        elif role == Qt.UserRole:
            return node.data
        elif role == Qt.TextAlignmentRole and col == 1:
            return Qt.AlignCenter
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    # -- 데이터 조작 API --

    def clear(self):
        """모든 결과 초기화"""
        self.beginResetModel()
        self._root.children.clear()
        self._file_cache.clear()
        self._sheet_cache.clear()
        self.endResetModel()

    def add_name_match(self, file_path, file_ext, match_type, sheet_name='',
                       highlighted_text=None):
        """파일 이름 또는 시트 이름 매칭 결과 추가.
        match_type: 'filename' | 'sheetname'
        """
        # -- 파일 노드 (없으면 생성) --
        file_node = self._file_cache.get(file_path)
        if file_node is None:
            file_name = os.path.basename(file_path)
            file_node = ResultNode({
                'type': 'file', 'file_path': file_path,
                'col_0': file_name, 'col_1': '', 'col_2': '',
                'file_ext': file_ext, 'name_match_only': True,
            })
            parent = self._root
            pos = len(parent.children)
            self.beginInsertRows(QModelIndex(), pos, pos)
            parent.append_child(file_node)
            self.endInsertRows()
            self._file_cache[file_path] = file_node

        if match_type == 'filename':
            # 파일 이름 매칭 — 파일 노드의 col_0 에 하이라이트 적용
            if highlighted_text:
                file_node.data['col_0'] = highlighted_text
        elif match_type == 'sheetname':
            # 시트 이름 매칭 — 결과 노드로 추가 (leaf)
            display_text = highlighted_text or sheet_name
            result_node = ResultNode({
                'type': 'result',
                'file_path': file_path,
                'sheet_name': sheet_name,
                'row': -2,
                'col_header': '',
                'col_0': display_text,
                'col_1': '',
                'col_2': '시트',
                'original_text': sheet_name,
                'is_name_match': True,
            })
            parent_index = self.createIndex(file_node.row, 0, file_node)
            pos = len(file_node.children)
            self.beginInsertRows(parent_index, pos, pos)
            file_node.append_child(result_node)
            self.endInsertRows()

    def add_result(self, file_path, sheet_name, row, col, value,
                   header_data, row_data, file_ext, show_intermediate,
                   col_header, display_number, display_type, highlighted_text=None):
        """검색 결과 추가 - O(1) 노드 조회"""

        # -- 파일 노드 --
        file_node = self._file_cache.get(file_path)
        if file_node is None:
            file_name = os.path.basename(file_path)
            file_node = ResultNode({
                'type': 'file', 'file_path': file_path,
                'col_0': file_name, 'col_1': '', 'col_2': '',
                'file_ext': file_ext,
            })
            parent = self._root
            pos = len(parent.children)
            self.beginInsertRows(QModelIndex(), pos, pos)
            parent.append_child(file_node)
            self.endInsertRows()
            self._file_cache[file_path] = file_node
        else:
            # 내용 매칭이 있으므로 name_match_only 플래그 제거
            file_node.data.pop('name_match_only', None)

        # -- 시트 노드 (조건부) --
        if show_intermediate:
            cache_key = (file_path, sheet_name)
            sheet_node = self._sheet_cache.get(cache_key)
            if sheet_node is None:
                sheet_node = ResultNode({
                    'type': 'sheet', 'sheet_name': sheet_name,
                    'file_path': file_path,
                    'col_0': sheet_name, 'col_1': '', 'col_2': '',
                })
                parent_index = self.createIndex(file_node.row, 0, file_node)
                pos = len(file_node.children)
                self.beginInsertRows(parent_index, pos, pos)
                file_node.append_child(sheet_node)
                self.endInsertRows()
                self._sheet_cache[cache_key] = sheet_node
            result_parent = sheet_node
        else:
            result_parent = file_node

        # -- 결과 노드 --
        original_text = str(value)
        result_node = ResultNode({
            'type': 'result',
            'file_path': file_path,
            'sheet_name': sheet_name,
            'row': row,
            'col_header': col_header,
            'col_0': highlighted_text or original_text,
            'col_1': display_number,
            'col_2': display_type,
            'original_text': original_text,
        })

        if result_parent is file_node:
            parent_index = self.createIndex(file_node.row, 0, file_node)
        else:
            parent_index = self.createIndex(result_parent.row, 0, result_parent)
        pos = len(result_parent.children)
        self.beginInsertRows(parent_index, pos, pos)
        result_parent.append_child(result_node)
        self.endInsertRows()

    def get_total_result_count(self):
        """전체 결과(leaf) 노드 수 반환 (파일 이름 매칭도 포함)"""
        count = 0
        for file_node in self._root.children:
            if file_node.data.get('name_match_only'):
                count += 1  # 파일 이름만 매칭된 경우
            for child in file_node.children:
                if child.data.get('type') == 'sheet':
                    count += len(child.children)
                elif child.data.get('type') == 'result':
                    count += 1
        return count
