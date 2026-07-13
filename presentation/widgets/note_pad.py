"""
NotePad — editor de texto rico estilo Word integrado ao DemandFlow.
Inclui toolbar de formatação, spell-check e reescrita por IA (seleção-aware).
"""
import html as _html

import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QComboBox, QColorDialog, QLabel,
    QApplication, QFileDialog, QLineEdit, QGraphicsDropShadowEffect,
    QListWidget, QListWidgetItem, QSplitter, QScrollBar, QTextEdit,
)
from PyQt6.QtGui import (
    QTextCharFormat, QTextListFormat, QColor, QFont, QTextCursor,
    QPainter, QBitmap, QTextBlockFormat,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QEvent

from presentation.widgets.spell_check import SpellCheckTextEdit

# (size_pt, margin_top, margin_bottom)
_HEADING_STYLES = {1: (22, 14, 6), 2: (16, 10, 4), 3: (13, 8, 2)}


# ── Toolbar de formatação ─────────────────────────────────────────────────────

class _Sep(QFrame):
    """Separador vertical compacto."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedWidth(2)
        self.setStyleSheet("background-color: #94A3B8; margin: 3px 0;")


class _ToolBtn(QPushButton):
    def __init__(self, icon_name: str, tooltip: str, checkable=False, dark=False, parent=None):
        super().__init__(parent)
        ic_color   = "#94A3B8" if dark else "#475569"
        hover_bg   = "#1E3A5F" if dark else "#E2E8F0"
        checked_bg = "#1E3A5F" if dark else "#DBEAFE"
        self.setIcon(qta.icon(icon_name, color=ic_color))
        self.setToolTip(tooltip)
        self.setFixedSize(28, 28)
        self.setCheckable(checkable)
        self.setAutoDefault(False)
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 5px; padding: 2px;
            }}
            QPushButton:hover {{ background: {hover_bg}; }}
            QPushButton:checked {{ background: {checked_bg}; border: 1px solid #3B82F6; }}
        """)


