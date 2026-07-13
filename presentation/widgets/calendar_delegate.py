"""
QCalendarWidget customizado que desenha pontos coloridos e contagem nas células.
Cada indicador é uma tupla (símbolo, cor_hex).
"""
from PyQt6.QtWidgets import QCalendarWidget
from PyQt6.QtCore import Qt, QDate, QRect
from PyQt6.QtGui import QPainter, QFont, QColor


_CAL_PT = 9


class IconCalendarWidget(QCalendarWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icons:  dict[QDate, list[tuple[str, str]]] = {}
        self._counts: dict[QDate, int] = {}

    def set_day_icons(self, icons: dict[QDate, list[tuple[str, str]]]):
        self._icons = icons
        self.updateCells()

    def set_day_counts(self, counts: dict[QDate, int]):
        self._counts = counts
        self.updateCells()

    def paintCell(self, painter: QPainter, rect: QRect, qdate: QDate):
        # A stylesheet global usa font-size em px → pointSize vem -1.
        # Força pt válido no painter antes do código C++ do Qt tentar criar
        # variantes bold/italic do font, que disparariam o aviso.
        f = painter.font()
        if f.pointSize() <= 0:
            f.setPointSize(_CAL_PT)
            painter.setFont(f)
        super().paintCell(painter, rect, qdate)

        icons  = self._icons.get(qdate, [])
        count  = self._counts.get(qdate, 0)

        # Dias de outro mês: o Qt pinta o número em cinza "desabilitado",
        # ignorando a cor definida via setDateTextFormat — isso o deixa
        # ilegível sobre o fundo colorido de eventos. Redesenha por cima.
        is_other_month = qdate.month() != self.monthShown() or qdate.year() != self.yearShown()
        if is_other_month and (icons or count):
            fmt = self.dateTextFormat(qdate)
            bg, fg = fmt.background(), fmt.foreground()
            painter.save()
            if bg.style() != Qt.BrushStyle.NoBrush:
                painter.fillRect(rect, bg)
            font = QFont(painter.font())
            if font.pointSize() <= 0:
                font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(fg.color() if fg.style() != Qt.BrushStyle.NoBrush else QColor("#1D4ED8"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(qdate.day()))
            painter.restore()

        if not icons and not count:
            return

        if rect.width() < 4 or rect.height() < 4:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Pontos coloridos — canto inferior direito ────────────────────────
        if icons:
            dot_r   = max(5, min(7, rect.height() // 6))
            spacing = dot_r * 2 + 3
            padding = 3
            total_w = spacing * len(icons) - 3
            x = rect.right()  - padding - total_w
            y = rect.bottom() - padding - dot_r

            painter.setPen(Qt.PenStyle.NoPen)
            for _, color in icons:
                painter.setBrush(QColor(color))
                painter.drawEllipse(x, y - dot_r, dot_r * 2, dot_r * 2)
                x += spacing

        # ── Contagem — canto inferior esquerdo ───────────────────────────────
        if count > 0:
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#1E293B"))
            badge_rect = QRect(rect.left() + 3, rect.bottom() - 17, 22, 15)
            painter.drawText(badge_rect,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             str(count))

        painter.restore()
