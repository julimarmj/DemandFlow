"""
Grade interativa de planejamento de capacidade — horas planejadas por
demanda x semana, comparadas com a capacidade semanal fixa.

Layout:
  [_PlanLabelPanel fixo] | [_PlanCanvas rolável V]

Arrastar verticalmente numa célula ajusta as horas planejadas daquela
demanda naquela semana (só comita ao soltar o botão). Duplo-clique abre
um campo para digitar o valor exato. Semanas passadas ou após o prazo da
demanda ficam travadas (não editáveis).
"""
from datetime import date, timedelta

from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QHBoxLayout, QFrame, QInputDialog, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QPen

LABEL_W       = 210
ROW_H         = 56
MIN_WEEK_COL_W = 86   # largura mínima de cada coluna — cresce pra preencher o espaço disponível
HDR_WEEK      = 26
HDR_TOTAL     = 26
HEADER_H      = HDR_WEEK + HDR_TOTAL

# Zona dos ícones "↻" (recalcular) e "✕" (limpar) no canto direito de cada linha
_ICON_W      = 24
_RECALC_X    = LABEL_W - 2 * _ICON_W - 10
_CLEAR_X     = LABEL_W - _ICON_W - 8

_HOURS_PER_PIXEL      = 1 / 6     # 6px de arraste vertical = 1h
_CELL_MAX_HOURS_TINT  = 20.0      # hora a partir da qual o tom de fundo satura


def _iso_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _fmt_h(hours: float) -> str:
    if hours <= 0:
        return ""
    if hours == int(hours):
        return f"{int(hours)}h"
    return f"{hours:.1f}h"


# ── Painel esquerdo fixo ──────────────────────────────────────────────────────

