"""
Diálogo para registro de atividades avulsas (sem demanda associada).
"""
from datetime import datetime, date, timedelta

import qtawesome as qta
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QLineEdit, QDateTimeEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QWidget,
)
from presentation.widgets.spell_check import SpellCheckLineEdit, SpellCheckTextEdit
from PyQt6.QtCore import Qt, QDateTime, QSize, pyqtSignal

_CATEGORIES = [
    "Suporte a usuário",
    "Reunião",
    "Capacitação / Treinamento",
    "Administrativo",
    "Infraestrutura",
    "Outro",
]


def _fmt(secs: int) -> str:
    h, m = secs // 3600, (secs % 3600) // 60
    return f"{h}h{m:02d}min" if h else f"{m}min"


class EditWorkLogDialog(QDialog):
    """Editar um apontamento já registrado (avulso ou de demanda), aberto pela
    lista de Atividades Avulsas, pela aba Apontamentos ou por clique no Gantt."""

    saved   = pyqtSignal()
    deleted = pyqtSignal()

    def __init__(self, use_cases, worklog, dark: bool = False, parent=None):
        super().__init__(parent)
        self._uc   = use_cases
        self._wl   = worklog
        self._dark = dark
        self._is_avulsa = worklog.demand_id is None
        self.setWindowTitle("Editar Atividade Avulsa" if self._is_avulsa else "Editar Apontamento")
        self.setMinimumWidth(420)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Início:"))
        self._inp_start = QDateTimeEdit()
        self._inp_start.setDisplayFormat("dd/MM/yyyy HH:mm")
        self._inp_start.setCalendarPopup(True)
        self._inp_start.setDateTime(QDateTime(self._wl.started_at))
        row1.addWidget(self._inp_start, 1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Fim:"))
        self._inp_end = QDateTimeEdit()
        self._inp_end.setDisplayFormat("dd/MM/yyyy HH:mm")
        self._inp_end.setCalendarPopup(True)
        ended = self._wl.ended_at or (self._wl.started_at + timedelta(seconds=self._wl.duration_seconds))
        self._inp_end.setDateTime(QDateTime(ended))
        row2.addWidget(self._inp_end, 1)
        root.addLayout(row2)

        self._inp_cat = None
        if self._is_avulsa:
            row3 = QHBoxLayout()
            row3.addWidget(QLabel("Categoria:"))
            self._inp_cat = QComboBox()
            self._inp_cat.setEditable(True)
            self._inp_cat.addItems(_CATEGORIES)
            self._inp_cat.setCurrentText(self._wl.category or "")
            row3.addWidget(self._inp_cat, 1)
            root.addLayout(row3)

        root.addWidget(QLabel("Nota:"))
        self._inp_note = SpellCheckTextEdit()
        self._inp_note.setPlaceholderText("Opcional…")
        self._inp_note.setFixedHeight(70)
        self._inp_note.setText(self._wl.note or "")
        root.addWidget(self._inp_note)

        btn_row = QHBoxLayout()
        del_btn = QPushButton("  Excluir")
        del_btn.setIcon(qta.icon("fa6s.trash", color="#EF4444"))
        del_btn.setAutoDefault(False)
        del_btn.clicked.connect(self._delete)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("  Salvar")
        save_btn.setIcon(qta.icon("fa6s.check", color="#FFFFFF"))
        save_btn.setObjectName("btn_primary")
        save_btn.setAutoDefault(False)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _save(self):
        qs = self._inp_start.dateTime()
        qe = self._inp_end.dateTime()
        start = datetime(qs.date().year(), qs.date().month(), qs.date().day(),
                         qs.time().hour(), qs.time().minute())
        end   = datetime(qe.date().year(), qe.date().month(), qe.date().day(),
                         qe.time().hour(), qe.time().minute())
        if end <= start:
            QMessageBox.warning(self, "Erro", "Horário de fim deve ser após o início.")
            return

        self._wl.started_at = start
        self._wl.ended_at = end
        self._wl.duration_seconds = int((end - start).total_seconds())
        if self._inp_cat is not None:
            self._wl.category = self._inp_cat.currentText()
        self._wl.note = self._inp_note.text().strip()

        self._uc.update_work_log(self._wl)
        self.saved.emit()
        self.accept()

    def _delete(self):
        r = QMessageBox.question(
            self, "Confirmar",
            f"Excluir {'atividade' if self._is_avulsa else 'apontamento'} de "
            f"{_fmt(self._wl.duration_seconds)} em {self._wl.started_at.strftime('%d/%m/%Y %H:%M')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            self._uc.delete_work_log(self._wl.id, self._wl.demand_id)
            self.deleted.emit()
            self.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)


class GeneralWorkLogDialog(QDialog):
    """Registrar e visualizar apontamentos avulsos."""

    log_added = pyqtSignal()

    def __init__(self, use_cases, dark: bool = False, parent=None):
        super().__init__(parent)
        self._uc   = use_cases
        self._dark = dark
        self.setWindowTitle("Atividades Avulsas")
        self.setMinimumWidth(720)
        self.setMinimumHeight(520)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._build()
        self._load()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame {{ background: {'#1E293B' if self._dark else '#FFFFFF'}; "
            f"border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'}; }}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 14, 24, 14)
        ic = QLabel(); ic.setPixmap(qta.icon("fa6s.bolt", color="#F59E0B").pixmap(18, 18))
        hl.addWidget(ic)
        ttl = QLabel("Atividades Avulsas")
        ttl.setStyleSheet("font-size: 15px; font-weight: 700;")
        hl.addWidget(ttl, 1)
        root.addWidget(hdr)

        # Tabela de registros
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["Data", "Início", "Fim", "Categoria", "Nota / Duração", ""])
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 40)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        # Footer: formulário de adição
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
        self._inp_start.setFixedWidth(130)
        fl.addWidget(self._inp_start)

        fl.addWidget(QLabel("Fim:"))
        self._inp_end = QDateTimeEdit()
        self._inp_end.setDisplayFormat("dd/MM HH:mm")
        self._inp_end.setDateTime(QDateTime.currentDateTime())
        self._inp_end.setCalendarPopup(True)
        self._inp_end.setFixedWidth(130)
        fl.addWidget(self._inp_end)

        fl.addWidget(QLabel("Categoria:"))
        self._inp_cat = QComboBox()
        self._inp_cat.setEditable(True)
        self._inp_cat.addItems(_CATEGORIES)
        self._inp_cat.setFixedWidth(180)
        fl.addWidget(self._inp_cat)

        fl.addWidget(QLabel("Nota:"))
        self._inp_note = SpellCheckTextEdit()
        self._inp_note.setPlaceholderText("Opcional…")
        self._inp_note.setFixedHeight(36)
        fl.addWidget(self._inp_note)

        add_btn = QPushButton("  Registrar")
        add_btn.setIcon(qta.icon("fa6s.plus", color="#FFFFFF"))
        add_btn.setObjectName("btn_primary")
        add_btn.setAutoDefault(False)
        add_btn.clicked.connect(self._add)
        fl.addWidget(add_btn)

        root.addWidget(footer)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load(self):
        logs = [w for w in self._uc.get_all_work_logs() if w.demand_id is None]
        logs.sort(key=lambda w: w.started_at, reverse=True)

        self._table.setRowCount(0)
        self._logs_cache = logs

        for wl in logs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(wl.started_at.strftime("%d/%m/%Y")))
            self._table.setItem(row, 1, QTableWidgetItem(wl.started_at.strftime("%H:%M")))
            ended = wl.ended_at or (wl.started_at + timedelta(seconds=wl.duration_seconds))
            self._table.setItem(row, 2, QTableWidgetItem(ended.strftime("%H:%M")))
            self._table.setItem(row, 3, QTableWidgetItem(wl.category or "—"))
            note_dur = _fmt(wl.duration_seconds)
            if wl.note:
                note_dur += f"  •  {wl.note}"
            self._table.setItem(row, 4, QTableWidgetItem(note_dur))

            edit_btn = QPushButton()
            edit_btn.setIcon(qta.icon("fa6s.pen", color="#64748B"))
            edit_btn.setIconSize(QSize(14, 14))
            edit_btn.setFixedSize(26, 26)
            edit_btn.setAutoDefault(False)
            edit_btn.setStyleSheet("border: none; background: transparent; padding: 0;")
            edit_btn.clicked.connect(lambda _, w=wl: self.edit_entry(w))

            del_btn = QPushButton()
            del_btn.setIcon(qta.icon("fa6s.trash", color="#EF4444"))
            del_btn.setIconSize(QSize(14, 14))
            del_btn.setFixedSize(26, 26)
            del_btn.setAutoDefault(False)
            del_btn.setStyleSheet("border: none; background: transparent; padding: 0;")
            del_btn.clicked.connect(lambda _, w=wl: self._delete(w))

            actions_wrap = QWidget()
            wl_layout = QHBoxLayout(actions_wrap)
            wl_layout.setContentsMargins(0, 0, 0, 0)
            wl_layout.setSpacing(2)
            wl_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wl_layout.addWidget(edit_btn)
            wl_layout.addWidget(del_btn)
            self._table.setCellWidget(row, 5, actions_wrap)

        self._table.resizeColumnsToContents()
        self._table.setColumnWidth(5, 72)
        self._table.resizeRowsToContents()

    def _add(self):
        qs = self._inp_start.dateTime()
        qe = self._inp_end.dateTime()
        start = datetime(qs.date().year(), qs.date().month(), qs.date().day(),
                         qs.time().hour(), qs.time().minute())
        end   = datetime(qe.date().year(), qe.date().month(), qe.date().day(),
                         qe.time().hour(), qe.time().minute())
        if end <= start:
            QMessageBox.warning(self, "Erro", "Horário de fim deve ser após o início.")
            return

        secs = int((end - start).total_seconds())
        self._uc.add_work_log(
            demand_id=None,
            started_at=start,
            ended_at=end,
            duration_seconds=secs,
            note=self._inp_note.text().strip(),
            manual=True,
            category=self._inp_cat.currentText(),
        )
        self._inp_note.clear()
        self._load()
        self.log_added.emit()

    def edit_entry(self, wl):
        dlg = EditWorkLogDialog(self._uc, wl, dark=self._dark, parent=self)
        dlg.saved.connect(self._load)
        dlg.saved.connect(self.log_added)
        dlg.deleted.connect(self._load)
        dlg.deleted.connect(self.log_added)
        dlg.exec()

    def _delete(self, wl):
        r = QMessageBox.question(
            self, "Confirmar",
            f"Excluir atividade de {_fmt(wl.duration_seconds)} em "
            f"{wl.started_at.strftime('%d/%m/%Y %H:%M')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r == QMessageBox.StandardButton.Yes:
            self._uc.delete_work_log(wl.id, None)
            self._load()
            self.log_added.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)
