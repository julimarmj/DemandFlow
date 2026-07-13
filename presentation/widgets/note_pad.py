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
)
from PyQt6.QtGui import (
    QTextCharFormat, QTextListFormat, QColor, QFont, QTextCursor,
    QPainter, QBitmap,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint

from presentation.widgets.spell_check import SpellCheckTextEdit


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
            px = fmt.fontPixelSize()
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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._editor = SpellCheckTextEdit()
        self._editor.setAcceptRichText(True)
        self._apply_bottom_margin()

        self._toolbar = _FormattingToolbar(self._editor, ai_service, dark)
        root.addWidget(self._toolbar)
        root.addWidget(self._editor, 1)

        # Auto-save com debounce de 2s.
        # Usa contentsChange (com args position/removed/added) em vez de
        # textChanged — o spell checker dispara textChanged para mudanças de
        # formatação (underlines), mas contentsChange com removed==added==0
        # indica formatação pura; só inicia o timer quando há texto real alterado.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(2000)
        self._save_timer.timeout.connect(self._emit_changed)
        self._editor.document().contentsChange.connect(self._on_content_change)

    def _on_content_change(self, _pos: int, removed: int, added: int):
        if removed > 0 or added > 0:
            self._save_timer.start()

    def _emit_changed(self):
        self.notes_changed.emit(self._editor.toHtml())

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

    def get_html(self) -> str:
        return self._editor.toHtml()

    def set_ai_service(self, ai_service):
        self._toolbar.set_ai_service(ai_service)

    def set_dark(self, dark: bool):
        self._dark = dark
        self._toolbar.set_dark(dark)

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