class _PlanLabelPanel(QWidget):
    """Coluna de demandas — não rola horizontalmente. Cada linha tem um campo
    real (QDoubleSpinBox) para editar a estimativa de horas da demanda."""

    demand_label_clicked    = pyqtSignal(int)         # duplo-clique → abrir detalhes
    suggest_clicked         = pyqtSignal(int)         # clique no ícone "↻" → recalcular sugestão
    clear_clicked           = pyqtSignal(int)         # clique no ícone "✕" → limpar horas planejadas
    estimated_hours_changed = pyqtSignal(int, float)  # demand_id, nova estimativa

    def __init__(self, demands, dark: bool, parent=None):
        super().__init__(parent)
        self._demands = demands
        self._dark = dark
        self.setFixedWidth(LABEL_W)
        self.setFixedHeight(HEADER_H + len(demands) * ROW_H)
        self.setMouseTracking(True)

        self._spins: dict[int, QDoubleSpinBox] = {}
        for ri, d in enumerate(demands):
            y = HEADER_H + ri * ROW_H
            spin = QDoubleSpinBox(self)
            spin.setObjectName("plan_estimate_spin")
            spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            spin.setDecimals(0)
            spin.setRange(0, 9999)
            spin.setSuffix("h")
            spin.setValue(round(d.estimated_hours))
            spin.setGeometry(10, y + 28, 64, 20)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Sobrescreve o padding genérico de QDoubleSpinBox do stylesheet
            # global (7px/11px) — não cabe num campo de 64x20.
            spin.setStyleSheet(
                "QDoubleSpinBox#plan_estimate_spin { padding: 0px 2px; font-size: 11px; border-radius: 4px; }"
            )
            baseline = round(d.estimated_hours)
            spin.editingFinished.connect(
                lambda spin=spin, demand=d, baseline=baseline: self._on_estimate_edited(spin, demand, baseline)
            )
            self._spins[d.id] = spin

    def _on_estimate_edited(self, spin, demand, baseline):
        new_value = spin.value()
        if new_value != baseline:
            self.estimated_hours_changed.emit(demand.id, new_value)

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        c_hdr     = "#1E293B" if self._dark else "#E2E8F0"
        c_row_alt = "#1A2433" if self._dark else "#F8FAFC"
        c_sep     = "#334155" if self._dark else "#CBD5E1"
        c_text    = "#E2E8F0" if self._dark else "#1E293B"
        c_muted   = "#94A3B8" if self._dark else "#9CA3AF"

        fn   = QFont(); fn.setPointSize(8)
        fn_b = QFont(); fn_b.setPointSize(8); fn_b.setBold(True)

        c_hdr_txt = "#F8FAFC" if self._dark else "#1E293B"
        painter.fillRect(0, 0, LABEL_W, HEADER_H, QColor(c_hdr))
        painter.setPen(QColor(c_hdr_txt))
        painter.setFont(fn_b)
        painter.drawText(QRect(10, 0, LABEL_W - 20, HEADER_H),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         "Demanda")

        painter.setPen(QPen(QColor(c_sep), 1))
        painter.drawLine(0, HEADER_H, LABEL_W, HEADER_H)

        for ri, d in enumerate(self._demands):
            y = HEADER_H + ri * ROW_H
            if ri % 2 == 0:
                painter.fillRect(0, y, LABEL_W, ROW_H, QColor(c_row_alt))
            painter.setPen(QPen(QColor(c_sep), 1))
            painter.drawLine(0, y + ROW_H, LABEL_W, y + ROW_H)

            remaining = max(d.estimated_hours - d.real_hours, 0.0)
            title = d.title if len(d.title) <= 26 else d.title[:24] + "…"

            painter.setPen(QColor(c_text))
            painter.setFont(fn)
            painter.drawText(QRect(10, y + 6, LABEL_W - 74, 18),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             title)

            # A direita do spinbox (que ocupa x=10..74,y+28..48): "Xh restantes"
            painter.setPen(QColor(c_muted))
            painter.drawText(QRect(80, y + 28, LABEL_W - 80 - 64, 20),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{remaining:.0f}h rest.")

            painter.setPen(QColor(c_muted))
            painter.setFont(fn_b)
            painter.drawText(QRect(_RECALC_X, y, _ICON_W, ROW_H),
                             Qt.AlignmentFlag.AlignCenter, "↻")
            painter.drawText(QRect(_CLEAR_X, y, _ICON_W, ROW_H),
                             Qt.AlignmentFlag.AlignCenter, "✕")

        painter.setPen(QPen(QColor(c_sep), 1))
        painter.drawLine(LABEL_W - 1, 0, LABEL_W - 1, self.height())
        painter.end()

    def _row_at(self, y: int):
        if y < HEADER_H:
            return None
        ri = (y - HEADER_H) // ROW_H
        return ri if 0 <= ri < len(self._demands) else None

    def mousePressEvent(self, event):
        ri = self._row_at(event.pos().y())
        x = event.pos().x()
        if ri is not None:
            if _RECALC_X <= x < _RECALC_X + _ICON_W:
                self.suggest_clicked.emit(self._demands[ri].id)
                return
            if _CLEAR_X <= x < _CLEAR_X + _ICON_W:
                self.clear_clicked.emit(self._demands[ri].id)
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        ri = self._row_at(event.pos().y())
        x = event.pos().x()
        if ri is not None and x < _RECALC_X:
            self.demand_label_clicked.emit(self._demands[ri].id)
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        ri = self._row_at(event.pos().y())
        x = event.pos().x()
        if ri is not None:
            d = self._demands[ri]
            if _RECALC_X <= x < _RECALC_X + _ICON_W:
                self.setToolTip("Recalcular sugestão de distribuição")
            elif _CLEAR_X <= x < _CLEAR_X + _ICON_W:
                self.setToolTip("Limpar horas planejadas")
            else:
                self.setToolTip(f"{d.title}\nDuplo-clique para abrir os detalhes")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setToolTip("")
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)


# ── Painel direito rolável ────────────────────────────────────────────────────

