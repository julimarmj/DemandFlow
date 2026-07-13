"""
DemandFlow - Widget Gerenciador de Arquivos v2
Melhorias:
  • Barra de pesquisa no lugar da toolbar
  • Copiar/Recortar integra com clipboard do SO (funciona fora do programa)
  • Drag & drop interno realmente move os arquivos no disco
  • Roteamento automático corrigido (tokens isolados, sem falsos positivos)
  • Drag visual destacando a pasta-alvo
"""
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional

import qtawesome as qta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QLineEdit, QFrame, QMenu, QMessageBox,
    QInputDialog, QFileDialog, QAbstractItemView, QApplication, QSizePolicy,
    QStyle, QFileIconProvider
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer, QFileInfo
from PyQt6.QtGui import (
    QDragEnterEvent, QDropEvent, QDragMoveEvent, QColor,
    QKeySequence, QShortcut, QBrush,
)

from infrastructure.services.file_service import DemandFileService


class FileManagerWidget(QWidget):
    files_changed = pyqtSignal()

    def __init__(
        self,
        demand_id: int,
        demand_title: str,
        file_service: DemandFileService,
        dark: bool = False,
        readonly=False,
        parent=None,
    ):
        super().__init__(parent)
        self.demand_id    = demand_id
        self.demand_title = demand_title
        self._fs          = file_service
        self._dark        = dark
        self._readonly    = readonly

        # Clipboard interno (complementa o do SO)
        self._clip_path:  Optional[Path] = None
        self._clip_paths: list[Path]     = []   # FIX: suporta múltiplos itens
        self._clip_cut:   bool           = False

        # Item de destino do drag interno
        self._drag_target_item: Optional[QTreeWidgetItem] = None

        self.icon_provider = QFileIconProvider()

        self._build()
        self._setup_shortcuts()
        self.setAcceptDrops(True)
        self.refresh()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def refresh_dark(self, dark: bool):
        self._dark = dark
        self.tree.setStyleSheet(self._tree_style())
        self._drop_hint_normal_style()
        ss_input = f"""
            QLineEdit {{
                background: {'#1E293B' if dark else ''};
                color: {'#E2E8F0' if dark else ''};
                border: 1px solid {'#334155' if dark else ''};
                border-radius: 6px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid #3B82F6; }}
        """ if dark else ""
        self._search_input.setStyleSheet(ss_input)
        self._status_lbl.setStyleSheet(
            f"font-size: 11px; color: {'#64748B' if dark else '#9CA3AF'}; background: transparent;"
        )

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Deixa o fundo transparente para herdar o background do widget pai (ex: card)
        self.setStyleSheet("FileManagerWidget { background: transparent; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ── Barra superior: pesquisa + botão explorer ─────────────────────────
        top = QHBoxLayout()
        top.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Pesquisar arquivos e pastas...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        if self._dark:
            self._search_input.setStyleSheet("""
                QLineEdit {
                    background: #1E293B;
                    color: #E2E8F0;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 4px 8px;
                }
                QLineEdit:focus { border: 1px solid #3B82F6; }
            """)
        top.addWidget(self._search_input)

        exp_btn = QPushButton()
        exp_btn.setIcon(qta.icon("fa6s.folder-open", color="#64748B"))
        exp_btn.setToolTip("Abrir pasta da demanda no Explorer")
        exp_btn.setFixedSize(32, 28)
        exp_btn.clicked.connect(self._open_root_in_explorer)
        top.addWidget(exp_btn)

        root.addLayout(top)

        # ── Drop hint ─────────────────────────────────────────────────────────
        self._drop_hint = QLabel("⬇  Arraste arquivos aqui para adicioná-los à demanda")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setFixedHeight(30)
        self._drop_hint.setVisible(not self._readonly)
        self._drop_hint_normal_style()
        root.addWidget(self._drop_hint)

        # ── Tree ──────────────────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nome", "Tamanho", "Modificado em"])
        self.tree.setColumnWidth(0, 340)
        self.tree.setColumnWidth(1, 80)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        #self.tree.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed |QAbstractItemView.EditTrigger.SelectedClicked)
        # DragOnly: Qt gera drag com URLs dos itens selecionados.
        # setAcceptDrops(False) na tree faria o drop ser ignorado quando o mouse
        # solta sobre ela — por isso usamos um event filter para redirecionar.
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.viewport().setAcceptDrops(True)
        self.tree.viewport().installEventFilter(self)

        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setStyleSheet(self._tree_style())
        root.addWidget(self.tree)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"font-size: 11px; color: {'#64748B' if self._dark else '#9CA3AF'}; background: transparent;"
        )
        root.addWidget(self._status_lbl)

    def _tree_style(self) -> str:
        return f"""
            QTreeWidget {{
                background: {'#1E293B' if self._dark else '#FFFFFF'};
                color: {'#E2E8F0' if self._dark else '#1E293B'};
                border: 1px solid {'#334155' if self._dark else '#E2E8F0'};
                border-radius: 8px;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 5px 4px;
                border-radius: 4px;
                color: {'#E2E8F0' if self._dark else '#1E293B'};
            }}
            QTreeWidget::item:selected {{
                background: {'#1D3461' if self._dark else '#EFF6FF'};
                color: {'#60A5FA' if self._dark else '#2563EB'};
            }}
            QTreeWidget::item:hover:!selected {{
                background: {'#334155' if self._dark else '#F8FAFC'};
            }}
            QScrollBar:vertical {{
                background: {'#1E293B' if self._dark else '#F1F5F9'};
                width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {'#475569' if self._dark else '#CBD5E1'};
                border-radius: 3px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QHeaderView::section {{
                background: {'#0F172A' if self._dark else '#F8FAFC'};
                color: {'#94A3B8' if self._dark else '#64748B'};
                font-weight: 600; font-size: 11px;
                padding: 6px 8px; border: none;
                border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'};
            }}
            QTreeWidget QLineEdit {{
                background: {'#0F172A' if self._dark else '#FFFFFF'};
                color: {'#E2E8F0' if self._dark else '#1E293B'};
                padding: 2px; min-height: 20px;
                border: 1px solid #3B82F6; border-radius: 2px;
            }}
        """

    def _setup_shortcuts(self):
        # WidgetWithChildrenShortcut — sem isso o padrão (WindowShortcut) faz
        # esses atalhos dispararem pra QUALQUER Ctrl+C/X/V/Delete na janela,
        # mesmo com o foco em outro widget (ex: título/descrição da demanda),
        # "engolindo" o evento antes dele chegar onde o usuário realmente quer.
        shortcuts = [
            QShortcut(QKeySequence.StandardKey.Copy,   self, self._action_copy),
            QShortcut(QKeySequence.StandardKey.Cut,    self, self._action_cut),
            QShortcut(QKeySequence.StandardKey.Paste,  self, self._action_paste_kbd),
            QShortcut(QKeySequence.StandardKey.Delete, self, self._action_delete),
            QShortcut(QKeySequence("F2"),              self, self._action_rename),
            QShortcut(QKeySequence("F5"),              self, self.refresh),
        ]
        for sc in shortcuts:
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    # ── Event filter (redireciona drag/drop do viewport da tree) ─────────────

    def eventFilter(self, obj, event):
        if obj is self.tree.viewport():
            if event.type() == event.Type.DragEnter:
                self.dragEnterEvent(event)
                return True
            if event.type() == event.Type.DragMove:
                self.dragMoveEvent(event)
                return True
            if event.type() == event.Type.DragLeave:
                self.dragLeaveEvent(event)
                return True
            if event.type() == event.Type.Drop:
                self.dropEvent(event)
                return True
        return super().eventFilter(obj, event)

    # ── Tree Population ───────────────────────────────────────────────────────

    def refresh(self):
        expanded = self._get_expanded_paths()
        selected = self._get_selected_paths()
        self.tree.clear()

        query = self._search_input.text().strip()
        if query:
            self._populate_search(query)
        else:
            nodes = self._fs.list_tree(self.demand_id, self.demand_title)
            if nodes:
                item = self._build_tree_item(nodes[0])
                self.tree.addTopLevelItem(item)
                item.setExpanded(True)
                self._restore_state(item, expanded, selected)

        self._update_status()

    def _populate_search(self, query: str):
        results = self._fs.search_files(self.demand_id, self.demand_title, query)
        if not results:
            placeholder = QTreeWidgetItem(["Nenhum resultado encontrado", "", ""])
            placeholder.setForeground(0, QColor("#94A3B8"))
            self.tree.addTopLevelItem(placeholder)
            return
        for node in results:
            item = self._build_tree_item(node)
            item.setText(1, node.get("relative", ""))
            self.tree.addTopLevelItem(item)

    def _build_tree_item(self, node: dict) -> QTreeWidgetItem:
        size = (DemandFileService.format_size(node["size"]) if not node["is_dir"] else "")
        item = QTreeWidgetItem([node["name"], size, node["modified"]])
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        item.setFlags(
            item.flags()
            | Qt.ItemFlag.ItemIsEditable
        )
        if node.get("icon"):
            item.setIcon(0, node["icon"])

        if node["is_dir"]:
            color = "#60A5FA" if self._dark else "#2563EB"
            if not node["is_root"]:
                color = "#F59E0B" if self._dark else "#D97706"
            item.setForeground(0, QColor(color))

        for child in node.get("children", []):
            item.addChild(self._build_tree_item(child))

        return item

    def _get_expanded_paths(self) -> set[str]:
        paths: set[str] = set()
        def collect(item):
            if item.isExpanded():
                node = item.data(0, Qt.ItemDataRole.UserRole)
                if node:
                    paths.add(node["path"])
            for i in range(item.childCount()):
                collect(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            collect(self.tree.topLevelItem(i))
        return paths

    def _get_selected_paths(self) -> set[str]:
        paths: set[str] = set()
        for item in self.tree.selectedItems():
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if node:
                paths.add(node["path"])
        return paths

    def _restore_state(self, item, expanded: set, selected: set):
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node:
            if node["path"] in expanded:
                item.setExpanded(True)
            if node["path"] in selected:
                item.setSelected(True)
                self.tree.setCurrentItem(item)
        for i in range(item.childCount()):
            self._restore_state(item.child(i), expanded, selected)

    def _update_status(self):
        query = self._search_input.text().strip()
        if query:
            self._status_lbl.setText(f"Resultados da busca por \"{query}\"")
            return
        count = self._fs.count_files(self.demand_id, self.demand_title)
        total = self._fs.total_size(self.demand_id)
        clip_info = ""
        clip_paths = self._clip_paths or ([self._clip_path] if self._clip_path else [])
        if clip_paths:
            op = "Recortado" if self._clip_cut else "Copiado"
            names = clip_paths[0].name if len(clip_paths) == 1 else f"{len(clip_paths)} itens"
            clip_info = f"  •  📋 {op}: {names}"
        self._status_lbl.setText(
            f"{count} arquivo{'s' if count != 1 else ''}  •  "
            f"{DemandFileService.format_size(total)} no total{clip_info}"
        )

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        if not hasattr(self, "_search_timer"):
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.timeout.connect(self.refresh)
        self._search_timer.start(250)

    # ── Selection helpers ─────────────────────────────────────────────────────

    def _selected_node(self) -> Optional[dict]:
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _selected_nodes(self) -> list[dict]:
        nodes = []
        for item in self.tree.selectedItems():
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if node:
                nodes.append(node)
        return nodes

    def _demand_root_path(self) -> str:
        # Usa find_demand_root para não criar pasta nova com nome diferente
        # caso o título já tenha sido atualizado mas o rename ainda não ocorreu.
        existing = self._fs.find_demand_root(self.demand_id)
        if existing:
            return str(existing)
        return str(self._fs.demand_root(self.demand_id, self.demand_title))

    def _target_dir_for_add(self) -> str:
        node = self._selected_node()
        if node and node["is_dir"]:
            return node["path"]
        if node and not node["is_dir"]:
            return str(Path(node["path"]).parent)
        return self._demand_root_path()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _open_root_in_explorer(self):
        try:
            DemandFileService.open_in_explorer(self._demand_root_path())
        except Exception as e:
            self._err(str(e))

    def _action_new_folder(self):
        parent = self._target_dir_for_add()
        name, ok = QInputDialog.getText(
            self, "Nova Subpasta", "Nome da subpasta:",
            QLineEdit.EchoMode.Normal, "Nova Pasta"
        )
        if ok and name.strip():
            try:
                self._fs.create_subfolder(parent, name)
                self.refresh()
                self.files_changed.emit()
            except ValueError as e:
                self._err(str(e))

    def _action_add_files(self, target_dir: Optional[str] = None):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Selecionar Arquivo(s) — serão MOVIDOS para a demanda", "",
            "Todos os Arquivos (*)"
        )
        if paths:
            self._move_files(paths, target_dir or self._target_dir_for_add())

    def _action_rename(self):
        node = self._selected_node()
        if not node or node.get("is_root"):
            return
        name, ok = QInputDialog.getText(
            self, "Renomear", "Novo nome:",
            QLineEdit.EchoMode.Normal, node["name"]
        )
        if ok and name.strip():
            try:
                self._fs.rename_item(node["path"], name)
                self.refresh()
                self.files_changed.emit()
            except Exception as e:
                self._err(str(e))

    def _action_delete(self):
        nodes = self._selected_nodes()
        nodes = [n for n in nodes if not n.get("is_root")]
        if not nodes:
            return
        names = "\n".join(f"• {n['name']}" for n in nodes[:5])
        if len(nodes) > 5:
            names += f"\n... e mais {len(nodes)-5}"
        r = QMessageBox.question(
            self, "Confirmar Exclusão",
            f"Excluir permanentemente:\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if r == QMessageBox.StandardButton.Yes:
            for node in nodes:
                try:
                    self._fs.delete_item(node["path"])
                except Exception as e:
                    self._err(str(e))
            self.refresh()
            self.files_changed.emit()

    # ── Clipboard ─────────────────────────────────────────────────────────────

    def _action_copy(self):
        nodes = self._selected_nodes()
        if not nodes:
            return
        self._clip_paths = [Path(n["path"]) for n in nodes]
        self._clip_path  = self._clip_paths[0]
        self._clip_cut   = False
        DemandFileService.copy_paths_to_clipboard([n["path"] for n in nodes])
        self._update_status()

    def _action_cut(self):
        nodes = [n for n in self._selected_nodes() if not n.get("is_root")]
        if not nodes:
            return
        self._clip_paths = [Path(n["path"]) for n in nodes]
        self._clip_path  = self._clip_paths[0]
        self._clip_cut   = True
        DemandFileService.copy_paths_to_clipboard([n["path"] for n in nodes])
        self.refresh()
        self._update_status()

    def _action_paste_kbd(self):
        """Paste via teclado: usa pasta selecionada ou raiz."""
        node = self._selected_node()
        if node and node["is_dir"]:
            self._do_paste(node["path"])
        else:
            self._do_paste(self._demand_root_path())
        self.refresh()

    def _do_paste(self, target_dir: str):
        """
        Cola os itens do clipboard interno (suporta múltiplos).
        Se o clipboard interno estiver vazio, tenta ler do clipboard do SO.
        """
        # FIX: itera _clip_paths em vez de colar só o primeiro
        valid = [p for p in self._clip_paths if p.exists()]
        # Fallback para código legado que preenchia só _clip_path
        if not valid and self._clip_path and self._clip_path.exists():
            valid = [self._clip_path]

        if valid:
            errors = []
            for src in valid:
                try:
                    if self._clip_cut:
                        self._fs.move_item(str(src), target_dir)
                    else:
                        self._fs.copy_item(str(src), target_dir)
                except Exception as e:
                    errors.append(f"• {src.name}: {e}")
            if self._clip_cut:
                self._clip_paths = []
                self._clip_path  = None
                self._clip_cut   = False
            self.refresh()
            self.files_changed.emit()
            self._update_status()
            if errors:
                self._err("Erros ao colar:\n" + "\n".join(errors))
            return

        # Fallback: lê do clipboard do SO (arquivos copiados do Explorer)
        so_files = DemandFileService.get_clipboard_files()
        if so_files:
            self._move_files(so_files, target_dir)

        self.refresh()

    # ── Double-click ──────────────────────────────────────────────────────────

    def _on_double_click(self, item: QTreeWidgetItem, col: int):
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node and not node["is_dir"]:
            try:
                DemandFileService.open_file(node["path"])
            except Exception as e:
                self._err(f"Não foi possível abrir:\n{e}")

    # ── Context Menu ──────────────────────────────────────────────────────────
    '''
    def _show_context_menu(self, pos):
        copy_icon = qta.icon("fa5s.copy")
        cut_icon = qta.icon("fa5s.cut")
        paste_icon = qta.icon("fa5s.paste")
        delete_icon = qta.icon("fa5s.trash")
        rename_icon = qta.icon("fa5s.edit")
        refresh_icon = qta.icon("fa5s.sync-alt")

        new_folder_icon = qta.icon("fa5s.folder-plus")
        folder_icon = qta.icon("fa5s.folder")
        open_folder_icon = qta.icon("fa5s.folder-open")

        add_file_icon = qta.icon("fa5s.file-upload")
        network_icon = qta.icon("fa5s.network-wired")
        file_icon = qta.icon("fa5s.file")

        node = self._selected_node()

        menu = QMenu(self)
        style = QApplication.style()

        if node and not node["is_dir"]:
            act_open = menu.addAction("🔍  Abrir arquivo")
            act_open.triggered.connect(lambda: self._ctx_open(node))
            act_reveal = menu.addAction("📂  Mostrar no Explorer")
            act_reveal.triggered.connect(
                lambda: DemandFileService.open_in_explorer(node["path"])
            )

        if node and node["is_dir"]:
            act_reveal = menu.addAction("📂  Abrir no Explorer")
            act_reveal.triggered.connect(
                lambda: DemandFileService.open_in_explorer(node["path"])
            )

        menu.addSeparator()
        act_refresh = menu.addAction("🔄  Atualizar  F5")
        act_refresh.triggered.connect(self.refresh)

        # Opções de edição só aparecem se não for readonly
        if not self._readonly:
            menu.addSeparator()
            menu_new = QMenu("📄  Novo", self)

        # ── Novo ──────────────────────────────────────────────────────────────
        menu_new = QMenu("Novo", self)
        menu_new.setIcon(new_folder_icon)
        new_items = [
            (
                style.standardIcon(QStyle.StandardPixmap.SP_DirIcon),
                "Pasta",
                self._action_new_folder
            ),
            (
                self.icon_provider.icon(QFileInfo("dummy.docx")),
                "Documento Word (.docx)",
                lambda: self._create_empty_file("Novo Documento.docx")
            ),
            (
                self.icon_provider.icon(QFileInfo("dummy.xlsx")),
                "Planilha Excel (.xlsx)",
                lambda: self._create_empty_file("Nova Planilha.xlsx")
            ),
            (
                self.icon_provider.icon(QFileInfo("dummy.pptx")),
                "Apresentação PowerPoint (.pptx)",
                lambda: self._create_empty_file("Nova Apresentação.pptx")
            ),
            (
                self.icon_provider.icon(QFileInfo("dummy.txt")),
                "Documento de Texto (.txt)",
                lambda: self._create_empty_file("Novo Texto.txt")
            ),
            (
                self.icon_provider.icon(QFileInfo("dummy.zip")),
                "Pasta compactada (.zip)",
                lambda: self._create_empty_file("Novo Arquivo.zip")
            ),
        ]

        for icon, text, slot in new_items:
            a = menu_new.addAction(icon, text)
            a.triggered.connect(slot)

        menu.addMenu(menu_new)

        # ── Pasta selecionada ────────────────────────────────────────────────
        if node and node["is_dir"]:
            menu.addSeparator()

            a = menu.addAction(open_folder_icon, "Abrir no Explorer")
            a.triggered.connect(lambda: DemandFileService.open_in_explorer(node["path"]))

            menu.addSeparator()

            has_clip = (
                bool(self._clip_paths)
                or (self._clip_path and self._clip_path.exists())
                or bool(DemandFileService.get_clipboard_files())
            )

            if has_clip:
                a = menu.addAction(paste_icon, "Colar\tCtrl+V")
                a.triggered.connect(lambda: self._do_paste(node["path"]))

        # ── Arquivo selecionado ──────────────────────────────────────────────
        if node and not node["is_dir"]:
            menu.addSeparator()

            icon = node.get("icon", style.standardIcon(QStyle.StandardPixmap.SP_FileIcon))

            a = menu.addAction(icon, "Abrir")
            a.triggered.connect(lambda: DemandFileService.open_file(node["path"]))

            a = menu.addAction(open_folder_icon, "Mostrar no Explorer")
            a.triggered.connect(lambda: DemandFileService.open_in_explorer(node["path"]))

        # ── Edição ───────────────────────────────────────────────────────────
        if node and not node.get("is_root"):
            menu.addSeparator()

            a = menu.addAction(copy_icon, "Copiar\tCtrl+C")
            a.triggered.connect(self._action_copy)

            a = menu.addAction(cut_icon, "Recortar\tCtrl+X")
            a.triggered.connect(self._action_cut)

            menu.addSeparator()
            a = menu.addAction(rename_icon, "Renomear\tF2")
            a.triggered.connect(self._action_rename)

            a = menu.addAction(delete_icon, "Excluir\tDel")
            a.triggered.connect(self._action_delete)

        # ── Geral ────────────────────────────────────────────────────────────
        menu.addSeparator()

        a = menu.addAction(refresh_icon, "Atualizar\tF5")
        a.triggered.connect(self.refresh)

        menu.exec(self.tree.viewport().mapToGlobal(pos))
    '''
    def _show_context_menu(self, pos):
        _c  = "#94A3B8" if self._dark else "#64748B"   # ícone neutro
        _bl = "#60A5FA" if self._dark else "#2563EB"   # ícone primário/azul
        _am = "#FBBF24" if self._dark else "#D97706"   # ícone pasta/âmbar
        _rd = "#EF4444"                                # ícone perigo

        copy_icon       = qta.icon("fa5s.copy",       color=_c)
        cut_icon        = qta.icon("fa5s.cut",         color=_c)
        paste_icon      = qta.icon("fa5s.paste",       color=_c)
        delete_icon     = qta.icon("fa5s.trash",       color=_rd)
        rename_icon     = qta.icon("fa5s.edit",        color=_c)
        refresh_icon    = qta.icon("fa5s.sync-alt",    color=_c)
        new_folder_icon = qta.icon("fa5s.folder-plus", color=_am)
        open_folder_icon= qta.icon("fa5s.folder-open", color=_am)

        node = self._selected_node()
        menu = QMenu(self)
        style = QApplication.style()

        # ── Novo (só se não for readonly) ────────────────────────────────────
        if not self._readonly:
            menu_new = QMenu("Novo", self)
            menu_new.setIcon(new_folder_icon)
            new_items = [
                (style.standardIcon(QStyle.StandardPixmap.SP_DirIcon),
                "Pasta", self._action_new_folder),
                (self.icon_provider.icon(QFileInfo("dummy.docx")),
                "Documento Word (.docx)", lambda: self._create_empty_file("Novo Documento.docx")),
                (self.icon_provider.icon(QFileInfo("dummy.xlsx")),
                "Planilha Excel (.xlsx)", lambda: self._create_empty_file("Nova Planilha.xlsx")),
                (self.icon_provider.icon(QFileInfo("dummy.pptx")),
                "Apresentação PowerPoint (.pptx)", lambda: self._create_empty_file("Nova Apresentação.pptx")),
                (self.icon_provider.icon(QFileInfo("dummy.txt")),
                "Documento de Texto (.txt)", lambda: self._create_empty_file("Novo Texto.txt")),
                (self.icon_provider.icon(QFileInfo("dummy.zip")),
                "Pasta compactada (.zip)", lambda: self._create_empty_file("Novo Arquivo.zip")),
            ]
            for icon, text, slot in new_items:
                a = menu_new.addAction(icon, text)
                a.triggered.connect(slot)
            menu.addMenu(menu_new)
            menu.addSeparator()

        # ── Pasta selecionada ─────────────────────────────────────────────────
        if node and node["is_dir"]:
            a = menu.addAction(open_folder_icon, "Abrir no Explorer")
            a.triggered.connect(lambda: DemandFileService.open_in_explorer(node["path"]))

            if not self._readonly:
                menu.addSeparator()
                has_clip = (
                    bool(self._clip_paths)
                    or (self._clip_path and self._clip_path.exists())
                    or bool(DemandFileService.get_clipboard_files())
                )
                if has_clip:
                    a = menu.addAction(paste_icon, "Colar\tCtrl+V")
                    a.triggered.connect(lambda: self._do_paste(node["path"]))

            menu.addSeparator()

        # ── Arquivo selecionado ───────────────────────────────────────────────
        if node and not node["is_dir"]:
            file_icon = node.get("icon", style.standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            a = menu.addAction(file_icon, "Abrir")
            a.triggered.connect(lambda: DemandFileService.open_file(node["path"]))
            a = menu.addAction(open_folder_icon, "Mostrar no Explorer")
            a.triggered.connect(lambda: DemandFileService.open_in_explorer(node["path"]))
            menu.addSeparator()

        # ── Edição (só se não for readonly) ───────────────────────────────────
        if not self._readonly and node and not node.get("is_root"):
            a = menu.addAction(copy_icon, "Copiar\tCtrl+C")
            a.triggered.connect(self._action_copy)
            a = menu.addAction(cut_icon, "Recortar\tCtrl+X")
            a.triggered.connect(self._action_cut)
            menu.addSeparator()
            a = menu.addAction(rename_icon, "Renomear\tF2")
            a.triggered.connect(self._action_rename)
            a = menu.addAction(delete_icon, "Excluir\tDel")
            a.triggered.connect(self._action_delete)
            menu.addSeparator()

        # ── Geral ─────────────────────────────────────────────────────────────
        a = menu.addAction(refresh_icon, "Atualizar\tF5")
        a.triggered.connect(self.refresh)

        menu.exec(self.tree.viewport().mapToGlobal(pos))
        
    def _ctx_add_link(self, node):
        link, ok = QInputDialog.getText(
            self, "Link de Rede", "URL ou caminho de rede:",
            QLineEdit.EchoMode.Normal, "\\\\servidor\\pasta"
        )
        if ok and link.strip():
            sub = Path(node["path"]).name if not node.get("is_root") else None
            try:
                self._fs.add_network_link(self.demand_id, self.demand_title, link.strip(), sub)
                self.refresh()
                self.files_changed.emit()
            except Exception as e:
                self._err(str(e))

    # ── File creation ─────────────────────────────────────────────────────────

    def _create_empty_file(self, default_name: str):
        node = self._selected_node()
        if node and node["is_dir"]:
            target_dir = Path(node["path"])
        elif node and not node["is_dir"]:
            target_dir = Path(node["path"]).parent
        else:
            target_dir = Path(self._demand_root_path())

        name, ok = QInputDialog.getText(
            self, "Novo Arquivo", "Nome do arquivo:",
            QLineEdit.EchoMode.Normal, default_name
        )
        if not ok or not name.strip():
            return

        dest = target_dir / name.strip()
        if dest.exists():
            self._err(f'Já existe um item com o nome "{dest.name}" nesta pasta.')
            return

        try:
            ext = dest.suffix.lower()
            if ext == ".docx":
                self._create_docx(dest)
            elif ext == ".xlsx":
                self._create_xlsx(dest)
            elif ext == ".pptx":
                self._create_pptx(dest)
            elif ext == ".zip":
                with zipfile.ZipFile(dest, "w"):
                    pass
            else:
                dest.touch()
            self.refresh()
            self.files_changed.emit()
        except Exception as e:
            self._err(f"Não foi possível criar o arquivo:\n{e}")

    @staticmethod
    def _create_docx(path: Path):
        try:
            from docx import Document
            Document().save(str(path))
        except ImportError:
            path.touch()

    @staticmethod
    def _create_xlsx(path: Path):
        try:
            from openpyxl import Workbook
            Workbook().save(str(path))
        except ImportError:
            path.touch()

    @staticmethod
    def _create_pptx(path: Path):
        try:
            from pptx import Presentation
            Presentation().save(str(path))
        except ImportError:
            path.touch()

    # ── File Move ─────────────────────────────────────────────────────────────

    def _move_files(self, paths: list[str], target_dir: str):
        root     = self._demand_root_path()
        use_auto = (target_dir == root)
        errors   = []
        moved    = 0

        for src in paths:
            try:
                if use_auto:
                    self._fs.move_file_to_demand(
                        self.demand_id, self.demand_title, src
                    )
                else:
                    relative_sub = str(Path(target_dir).relative_to(root))
                    self._fs.move_file_to_demand(
                        self.demand_id, self.demand_title, src,
                        target_subfolder=None if relative_sub == "." else relative_sub
                    )
                moved += 1
            except Exception as e:
                errors.append(f"• {Path(src).name}: {e}")

        self.refresh()
        self.files_changed.emit()
        if errors:
            self._err(f"{moved} arquivo(s) movido(s).\n\nErros:\n" + "\n".join(errors))

    # ── Drag & Drop externos (do Explorer para o widget) ─────────────────────

    def _drop_hint_normal_style(self):
        self._drop_hint.setStyleSheet(f"""
            QLabel {{
                background: {'#1D3461' if self._dark else '#EFF6FF'};
                color: {'#60A5FA' if self._dark else '#2563EB'};
                border: 2px dashed {'#3B82F6' if self._dark else '#93C5FD'};
                border-radius: 8px; padding: 4px;
                font-size: 12px; font-weight: 500;
            }}
        """)

    def _drop_hint_active_style(self):
        self._drop_hint.setStyleSheet(f"""
            QLabel {{
                background: {'#1D3461' if self._dark else '#DBEAFE'};
                color: {'#60A5FA' if self._dark else '#1D4ED8'};
                border: 2px dashed #3B82F6;
                border-radius: 8px; padding: 4px;
                font-size: 12px; font-weight: 700;
            }}
        """)

    def _highlight_drop_target(self, item: Optional[QTreeWidgetItem]):
        """Destaca visualmente a pasta-alvo durante drag interno."""
        if self._drag_target_item:
            node = self._drag_target_item.data(0, Qt.ItemDataRole.UserRole)
            if node and node["is_dir"]:
                self._drag_target_item.setBackground(0, QBrush())
        self._drag_target_item = item
        if item:
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if node and node["is_dir"]:
                item.setBackground(0, QBrush(QColor("#3B82F6" if self._dark else "#DBEAFE")))

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._readonly:
            event.ignore()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drop_hint_active_style()
        elif event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            # Drag interno vindo da própria árvore
            event.acceptProposedAction()
            self._drop_hint_active_style()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        has_urls     = event.mimeData().hasUrls()
        has_internal = event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist")
        if not has_urls and not has_internal:
            event.ignore()
            return
        # position() já está em coordenadas do viewport (evento vem via eventFilter)
        local_pos = event.position().toPoint()
        item = self.tree.itemAt(local_pos)
        node = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        target = item if (node and node["is_dir"]) else (
            self.tree.topLevelItem(0) if self.tree.topLevelItemCount() else None
        )
        self._highlight_drop_target(target)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drop_hint_normal_style()
        self._highlight_drop_target(None)

    def dropEvent(self, event: QDropEvent):
        self._drop_hint_normal_style()
        self._highlight_drop_target(None)

        # Descobre pasta-alvo independente do tipo de drag
        # position() já está em coordenadas do viewport (evento vem via eventFilter)
        local_pos   = event.position().toPoint()
        target_item = self.tree.itemAt(local_pos)
        target_dir  = self._demand_root_path()

        if target_item:
            node = target_item.data(0, Qt.ItemDataRole.UserRole)
            if node and node["is_dir"]:
                target_dir = node["path"]
            elif node and not node["is_dir"]:
                target_dir = str(Path(node["path"]).parent)

        root = self._demand_root_path()

        # ── Drag interno (árvore usa formato próprio, sem URLs) ───────────────
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist") \
                and not event.mimeData().hasUrls():
            internal = [
                n["path"] for n in self._selected_nodes()
                if n["path"] != target_dir and not n.get("is_root")
            ]
            errors = []
            for src in internal:
                if Path(target_dir).is_relative_to(src):
                    continue  # não mover pasta para dentro de si mesma
                try:
                    self._fs.move_item(src, target_dir)
                except Exception as e:
                    errors.append(f"• {Path(src).name}: {e}")
            if internal:
                self.refresh()
                self.files_changed.emit()
            if errors:
                self._err("Erros ao mover:\n" + "\n".join(errors))
            event.acceptProposedAction()
            return

        # ── Drag externo (URLs do Explorer ou outro app) ──────────────────────
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            event.ignore()
            return

        external = [p for p in paths if not p.startswith(root)]
        internal = [p for p in paths if p.startswith(root) and p != target_dir]

        if external:
            self._move_files(external, target_dir)

        if internal:
            errors = []
            for src in internal:
                if src == target_dir or Path(target_dir).is_relative_to(src):
                    continue
                try:
                    self._fs.move_item(src, target_dir)
                except Exception as e:
                    errors.append(f"• {Path(src).name}: {e}")
            if internal:
                self.refresh()
                self.files_changed.emit()
            if errors:
                self._err("Erros ao mover:\n" + "\n".join(errors))

        event.acceptProposedAction()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _err(self, msg: str):
        QMessageBox.critical(self, "Erro", msg)

    def _warn(self, msg: str):
        QMessageBox.warning(self, "Atenção", msg)