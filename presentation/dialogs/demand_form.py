"""
DemandFlow - Diálogo de Criação/Edição de Demanda
"""
from datetime import date
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox, QDateEdit,
    QPushButton, QScrollArea, QWidget, QFrame, QCompleter
)
from presentation.widgets.spell_check import SpellCheckLineEdit
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont
import qtawesome as qta
import win32api # type: ignore

from core.domain.entities import Demand, Status, Priority, CATEGORIES
from presentation.widgets.common_widgets import AITextEdit

class DemandFormDialog(QDialog):

    def __init__(self, demand: Demand = None, dark: bool = False, ai_service=None,
                 clients: list = None, parent=None):
        super().__init__(parent)
        self.demand  = demand
        self._dark   = dark
        self._clients = clients or []
        self.result_demand = None
        self._ai_service = ai_service

        self._build()
        if demand:
            self._populate(demand)

    def _build(self):
        is_edit = self.demand is not None
        self.setWindowTitle("Editar Demanda" if is_edit else "Nova Demanda")
        self.setMinimumWidth(640)
        self.setMinimumHeight(580)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Scroll area ───────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ── Header ────────────────────────────────────────────────────────────
        header_lbl = QLabel("Editar Demanda" if is_edit else "Nova Demanda")
        header_lbl.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(header_lbl)

        # ── Grid fields ───────────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        def lbl(text):
            l = QLabel(text)
            l.setObjectName("label_section")
            return l

        # Título
        layout.addWidget(lbl("Título *"))
        self.inp_title = SpellCheckLineEdit()
        self.inp_title.setPlaceholderText("Título da demanda...")
        layout.addWidget(self.inp_title)

        # Descrição
        '''
        self.inp_desc = QTextEdit()
        self.inp_desc.setPlaceholderText("Descreva a demanda em detalhes...")
        self.inp_desc.setFixedHeight(80)
        layout.addWidget(self.inp_desc)
        '''
        layout.addWidget(lbl("Descrição"))
        self.inp_desc = AITextEdit(
            placeholder="Descreva a demanda em detalhes...",
            context="descrição de demanda técnica profissional",
            ai_service=self._ai_service,
            dark=self._dark,
            fixed_height=80,
        )
        layout.addWidget(self.inp_desc)

        layout.addLayout(grid)
        r = 0

        # Status | Prioridade
        grid.addWidget(lbl("Status"), r, 0)
        grid.addWidget(lbl("Prioridade"), r, 1)
        r += 1

        self.inp_status = QComboBox()
        for s in Status:
            self.inp_status.addItem(qta.icon(s.fa_icon, color=s.color), s.label, s)
        grid.addWidget(self.inp_status, r, 0)

        self.inp_priority = QComboBox()
        for p in Priority:
            self.inp_priority.addItem(p.label, p)
        grid.addWidget(self.inp_priority, r, 1)
        r += 1

        # Categoria | Cliente
        grid.addWidget(lbl("Categoria"), r, 0)
        grid.addWidget(lbl("Cliente / Área"), r, 1)
        r += 1

        self.inp_category = QComboBox()
        for c in CATEGORIES:
            self.inp_category.addItem(c)
        grid.addWidget(self.inp_category, r, 0)

        self.inp_client = QLineEdit()
        self.inp_client.setPlaceholderText("Cliente ou área solicitante")
        if self._clients:
            _completer = QCompleter(self._clients, self.inp_client)
            _completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            _completer.setFilterMode(Qt.MatchFlag.MatchContains)
            _completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            self.inp_client.setCompleter(_completer)

            def _show_all(event):
                QLineEdit.mousePressEvent(self.inp_client, event)
                _completer.setCompletionPrefix("")
                _completer.complete()
            self.inp_client.mousePressEvent = _show_all
        grid.addWidget(self.inp_client, r, 1)
        r += 1

        # Responsável | Horas estimadas
        grid.addWidget(lbl("Responsável"), r, 0)
        grid.addWidget(lbl("Tempo Estimado (h)"), r, 1)
        r += 1

        nome = win32api.GetUserNameEx(3)  # NameDisplay
        self.inp_resp = QLineEdit(nome)
        self.inp_resp.setPlaceholderText("Nome do responsável")
        grid.addWidget(self.inp_resp, r, 0)

        self.inp_hours = QDoubleSpinBox()
        self.inp_hours.setRange(0, 9999)
        self.inp_hours.setSuffix(" h")
        self.inp_hours.setValue(40)
        grid.addWidget(self.inp_hours, r, 1)
        r += 1

        # Data limite
        grid.addWidget(lbl("Data Limite"), r, 0)
        r += 1

        self.inp_deadline = QDateEdit()
        self.inp_deadline.setCalendarPopup(True)
        self.inp_deadline.setDate(QDate.currentDate().addDays(14))
        self.inp_deadline.setDisplayFormat("dd/MM/yyyy")
        grid.addWidget(self.inp_deadline, r, 0)
        r += 1

        # Tags
        layout.addWidget(lbl("Tags (separadas por vírgula)"))
        self.inp_tags = QLineEdit()
        self.inp_tags.setPlaceholderText("ex: backend, urgente, cliente-abc")
        layout.addWidget(self.inp_tags)

        scroll.setWidget(container)
        root.addWidget(scroll)

        # ── Footer ────────────────────────────────────────────────────────────
        footer = QHBoxLayout()
        footer.setContentsMargins(24, 12, 24, 20)
        footer.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        btn_save = QPushButton("Salvar Alterações" if is_edit else "Criar Demanda")
        btn_save.setObjectName("btn_primary")
        btn_save.clicked.connect(self._submit)
        footer.addWidget(btn_save)

        root.addLayout(footer)

    def _populate(self, d: Demand):
        self.inp_title.setText(d.title)
        self.inp_desc.setPlainText(d.description)
        for i in range(self.inp_status.count()):
            if self.inp_status.itemData(i) == d.status:
                self.inp_status.setCurrentIndex(i)
        for i in range(self.inp_priority.count()):
            if self.inp_priority.itemData(i) == d.priority:
                self.inp_priority.setCurrentIndex(i)
        idx = self.inp_category.findText(d.category)
        if idx >= 0:
            self.inp_category.setCurrentIndex(idx)
        self.inp_client.setText(d.client)
        self.inp_resp.setText(d.responsible)
        self.inp_hours.setValue(d.estimated_hours)
        self.inp_deadline.setDate(QDate(d.deadline.year, d.deadline.month, d.deadline.day))
        self.inp_tags.setText(", ".join(d.tags))

    def _submit(self):
        title = self.inp_title.text().strip()
        if not title:
            self.inp_title.setFocus()
            self.inp_title.setStyleSheet("border: 1px solid #DC2626;")
            return

        qd = self.inp_deadline.date()
        deadline = date(qd.year(), qd.month(), qd.day())
        tags = [t.strip() for t in self.inp_tags.text().split(",") if t.strip()]

        if self.demand:
            self.demand.title           = title
            self.demand.description     = self.inp_desc.toPlainText()
            self.demand.status          = self.inp_status.currentData()
            self.demand.priority        = self.inp_priority.currentData()
            self.demand.category        = self.inp_category.currentText()
            self.demand.client          = self.inp_client.text().strip()
            self.demand.responsible     = self.inp_resp.text().strip()
            self.demand.estimated_hours = self.inp_hours.value()
            self.demand.deadline        = deadline
            self.demand.tags            = tags
            self.result_demand = self.demand
        else:
            self.result_demand = {
                "title":           title,
                "description":     self.inp_desc.toPlainText(),
                "status":          self.inp_status.currentData(),
                "priority":        self.inp_priority.currentData(),
                "category":        self.inp_category.currentText(),
                "client":          self.inp_client.text().strip(),
                "responsible":     self.inp_resp.text().strip(),
                "estimated_hours": self.inp_hours.value(),
                "deadline":        deadline,
                "tags":            tags,
            }

        self.accept()
