"""
DemandFlow - Diálogo de Histórico de Apontamentos
Visualização completa, edição e exclusão de work logs de uma demanda.
"""
from datetime import datetime, date, timedelta
from typing import Optional
import qtawesome as qta

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QLineEdit, QTextEdit,
    QDateTimeEdit, QDoubleSpinBox, QMessageBox, QGridLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QComboBox
)
from presentation.widgets.spell_check import SpellCheckLineEdit, SpellCheckTextEdit
from PyQt6.QtCore import Qt, QDateTime, pyqtSignal, QDate, QTime
from PyQt6.QtGui import QColor

from infrastructure.services.work_hours import effective_seconds


def _fmt_seconds(secs: int) -> str:
    h = secs // 3600
    m = (secs % 3600) // 60
    if h > 0:
        return f"{h}h{m:02d}min" if m else f"{h}h"
    return f"{m}min"


class WorkLogDialog(QDialog):
    logs_changed = pyqtSignal()

    def __init__(self, demand, use_cases, dark: bool = False, parent=None):
        super().__init__(parent)
        self.demand    = demand
        self._uc       = use_cases
        self._dark     = dark
        self.setWindowTitle(f"Apontamentos — {demand.title}")
        self.setMinimumWidth(780)
        self.setMinimumHeight(580)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._build()
        self._load_data()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame {{ background: {'#1E293B' if self._dark else '#FFFFFF'}; "
            f"border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'}; }}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 14, 24, 14)

        _ic = "#94A3B8" if self._dark else "#64748B"
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa6s.clock", color="#3B82F6").pixmap(20, 20))
        hl.addWidget(icon_lbl)
        title = QLabel(f"Apontamentos — {self.demand.title}")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        hl.addWidget(title, 1)

        close = QPushButton()
        close.setIcon(qta.icon("fa6s.xmark", color=_ic))
        close.setFixedSize(28, 28)
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        hl.addWidget(close)
        root.addWidget(hdr)

        # ── Sumário ───────────────────────────────────────────────────────
        self._summary_frame = QFrame()
        self._summary_frame.setStyleSheet(
            f"QFrame {{ background: {'#0F172A' if self._dark else '#F8FAFC'}; "
            f"border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'}; }}"
        )
        sl = QHBoxLayout(self._summary_frame)
        sl.setContentsMargins(24, 10, 24, 10)
        sl.setSpacing(32)
        self._stat_widgets = {}
        for key, label in [
            ("total", "Total registrado"),
            ("sessions", "Sessões"),
            ("estimated", "Estimado"),
            ("progress", "Progresso"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)
            k = QLabel(label.upper())
            k.setStyleSheet(
                f"font-size: 10px; font-weight: 700; color: {'#64748B' if self._dark else '#9CA3AF'};"
            )
            v = QLabel("—")
            v.setStyleSheet("font-size: 16px; font-weight: 700;")
            col.addWidget(k)
            col.addWidget(v)
            sl.addLayout(col)
            self._stat_widgets[key] = v
        sl.addStretch()
        root.addWidget(self._summary_frame)

        # ── Tabs ──────────────────────────────────────────────────────────
        tabs = QTabWidget()

        # Tab: Histórico
        history_w = QWidget()
        hv = QVBoxLayout(history_w)
        hv.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Data", "Início", "Fim", "Duração", "Nota", ""]
        )
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 60)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hv.addWidget(self._table)
        tabs.addTab(history_w, "Histórico")
        tabs.setTabIcon(0, qta.icon("fa6s.list", color="#64748B"))

        # Tab: Por dia
        day_w = QWidget()
        dv = QVBoxLayout(day_w)
        dv.setContentsMargins(0, 0, 0, 0)
        self._day_table = QTableWidget(0, 3)
        self._day_table.setHorizontalHeaderLabels(["Data", "Sessões", "Total"])
        self._day_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._day_table.setAlternatingRowColors(True)
        self._day_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        dv.addWidget(self._day_table)
        tabs.addTab(day_w, "Por Dia")
        tabs.setTabIcon(1, qta.icon("fa6s.calendar-days", color="#64748B"))

        root.addWidget(tabs, 1)

        # ── Footer: adicionar manual ───────────────────────────────────────
        footer = QFrame()
        footer.setObjectName("dialog_footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 12, 24, 12)
        fl.setSpacing(8)

        fl.addWidget(QLabel("Início:"))
        self._inp_start = QDateTimeEdit()
        self._inp_start.setDisplayFormat("dd/MM HH:mm")
        self._inp_start.setDateTime(QDateTime.currentDateTime().addSecs(-3600))
        self._inp_start.setCalendarPopup(True)
        fl.addWidget(self._inp_start)

        fl.addWidget(QLabel("Fim:"))
        self._inp_end = QDateTimeEdit()
        self._inp_end.setDisplayFormat("dd/MM HH:mm")
        self._inp_end.setDateTime(QDateTime.currentDateTime())
        self._inp_end.setCalendarPopup(True)
        fl.addWidget(self._inp_end)

        fl.addWidget(QLabel("Nota:"))
        self._inp_note = SpellCheckTextEdit()
        self._inp_note.setPlaceholderText("Opcional...")
        self._inp_note.setFixedHeight(36)
        fl.addWidget(self._inp_note)

        add_btn = QPushButton("  Adicionar Apontamento")
        add_btn.setIcon(qta.icon("fa6s.plus", color="#FFFFFF"))
        add_btn.setObjectName("btn_primary")
        add_btn.setAutoDefault(False)
        add_btn.clicked.connect(self._add_manual)
        fl.addWidget(add_btn)

        root.addWidget(footer)

    def _load_data(self):
        stats = self._uc.get_worklog_stats(self.demand.id)
        logs  = self._uc.get_work_logs(self.demand.id)

        # Sumário
        total_h = stats["total_hours"]
        est_h   = self.demand.estimated_hours
        pct     = f"{total_h / est_h * 100:.0f}%" if est_h > 0 else "—"
        h = int(total_h)
        m = int((total_h % 1) * 60)

        self._stat_widgets["total"].setText(f"{h}h{m:02d}min" if h else f"{m}min")
        self._stat_widgets["sessions"].setText(str(stats["sessions"]))
        self._stat_widgets["estimated"].setText(f"{est_h:.0f}h")
        self._stat_widgets["progress"].setText(pct)

        # Tabela histórico
        self._table.setRowCount(0)
        for wl in logs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(
                wl.started_at.strftime("%d/%m/%Y")
            ))
            self._table.setItem(row, 1, QTableWidgetItem(
                wl.started_at.strftime("%H:%M")
            ))
            self._table.setItem(row, 2, QTableWidgetItem(
                wl.ended_at.strftime("%H:%M") if wl.ended_at else "—"
            ))
            dur_item = QTableWidgetItem(_fmt_seconds(wl.duration_seconds))
            if wl.manual:
                dur_item.setForeground(QColor("#A78BFA"))
            self._table.setItem(row, 3, dur_item)
            self._table.setItem(row, 4, QTableWidgetItem(wl.note or ""))

            del_btn = QPushButton()
            del_btn.setIcon(qta.icon("fa6s.trash", color="#EF4444"))
            del_btn.setAutoDefault(False)
            del_btn.setStyleSheet("border: none; background: transparent; padding: 2px 6px;")
            del_btn.clicked.connect(lambda _, w=wl: self._delete_log(w))
            self._table.setCellWidget(row, 5, del_btn)

        # Tabela por dia
        self._day_table.setRowCount(0)
        for day_str, info in stats.get("by_day", {}).items():
            row = self._day_table.rowCount()
            self._day_table.insertRow(row)
            dt = datetime.fromisoformat(day_str + "T00:00:00")
            self._day_table.setItem(row, 0, QTableWidgetItem(
                dt.strftime("%d/%m/%Y (%A)")
            ))
            self._day_table.setItem(row, 1, QTableWidgetItem(
                str(len(info["sessions"]))
            ))
            self._day_table.setItem(row, 2, QTableWidgetItem(
                _fmt_seconds(info["seconds"])
            ))

    def _add_manual(self):
        qs = self._inp_start.dateTime()
        qe = self._inp_end.dateTime()
        start = datetime(qs.date().year(), qs.date().month(), qs.date().day(),
                         qs.time().hour(), qs.time().minute())
        end   = datetime(qe.date().year(), qe.date().month(), qe.date().day(),
                         qe.time().hour(), qe.time().minute())
        if end <= start:
            QMessageBox.warning(self, "Erro", "O horário de fim deve ser após o início.")
            return
        secs = effective_seconds(start, end)
        if secs == 0:
            QMessageBox.warning(self, "Aviso",
                "Nenhum tempo útil calculado.\n"
                "Verifique se o período está dentro do expediente (08:00–17:00)."
            )
            return
        self._uc.add_work_log(
            demand_id=self.demand.id,
            started_at=start,
            ended_at=end,
            duration_seconds=secs,
            note=self._inp_note.text().strip(),
            manual=True,
        )
        self._inp_note.clear()
        self._load_data()
        self.logs_changed.emit()

    def _delete_log(self, wl):
        r = QMessageBox.question(
            self, "Confirmar",
            f"Excluir apontamento de {_fmt_seconds(wl.duration_seconds)} "
            f"em {wl.started_at.strftime('%d/%m/%Y %H:%M')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if r == QMessageBox.StandardButton.Yes:
            self._uc.delete_work_log(wl.id, self.demand.id)
            self._load_data()
            self.logs_changed.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)
