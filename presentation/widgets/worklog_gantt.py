"""
Gráfico de Gantt de horas trabalhadas.

Layout:
  [_LabelPanel fixo] | [_TimelineCanvas rolável H+V]

Eixo X: linha de datas (topo escuro) + linha de horários abaixo.
Os labels das demandas ficam fixos durante o scroll horizontal.
"""
from datetime import date, datetime, timedelta

import qtawesome as qta
from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QHBoxLayout, QVBoxLayout, QFrame, QPushButton,
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QLabel,
)
from PyQt6.QtCore import Qt, QRect, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QFont, QPen

# ── Paleta de cores das demandas ──────────────────────────────────────────────
_PALETTE = [
    "#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
    "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16",
    "#06B6D4", "#A855F7", "#22C55E", "#F43F5E", "#EAB308",
]
_DOW_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# ── Constantes de layout (compartilhadas pelos dois painéis) ──────────────────
LABEL_W   = 210
ROW_H     = 34
HDR_DATE  = 28   # altura da linha de datas
HDR_HOUR  = 28   # altura da linha de horários
HEADER_H  = HDR_DATE + HDR_HOUR

# Janela horária visível no eixo X
_H_START  = 6
_H_END    = 23
_VISIBLE  = _H_END - _H_START   # 17 horas por dia


def _calc_pph(n_days: int) -> int:
    """Pixels por hora conforme o período."""
    if n_days <= 7:  return 30
    if n_days <= 14: return 20
    if n_days <= 31: return 12
    return 6


def _calc_hstep(pph: int) -> int:
    """Intervalo (em horas) entre marcadores."""
    if pph >= 24: return 1
    if pph >= 10: return 2
    if pph >= 6:  return 4
    return 6


def _snap_minutes(total_minutes: float, step: int = 15) -> int:
    """Arredonda minutos-desde-meia-noite para o múltiplo de `step` mais próximo."""
    return int(round(total_minutes / step) * step)


def _fmt_hm(total_minutes: int) -> str:
    total_minutes = max(0, total_minutes)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _fmt_duration_min(minutes: int) -> str:
    minutes = max(0, minutes)
    h, m = minutes // 60, minutes % 60
    return f"{h}h{m:02d}min" if h else f"{m}min"


_GENERAL_KEY = object()   # sentinela para atividades avulsas (demand_id=None)


def _build_data(logs, extra_demand_ids=None):
    """
    Agrupa logs por demand_id. Logs sem demanda (demand_id=None) são
    agrupados juntos sob a chave especial _GENERAL_KEY.
    `extra_demand_ids` adiciona demandas "fixadas" sem nenhum log ainda,
    para permitir alocar a primeira hora via clique e arraste.
    """
    order: list = []
    by_demand: dict = {}
    for log in sorted(logs, key=lambda l: l.started_at):
        key = log.demand_id if log.demand_id is not None else _GENERAL_KEY
        if key not in by_demand:
            by_demand[key] = []
            order.append(key)
        by_demand[key].append(log)

    for did in (extra_demand_ids or []):
        if did not in by_demand:
            by_demand[did] = []
            order.append(did)

    return order, by_demand


# ── Painel esquerdo fixo ──────────────────────────────────────────────────────

