"""
DemandFlow - Widgets Reutilizáveis
Componentes visuais customizados para uso em toda a aplicação.
"""
import html as _html
import re as _re

import qtawesome as qta
from PyQt6.QtWidgets import (
    QProgressBar, QScrollArea, QWidget, QLabel, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QSizePolicy, QGraphicsDropShadowEffect, QLineEdit, QApplication
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QTextCursor, QTextCharFormat, QBitmap

from core.domain.entities import Demand, Status, Priority
from core.domain.text_match import find_fuzzy_word
from presentation.widgets.spell_check import SpellCheckTextEdit


def _plain_text(html: str) -> str:
    """Remove tags HTML e decodifica entidades, retornando texto simples."""
    text = _re.sub(r'<[^>]+>', ' ', html)
    text = _html.unescape(text)
    return _re.sub(r'\s+', ' ', text).strip()


def _highlight_html(text: str, query: str, dark: bool) -> str:
    """Escapa `text` e destaca a parte que bateu com a busca: ocorrências
    exatas (case-insensitive) do texto digitado, ou — se não houver nenhuma —
    a palavra inteira que bateu por correspondência aproximada (mesmo
    critério tolerante a erro de digitação usado no filtro da lista)."""
    if not query:
        return text  # sem destaque: texto puro, QLabel renderiza sem escapar

    # Tom suave (não um amarelo berrante) + negrito — destaca sem gritar,
    # mantendo a cor de texto original do label.
    bg = "#5C3A0A" if dark else "#FEF3C7"

    def _wrap(s: str) -> str:
        return f'<span style="background-color:{bg}; font-weight:600; border-radius:2px;">{_html.escape(s)}</span>'

    matches = list(_re.finditer(_re.escape(query), text, _re.IGNORECASE))
    if matches:
        out, last = [], 0
        for m in matches:
            out.append(_html.escape(text[last:m.start()]))
            out.append(_wrap(m.group(0)))
            last = m.end()
        out.append(_html.escape(text[last:]))
        return "".join(out)

    if len(query) >= 3:
        m = find_fuzzy_word(query, text, 1)
        if m:
            return (
                _html.escape(text[:m.start()]) + _wrap(m.group(0)) + _html.escape(text[m.end():])
            )

    return text  # busca sem match: texto puro, evita exibir &quot; etc. literalmente


def highlight_matches_in_text_edit(text_edit, query: str, dark: bool):
    """Destaca ocorrências de `query` dentro de um QTextEdit que já tem
    conteúdo (possivelmente HTML rico — negrito, links, imagens) carregado.
    Diferente de `_highlight_html`, opera no QTextDocument já parseado via
    QTextCursor — não mexe na string HTML, então nunca corrompe formatação
    existente. Se não achar nenhuma ocorrência exata, tenta destacar a
    palavra inteira que bate por correspondência aproximada."""
    if not query:
        return
    doc = text_edit.document()
    fmt = QTextCharFormat()
    fmt.setBackground(QColor("#5C3A0A" if dark else "#FEF3C7"))
    fmt.setFontWeight(QFont.Weight.DemiBold)

    found_any = False
    cursor = QTextCursor(doc)
    while True:
        cursor = doc.find(query, cursor)  # sem FindCaseSensitively => case-insensitive
        if cursor.isNull():
            break
        cursor.mergeCharFormat(fmt)
        found_any = True

    if not found_any and len(query) >= 3:
        m = find_fuzzy_word(query, doc.toPlainText(), 1)
        if m:
            hcursor = QTextCursor(doc)
            hcursor.setPosition(m.start())
            hcursor.setPosition(m.end(), QTextCursor.MoveMode.KeepAnchor)
            hcursor.mergeCharFormat(fmt)


# ─── Badge Label ──────────────────────────────────────────────────────────────

class BadgeLabel(QLabel):
    """Pill badge com cor de fundo e texto."""

    def __init__(self, text: str, bg: str, fg: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border-radius: 10px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
        """)
        self.setFixedHeight(20)


def status_badge(status: Status) -> BadgeLabel:
    bgs = {
        Status.NAO_INICIADA: "#F3F4F6", Status.EM_ANDAMENTO: "#DBEAFE",
        Status.AGUARDANDO:   "#FEF3C7", Status.BLOQUEADA:    "#FEE2E2",
        Status.CONCLUIDA:    "#D1FAE5", Status.CANCELADA:    "#F9FAFB",
    }
    return BadgeLabel(
        f"{status.icon} {status.label}",
        bgs.get(status, "#F3F4F6"),
        status.color,
    )


def priority_badge(priority: Priority) -> BadgeLabel:
    bgs = {
        Priority.BAIXA:   "#F3F4F6", Priority.MEDIA:   "#DBEAFE",
        Priority.ALTA:    "#FEF3C7", Priority.CRITICA: "#FEE2E2",
    }
    return BadgeLabel(priority.label, bgs.get(priority, "#F3F4F6"), priority.color)


# ─── Stat Card ────────────────────────────────────────────────────────────────

class StatCard(QFrame):
    def __init__(self, label: str, value: str, color: str,
                 icon: str = "", dark: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedHeight(100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(0)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {'#94A3B8' if dark else '#64748B'}; font-size: 12px; font-weight: 500;")
        top.addWidget(lbl)
        top.addStretch()

        if icon:
            ico = QLabel(icon)
            ico.setStyleSheet("font-size: 18px; background: transparent;")
            top.addWidget(ico)

        layout.addLayout(top)

        val_lbl = QLabel(str(value))
        val_lbl.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: 700;")
        layout.addWidget(val_lbl)
        layout.addStretch()

        self.setStyleSheet(self.styleSheet() + f"""
            QFrame#card {{
                border-left: 4px solid {color};
            }}
        """)


# ─── Mini Bar Chart ───────────────────────────────────────────────────────────

class MiniBarChart(QWidget):
    bar_clicked = pyqtSignal(object)   # emite item["key"] (ou item["label"] se não houver key)

    def __init__(self, data: list[dict], title: str = "", dark: bool = False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if title:
            t = QLabel(title)
            t.setStyleSheet(f"color: {'#94A3B8' if dark else '#64748B'}; font-size: 12px; font-weight: 600;")
            layout.addWidget(t)

        max_val = max((d["value"] for d in data), default=1) or 1

        for item in data:
            item_frame = QFrame()
            item_frame.setObjectName("mbc_item")
            item_frame.setCursor(Qt.CursorShape.PointingHandCursor)
            # Policy "Minimum" em vez do padrão "Preferred": sem isso, quando a
            # janela fica pequena demais pra caber todas as linhas do card
            # (ex: "Por Status" com 6 itens), o layout comprime cada linha
            # abaixo do que o texto precisa em vez de deixar o card crescer /
            # rolar — o resultado é texto cortado/sobreposto.
            item_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            item_frame.setStyleSheet(
                "QFrame#mbc_item { background: transparent; border-radius: 4px; }"
                f"QFrame#mbc_item:hover {{ background: {'#1E293B' if dark else '#F8FAFC'}; }}"
            )
            row = QVBoxLayout(item_frame)
            row.setContentsMargins(4, 3, 4, 3)
            row.setSpacing(3)

            header = QHBoxLayout()
            name_lbl = QLabel(item["label"])
            name_lbl.setStyleSheet(f"font-size: 12px; color: {'#E2E8F0' if dark else '#1E293B'}; background: transparent;")
            # Sem isso, quando o card fica estreito demais pro texto caber
            # numa linha só, o QLabel (que não corta nem quebra por padrão)
            # deixa o texto vazar por cima da barra/número ao lado em vez de
            # simplesmente quebrar linha.
            name_lbl.setWordWrap(True)
            val_lbl  = QLabel(str(item["value"]))
            val_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {'#94A3B8' if dark else '#64748B'}; background: transparent;")
            val_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            header.addWidget(name_lbl, 1)
            header.addWidget(val_lbl)
            row.addLayout(header)

            track = QFrame()
            track.setFixedHeight(6)
            track.setStyleSheet(f"background: {'#334155' if dark else '#F1F5F9'}; border-radius: 3px;")

            bar_w = QWidget(track)
            bar_w.setFixedHeight(6)
            pct = int(item["value"] / max_val * 100)
            color = item.get("color", "#3B82F6")
            bar_w.setStyleSheet(f"background: {color}; border-radius: 3px;")

            def resize_bar(ev=None, bw=bar_w, tr=track, p=pct):
                w = tr.width()
                if w > 0:
                    bw.setFixedWidth(max(4, int(w * p / 100)))
            track.resizeEvent = resize_bar
            resize_bar()

            row.addWidget(track)

            key = item.get("key", item["label"])
            item_frame.mouseDoubleClickEvent = lambda _, k=key: self.bar_clicked.emit(k)

            layout.addWidget(item_frame)

        layout.addStretch()


# ─── Demand List Item ─────────────────────────────────────────────────────────

class DemandListItem(QFrame):
    selected      = pyqtSignal(object)
    double_clicked = pyqtSignal(object)

    def __init__(self, demand: Demand, dark: bool = False, parent=None, search_query: str = ""):
        super().__init__(parent)
        self.demand = demand
        self._dark = dark
        self._search_query = search_query.strip()
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._build()

    def _build(self):
        d = self.demand
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ── Top row: badges ──────────────────────────────────────────────────
        badges = QHBoxLayout()
        badges.setSpacing(6)
        badges.addWidget(status_badge(d.status))
        badges.addWidget(priority_badge(d.priority))

        if d.is_overdue:
            badges.addWidget(BadgeLabel("Atrasada", "#FEE2E2", "#DC2626"))
        if d.is_inactive:
            days = d.days_since_activity
            badges.addWidget(BadgeLabel(f"Inativa {days}d", "#FEF3C7", "#D97706"))
        badges.addStretch()

        root.addLayout(badges)

        # ── Title ────────────────────────────────────────────────────────────
        title = QLabel(_highlight_html(d.title, self._search_query, self._dark))
        title.setStyleSheet(f"font-weight: 600; font-size: 14px; color: {'#E2E8F0' if self._dark else '#0F172A'};")
        title.setWordWrap(True)
        root.addWidget(title)

        if d.description:
            plain = _plain_text(d.description)
            desc_text = plain[:250] + ("…" if len(plain) > 250 else "")
            desc = QLabel(_highlight_html(desc_text, self._search_query, self._dark))
            desc.setStyleSheet(f"color: {'#94A3B8' if self._dark else '#64748B'}; font-size: 12px;")
            desc.setWordWrap(True)
            root.addWidget(desc)

        # ── Meta row ─────────────────────────────────────────────────────────
        meta = QHBoxLayout()
        meta.setSpacing(10)
        _ic = "#64748B" if self._dark else "#9CA3AF"
        for icon_name, val in [
            ("fa6s.user",     d.responsible or "—"),
            ("fa6s.building", d.client or "—"),
            ("fa6s.folder",   d.category),
            ("fa6s.clock",    f"{d.real_hours}/{d.estimated_hours}h"),
            ("fa6s.calendar", d.deadline.strftime("%d/%m/%Y")),
        ]:
            item_row = QHBoxLayout()
            item_row.setSpacing(3)
            item_row.setContentsMargins(0, 0, 0, 0)
            ic = QLabel()
            ic.setPixmap(qta.icon(icon_name, color=_ic).pixmap(11, 11))
            vl = QLabel(val)
            vl.setStyleSheet(f"color: {_ic}; font-size: 11px;")
            item_row.addWidget(ic)
            item_row.addWidget(vl)
            meta.addLayout(item_row)
        meta.addStretch()
        root.addLayout(meta)

        # ── Tags ─────────────────────────────────────────────────────────────
        if d.tags:
            tags_row = QHBoxLayout()
            tags_row.setSpacing(4)
            for t in d.tags[:6]:
                tl = QLabel(f"#{t}")
                tl.setStyleSheet(f"""
                    background: {'#334155' if self._dark else '#F1F5F9'};
                    color: {'#94A3B8' if self._dark else '#64748B'};
                    border-radius: 10px; padding: 1px 8px; font-size: 11px;
                """)
                tags_row.addWidget(tl)
            tags_row.addStretch()
            root.addLayout(tags_row)

        # ── Progress bar ─────────────────────────────────────────────────────
        if d.estimated_hours > 0:
            real_pct = d.real_hours / d.estimated_hours * 100
            pct = min(100, int(real_pct))

            pb = QProgressBar()
            pb.setRange(0, 100)
            pb.setValue(pct)
            pb.setTextVisible(False)
            pb.setFixedHeight(6)

            color = "#DC2626" if real_pct > 100 else "#3B82F6"

            pb.setStyleSheet(f"""
                QProgressBar {{
                    border: none;
                    border-radius: 3px;
                    background: {'#334155' if self._dark else '#E2E8F0'};
                }}

                QProgressBar::chunk {{
                    background: {color};
                    border-radius: 3px;
                }}
            """)

            root.addWidget(pb)

        # left-border color based on urgency
        if d.is_overdue:
            bg      = "#2D0A0A" if self._dark else "#FFF5F5"
            border  = "#EF4444"
            bg_hover= "#3D1010" if self._dark else "#FEE2E2"
        elif d.is_inactive:
            bg      = "#2D1F00" if self._dark else "#FFFBEB"
            border  = "#F59E0B"
            bg_hover= "#3D2A00" if self._dark else "#FEF3C7"
        else:
            bg      = "#1E293B" if self._dark else "#FFFFFF"
            border  = "transparent"
            bg_hover= "#1E2D40" if self._dark else "#F8FAFC"

        self.setStyleSheet(f"""
            QFrame#card {{
                background-color: {bg};
                border-left: 4px solid {border};
                margin-bottom: 2px;
            }}
            QFrame#card:hover {{
                background-color: {bg_hover};
            }}
        """)

    def mousePressEvent(self, event):
        self.selected.emit(self.demand)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Guard: widget may be deleted between single and double click
        # (e.g. if _on_demand_selected triggered a list rebuild)
        try:
            demand = self.demand
        except RuntimeError:
            return
        self.double_clicked.emit(demand)
        try:
            super().mouseDoubleClickEvent(event)
        except RuntimeError:
            pass



# ─── Kanban Card ──────────────────────────────────────────────────────────────

class KanbanCard(QFrame):
    clicked      = pyqtSignal(object)
    status_drop  = pyqtSignal(object, str)   # demand, new_status

    def __init__(self, demand: Demand, dark: bool = False, parent=None):
        super().__init__(parent)
        self.demand = demand
        self._dark  = dark
        self.setObjectName("kanban_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(False)
        self._build()

    def _build(self):
        d = self.demand

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # Título
        title = QLabel(d.title)
        title.setWordWrap(True)
        title.setObjectName("kanban_title")
        root.addWidget(title)

        # Prioridade
        root.addWidget(priority_badge(d.priority))

        # Espaçador
        root.addStretch()

        # Responsável
        resp = QLabel(d.responsible or "Sem responsável")
        resp.setObjectName("kanban_meta")
        root.addWidget(resp)

        # Rodapé
        footer = QHBoxLayout()

        deadline = QLabel(
            d.deadline.strftime("%d/%m")
        )
        deadline.setObjectName("kanban_deadline")

        progress = QLabel(
            f"{d.real_hours:.0f}/{d.estimated_hours:.0f}h"
        )
        progress.setObjectName("kanban_meta")

        footer.addWidget(deadline)
        footer.addStretch()
        footer.addWidget(progress)

        root.addLayout(footer)

        # Indicador atraso
        if d.is_overdue:
            overdue = QLabel("ATRASADA")
            overdue.setObjectName("kanban_overdue")
            root.insertWidget(1, overdue)

        if d.is_overdue:
            bg     = "#2D0A0A" if self._dark else "#FFF5F5"
            border = "1px solid #EF4444"
            left   = "4px solid #EF4444"
        elif d.is_inactive:
            bg     = "#2D1F00" if self._dark else "#FFFBEB"
            border = "1px solid #F59E0B"
            left   = "4px solid #F59E0B"
        else:
            bg     = "#1E293B" if self._dark else "#FFFFFF"
            border = f"1px solid {'#334155' if self._dark else '#E2E8F0'}"
            left   = "none"

        self.setStyleSheet(f"""
            QFrame#kanban_card {{
                background: {bg};
                border: {border};
                border-left: {left};
                border-radius: 8px;
                margin-bottom: 2px;
            }}
            QFrame#kanban_card:hover {{
                background: {'#2D3748' if self._dark else '#F8FAFC'};
            }}
        """)

    def mouseDoubleClickEvent(self, event):
        try:
            self.clicked.emit(self.demand)
        except Exception as e:
            print(e)
        super().mouseDoubleClickEvent(event)

class AITextEdit(QWidget):
    """
    QTextEdit com botão ✨ de reescrita por IA ao lado.
    Uso: substitui QTextEdit/QPlainTextEdit nos formulários.
    """
    def __init__(self, placeholder: str = "", context: str = "",
                 ai_service=None, dark: bool = False,
                 fixed_height: int = 80, parent=None):
        super().__init__(parent)
        self._ai_service = ai_service
        self._context    = context
        self._dark       = dark

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.editor = SpellCheckTextEdit()
        self.editor.setPlaceholderText(placeholder)
        self.editor.setFixedHeight(fixed_height)
        layout.addWidget(self.editor, alignment=Qt.AlignmentFlag.AlignTop)

        self._btn = QPushButton()
        self._btn.setIcon(qta.icon("fa6s.wand-magic-sparkles", color="white"))
        self._btn.setToolTip("Reescrever com IA")
        self._btn.setFixedSize(28, 28)
        self._btn.setAutoDefault(False)
        self._btn.setStyleSheet("""
            QPushButton {
                background: #8B5CF6;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background: #7C3AED; }
            QPushButton:disabled { background: #6B7280; }
        """)
        self._btn.clicked.connect(self._rewrite)
        self._btn.setVisible(bool(ai_service and ai_service.is_configured()))
        layout.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignTop)

    def set_ai_service(self, ai_service):
        self._ai_service = ai_service
        self._btn.setVisible(bool(ai_service and ai_service.is_configured()))

    def toPlainText(self) -> str:
        return self.editor.toPlainText()

    def setPlainText(self, text: str):
        self.editor.setPlainText(text)

    def clear(self):
        self.editor.clear()

    def _rewrite(self):
        if not self.editor.toPlainText().strip():
            return
        if not (self._ai_service and self._ai_service.is_configured()):
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
        btn_global = self._btn.mapToGlobal(QPoint(0, 0))
        x = btn_global.x() - popup.width() + self._btn.width()
        y = btn_global.y() - popup.height() - 6
        popup.move(x, y)
        popup.show()
        inp.setFocus()

    def _run_rewrite(self, instruction: str):
        text = self.editor.toPlainText().strip()
        if not text:
            return
        self._btn.setEnabled(False)
        QApplication.processEvents()
        try:
            rewritten = self._ai_service.rewrite_text(text, instruction)
            self.editor.setPlainText(rewritten)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Erro IA", str(e))
        finally:
            self._btn.setEnabled(True)


class MilestoneCalendarItem(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, demand, milestone, dark=False, parent=None):
        super().__init__(parent)

        self.demand = demand
        self.milestone = milestone

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("card")

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)

        title = QLabel(demand.title)
        title.setStyleSheet("font-weight: 700;")
        title.setWordWrap(True)

        status_ic = QLabel()
        status_color = "#22C55E" if milestone.done else "#3B82F6"
        status_ic.setPixmap(
            qta.icon(
                "fa6s.circle-check" if milestone.done else "fa6s.circle",
                color=status_color
            ).pixmap(14, 14)
        )
        lbl = QLabel(f"Milestone: {milestone.title}")
        lbl.setWordWrap(True)
        milestone_row = QHBoxLayout()
        milestone_row.setSpacing(6)
        milestone_row.addWidget(status_ic)
        milestone_row.addWidget(lbl, 1)

        v.addWidget(title)
        v.addLayout(milestone_row)

    def mouseDoubleClickEvent(self, event):
        self.clicked.emit(self.demand)
        super().mouseDoubleClickEvent(event)


class ReminderCalendarItem(QFrame):
    clicked = pyqtSignal(object)  # emite a demand

    def __init__(self, demand, reminder, dark=False, parent=None):
        super().__init__(parent)
        self.demand   = demand
        self.reminder = reminder
        self._dark    = dark
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()

    def _build(self):
        self.setObjectName("reminder_cal_item")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)

        icon = QLabel()
        icon.setPixmap(qta.icon("fa6s.bell", color="#7C3AED").pixmap(16, 16))
        layout.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(1)

        title = QLabel(self.reminder.title)
        title.setWordWrap(True)
        title.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {'#C084FC' if self._dark else '#7C3AED'};")
        info.addWidget(title)

        # Mostra de qual demanda é
        demand_lbl = QLabel(f"↳ {self.demand.title}")
        demand_lbl.setStyleSheet(
            f"font-size: 11px; color: {'#94A3B8' if self._dark else '#9CA3AF'};"
        )
        demand_lbl.setWordWrap(True)
        info.addWidget(demand_lbl)

        if self.reminder.note:
            note = QLabel(self.reminder.note)
            note.setStyleSheet(
                f"font-size: 11px; color: {'#94A3B8' if self._dark else '#9CA3AF'};"
            )
            note.setWordWrap(True)
            info.addWidget(note)

        layout.addLayout(info, 1)

    def mouseDoubleClickEvent(self, event):
        self.clicked.emit(self.demand)
        super().mouseDoubleClickEvent(event)

class DemandPreviewPanel(QFrame):
    open_requested        = pyqtSignal(object)

    def __init__(self, dark=False, parent=None):
        super().__init__(parent)
        self._dark    = dark
        self._demand  = None
        self._fs      = None
        self.setObjectName("card")
        self.setMinimumWidth(260)
        self.setMaximumWidth(500)
        self._build()

    def _build(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 14, 14, 14)
        self._layout.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        self._title_lbl = QLabel("—")
        
        self._title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 700; "
        )
        self._title_lbl.setWordWrap(True)
        hdr.addWidget(self._title_lbl, 1)

        _ic = "#94A3B8" if self._dark else "#64748B"
        close_btn = QPushButton()
        close_btn.setIcon(qta.icon("fa6s.xmark", color=_ic))
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("border: none; background: transparent;")
        close_btn.setAutoDefault(False)
        close_btn.clicked.connect(lambda: self.setVisible(False))
        hdr.addWidget(close_btn)
        self._layout.addLayout(hdr)

        # ── Badges ────────────────────────────────────────────────────────
        self._badges_row = QHBoxLayout()
        self._badges_row.setSpacing(4)
        self._layout.addLayout(self._badges_row)

        # ── Info ──────────────────────────────────────────────────────────
        self._info_widget = QWidget()
        self._info_widget.setStyleSheet("background: transparent;")
        self._info_layout = QVBoxLayout(self._info_widget)
        self._info_layout.setContentsMargins(0, 0, 0, 0)
        self._info_layout.setSpacing(4)
        self._layout.addWidget(self._info_widget)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {'#334155' if self._dark else '#E2E8F0'};")
        self._layout.addWidget(sep)

        # ── Arquivos — FileManagerWidget em modo readonly ─────────────────
        files_lbl = QLabel("ARQUIVOS")
        files_lbl.setObjectName("label_section")
        self._layout.addWidget(files_lbl)

        # Placeholder — será substituído quando set_demand for chamado
        self._file_manager_placeholder = QWidget()
        self._file_manager_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._layout.addWidget(self._file_manager_placeholder, 1)

        # ── Botão abrir ───────────────────────────────────────────────────
        btns_row = QHBoxLayout()
        btns_row.setSpacing(8)

        open_btn = QPushButton("  Detalhes")
        open_btn.setIcon(qta.icon("fa6s.arrow-up-right-from-square", color="white"))
        open_btn.setObjectName("btn_primary")
        open_btn.setAutoDefault(False)
        open_btn.clicked.connect(lambda: self.open_requested.emit(self._demand) if self._demand else None)
        btns_row.addWidget(open_btn, 1)

        self._layout.addLayout(btns_row)

        self._current_fm = None  # referência ao FileManagerWidget atual

    def set_demand(self, demand, file_service=None):
        self._demand = demand
        self._fs     = file_service

        # Título
        self._title_lbl.setText(demand.title)

        # Badges
        while self._badges_row.count():
            item = self._badges_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._badges_row.addWidget(status_badge(demand.status))
        self._badges_row.addWidget(priority_badge(demand.priority))
        if demand.is_overdue:
            self._badges_row.addWidget(BadgeLabel("Atrasada", "#FEE2E2", "#DC2626"))
        elif demand.is_inactive:
            self._badges_row.addWidget(
                BadgeLabel(f"Inativa {demand.days_since_activity}d", "#FEF3C7", "#D97706")
            )
        self._badges_row.addStretch()

        # Info
        while self._info_layout.count():
            item = self._info_layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

            elif item.layout():
                self._clear_layout(item.layout())  

        _ic = "#94A3B8" if self._dark else "#64748B"
        for icon_name, val in [
            ("fa6s.user",     demand.responsible or "—"),
            ("fa6s.building", demand.client or "—"),
            ("fa6s.calendar", demand.deadline.strftime("%d/%m/%Y")),
            ("fa6s.clock",    f"{demand.real_hours}/{demand.estimated_hours}h"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(6)
            k = QLabel()
            k.setPixmap(qta.icon(icon_name, color=_ic).pixmap(14, 14))
            k.setFixedWidth(18)
            vl = QLabel(str(val))
            vl.setObjectName("label_section")
            row.addWidget(k)
            row.addWidget(vl, 1)
            self._info_layout.addLayout(row)

        # FileManager readonly
        if self._current_fm:
            self._current_fm.setParent(None)
            self._current_fm.deleteLater()
            self._current_fm = None

        if file_service:
            from ..widgets.file_manager import FileManagerWidget
            fm = FileManagerWidget(
                demand_id    = demand.id,
                demand_title = demand.title,
                file_service = file_service,
                dark         = self._dark,
                readonly     = True,       # <- modo somente leitura
            )
            # Substitui o placeholder no layout
            idx = self._layout.indexOf(self._file_manager_placeholder)
            self._layout.insertWidget(idx, fm, 1)
            self._file_manager_placeholder.hide()
            self._current_fm = fm

    def set_dark(self, dark: bool):
        """Atualiza o tema do painel e do file manager já instanciado."""
        self._dark = dark
        self._title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 700; "
            f"color: {'#E2E8F0' if dark else '#0F172A'}; background: transparent;"
        )
        if self._current_fm:
            self._current_fm.refresh_dark(dark)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

            elif item.layout():
                self._clear_layout(item.layout())
        
    def hide(self):
        self.setVisible(False)