class _TextBtn(QPushButton):
    """Botão da toolbar com texto em vez de ícone (ex.: H1, H2, H3, ¶)."""
    def __init__(self, text: str, tooltip: str, checkable=False, dark=False, parent=None):
        super().__init__(text, parent)
        hover_bg   = "#1E3A5F" if dark else "#E2E8F0"
        checked_bg = "#1E3A5F" if dark else "#DBEAFE"
        self.setToolTip(tooltip)
        self.setFixedSize(28, 28)
        self.setCheckable(checkable)
        self.setAutoDefault(False)
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 5px;
                font-size: 11px; font-weight: 700; padding: 0;
            }}
            QPushButton:hover {{ background: {hover_bg}; }}
            QPushButton:checked {{ background: {checked_bg}; border: 1px solid #3B82F6; }}
        """)


class _FormattingToolbar(QFrame):
    def __init__(self, editor: SpellCheckTextEdit, ai_service=None, dark=False, parent=None):
        super().__init__(parent)
        self._editor = editor
        self._ai_service = ai_service
        self._dark = dark

        bg  = "#1E293B" if dark else "#F8FAFC"
        brd = "#334155" if dark else "#E2E8F0"
        self.setStyleSheet(f"QFrame {{ background:{bg}; border-bottom:1px solid {brd}; }}")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(2)

        # Negrito / Itálico / Sublinhado
        self._bold_btn = _ToolBtn("fa6s.bold", "Negrito (Ctrl+B)", checkable=True, dark=dark)
        self._ital_btn = _ToolBtn("fa6s.italic", "Itálico (Ctrl+I)", checkable=True, dark=dark)
        self._ulin_btn = _ToolBtn("fa6s.underline", "Sublinhado (Ctrl+U)", checkable=True, dark=dark)
        self._bold_btn.clicked.connect(
            lambda c: editor.setFontWeight(QFont.Weight.Bold if c else QFont.Weight.Normal))
        self._ital_btn.clicked.connect(editor.setFontItalic)
        self._ulin_btn.clicked.connect(editor.setFontUnderline)
        for b in (self._bold_btn, self._ital_btn, self._ulin_btn):
            row.addWidget(b)

        row.addWidget(_Sep())

        # Cor do texto
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(28, 28)
        self._color_btn.setToolTip("Cor do texto")
        self._color_btn.setAutoDefault(False)
        self._color_btn.setStyleSheet(
            "QPushButton { border:2px solid #334155; border-radius:5px; background:#E2E8F0; }"
            "QPushButton:hover { border-color:#3B82F6; }"
        )
        self._color_btn.clicked.connect(self._pick_color)
        row.addWidget(self._color_btn)

        row.addWidget(_Sep())

        # Tamanho de fonte
        self._size_combo = QComboBox()
        self._size_combo.setObjectName("font_size_combo")
        self._size_combo.setFixedWidth(62)
        self._size_combo.setFixedHeight(26)
        for s in ["8","9","10","11","12","14","16","18","20","24","28","32","36","48","72"]:
            self._size_combo.addItem(s)
        self._size_combo.setCurrentText("12")
        self._size_combo.activated.connect(self._change_size)
        row.addWidget(self._size_combo)

        row.addWidget(_Sep())

        # Listas
        self._blist_btn = _ToolBtn("fa6s.list-ul", "Lista com marcadores", checkable=True, dark=dark)
        self._nlist_btn = _ToolBtn("fa6s.list-ol", "Lista numerada", checkable=True, dark=dark)
        self._blist_btn.clicked.connect(
            lambda: self._toggle_list(QTextListFormat.Style.ListDisc))
        self._nlist_btn.clicked.connect(
            lambda: self._toggle_list(QTextListFormat.Style.ListDecimal))
        row.addWidget(self._blist_btn)
        row.addWidget(self._nlist_btn)

        row.addWidget(_Sep())

        # Alinhamento
        self._align_left_btn    = _ToolBtn("fa6s.align-left",    "Alinhar à esquerda", checkable=True, dark=dark)
        self._align_center_btn  = _ToolBtn("fa6s.align-center",  "Centralizar",        checkable=True, dark=dark)
        self._align_right_btn   = _ToolBtn("fa6s.align-right",   "Alinhar à direita",  checkable=True, dark=dark)
        self._align_justify_btn = _ToolBtn("fa6s.align-justify", "Justificar",         checkable=True, dark=dark)
        self._align_btns = {
            self._align_left_btn:    Qt.AlignmentFlag.AlignLeft,
            self._align_center_btn:  Qt.AlignmentFlag.AlignHCenter,
            self._align_right_btn:   Qt.AlignmentFlag.AlignRight,
            self._align_justify_btn: Qt.AlignmentFlag.AlignJustify,
        }
        for btn, align in self._align_btns.items():
            btn.clicked.connect(lambda _, a=align: self._set_alignment(a))
            row.addWidget(btn)

        row.addWidget(_Sep())

        # Inserir imagem
        self._img_btn = _ToolBtn("fa6s.image", "Inserir imagem", dark=dark)
        self._img_btn.clicked.connect(self._insert_image)
        row.addWidget(self._img_btn)

        row.addWidget(_Sep())

        # Limpar formatação (seleção) — volta negrito/itálico/cor/link etc.
        # ao padrão, útil depois de colar texto de outro lugar.
        self._clear_fmt_btn = _ToolBtn("fa6s.eraser", "Limpar formatação da seleção", dark=dark)
        self._clear_fmt_btn.clicked.connect(self._clear_formatting)
        row.addWidget(self._clear_fmt_btn)

        row.addWidget(_Sep())

        # Estilos de título
        self._h1_btn   = _TextBtn("H1", "Título 1", checkable=True, dark=dark)
        self._h2_btn   = _TextBtn("H2", "Título 2", checkable=True, dark=dark)
        self._h3_btn   = _TextBtn("H3", "Título 3", checkable=True, dark=dark)
        self._para_btn = _TextBtn("¶",  "Parágrafo normal", checkable=True, dark=dark)
        self._h1_btn.clicked.connect(lambda: self._apply_heading(1))
        self._h2_btn.clicked.connect(lambda: self._apply_heading(2))
        self._h3_btn.clicked.connect(lambda: self._apply_heading(3))
        self._para_btn.clicked.connect(lambda: self._apply_heading(0))
        for b in (self._h1_btn, self._h2_btn, self._h3_btn, self._para_btn):
            row.addWidget(b)

        row.addStretch()

        # Botão IA (só aparece se configurado)
        self._ai_btn = QPushButton("  Reescrever")
        self._ai_btn.setIcon(qta.icon("fa6s.wand-magic-sparkles", color="white"))
        self._ai_btn.setToolTip("Reescrever texto selecionado com IA")
        self._ai_btn.setFixedHeight(26)
        self._ai_btn.setAutoDefault(False)
        self._ai_btn.setStyleSheet(
            "QPushButton { background:#8B5CF6; color:white; border:none; border-radius:6px;"
            " padding:0 10px; font-size:12px; font-weight:600; }"
            "QPushButton:hover { background:#7C3AED; }"
            "QPushButton:disabled { background:#6B7280; }"
        )
        self._ai_btn.clicked.connect(self._ai_rewrite)
        self._ai_btn.setVisible(bool(ai_service and ai_service.is_configured()))
        row.addWidget(self._ai_btn)

        # Sincroniza estado com o cursor e seleção
        editor.currentCharFormatChanged.connect(self._sync_format)
        editor.cursorPositionChanged.connect(self._sync_format_from_cursor)
        editor.selectionChanged.connect(self._sync_format_from_cursor)
        editor.cursorPositionChanged.connect(self._sync_list_state)
        editor.cursorPositionChanged.connect(self._sync_alignment)
        self._sync_alignment()

    # ── Sync ─────────────────────────────────────────────────────────────────

    def _fmt_at_pos(self, pos: int) -> QTextCharFormat:
        """Retorna o QTextCharFormat do caractere na posição absoluta pos."""
        block = self._editor.document().findBlock(pos)
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.position() <= pos < frag.position() + frag.length():
                return frag.charFormat()
            it += 1
        return self._editor.currentCharFormat()

    def _sync_format_from_cursor(self):
        cursor = self._editor.textCursor()
        pos = cursor.selectionStart() if cursor.hasSelection() else max(0, cursor.position() - 1)
        self._sync_format(self._fmt_at_pos(pos))
        state = cursor.block().userState()
        self._sync_heading_btns(state if state >= 0 else 0)

    def _sync_heading_btns(self, state: int):
        self._h1_btn.setChecked(state == 1)
        self._h2_btn.setChecked(state == 2)
        self._h3_btn.setChecked(state == 3)
        self._para_btn.setChecked(state <= 0)

    def _sync_format(self, fmt: QTextCharFormat):
        self._bold_btn.setChecked(fmt.fontWeight() >= QFont.Weight.Bold)
        self._ital_btn.setChecked(fmt.fontItalic())
        self._ulin_btn.setChecked(fmt.fontUnderline())
        color = fmt.foreground().color()
        if color.isValid():
            self._color_btn.setStyleSheet(
                f"QPushButton {{ border:2px solid #334155; border-radius:5px; background:{color.name()}; }}"
                "QPushButton:hover { border-color:#3B82F6; }"
            )
        size = fmt.fontPointSize()
        if size <= 0:
            # texto colado de fontes externas pode usar pixels em vez de pontos
            px = fmt.font().pixelSize()
            if px > 0:
                dpi = QApplication.primaryScreen().logicalDotsPerInch()
                size = px * 72.0 / dpi
            else:
                size = self._editor.document().defaultFont().pointSize()
        if size > 0:
            self._size_combo.blockSignals(True)
            target = str(round(size))
            idx = self._size_combo.findText(target)
            if idx >= 0:
                self._size_combo.setCurrentIndex(idx)
            else:
                # tamanho não está na lista — insere temporariamente
                self._size_combo.insertItem(0, target)
                self._size_combo.setCurrentIndex(0)
            self._size_combo.blockSignals(False)

    def _sync_alignment(self):
        align = self._editor.alignment()
        for btn, a in self._align_btns.items():
            btn.setChecked(align == a)

    def _sync_list_state(self):
        cur_list = self._editor.textCursor().currentList()
        if cur_list:
            style = cur_list.format().style()
            self._blist_btn.setChecked(style == QTextListFormat.Style.ListDisc)
            self._nlist_btn.setChecked(style == QTextListFormat.Style.ListDecimal)
        else:
            self._blist_btn.setChecked(False)
            self._nlist_btn.setChecked(False)

    # ── Ações ─────────────────────────────────────────────────────────────────

    def _pick_color(self):
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self._editor.setTextColor(color)
            self._color_btn.setStyleSheet(
                f"QPushButton {{ border:2px solid #334155; border-radius:5px; background:{color.name()}; }}"
                "QPushButton:hover { border-color:#3B82F6; }"
            )

    def _change_size(self, _index: int = 0):
        try:
            size = float(self._size_combo.currentText())
            if size > 0:
                self._editor.setFontPointSize(size)
                self._editor.setFocus()
        except ValueError:
            pass

    def _toggle_list(self, style: QTextListFormat.Style):
        cursor = self._editor.textCursor()
        cur_list = cursor.currentList()
        fmt = QTextListFormat()
        if cur_list and cur_list.format().style() == style:
            # Remove list — reset block format
            block_fmt = cursor.blockFormat()
            block_fmt.setIndent(0)
            cursor.setBlockFormat(block_fmt)
            cursor.setBlockCharFormat(QTextCharFormat())
        else:
            fmt.setStyle(style)
            fmt.setIndent(1)
            cursor.createList(fmt)
        self._editor.setTextCursor(cursor)
        self._sync_list_state()

    def _set_alignment(self, align: Qt.AlignmentFlag):
        self._editor.setAlignment(align)
        self._sync_alignment()

    def _clear_formatting(self):
        """Remove negrito/itálico/sublinhado/cor/fonte/link da seleção,
        voltando ao estilo padrão — útil pra "limpar" texto colado de fora."""
        cursor = self._editor.textCursor()
        if not cursor.hasSelection():
            return
        cursor.setCharFormat(QTextCharFormat())

    def _apply_heading(self, level: int):
        cursor = self._editor.textCursor()
        # Toggle: clicar o mesmo nível novamente vira parágrafo normal
        if level != 0 and cursor.block().userState() == level:
            level = 0

        doc = self._editor.document()
        default_size = doc.defaultFont().pointSize()
        if default_size <= 0:
            default_size = 11
        sel_start = cursor.selectionStart()
        sel_end   = cursor.selectionEnd()

        cursor.beginEditBlock()
        block = doc.findBlock(sel_start)
        while block.isValid():
            char_fmt  = QTextCharFormat()
            block_fmt = QTextBlockFormat()
            if level == 0:
                char_fmt.setFontPointSize(default_size)
                char_fmt.setFontWeight(QFont.Weight.Normal)
            else:
                size, mt, mb = _HEADING_STYLES[level]
                char_fmt.setFontPointSize(size)
                char_fmt.setFontWeight(QFont.Weight.Bold)
                block_fmt.setTopMargin(mt)
                block_fmt.setBottomMargin(mb)

            bc = QTextCursor(block)
            bc.setBlockFormat(block_fmt)
            bc.setBlockCharFormat(char_fmt)
            bc.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            bc.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
            bc.setCharFormat(char_fmt)
            block.setUserState(level)

            if block.position() + block.length() - 1 >= sel_end:
                break
            block = block.next()
        cursor.endEditBlock()
        self._sync_heading_btns(level)

    def _ai_rewrite(self):
        if not (self._ai_service and self._ai_service.is_configured()):
            return
        cursor = self._editor.textCursor()
        text = (
            cursor.selectedText().replace(" ", "\n").strip()
            if cursor.hasSelection()
            else self._editor.toPlainText().strip()
        )
        if not text:
            return
        self._show_prompt_popup()

    def _show_prompt_popup(self):
        popup = QFrame(self, Qt.WindowType.Popup)
        popup.setObjectName("ai_prompt_popup")

        v = QVBoxLayout(popup)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)

        lbl = QLabel("O que a IA deve fazer?")
        v.addWidget(lbl)

        inp = QLineEdit()
        inp.setPlaceholderText("Ex: Resumir, melhorar, corrigir...")
        inp.setFixedWidth(260)
        v.addWidget(inp)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(4)
        for chip_label in ("Resumir", "Melhorar", "Formalizar", "Corrigir"):
            chip = QPushButton(chip_label)
            chip.setObjectName("btn_chip")
            chip.setAutoDefault(False)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, t=chip_label: inp.setText(t))
            chips_row.addWidget(chip)
        chips_row.addStretch()
        v.addLayout(chips_row)

        apply_btn = QPushButton("Aplicar")
        apply_btn.setObjectName("btn_primary")
        apply_btn.setAutoDefault(False)

        def _apply():
            instruction = inp.text().strip()
            popup.close()
            if instruction:
                self._run_rewrite(instruction)

        apply_btn.clicked.connect(_apply)
        inp.returnPressed.connect(_apply)
        v.addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignRight)

        popup.adjustSize()
        bmp = QBitmap(popup.size())
        bmp.fill(Qt.GlobalColor.color0)
        p = QPainter(bmp)
        p.setBrush(Qt.GlobalColor.color1)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(popup.rect(), 8, 8)
        p.end()
        popup.setMask(bmp)
        btn_global = self._ai_btn.mapToGlobal(QPoint(0, 0))
        x = btn_global.x() - popup.width() + self._ai_btn.width()
        y = btn_global.y() - popup.height() - 6
        popup.move(x, y)
        popup.show()
        inp.setFocus()

    def _run_rewrite(self, instruction: str):
        cursor = self._editor.textCursor()
        text = (
            cursor.selectedText().replace(" ", "\n").strip()
            if cursor.hasSelection()
            else self._editor.toPlainText().strip()
        )
        if not text:
            return
        self._ai_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            rewritten = self._ai_service.rewrite_text(text, instruction)
            if cursor.hasSelection():
                cursor.insertText(rewritten)
            else:
                self._editor.setPlainText(rewritten)
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self._editor, "Erro IA", str(exc))
        finally:
            self._ai_btn.setEnabled(True)

    def set_ai_service(self, ai_service):
        self._ai_service = ai_service
        self._ai_btn.setVisible(bool(ai_service and ai_service.is_configured()))

    def set_dark(self, dark: bool):
        self._dark = dark
        bg  = "#1E293B" if dark else "#F8FAFC"
        brd = "#334155" if dark else "#E2E8F0"
        self.setStyleSheet(f"QFrame {{ background:{bg}; border-bottom:1px solid {brd}; }}")

    def _insert_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Inserir imagem", "",
            "Imagens (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
        )
        if path:
            self._editor.insert_image_from_path(path)


# ── Marcadores na scrollbar ──────────────────────────────────────────────────

class _MatchMarks(QWidget):
    """Widget filho da QScrollBar vertical, transparente para o mouse,
    que pinta pequenos ticks amarelos nas posições dos matches de busca."""

    def __init__(self, scrollbar: QScrollBar):
        super().__init__(scrollbar)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._fracs: list[float] = []
        self._color = QColor("#F59E0B")
        scrollbar.installEventFilter(self)
        self.setGeometry(scrollbar.rect())
        self.raise_()
        self.show()

    def set_fracs(self, fracs: list[float]):
        self._fracs = fracs
        self.setGeometry(self.parent().rect())
        self.raise_()
        self.update()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
            self.raise_()
        return False

    def paintEvent(self, event):
        if not self._fracs:
            return
        p = QPainter(self)
        h = self.height()
        w = self.width()
        for frac in self._fracs:
            y = int(frac * h)
            p.fillRect(1, max(0, y - 1), w - 2, 2, self._color)
        p.end()


# ── Painel TOC ───────────────────────────────────────────────────────────────

class _TocPanel(QFrame):
    """Painel lateral com índice de títulos (H1/H2/H3) do editor."""

    heading_clicked = pyqtSignal(int)   # posição do bloco no documento
    search_changed  = pyqtSignal(str)   # query de busca digitada pelo usuário

    def __init__(self, dark=False, parent=None):
        super().__init__(parent)
        self._dark = dark
        self._all_headings: list[tuple[int, str, int]] = []
        self._apply_styles()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setObjectName("search_input")
        self._search.setPlaceholderText("🔍  Buscar nas notas...")
        self._search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(
            lambda item: self.heading_clicked.emit(item.data(Qt.ItemDataRole.UserRole))
        )
        layout.addWidget(self._list, 1)

    def _apply_styles(self):
        dark = self._dark
        bg   = "#1E293B" if dark else "#F8FAFC"
        brd  = "#334155" if dark else "#E2E8F0"
        fg   = "#94A3B8" if dark else "#64748B"
        hov  = "#1E3A5F" if dark else "#E2E8F0"
        sel  = "#1E3A5F" if dark else "#DBEAFE"
        selc = "#93C5FD" if dark else "#1D4ED8"
        self.setStyleSheet(f"""
            QFrame {{ background:{bg}; border-right:1px solid {brd}; }}
            QListWidget {{ background:{bg}; color:{fg}; border:none; font-size:12px; }}
            QListWidget::item {{ padding:3px 6px; border-radius:3px; }}
            QListWidget::item:hover {{ background:{hov}; }}
            QListWidget::item:selected {{ background:{sel}; color:{selc}; }}
        """)

    def update_headings(self, doc):
        self._all_headings = []
        block = doc.begin()
        while block.isValid():
            state = block.userState()
            if state in (1, 2, 3):
                text = block.text().strip()
                if text:
                    self._all_headings.append((state, text, block.position()))
            block = block.next()
        self._apply_filter(self._search.text())

    def _apply_filter(self, query: str):
        self._list.clear()
        q = query.strip().lower()
        for state, text, pos in self._all_headings:
            if q and q not in text.lower():
                continue
            item = QListWidgetItem("  " * (state - 1) + text)
            item.setData(Qt.ItemDataRole.UserRole, pos)
            f = item.font()
            f.setBold(state == 1)
            f.setPointSize(11 if state <= 2 else 10)
            item.setFont(f)
            self._list.addItem(item)

    def _on_search_changed(self, query: str):
        self._apply_filter(query)
        self.search_changed.emit(query)

    def current_search(self) -> str:
        return self._search.text()

    def clear_search(self):
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._apply_filter("")

    def set_dark(self, dark: bool):
        self._dark = dark
        self._apply_styles()


# ── Widget público ────────────────────────────────────────────────────────────

class NotePad(QWidget):
    """
    Editor de texto rico com toolbar de formatação, spell-check e IA.
    Emite `notes_changed(html)` após 2s de inatividade.
    """

    notes_changed = pyqtSignal(str)

    def __init__(self, ai_service=None, dark: bool = False, parent=None):
        super().__init__(parent)
        self._dark = dark
        self._toc_open = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._editor = SpellCheckTextEdit()
        self._editor.setAcceptRichText(True)
        self._apply_bottom_margin()
        self._match_marks = _MatchMarks(self._editor.verticalScrollBar())

        self._toolbar = _FormattingToolbar(self._editor, ai_service, dark)
        root.addWidget(self._toolbar)

        # ── Área de conteúdo: coluna TOC + editor ──────────────────────────
        # Coluna esquerda: botão de toggle + painel TOC
        self._toc_col = QWidget()
        self._toc_col.setMinimumWidth(32)
        self._toc_open_width = 200
        toc_col_v = QVBoxLayout(self._toc_col)
        toc_col_v.setContentsMargins(0, 0, 0, 0)
        toc_col_v.setSpacing(0)

        self._toc_toggle_btn = QPushButton("◀  Índice")
        self._toc_toggle_btn.setFixedHeight(28)
        self._toc_toggle_btn.setAutoDefault(False)
        self._toc_toggle_btn.clicked.connect(self._toggle_toc)
        self._set_toc_btn_open(True)
        toc_col_v.addWidget(self._toc_toggle_btn)

        self._toc_panel = _TocPanel(dark=dark)
        self._toc_panel.heading_clicked.connect(self._goto_heading)
        self._toc_panel.search_changed.connect(self._search_in_notes)
        toc_col_v.addWidget(self._toc_panel, 1)

        # Splitter permite arrastar para redimensionar a coluna do índice
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._toc_col)
        self._splitter.addWidget(self._editor)
        self._splitter.setSizes([200, 800])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

        root.addWidget(self._splitter, 1)

        # Auto-save com debounce de 2s.
        # Usa contentsChange (com args position/removed/added) em vez de
        # textChanged — o spell checker dispara textChanged para mudanças de
        # formatação (underlines), mas contentsChange com removed==added==0
        # indica formatação pura; só inicia o timer quando há texto real alterado.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(2000)
        self._save_timer.timeout.connect(self._emit_changed)

        self._toc_timer = QTimer(self)
        self._toc_timer.setSingleShot(True)
        self._toc_timer.setInterval(400)
        self._toc_timer.timeout.connect(self._update_toc)

        self._editor.document().contentsChange.connect(self._on_content_change)

    def _on_content_change(self, _pos: int, removed: int, added: int):
        if removed > 0 or added > 0:
            self._save_timer.start()
            self._toc_timer.start()

    def _emit_changed(self):
        self.notes_changed.emit(self._editor.toHtml())

    def _set_toc_btn_open(self, open_: bool):
        ic_color = "#94A3B8" if self._dark else "#475569"
        if open_:
            self._toc_toggle_btn.setIcon(
                qta.icon("fa6s.chevron-left", color=ic_color))
            self._toc_toggle_btn.setText(" Índice")
        else:
            self._toc_toggle_btn.setIcon(
                qta.icon("fa6s.chevron-right", color=ic_color))
            self._toc_toggle_btn.setText("")
        self._apply_toc_toggle_style(open_)

    def _apply_toc_toggle_style(self, open_: bool = True):
        dark = self._dark
        bg  = "#1E293B" if dark else "#F8FAFC"
        brd = "#334155" if dark else "#E2E8F0"
        fg  = "#94A3B8" if dark else "#475569"
        hov = "#1E3A5F" if dark else "#E2E8F0"
        padding = "padding-left:6px;" if open_ else "padding:0;"
        align   = "left" if open_ else "center"
        self._toc_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background:{bg}; border:none;
                border-bottom:1px solid {brd}; border-right:1px solid {brd};
                color:{fg}; font-size:11px; font-weight:600;
                text-align:{align}; {padding}
            }}
            QPushButton:hover {{ background:{hov}; }}
        """)

    def _restore_heading_states(self):
        """Infere nível de título a partir do formato do primeiro fragmento do bloco."""
        doc = self._editor.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            if not it.atEnd():
                fmt  = it.fragment().charFormat()
                size = fmt.fontPointSize()
                bold = fmt.fontWeight() >= QFont.Weight.Bold
                if bold and size >= 20:
                    block.setUserState(1)
                elif bold and size >= 14:
                    block.setUserState(2)
                elif bold and size >= 12:
                    block.setUserState(3)
                else:
                    block.setUserState(0)
            else:
                block.setUserState(0)
            block = block.next()

    def _update_toc(self):
        self._toc_panel.update_headings(self._editor.document())

    def _toggle_toc(self):
        self._toc_open = not self._toc_open
        self._toc_panel.setVisible(self._toc_open)
        sizes = self._splitter.sizes()
        total = sum(sizes)
        if self._toc_open:
            w = max(self._toc_open_width, 120)
            self._splitter.setSizes([w, total - w])
            self._set_toc_btn_open(True)
        else:
            self._toc_open_width = sizes[0]  # guarda largura atual
            self._splitter.setSizes([32, total - 32])
            self._set_toc_btn_open(False)

    def _goto_heading(self, pos: int):
        cursor = self._editor.textCursor()
        cursor.setPosition(pos)
        self._editor.setTextCursor(cursor)
        self._editor.ensureCursorVisible()
        self._editor.setFocus()

    def _search_in_notes(self, query: str):
        doc = self._editor.document()
        selections: list[QTextEdit.ExtraSelection] = []
        fracs: list[float] = []
        q = query.strip()

        if q:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#5C3A0A" if self._dark else "#FEF3C7"))
            fmt.setForeground(QColor("#F59E0B" if self._dark else "#92400E"))
            fmt.setFontWeight(QFont.Weight.DemiBold)

            cursor  = QTextCursor(doc)
            layout  = doc.documentLayout()
            doc_h   = doc.size().height()

            while True:
                cursor = doc.find(q, cursor)
                if cursor.isNull():
                    break
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format  = fmt
                selections.append(sel)
                if doc_h > 0:
                    top = layout.blockBoundingRect(cursor.block()).top()
                    fracs.append(top / doc_h)

        self._editor.setExtraSelections(selections)
        self._match_marks.set_fracs(fracs)

    # ── API pública ───────────────────────────────────────────────────────────

    def _apply_bottom_margin(self):
        line_h = self._editor.fontMetrics().lineSpacing()
        fmt = self._editor.document().rootFrame().frameFormat()
        fmt.setBottomMargin(line_h * 5)
        self._editor.document().rootFrame().setFrameFormat(fmt)

    def set_html(self, html: str):
        # Bloqueia sinais do documento (não só do widget) para que o setHtml
        # não dispare contentsChange e inicie o timer de save indevidamente.
        self._editor._deselect_image()
        doc = self._editor.document()
        doc.blockSignals(True)
        self._editor.setHtml(html)
        self._apply_bottom_margin()
        doc.blockSignals(False)
        self._save_timer.stop()
        self._restore_heading_states()
        self._update_toc()
        self._search_in_notes(self._toc_panel.current_search())

    def get_html(self) -> str:
        return self._editor.toHtml()

    def set_ai_service(self, ai_service):
        self._toolbar.set_ai_service(ai_service)

    def set_dark(self, dark: bool):
        self._dark = dark
        self._toolbar.set_dark(dark)
        self._toc_panel.set_dark(dark)
        self._set_toc_btn_open(self._toc_open)

    def import_comments(self, comments: list) -> str:
        """Converte lista de Comment em HTML e carrega no editor. Retorna o HTML."""
        if not comments:
            return ""
        parts = ['<p style="color:#94A3B8;font-size:11px"><i>Importado dos comentários</i></p><hr/>']
        for c in comments:
            dt = c.created_at.strftime("%d/%m/%Y %H:%M")
            text_html = _html.escape(c.text).replace("\n", "<br>")
            parts.append(
                f'<p><b>{_html.escape(c.author)}</b>'
                f' <span style="color:#94A3B8;font-size:11px">· {dt}</span></p>'
                f'<p>{text_html}</p><hr/>'
            )
        result = "".join(parts)
        self.set_html(result)
        return result