class _DemandPickerDialog(QDialog):
    """Busca fuzzy + lista com highlight para escolher demanda não exibida no gráfico."""

    def __init__(self, candidates: list, dark: bool = False, parent=None):
        from core.domain.text_match import fuzzy_word_match
        from presentation.widgets.common_widgets import _highlight_html

        super().__init__(parent)
        self.selected = None
        self._dark = dark
        self._candidates = sorted(candidates, key=lambda d: d.title.casefold())
        self._selected_id = None

        self.setWindowTitle("Adicionar demanda ao gráfico")
        self.setMinimumSize(420, 480)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        search = QLineEdit()
        search.setPlaceholderText("Buscar demanda...")
        v.addWidget(search)

        # Lista rolável com QLabel (suporta HTML para highlight)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self._list_layout = QVBoxLayout(container)
        self._list_layout.setSpacing(2)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.addStretch()
        scroll.setWidget(container)
        v.addWidget(scroll, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancelar")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self._ok_btn = QPushButton("Adicionar")
        self._ok_btn.setObjectName("btn_primary")
        self._ok_btn.setAutoDefault(False)
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self.accept)
        btns.addWidget(self._ok_btn)
        v.addLayout(btns)

        def _rebuild(query: str):
            # Remove rows (keep the trailing stretch)
            while self._list_layout.count() > 1:
                item = self._list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._selected_id = None
            self._ok_btn.setEnabled(False)

            q = query.strip().lower()
            allow_fuzzy = len(q) >= 3

            def _matches(d):
                if not q:
                    return True
                if q in d.title.lower():
                    return True
                return allow_fuzzy and fuzzy_word_match(q, d.title, 1)

            bg_sel  = "#1E3A5F" if dark else "#DBEAFE"
            fg_sel  = "#60A5FA" if dark else "#1D4ED8"
            bg_row  = "transparent"
            fg_row  = "#E2E8F0" if dark else "#1E293B"

            for d in self._candidates:
                if not _matches(d):
                    continue

                row = QFrame()
                row.setObjectName(f"picker_row_{d.id}")
                row.setCursor(Qt.CursorShape.PointingHandCursor)
                row.setStyleSheet(
                    f"QFrame {{ background: {bg_row}; border-radius: 6px; padding: 2px; }}"
                    f"QFrame:hover {{ background: {'#1E293B' if dark else '#F1F5F9'}; }}"
                )

                lbl = QLabel(_highlight_html(d.title, query.strip(), dark))
                lbl.setStyleSheet(f"color: {fg_row}; font-size: 13px; padding: 6px 8px;")
                lbl.setWordWrap(True)

                rl = QVBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.addWidget(lbl)

                def _select(_, did=d.id, r=row, lbl=lbl):
                    # Deseleciona anterior
                    for i in range(self._list_layout.count() - 1):
                        w = self._list_layout.itemAt(i).widget()
                        if w:
                            w.setStyleSheet(
                                f"QFrame {{ background: {bg_row}; border-radius: 6px; padding: 2px; }}"
                                f"QFrame:hover {{ background: {'#1E293B' if dark else '#F1F5F9'}; }}"
                            )
                    r.setStyleSheet(
                        f"QFrame {{ background: {bg_sel}; border-radius: 6px; padding: 2px; }}"
                    )
                    lbl.setStyleSheet(f"color: {fg_sel}; font-size: 13px; font-weight: 600; padding: 6px 8px;")
                    self._selected_id = did
                    self.selected = did
                    self._ok_btn.setEnabled(True)

                def _confirm(_, did=d.id):
                    self.selected = did
                    self.accept()

                row.mousePressEvent = _select
                row.mouseDoubleClickEvent = _confirm

                self._list_layout.insertWidget(self._list_layout.count() - 1, row)

        search.textChanged.connect(_rebuild)
        _rebuild("")
        search.setFocus()