class _PlanCanvas(QWidget):
    """Grade de semanas: cada célula é editável por arrastar (vertical) ou
    duplo-clique (digitar valor exato). Semana passada ou após o prazo da
    demanda fica travada."""

    hours_adjusted = pyqtSignal(int, object, float)   # demand_id, week_start, new_hours

    def __init__(self, demands, weeks, allocations, totals_by_week, capacity,
                 dark: bool, parent=None):
        super().__init__(parent)
        self._demands  = demands
        self._weeks    = weeks
        self._alloc    = dict(allocations)       # {(demand_id, week_start): hours} — preview local
        self._totals   = dict(totals_by_week)
        self._capacity = capacity
        self._dark     = dark

        # Largura mínima (ativa scroll horizontal só se a janela for estreita
        # demais); altura fixa — quem estica é o QScrollArea ao redor (ver
        # CapacityGridWidget), não esta linha de células.
        self.setMinimumWidth(max(len(weeks) * MIN_WEEK_COL_W, 1))
        self.setFixedHeight(max(HEADER_H + len(demands) * ROW_H, 1))
        self.setMouseTracking(True)

        self._dragging       = False
        self._drag_row       = -1
        self._drag_col       = -1
        self._drag_start_y   = 0
        self._drag_start_val = 0.0
        self._drag_val       = 0.0
        self._drag_max       = 0.0

    def _col_w(self) -> float:
        """Largura efetiva de cada coluna — estica pra preencher a largura
        disponível, sem nunca ficar menor que MIN_WEEK_COL_W."""
        n = max(len(self._weeks), 1)
        return max(MIN_WEEK_COL_W, self.width() / n)

    def _cell_at(self, x: int, y: int):
        if y < HEADER_H:
            return None
        col_w = self._col_w()
        ri = (y - HEADER_H) // ROW_H
        ci = int(x // col_w)
        if 0 <= ri < len(self._demands) and 0 <= ci < len(self._weeks):
            return ri, ci
        return None

    def _is_locked(self, demand, week_start: date) -> bool:
        today_wk = _iso_week_start(date.today())
        deadline_wk = _iso_week_start(demand.deadline)
        return week_start < today_wk or week_start > deadline_wk

    def _max_for_cell(self, demand, week_start: date) -> float:
        """Quanto essa célula pode chegar a ter sem passar da estimativa da
        demanda, dado o que já está alocado nas OUTRAS semanas dela. Usado
        pra travar o arraste/digitação no limite em vez de deixar passar e
        só avisar depois."""
        remaining_budget = max(demand.estimated_hours - demand.real_hours, 0.0)
        other_total = sum(
            h for (did, wk), h in self._alloc.items()
            if did == demand.id and wk != week_start
        )
        return max(remaining_budget - other_total, 0.0)

    # ── paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        c_bg      = "#0F172A" if self._dark else "#FFFFFF"
        c_hdr     = "#1E293B" if self._dark else "#E2E8F0"
        c_row_alt = "#1A2433" if self._dark else "#F8FAFC"
        c_line    = "#2D3F55" if self._dark else "#E2E8F0"
        c_grid    = "#334155"

        painter.fillRect(self.rect(), QColor(c_bg))

        fn   = QFont(); fn.setPointSize(8)
        fn_b = QFont(); fn_b.setPointSize(8); fn_b.setBold(True)

        today_wk = _iso_week_start(date.today())
        col_w = self._col_w()
        col_w_i = int(col_w)

        # ── Cabeçalho: data da semana + total vs. capacidade ──────────────────
        c_hdr_txt = "#F8FAFC" if self._dark else "#1E293B"
        painter.fillRect(0, 0, self.width(), HEADER_H, QColor(c_hdr))
        for ci, wk in enumerate(self._weeks):
            x = int(ci * col_w)
            painter.setPen(QPen(QColor(c_grid), 1))
            painter.drawLine(x, 0, x, self.height())

            is_current = wk == today_wk
            if is_current:
                painter.fillRect(x, 0, col_w_i, HDR_WEEK, QColor("#2563EB"))

            painter.setPen(QColor("#F8FAFC" if is_current else c_hdr_txt))
            painter.setFont(fn_b if is_current else fn)
            painter.drawText(QRect(x, 0, col_w_i, HDR_WEEK),
                             Qt.AlignmentFlag.AlignCenter, wk.strftime("%d/%m"))

            total = self._totals.get(wk, 0.0)
            over = total > self._capacity
            if self._dark:
                c_ok, c_over = "#86EFAC", "#FCA5A5"
            else:
                c_ok, c_over = "#15803D", "#B91C1C"
            painter.setPen(QColor(c_over if over else c_ok))
            painter.setFont(fn_b if over else fn)
            painter.drawText(QRect(x, HDR_WEEK, col_w_i, HDR_TOTAL),
                             Qt.AlignmentFlag.AlignCenter,
                             f"{total:.0f}h" + (" ⚠" if over else ""))

        painter.setPen(QPen(QColor(c_grid), 1))
        painter.drawLine(0, HEADER_H, self.width(), HEADER_H)

        # ── Linhas de demanda ─────────────────────────────────────────────────
        for ri, d in enumerate(self._demands):
            y = HEADER_H + ri * ROW_H
            if ri % 2 == 0:
                painter.fillRect(0, y, self.width(), ROW_H, QColor(c_row_alt))
            painter.setPen(QPen(QColor(c_line), 1))
            painter.drawLine(0, y + ROW_H, self.width(), y + ROW_H)

            for ci, wk in enumerate(self._weeks):
                x = int(ci * col_w)
                locked = self._is_locked(d, wk)
                hours = self._alloc.get((d.id, wk), 0.0)
                is_drag_cell = self._dragging and self._drag_row == ri and self._drag_col == ci
                if is_drag_cell:
                    hours = self._drag_val

                cell_rect = QRect(x + 3, y + 5, col_w_i - 6, ROW_H - 10)

                if locked:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(255, 255, 255, 18) if self._dark else QColor(100, 116, 139, 28))
                    painter.drawRoundedRect(cell_rect, 4, 4)
                    continue

                intensity = min(hours / _CELL_MAX_HOURS_TINT, 1.0) if hours > 0 else 0.0
                if hours > 0:
                    color = QColor("#3B82F6")
                    color.setAlphaF(0.18 + 0.55 * intensity)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(color)
                    painter.drawRoundedRect(cell_rect, 4, 4)

                if is_drag_cell:
                    painter.setPen(QPen(QColor("#93C5FD"), 1.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(cell_rect, 4, 4)

                if hours > 0:
                    if self._dark:
                        text_color = "#F8FAFC"
                    else:
                        text_color = "#FFFFFF" if intensity >= 0.45 else "#1E293B"
                    painter.setPen(QColor(text_color))
                    painter.setFont(fn)
                    painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, _fmt_h(hours))

        rx = int(len(self._weeks) * col_w)
        painter.setPen(QPen(QColor(c_grid), 1))
        painter.drawLine(rx, 0, rx, self.height())

        painter.end()

    # ── Arrastar / duplo-clique para ajustar horas ───────────────────────────

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        cell = self._cell_at(event.pos().x(), event.pos().y())
        if not cell:
            super().mousePressEvent(event)
            return
        ri, ci = cell
        d, wk = self._demands[ri], self._weeks[ci]
        if self._is_locked(d, wk):
            return

        self._dragging       = True
        self._drag_row       = ri
        self._drag_col       = ci
        self._drag_start_y   = event.pos().y()
        self._drag_start_val = self._alloc.get((d.id, wk), 0.0)
        self._drag_val       = self._drag_start_val
        # Teto calculado uma vez no início do arraste — monitora cada
        # incremento e só trava quando bater nesse limite, em vez de deixar
        # passar e avisar depois.
        self._drag_max       = self._max_for_cell(d, wk)
        self.update()

    def mouseMoveEvent(self, event):
        if self._dragging:
            dy = self._drag_start_y - event.pos().y()   # arrastar pra cima aumenta
            # Sempre hora inteira — sem valor quebrado — e nunca passa do teto.
            raw = round(max(0.0, self._drag_start_val + dy * _HOURS_PER_PIXEL))
            self._drag_val = min(raw, self._drag_max)
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            ri, ci = self._drag_row, self._drag_col
            d, wk = self._demands[ri], self._weeks[ci]
            new_val = round(self._drag_val)
            self._dragging = False
            if new_val != self._drag_start_val:
                self._alloc[(d.id, wk)] = new_val   # preview otimista — confirmado no próximo refresh
                self.hours_adjusted.emit(d.id, wk, new_val)
            self.update()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        cell = self._cell_at(event.pos().x(), event.pos().y())
        if not cell:
            super().mouseDoubleClickEvent(event)
            return
        ri, ci = cell
        d, wk = self._demands[ri], self._weeks[ci]
        if self._is_locked(d, wk):
            return
        current = self._alloc.get((d.id, wk), 0.0)
        max_for_cell = max(self._max_for_cell(d, wk), current)   # nunca menor que o valor atual
        value, ok = QInputDialog.getInt(
            self, "Horas planejadas",
            f"{d.title} — semana de {wk:%d/%m} (máx. {max_for_cell:.0f}h):",
            round(current), 0, int(max_for_cell), 1,
        )
        if ok:
            self._alloc[(d.id, wk)] = value
            self.update()
            self.hours_adjusted.emit(d.id, wk, value)


# ── Widget público ────────────────────────────────────────────────────────────

class CapacityGridWidget(QWidget):
    """
    Container principal:
      - Painel esquerdo (_PlanLabelPanel) fixo — não rola
      - Painel direito (_PlanCanvas) com colunas que esticam pra preencher a
        largura disponível; só rola horizontalmente se a janela for estreita
        demais pro número de semanas exibido
      - Altura acompanha o número de demandas (sem teto artificial)

    `grid_data` é o dict retornado por `DemandUseCases.get_capacity_grid()`.
    """

    hours_adjusted          = pyqtSignal(int, object, float)   # demand_id, week_start, new_hours
    demand_label_clicked    = pyqtSignal(int)                  # demand_id — abrir detalhes
    suggest_requested       = pyqtSignal(int)                  # demand_id — recalcular sugestão
    clear_requested         = pyqtSignal(int)                  # demand_id — limpar horas planejadas
    estimated_hours_changed = pyqtSignal(int, float)            # demand_id, nova estimativa

    def __init__(self, grid_data: dict, dark: bool = False, parent=None):
        super().__init__(parent)
        demands = grid_data["demands"]
        weeks   = grid_data["weeks"]

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

        lp = _PlanLabelPanel(demands, dark)
        lp.demand_label_clicked.connect(self.demand_label_clicked)
        lp.suggest_clicked.connect(self.suggest_requested)
        lp.clear_clicked.connect(self.clear_requested)
        lp.estimated_hours_changed.connect(self.estimated_hours_changed)
        self._lscroll.setWidget(lp)
        layout.addWidget(self._lscroll)

        # ── Painel direito (grade rolável) ────────────────────────────────────
        self._tscroll = QScrollArea()
        # resizable=True: o canvas estica pra preencher a largura disponível
        # (colunas mais largas em vez de barra de rolagem horizontal), só
        # rola se a janela for mais estreita que MIN_WEEK_COL_W x nº semanas.
        self._tscroll.setWidgetResizable(True)
        self._tscroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._tscroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        canvas = _PlanCanvas(
            demands, weeks, grid_data["allocations"], grid_data["totals_by_week"],
            grid_data["capacity"], dark,
        )
        canvas.hours_adjusted.connect(self.hours_adjusted)
        self._tscroll.setWidget(canvas)
        layout.addWidget(self._tscroll)

        # Sem teto artificial — a altura acompanha o número de demandas. Se não
        # couber na janela, quem rola é a página inteira (fora deste widget).
        self.setFixedHeight(HEADER_H + len(demands) * ROW_H + 2)