class _LabelPanel(QWidget):
    """Coluna de demandas — não rola horizontalmente."""

    demand_picked        = pyqtSignal(int)   # demand_id escolhido no seletor "+"
    demand_unpinned      = pyqtSignal(int)   # demand_id removido (linha vazia)
    demand_label_clicked = pyqtSignal(int)   # clique no nome da demanda → abrir detalhes

    def __init__(self, demand_order, demand_logs, demands_map, colors, dark, parent=None):
        super().__init__(parent)
        self._order       = demand_order
        self._logs        = demand_logs
        self._demands_map = demands_map
        self._colors      = colors
        self._dark        = dark

        self.setFixedWidth(LABEL_W)
        self.setFixedHeight(HEADER_H + len(demand_order) * ROW_H)
        self.setMouseTracking(True)

        self._add_btn = QPushButton(self)
        self._add_btn.setIcon(qta.icon("fa6s.plus", color="#F8FAFC"))
        self._add_btn.setFixedSize(20, 20)
        self._add_btn.setToolTip("Adicionar demanda ao gráfico")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,30); border: none; border-radius: 10px; }"
            "QPushButton:hover { background: rgba(255,255,255,60); }"
        )
        self._add_btn.move(LABEL_W - 28, 4)
        self._add_btn.clicked.connect(self._pick_demand)

    def _pick_demand(self):
        shown = {d for d in self._order if d is not _GENERAL_KEY}
        candidates = [d for d in self._demands_map.values() if d.id not in shown]
        if not candidates:
            QMessageBox.information(self, "Sem demandas", "Todas as demandas já estão no gráfico.")
            return
        dlg = _DemandPickerDialog(candidates, dark=self._dark, parent=self)
        if dlg.exec() and dlg.selected:
            self.demand_picked.emit(dlg.selected)

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        c_hdr1    = "#1E293B" if self._dark else "#E2E8F0"
        c_hdr2    = "#263347" if self._dark else "#F1F5F9"
        c_row_alt = "#1A2433" if self._dark else "#F8FAFC"
        c_sep     = "#334155" if self._dark else "#CBD5E1"
        c_text    = "#E2E8F0" if self._dark else "#1E293B"
        c_hdr_txt = "#F8FAFC" if self._dark else "#1E293B"

        fn   = QFont(); fn.setPointSize(8)
        fn_b = QFont(); fn_b.setPointSize(8); fn_b.setBold(True)

        # ── Canto do cabeçalho ────────────────────────────────────────────────
        painter.fillRect(0, 0, LABEL_W, HDR_DATE, QColor(c_hdr1))
        painter.fillRect(0, HDR_DATE, LABEL_W, HDR_HOUR, QColor(c_hdr2))

        painter.setPen(QColor(c_hdr_txt))
        painter.setFont(fn_b)
        painter.drawText(QRect(10, 0, LABEL_W - 34, HDR_DATE),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         "Demanda")

        painter.setPen(QPen(QColor(c_sep), 1))
        painter.drawLine(0, HEADER_H, LABEL_W, HEADER_H)

        # ── Linhas de demandas ────────────────────────────────────────────────
        for ri, did in enumerate(self._order):
            y = HEADER_H + ri * ROW_H
            is_empty = did is not _GENERAL_KEY and not self._logs.get(did)

            if ri % 2 == 0:
                painter.fillRect(0, y, LABEL_W, ROW_H, QColor(c_row_alt))

            painter.setPen(QPen(QColor(c_sep), 1))
            painter.drawLine(0, y + ROW_H, LABEL_W, y + ROW_H)

            # Faixa colorida lateral
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._colors.get(did, "#3B82F6")))
            painter.drawRect(0, y + 5, 4, ROW_H - 10)

            if did is _GENERAL_KEY:
                label = "Atividades Avulsas"
            else:
                demand = self._demands_map.get(did)
                label  = demand.title if demand else f"ID {did}"
            text_w = LABEL_W - (32 if is_empty else 14)
            disp = label if len(label) <= 27 else label[:25] + "…"

            painter.setPen(QColor(c_text))
            painter.setFont(fn)
            painter.drawText(QRect(10, y, text_w, ROW_H),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             disp)

            if is_empty:
                painter.setPen(QColor("#94A3B8" if self._dark else "#9CA3AF"))
                painter.setFont(fn_b)
                painter.drawText(QRect(LABEL_W - 24, y, 18, ROW_H),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter,
                                 "×")

        # Borda direita
        painter.setPen(QPen(QColor(c_sep), 1))
        painter.drawLine(LABEL_W - 1, 0, LABEL_W - 1, self.height())

        painter.end()

    def mousePressEvent(self, event):
        x, y = event.pos().x(), event.pos().y()
        if y >= HEADER_H and x >= LABEL_W - 24:
            ri = (y - HEADER_H) // ROW_H
            if 0 <= ri < len(self._order):
                did = self._order[ri]
                if did is not _GENERAL_KEY and not self._logs.get(did):
                    self.demand_unpinned.emit(did)
                    return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        x, y = event.pos().x(), event.pos().y()
        if y >= HEADER_H:
            ri = (y - HEADER_H) // ROW_H
            if 0 <= ri < len(self._order):
                did = self._order[ri]
                if did is not _GENERAL_KEY:
                    self.demand_label_clicked.emit(did)
                    return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        y = event.pos().y()
        if y < HEADER_H:
            self.setToolTip("")
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        ri = (y - HEADER_H) // ROW_H
        if 0 <= ri < len(self._order):
            did = self._order[ri]
            if did is _GENERAL_KEY:
                self.setToolTip("Atividades Avulsas (sem demanda associada)")
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                demand = self._demands_map.get(did)
                self.setToolTip(
                    f"{demand.title if demand else f'ID {did}'}\nClique para abrir apontamentos"
                )
                self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setToolTip("")
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)


# ── Painel direito rolável ────────────────────────────────────────────────────

class _TimelineCanvas(QWidget):
    """Timeline rolável: cabeçalho (data + hora) e barras de sessão."""

    log_requested = pyqtSignal(object, object, object)   # demand_id, start_dt, end_dt
    log_clicked   = pyqtSignal(object)                    # log — clique (sem arrastar) sobre uma barra existente

    def __init__(self, demand_order, demand_logs, demands_map, colors,
                 date_from: date, date_to: date, dark: bool, zoom: float = 1.0, parent=None):
        super().__init__(parent)
        self._order       = demand_order
        self._logs        = demand_logs
        self._demands_map = demands_map
        self._colors      = colors
        self._date_from   = date_from
        self._date_to     = date_to
        self._dark        = dark
        self._n_days      = (date_to - date_from).days + 1

        self._pph   = max(4, int(_calc_pph(self._n_days) * zoom))
        self._day_w = _VISIBLE * self._pph
        self._hstep = _calc_hstep(self._pph)

        self.setMinimumSize(
            self._n_days * self._day_w,
            max(HEADER_H + len(demand_order) * ROW_H, 120),
        )
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)   # necessário para o Esc cancelar o arraste
        self._ttmap: list[tuple] = []

        # ── Estado de arrastar para alocar horas ────────────────────────────
        self._dragging     = False
        self._drag_did      = None
        self._drag_row_y    = 0
        self._drag_day_idx  = 0
        self._drag_x0       = 0
        self._drag_x1       = 0
        self._press_log     = None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _day_x(self, i: int) -> int:
        return i * self._day_w

    def _t2x(self, day_idx: int, frac_hour: float) -> int:
        h = max(_H_START, min(_H_END, frac_hour))
        return self._day_x(day_idx) + int((h - _H_START) * self._pph)

    def _x2h(self, local_x: int) -> float:
        h = _H_START + local_x / self._pph
        return max(_H_START, min(_H_END, h))

    def _session_rects(self, log, row_y: int) -> list[tuple]:
        started: datetime = log.started_at
        ended: datetime   = log.ended_at or (started + timedelta(seconds=log.duration_seconds))

        rects = []
        cur = started
        while cur.date() <= ended.date() and cur.date() <= self._date_to:
            day = cur.date()
            if day < self._date_from:
                cur = datetime(day.year, day.month, day.day) + timedelta(days=1)
                continue
            di = (day - self._date_from).days
            if di >= self._n_days:
                break

            seg_end = min(ended, datetime(day.year, day.month, day.day, 23, 59, 59))
            h0 = cur.hour     + cur.minute     / 60
            h1 = seg_end.hour + seg_end.minute / 60 + seg_end.second / 3600
            h0 = max(h0, _H_START)
            h1 = min(h1, _H_END)

            if h1 > h0:
                x  = self._t2x(di, h0)
                x2 = self._t2x(di, h1)
                rects.append((x, row_y + 5, max(2, x2 - x), ROW_H - 10))

            cur = datetime(day.year, day.month, day.day) + timedelta(days=1)
        return rects

    # ── paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        today = date.today()

        c_bg      = "#0F172A" if self._dark else "#FFFFFF"
        c_hdr1    = "#1E293B" if self._dark else "#E2E8F0"
        c_hdr2    = "#263347" if self._dark else "#F1F5F9"
        c_hdr_txt = "#F8FAFC" if self._dark else "#1E293B"
        c_row_alt = "#1A2433" if self._dark else "#F8FAFC"
        c_line_h  = "#2D3F55" if self._dark else "#E2E8F0"
        c_line_d  = "#1D2D42" if self._dark else "#94A3B8"
        c_muted   = "#64748B" if self._dark else "#64748B"

        painter.fillRect(self.rect(), QColor(c_bg))

        fn_s  = QFont(); fn_s.setPointSize(8)
        fn_b  = QFont(); fn_b.setPointSize(8); fn_b.setBold(True)
        fn_xs = QFont(); fn_xs.setPointSize(7)

        # ── Cabeçalho linha 1: Datas ──────────────────────────────────────────
        painter.fillRect(0, 0, self.width(), HDR_DATE, QColor(c_hdr1))

        for i in range(self._n_days):
            day = self._date_from + timedelta(days=i)
            dx  = self._day_x(i)
            dw  = self._day_w
            is_today   = (day == today)
            is_weekend = (day.weekday() >= 5)

            if is_today:
                painter.fillRect(dx, 0, dw, HDR_DATE, QColor("#2563EB"))
            elif is_weekend:
                painter.fillRect(dx, 0, dw, HDR_DATE, QColor("#162032" if self._dark else "#CBD5E1"))

            painter.setPen(QColor("#F8FAFC" if (is_today or self._dark) else "#475569"))
            painter.setFont(fn_b if is_today else fn_s)

            if dw >= 110:
                lbl = f"{_DOW_PT[day.weekday()]} {day.day:02d}/{day.month:02d}/{day.year}"
            elif dw >= 65:
                lbl = f"{_DOW_PT[day.weekday()]} {day.day:02d}/{day.month:02d}"
            elif dw >= 36:
                lbl = f"{day.day:02d}/{day.month:02d}"
            else:
                lbl = str(day.day)

            painter.drawText(QRect(dx + 4, 0, dw - 6, HDR_DATE),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lbl)

        # ── Cabeçalho linha 2: Horários ───────────────────────────────────────
        painter.fillRect(0, HDR_DATE, self.width(), HDR_HOUR, QColor(c_hdr2))

        for i in range(self._n_days):
            dx = self._day_x(i)

            # Linha separadora de dia (mais escura, vai do topo ao rodapé)
            painter.setPen(QPen(QColor(c_line_d), 1))
            painter.drawLine(dx, 0, dx, self.height())

            # Marcadores de hora
            for h in range(_H_START, _H_END + 1, self._hstep):
                hx = dx + int((h - _H_START) * self._pph)
                if h != _H_START:
                    painter.setPen(QPen(QColor(c_line_h), 1))
                    painter.drawLine(hx, HDR_DATE, hx, self.height())
                # Label — só desenha se tiver espaço suficiente
                slot_px = self._pph * self._hstep
                if slot_px >= 16:
                    painter.setPen(QColor(c_muted))
                    painter.setFont(fn_s)
                    painter.drawText(
                        QRect(hx + 3, HDR_DATE + 2, slot_px - 4, HDR_HOUR - 4),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        f"{h:02d}h",
                    )

        # Borda direita + inferior do cabeçalho
        rx = self._n_days * self._day_w
        painter.setPen(QPen(QColor(c_line_d), 1))
        painter.drawLine(rx, 0, rx, self.height())
        painter.drawLine(0, HEADER_H, self.width(), HEADER_H)

        # ── Demandas ──────────────────────────────────────────────────────────
        self._ttmap = []

        now_x = None
        if self._date_from <= today <= self._date_to:
            now = datetime.now()
            fh  = now.hour + now.minute / 60
            if _H_START <= fh <= _H_END:
                ti    = (today - self._date_from).days
                now_x = self._t2x(ti, fh)

        for ri, did in enumerate(self._order):
            y = HEADER_H + ri * ROW_H

            if ri % 2 == 0:
                painter.fillRect(0, y, self.width(), ROW_H, QColor(c_row_alt))

            # Coluna de hoje (leve azul)
            if self._date_from <= today <= self._date_to:
                ti = (today - self._date_from).days
                painter.fillRect(self._day_x(ti), y, self._day_w, ROW_H,
                                 QColor(37, 99, 235, 14))

            # Linha horizontal
            painter.setPen(QPen(QColor(c_line_h), 1))
            painter.drawLine(0, y + ROW_H, self.width(), y + ROW_H)

            # Barras de sessão
            color_hex = self._colors.get(did, "#3B82F6")
            if did is _GENERAL_KEY:
                demand_label = "Atividade Avulsa"
            else:
                demand = self._demands_map.get(did)
                demand_label = demand.title if demand else f"ID {did}"

            for log in self._logs.get(did, []):
                for (bx, by, bw, bh) in self._session_rects(log, y):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(color_hex))
                    painter.drawRoundedRect(bx, by, bw, bh, 3, 3)

                    if bw >= 34 and bh >= 12:
                        painter.setPen(QColor("#FFFFFF"))
                        painter.setFont(fn_xs)
                        painter.drawText(QRect(bx + 2, by, bw - 4, bh),
                                         Qt.AlignmentFlag.AlignCenter,
                                         log.duration_display)

                    started = log.started_at
                    ended   = log.ended_at or (started + timedelta(seconds=log.duration_seconds))
                    cat_line = f"\n{log.category}" if (did is _GENERAL_KEY and log.category) else ""
                    tip = (
                        f"{demand_label}{cat_line}\n"
                        f"{started.strftime('%d/%m %H:%M')} → {ended.strftime('%H:%M')}"
                        f"  ({log.duration_display})"
                        + (f"\n{log.note}" if log.note else "")
                    )
                    self._ttmap.append((bx, by, bw, bh, tip, log))

        # Linha vermelha "agora"
        if now_x is not None:
            painter.setPen(QPen(QColor("#EF4444"), 2))
            painter.drawLine(now_x, HEADER_H, now_x, self.height())

        # ── Ghost da seleção sendo arrastada ──────────────────────────────────
        if self._dragging:
            x0, x1 = sorted((self._drag_x0, self._drag_x1))
            gw = max(2, x1 - x0)
            if self._dark:
                pen_col   = QColor("#FFFFFF")
                brush_col = QColor(255, 255, 255, 60)
                lbl_col   = QColor("#FFFFFF")
            else:
                pen_col   = QColor("#1D4ED8")
                brush_col = QColor(59, 130, 246, 80)   # azul com alpha
                lbl_col   = QColor("#1D4ED8")
            painter.setPen(QPen(pen_col, 1, Qt.PenStyle.DashLine))
            painter.setBrush(brush_col)
            painter.drawRoundedRect(x0, self._drag_row_y + 5, gw, ROW_H - 10, 3, 3)

            day_x = self._day_x(self._drag_day_idx)
            h0 = self._x2h(x0 - day_x)
            h1 = self._x2h(x1 - day_x)
            m0 = _snap_minutes(h0 * 60)
            m1 = _snap_minutes(h1 * 60)
            # Desconta almoço (12h-13h) do preview
            _LUNCH_S, _LUNCH_E = 12 * 60, 13 * 60
            lunch_ov = max(0, min(m1, _LUNCH_E) - max(m0, _LUNCH_S))
            net_min  = max(0, m1 - m0) - lunch_ov
            lbl = f"{_fmt_hm(m0)} → {_fmt_hm(m1)}  ({_fmt_duration_min(net_min)})"
            painter.setPen(lbl_col)
            painter.setFont(fn_xs)
            painter.drawText(x0, max(0, self._drag_row_y - 4), lbl)

        painter.end()

    # ── Arrastar para alocar horas ───────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        x, y = event.pos().x(), event.pos().y()
        if y < HEADER_H:
            super().mousePressEvent(event)
            return

        ri = (y - HEADER_H) // ROW_H
        if not (0 <= ri < len(self._order)):
            super().mousePressEvent(event)
            return

        did = self._order[ri]
        drag_id = None if did is _GENERAL_KEY else did   # None = atividade avulsa

        self._press_log = None
        for (bx, by, bw, bh, _tip, log) in self._ttmap:
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self._press_log = log
                break

        day_idx = min(max(0, x // self._day_w), self._n_days - 1)
        self._drag_did     = drag_id
        self._drag_row_y   = HEADER_H + ri * ROW_H
        self._drag_day_idx = day_idx
        self._drag_x0 = x
        self._drag_x1 = x
        self._dragging = True
        self.setFocus()   # permite cancelar com Esc
        self.update()

    def mouseMoveEvent(self, event):
        if self._dragging:
            lo = self._day_x(self._drag_day_idx)
            hi = lo + self._day_w
            self._drag_x1 = max(lo, min(event.pos().x(), hi))
            self.update()
            return

        px, py = event.pos().x(), event.pos().y()
        for (x, y, w, h, tip, _log) in self._ttmap:
            if x <= px <= x + w and y <= py <= y + h:
                self.setToolTip(tip)
                return
        self.setToolTip("")
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            if self._drag_x0 == self._drag_x1 and self._press_log is not None:
                # Clique simples (sem arrastar) sobre uma barra existente → editar
                log = self._press_log
                self._dragging  = False
                self._drag_did  = None
                self._press_log = None
                self.update()
                self.log_clicked.emit(log)
                return

            x0, x1 = sorted((self._drag_x0, self._drag_x1))
            day_idx = self._drag_day_idx
            day_x   = self._day_x(day_idx)
            h0 = self._x2h(x0 - day_x)
            h1 = self._x2h(x1 - day_x)

            day  = self._date_from + timedelta(days=day_idx)
            base = datetime(day.year, day.month, day.day)
            m0 = _snap_minutes(h0 * 60)
            m1 = _snap_minutes(h1 * 60)
            start_dt = base + timedelta(minutes=m0)
            end_dt   = base + timedelta(minutes=m1)

            did = self._drag_did
            self._dragging  = False
            self._drag_did  = None
            self.update()

            if (end_dt - start_dt) >= timedelta(minutes=5):
                self.log_requested.emit(did, start_dt, end_dt)
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._dragging:
            self._dragging = False
            self._drag_did  = None
            self.update()
            event.accept()
            return
        super().keyPressEvent(event)


# ── Widget público ────────────────────────────────────────────────────────────

class WorklogGanttWidget(QWidget):
    """
    Container principal:
      - Painel esquerdo (_LabelPanel) fixo — não rola horizontalmente
      - Painel direito (_TimelineCanvas) dentro de QScrollArea (H + V)
      - Scrollbars verticais sincronizados

    Clique e arraste sobre uma linha de demanda na timeline para alocar horas
    (emite `log_requested`). Use o "+" no canto do painel de labels para
    fixar uma demanda sem apontamentos ainda (emite `demand_pinned`); o "×"
    em uma linha vazia remove a fixação (emite `demand_unpinned`).
    """

    log_requested        = pyqtSignal(object, object, object)   # demand_id (ou None p/ avulsa), start_dt, end_dt
    demand_pinned        = pyqtSignal(int)                      # demand_id
    demand_unpinned      = pyqtSignal(int)                      # demand_id
    demand_label_clicked = pyqtSignal(int)                      # demand_id — abrir detalhes
    log_edit_requested   = pyqtSignal(object)                    # log — clique sobre uma barra existente

    def __init__(self, logs, demands_map, date_from: date, date_to: date,
                 dark: bool = False, zoom: float = 1.0, extra_demand_ids=None, parent=None):
        super().__init__(parent)

        order, by_demand = _build_data(logs, extra_demand_ids)
        colors = {did: _PALETTE[i % len(_PALETTE)] for i, did in enumerate(order)}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Coluna esquerda (labels fixos) ────────────────────────────────────
        self._lscroll = QScrollArea()
        self._lscroll.setWidgetResizable(False)
        self._lscroll.setFrameShape(QFrame.Shape.NoFrame)
        self._lscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._lscroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._lscroll.setFixedWidth(LABEL_W)

        lp = _LabelPanel(order, by_demand, demands_map, colors, dark)
        lp.demand_picked.connect(self.demand_pinned)
        lp.demand_unpinned.connect(self.demand_unpinned)
        lp.demand_label_clicked.connect(self.demand_label_clicked)
        self._lscroll.setWidget(lp)
        layout.addWidget(self._lscroll)

        # ── Painel direito (timeline rolável) ─────────────────────────────────
        self._tscroll = QScrollArea()
        self._tscroll.setWidgetResizable(False)
        self._tscroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._tscroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        canvas = _TimelineCanvas(order, by_demand, demands_map, colors,
                                 date_from, date_to, dark, zoom=zoom)
        canvas.log_requested.connect(self.log_requested)
        canvas.log_clicked.connect(self.log_edit_requested)
        self._tscroll.setWidget(canvas)
        layout.addWidget(self._tscroll)

        # ── Sync de scroll vertical ───────────────────────────────────────────
        self._lscroll.verticalScrollBar().valueChanged.connect(
            self._tscroll.verticalScrollBar().setValue
        )
        self._tscroll.verticalScrollBar().valueChanged.connect(
            self._lscroll.verticalScrollBar().setValue
        )

        # Altura exata conforme o número de demandas (scroll vertical ativa quando necessário)
        self.setFixedHeight(min(HEADER_H + len(order) * ROW_H + 22, 460))

        # Posiciona no dia mais recente ao abrir
        QTimer.singleShot(0, lambda: self._tscroll.horizontalScrollBar().setValue(
            self._tscroll.horizontalScrollBar().maximum()
        ))
