"""
DemandFlow - Diálogo de Detalhes da Demanda
Visualização completa com comentários, histórico, status e arquivos.
"""


from datetime import date, datetime
import qtawesome as qta
from PyQt6.QtWidgets import (
    QCheckBox, QDateEdit, QDateTimeEdit, QDialog, QHeaderView, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QComboBox,
    QTabWidget, QFileDialog
)
from presentation.widgets.note_pad import NotePad
from PyQt6.QtCore import QDate, QDateTime, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
import os

from core.servicenow import extract_number as _servicenow_number, demand_url as _servicenow_url
from core.domain.entities import Demand, Status, CommentType, Milestone, Reminder
from infrastructure.services.work_hours import effective_seconds
from presentation.widgets.common_widgets import status_badge, priority_badge, BadgeLabel, AITextEdit
from presentation.widgets.spell_check import SpellCheckTextEdit
from presentation.widgets.file_manager import FileManagerWidget
from presentation.dialogs.general_worklog_dialog import EditWorkLogDialog

STATUS_COLORS = {
    Status.NAO_INICIADA: ("#F3F4F6", "#6B7280"),
    Status.EM_ANDAMENTO: ("#DBEAFE", "#2563EB"),
    Status.AGUARDANDO:   ("#FEF3C7", "#D97706"),
    Status.BLOQUEADA:    ("#FEE2E2", "#DC2626"),
    Status.CONCLUIDA:    ("#D1FAE5", "#059669"),
    Status.CANCELADA:    ("#F9FAFB", "#9CA3AF"),
}


class _StatusBtn(QPushButton):
    """Botão de status que só dispara ação no duplo clique."""
    status_selected = pyqtSignal(object)

    def __init__(self, status, label: str):
        super().__init__(label)
        self._status = status
        self.setToolTip("Duplo clique para alterar o status")
        self.setIconSize(QSize(14, 14))
        self._set_icon(status.color)

    def _set_icon(self, color: str):
        self.setIcon(qta.icon(self._status.fa_icon, color=color))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.status_selected.emit(self._status)
        super().mouseDoubleClickEvent(event)


class DemandDetailDialog(QDialog):
    demand_updated          = pyqtSignal(object)
    demand_deleted          = pyqtSignal(int)
    edit_requested          = pyqtSignal(object)
    calendar_refresh        = pyqtSignal()

    def __init__(self, demand: Demand, use_cases, file_service=None, ai_service=None,
                 dark: bool = False, parent=None):
        super().__init__(parent)
        self.demand     = demand
        self._uc        = use_cases
        self._fs        = file_service
        self._dark      = dark
        self._ai        = ai_service

        self.status_buttons = {}

        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self.setWindowTitle(demand.title)
        self.setMinimumWidth(420)
        self.setMinimumHeight(300)
        self._build()

    def _build(self):
        if self._dark:
            self.setStyleSheet("""
                QDialog                    { background: #0F172A; }
                QTabWidget::pane           { background: #0F172A; border: none; }
                QTabBar                    { background: #1E293B; }
                QTabBar::tab               {
                    background: #1E293B; color: #94A3B8; border: none;
                    border-bottom: 2px solid transparent;
                    padding: 8px 16px; margin-right: 2px;
                }
                QTabBar::tab:selected      { background: #0F172A; color: #E2E8F0; border-bottom: 2px solid #3B82F6; }
                QTabBar::tab:hover         { color: #CBD5E1; }
                QScrollArea                { background: #0F172A; border: none; }
                QScrollArea > QWidget > QWidget { background: #0F172A; }
                QScrollBar:vertical        { background: #1E293B; width: 6px; border: none; }
                QScrollBar::handle:vertical { background: #475569; border-radius: 3px; min-height: 20px; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
                QTableWidget               {
                    background: #0F172A; color: #E2E8F0;
                    gridline-color: #1E293B; alternate-background-color: #1E293B; border: none;
                }
                QTableWidget::item:selected { background: #1E3A5F; color: #E2E8F0; }
                QHeaderView::section       {
                    background: #1E293B; color: #94A3B8;
                    border: none; border-right: 1px solid #334155;
                    padding: 6px 8px; font-weight: 600;
                }
                QComboBox                  {
                    background: #1E293B; color: #E2E8F0;
                    border: 1px solid #334155; border-radius: 8px; padding: 7px 11px;
                }
                QComboBox::drop-down       { border: none; }
                QComboBox QAbstractItemView {
                    background: #1E293B; color: #E2E8F0;
                    selection-background-color: #2563EB;
                    border: 1px solid #334155; outline: none;
                }
                QTextEdit                  {
                    background: #1E293B; color: #E2E8F0;
                    border: 1px solid #334155; border-radius: 8px; padding: 7px 11px;
                }
                QCheckBox                  { color: #E2E8F0; background: transparent; }
                QCheckBox::indicator       {
                    width: 16px; height: 16px;
                    border: 1px solid #475569; border-radius: 3px; background: #1E293B;
                }
                QCheckBox::indicator:checked { background: #3B82F6; border-color: #3B82F6; }
                QLabel                     { color: #E2E8F0; background: transparent; }
                QLabel#label_section       { color: #94A3B8; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
                QLabel#label_muted         { color: #64748B; font-size: 11px; }
                QDateTimeEdit              {
                    background: #0F172A; color: #E2E8F0;
                    border: 1px solid #334155; border-radius: 8px; padding: 7px 11px;
                }
                QDateTimeEdit:focus        { border-color: #3B82F6; }
                QDateTimeEdit::drop-down   { border: none; }
            """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────────────
        header = QFrame()
        self._header_frame = header
        header.setStyleSheet(
            f"QFrame {{ background: {'#1E293B' if self._dark else '#FFFFFF'}; "
            f"border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'}; }}"
        )
        hl = QVBoxLayout(header)
        hl.setContentsMargins(28, 20, 28, 16)
        hl.setSpacing(8)

        # badges
        self.badges_row = QHBoxLayout()
        self.badges_row.setSpacing(6)

        # Sub-layout só para os badges que mudam (status/prioridade/alertas)
        self._dynamic_badges_layout = QHBoxLayout()
        self._dynamic_badges_layout.setSpacing(6)
        self._dynamic_badges_layout.addWidget(status_badge(self.demand.status))
        self._dynamic_badges_layout.addWidget(priority_badge(self.demand.priority))
        if self.demand.is_overdue:
            self._dynamic_badges_layout.addWidget(BadgeLabel("Atrasada", "#FEE2E2", "#DC2626"))
        if self.demand.is_inactive:
            self._dynamic_badges_layout.addWidget(BadgeLabel(f"Inativa {self.demand.days_since_activity}d", "#FEF3C7", "#D97706"))

        self.badges_row.addLayout(self._dynamic_badges_layout)
        self.badges_row.addStretch()

        _ic = "#94A3B8" if self._dark else "#64748B"

        self._sn_btn = QPushButton("  Abrir no ServiceNow")
        self._sn_btn.setIcon(qta.icon("fa6s.arrow-up-right-from-square", color=_ic))
        self._sn_btn.clicked.connect(self._open_servicenow)
        self.badges_row.addWidget(self._sn_btn)
        self._update_servicenow_button()

        self._edit_btn = QPushButton("  Editar")
        self._edit_btn.setIcon(qta.icon("fa6s.pen", color=_ic))
        self._edit_btn.clicked.connect(self._on_edit)
        self.badges_row.addWidget(self._edit_btn)

        self._del_btn = QPushButton("  Remover")
        self._del_btn.setIcon(qta.icon("fa6s.trash", color="#EF4444"))
        self._del_btn.clicked.connect(self._on_delete)
        self.badges_row.addWidget(self._del_btn)


        hl.addLayout(self.badges_row)

        self.title_lbl = QLabel(self.demand.title)
        self.title_lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {'#E2E8F0' if self._dark else '#1E293B'};")
        # TextSelectableByKeyboard + FocusPolicy — sem isso o label nunca
        # ganha foco de teclado e Ctrl+C não tem efeito (só funciona pelo
        # menu de clique direito, que não depende de foco).
        self.title_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
        self.title_lbl.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.title_lbl.setWordWrap(True)
        hl.addWidget(self.title_lbl)

        self.desc_lbl = QLabel(self.demand.description)
        self.desc_lbl.setStyleSheet(f"color: {'#94A3B8' if self._dark else '#64748B'}; font-size: 13px;")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
        self.desc_lbl.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        hl.addWidget(self.desc_lbl)

        root.addWidget(header)

        # ── Tabs ──────────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: none; margin-top: 0; "
            f"background: {'#0F172A' if self._dark else 'transparent'}; }}"
        )

        _ic = "#64748B"

        # Tab 1: Ações
        _idx = self.tabs.addTab(self._build_actions_tab(), "Ações")
        self.tabs.setTabIcon(_idx, qta.icon("fa6s.bolt", color=_ic))

        # Tab 2: Apontamentos
        _idx = self.tabs.addTab(self._build_worklogs_tab(), "Apontamentos")
        self.tabs.setTabIcon(_idx, qta.icon("fa6s.clock", color=_ic))

        # Tab 3: Notas
        self.notes_tab_index = self.tabs.addTab(self._build_notes_tab(), "Notas")
        self.tabs.setTabIcon(self.notes_tab_index, qta.icon("fa6s.file-lines", color=_ic))

        # Tab 4: Arquivos
        files_tab = self._build_files_tab()
        self.files_tab_index = self.tabs.addTab(files_tab, "Arquivos")
        self.tabs.setTabIcon(self.files_tab_index, qta.icon("fa6s.paperclip", color=_ic))

        # Tab 6: Histórico
        history_tab = self._build_history_tab()
        self.history_tab_index = self.tabs.addTab(history_tab, "Histórico")
        self.tabs.setTabIcon(self.history_tab_index, qta.icon("fa6s.clock-rotate-left", color=_ic))

        # Tab: Comentários — substituída pela aba Notas, mantida apenas para referência
        # comments_tab = self._build_comments_tab()
        # self.comments_tab_index = self.tabs.addTab(comments_tab, f"Comentários ({len(self.demand.comments)})")
        # self.tabs.setTabIcon(self.comments_tab_index, qta.icon("fa6s.comment", color=_ic))


        self._disable_default_buttons()
        root.addWidget(self.tabs)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return  # ignora completamente
        super().keyPressEvent(event)

    def open_worklogs_tab(self):
        idx = self._get_tab_index("Apontamentos")
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def _disable_default_buttons(self):
        for btn in self.findChildren(QPushButton):
            btn.setAutoDefault(False)
            btn.setDefault(False)

    # ── Actions Tab ───────────────────────────────────────────────────────────

    def _render_history(self):
        if not hasattr(self, "history_layout"):
            return

        self._clear_layout(self.history_layout)

        for h in self.demand.history:
            row = QHBoxLayout()
            dt = QLabel(h.created_at.strftime("%d/%m/%Y %H:%M"))
            dt.setFixedWidth(90)
            dt.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 12px;")
            dot = QLabel("●")
            dot.setStyleSheet("color: #3B82F6; font-size: 8px;")
            dot.setFixedWidth(16)
            act = QLabel(h.action)
            act.setStyleSheet(f"font-size: 12px; color: {'#E2E8F0' if self._dark else '#1E293B'};")
            user = QLabel(f"— {h.user}")
            user.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 12px;")
            row.addWidget(dt)
            row.addWidget(dot)
            row.addWidget(act)
            row.addWidget(user)
            row.addStretch()
            self.history_layout.addLayout(row)

        self.history_layout.addStretch()

    def _build_actions_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(20)

        # Change status
        s_lbl = QLabel("ALTERAR STATUS")
        s_lbl.setObjectName("label_section")
        layout.addWidget(s_lbl)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        for s in Status:
            btn = _StatusBtn(s, s.label)
            bg, fg = STATUS_COLORS.get(s, ("#F3F4F6", "#6B7280"))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {''+bg if s == self.demand.status else 'transparent'};
                    color: {fg if s == self.demand.status else (''+('#94A3B8' if self._dark else '#64748B'))};
                    border: 1px solid {fg if s == self.demand.status else (''+('#334155' if self._dark else '#E2E8F0'))};
                    border-radius: 8px; padding: 6px 12px; font-size: 12px;
                    font-weight: {'700' if s == self.demand.status else '400'};
                }}
                QPushButton:hover {{ background: {bg}; color: {fg}; }}
            """)
            btn.status_selected.connect(self._change_status)
            status_row.addWidget(btn)
            self.status_buttons[s] = btn
        status_row.addStretch()
        layout.addLayout(status_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {'#334155' if self._dark else '#E2E8F0'};")
        layout.addWidget(sep2)

        # ── Duas colunas: Milestones | Lembretes ───────────────────────────
        cols = QHBoxLayout()
        cols.setSpacing(24)

        # Coluna Milestones
        m_col = QVBoxLayout()
        m_col.setSpacing(8)
        m_lbl = QLabel("MILESTONES")
        m_lbl.setObjectName("label_section")
        m_col.addWidget(m_lbl)

        self._milestones_container = QWidget()
        self._milestones_layout = QVBoxLayout(self._milestones_container)
        self._milestones_layout.setContentsMargins(0, 0, 0, 0)
        self._milestones_layout.setSpacing(6)

        self._milestones_scroll = QScrollArea()
        self._milestones_scroll.setWidgetResizable(True)
        self._milestones_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._milestones_scroll.setWidget(self._milestones_container)
        self._milestones_scroll.setMinimumHeight(80)
        m_col.addWidget(self._milestones_scroll, 1)

        add_m_btn = QPushButton("+ Adicionar Milestone")
        add_m_btn.setObjectName("btn_primary")
        add_m_btn.clicked.connect(self._add_milestone)
        m_col.addWidget(add_m_btn)

        cols.addLayout(m_col, 1)

        # Separador vertical entre as colunas
        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setStyleSheet(f"color: {'#334155' if self._dark else '#E2E8F0'};")
        cols.addWidget(vsep)

        # Coluna Lembretes
        r_col = QVBoxLayout()
        r_col.setSpacing(8)
        r_lbl = QLabel("LEMBRETES")
        r_lbl.setObjectName("label_section")
        r_col.addWidget(r_lbl)

        self._reminders_container = QWidget()
        self._reminders_layout = QVBoxLayout(self._reminders_container)
        self._reminders_layout.setContentsMargins(0, 0, 0, 0)
        self._reminders_layout.setSpacing(6)
        r_col.addWidget(self._reminders_container, 1)

        add_r_btn = QPushButton("+ Novo Lembrete")
        add_r_btn.setObjectName("btn_primary")
        add_r_btn.clicked.connect(self._add_reminder)
        r_col.addWidget(add_r_btn)

        cols.addLayout(r_col, 1)

        layout.addLayout(cols, 1)

        self._render_milestones()
        self._render_reminders()
        return w


    def _update_status_buttons(self):

        for status, btn in self.status_buttons.items():

            selected = status == self.demand.status
            bg, fg = STATUS_COLORS.get(status, ("#F3F4F6", "#6B7280"))
            icon_color = fg if selected else ('#94A3B8' if self._dark else '#CBD5E1')

            btn.setChecked(selected)
            btn._set_icon(icon_color)

            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {bg if selected else 'transparent'};
                    color: {fg if selected else ('#94A3B8' if self._dark else '#64748B')};
                    border: 1px solid {fg if selected else ('#334155' if self._dark else '#E2E8F0')};
                    border-radius: 8px;
                    padding: 6px 12px;
                    font-size: 12px;
                    font-weight: {'700' if selected else '400'};
                }}
                QPushButton:hover {{
                    background: {bg};
                    color: {fg};
                }}
            """)

    # ── Notes Tab ─────────────────────────────────────────────────────────────

    def _build_notes_tab(self) -> QWidget:
        self._note_pad = NotePad(
            ai_service=getattr(self, "_ai", None),
            dark=self._dark,
        )
        # Carrega notas salvas
        if self.demand.notes:
            self._note_pad.set_html(self.demand.notes)
        elif self.demand.comments:
            # Importa comentários existentes na primeira vez
            imported = self._note_pad.import_comments(self.demand.comments)
            self._uc.update_notes(self.demand.id, imported)
            self.demand.notes = imported

        self._note_pad.notes_changed.connect(self._on_notes_changed)
        return self._note_pad

    def _on_notes_changed(self, html: str):
        self._uc.update_notes(self.demand.id, html)
        self.demand = self._uc.get(self.demand.id)
        self.demand_updated.emit(self.demand)
        self.refresh_demand()

    # ── Comments Tab ──────────────────────────────────────────────────────────

    def _build_comments_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 16, 28, 16)
        layout.setSpacing(12)

        # Type selector
        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        self.comment_type_combo = QComboBox()
        for ct in CommentType:
            self.comment_type_combo.addItem(ct.label, ct)
        type_row.addWidget(QLabel("Tipo:"))
        type_row.addWidget(self.comment_type_combo)
        type_row.addStretch()
        layout.addLayout(type_row)

        # Text input
        self.comment_input = AITextEdit(
            placeholder="Escreva seu comentário, nota, decisão ou registro de reunião...",
            context="comentário técnico profissional em sistema de gestão de demandas",
            ai_service=self._ai,
            dark=self._dark,
            fixed_height=80,
        )
        layout.addWidget(self.comment_input)
        '''
        self.comment_input = QTextEdit()
        self.comment_input.setFixedHeight(80)
        self.comment_input.setPlaceholderText("Escreva seu comentário, nota, decisão ou registro de reunião...")
        layout.addWidget(self.comment_input)
        '''

        add_btn = QPushButton("Registrar")
        add_btn.setObjectName("btn_primary")
        add_btn.clicked.connect(self._add_comment)
        layout.addWidget(add_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {'#334155' if self._dark else '#E2E8F0'};")
        layout.addWidget(sep)

        # Comments list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.comments_container = QWidget()
        self.comments_layout = QVBoxLayout(self.comments_container)
        self.comments_layout.setContentsMargins(0, 0, 0, 0)
        self.comments_layout.setSpacing(8)
        self._render_comments()
        self.comments_layout.addStretch()

        scroll.setWidget(self.comments_container)
        layout.addWidget(scroll)
        return w

    def _render_comments(self):
        if not hasattr(self, 'comments_layout'):
            return  # aba de comentários ainda não foi construída

        while self.comments_layout.count():
            item = self.comments_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        ct_colors = {
            CommentType.COMMENT:  "#94A3B8",
            CommentType.NOTE:     "#F59E0B",
            CommentType.DECISION: "#10B981",
            CommentType.MEETING:  "#3B82F6",
        }

        for c in reversed(self.demand.comments):
            frame = QFrame()
            ct_color = ct_colors.get(c.comment_type, "#94A3B8")
            frame.setStyleSheet(f"""
                QFrame {{
                    background: {'#0F172A' if self._dark else '#F8FAFC'};
                    border-left: 3px solid {ct_color};
                    border-radius: 6px;
                    padding: 4px;
                }}
            """)
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(12, 10, 12, 10)
            fl.setSpacing(4)

            top = QHBoxLayout()
            author = QLabel(c.author)
            author.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {'#E2E8F0' if self._dark else '#1E293B'};")
            dt = QLabel(c.created_at.strftime("%d/%m/%Y"))
            dt.setStyleSheet(f"font-size: 11px; color: {'#64748B' if self._dark else '#9CA3AF'};")
            type_badge = BadgeLabel(c.comment_type.label, f"{ct_color}22", ct_color)
            top.addWidget(author)
            top.addWidget(dt)
            top.addWidget(type_badge)
            top.addStretch()
            fl.addLayout(top)

            txt = QLabel(c.text)
            txt.setStyleSheet(f"font-size: 13px; color: {'#E2E8F0' if self._dark else '#1E293B'};")
            txt.setWordWrap(True)
            txt.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            txt.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            fl.addWidget(txt)

            self.comments_layout.addWidget(frame)

        self.comments_layout.addStretch()

    # ── History Tab ───────────────────────────────────────────────────────────

    def _build_history_tab(self):
        
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 16, 28, 16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)

        self.history_container = QWidget()
        self.history_layout = QVBoxLayout(self.history_container)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(6)

        for h in self.demand.history:
            row = QHBoxLayout()
            dt = QLabel(h.created_at.strftime("%d/%m/%Y %H:%M"))
            dt.setFixedWidth(90)
            dt.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 12px;")
            dot = QLabel("●")
            dot.setStyleSheet("color: #3B82F6; font-size: 8px;")
            dot.setFixedWidth(16)
            act = QLabel(h.action)
            act.setStyleSheet(f"font-size: 12px; color: {'#E2E8F0' if self._dark else '#1E293B'};")
            user = QLabel(f"— {h.user}")
            user.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 12px;")
            row.addWidget(dt)
            row.addWidget(dot)
            row.addWidget(act)
            row.addWidget(user)
            row.addStretch()
            self.history_layout.addLayout(row)

        self.history_layout.addStretch()
        scroll.setWidget(self.history_container)
        layout.addWidget(scroll)
        return w

    # ── Files Tab — Gerenciador Completo ─────────────────────────────────────

    def _build_files_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(0)

        if self._fs:
            self._file_manager = FileManagerWidget(
                demand_id    = self.demand.id,
                demand_title = self.demand.title,
                file_service = self._fs,
                dark         = self._dark,
                parent       = w,
            )
            self._file_manager.files_changed.connect(lambda: self.demand_updated.emit(self.demand))
            layout.addWidget(self._file_manager)
        else:
            lbl = QLabel("Serviço de arquivos não configurado.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
        return w

    def _render_files(self):
        while self.files_container.count():
            item = self.files_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for att in self.demand.attachments:
            row = QFrame()
            row.setStyleSheet(f"QFrame {{ background: {'#0F172A' if self._dark else '#F8FAFC'}; border-radius: 8px; padding: 4px; }}")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 8, 12, 8)

            icon_map = {".txt": "📄",".pdf": "📄", ".xlsx": "📊", ".docx": "📝",
                        ".pptx": "📽", ".png": "🖼", ".jpg": "🖼",
                        ".zip": "🗜", ".mp4": "🎬"}
            ext = os.path.splitext(att.filename)[1].lower()
            icon = icon_map.get(ext, "📎")

            name_lbl = QLabel(f"{icon}  {att.filename}")
            name_lbl.setStyleSheet("font-size: 13px;")
            dt_lbl = QLabel(att.created_at.strftime("%d/%m/%Y"))
            dt_lbl.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 11px;")

            open_btn = QPushButton("Abrir")
            open_btn.setFixedWidth(60)
            open_btn.clicked.connect(lambda _, p=att.filepath: os.startfile(p) if os.name == "nt" else os.system(f"xdg-open '{p}'"))

            rl.addWidget(name_lbl)
            rl.addStretch()
            rl.addWidget(dt_lbl)
            rl.addWidget(open_btn)
            self.files_container.addWidget(row)

    def _render_reminders(self):
        while self._reminders_layout.count():
            item = self._reminders_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        reminders = self._uc.get_reminders(self.demand.id)
        today = date.today()

        if not reminders:
            lbl = QLabel("Nenhum lembrete cadastrado.")
            lbl.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._reminders_layout.addWidget(lbl)

        for r in reminders:
            is_daily = getattr(r, 'daily', False)
            overdue  = not r.done and not is_daily and r.remind_at < today
            today_r  = not r.done and not is_daily and r.remind_at == today

            row = QFrame()
            border = "#EF4444" if overdue else "#F59E0B" if (today_r or (is_daily and not r.done)) else (
                "#334155" if self._dark else "#E2E8F0"
            )
            row.setStyleSheet(f"""
                QFrame {{
                    background: {'#0F172A' if self._dark else '#F8FAFC'};
                    border-left: 3px solid {border};
                    border-radius: 8px;
                }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 10, 12, 10)
            rl.setSpacing(10)

            from PyQt6.QtWidgets import QCheckBox
            chk = QCheckBox()
            chk.setChecked(r.done)
            chk.toggled.connect(lambda checked, rem=r: self._toggle_reminder(rem, checked))
            rl.addWidget(chk)

            info = QVBoxLayout()
            info.setSpacing(2)

            title_style = f"font-size: 13px; font-weight: 600; color: {'#E2E8F0' if self._dark else '#1E293B'};"
            if r.done:
                title_style += f" color: {'#475569' if self._dark else '#94A3B8'}; text-decoration: line-through;"
            title_lbl = QLabel(r.title)
            title_lbl.setStyleSheet(title_style)
            title_lbl.setWordWrap(True)
            info.addWidget(title_lbl)

            if r.note:
                note_lbl = QLabel(r.note)
                note_lbl.setStyleSheet(
                    f"font-size: 11px; color: {'#64748B' if self._dark else '#9CA3AF'};"
                )
                note_lbl.setWordWrap(True)
                info.addWidget(note_lbl)

            rl.addLayout(info, 1)

            # Badge de data
            if is_daily and not r.done:
                date_badge = BadgeLabel("Diário", "#FEF3C7", "#D97706")
            elif is_daily and r.done:
                date_badge = BadgeLabel("Diário", "#F1F5F9", "#64748B")
            else:
                date_str = r.remind_at.strftime("%d/%m/%Y")
                if overdue:
                    date_badge = BadgeLabel(date_str, "#FEE2E2", "#DC2626")
                elif today_r:
                    date_badge = BadgeLabel("Hoje", "#FEF3C7", "#D97706")
                else:
                    date_badge = BadgeLabel(date_str, "#F1F5F9", "#64748B")
            rl.addWidget(date_badge)

            edit_btn = QPushButton()
            edit_btn.setObjectName("btn_icon")
            edit_btn.setIcon(qta.icon("fa6s.pen", color="#64748B"))
            edit_btn.setToolTip("Editar lembrete")
            edit_btn.setAutoDefault(False)
            edit_btn.clicked.connect(lambda _, rem=r: self._edit_reminder(rem))
            rl.addWidget(edit_btn)

            del_btn = QPushButton()
            del_btn.setObjectName("btn_icon_danger")
            del_btn.setIcon(qta.icon("fa6s.xmark", color="#EF4444"))
            del_btn.setAutoDefault(False)
            del_btn.clicked.connect(lambda _, rem=r: self._delete_reminder(rem))
            rl.addWidget(del_btn)

            self._reminders_layout.addWidget(row)

        self._reminders_layout.addStretch()

    def _add_reminder(self):

        dlg = QDialog(self)
        dlg.setWindowTitle("Novo Lembrete")
        dlg.setMinimumWidth(360)
        dlg.setModal(True)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)

        v.addWidget(QLabel("Título *"))
        inp_title = QLineEdit()
        inp_title.setPlaceholderText("ex: Ligar para o cliente")
        inp_title.setAutoFillBackground(False)
        v.addWidget(inp_title)

        chk_daily = QCheckBox("Repetir diariamente (sem data fixa)")
        v.addWidget(chk_daily)

        lbl_date = QLabel("Data do lembrete")
        v.addWidget(lbl_date)
        inp_date = QDateEdit()
        inp_date.setCalendarPopup(True)
        inp_date.setDisplayFormat("dd/MM/yyyy")
        inp_date.setDate(QDate.currentDate().addDays(1))
        v.addWidget(inp_date)

        def _toggle_daily(checked):
            lbl_date.setVisible(not checked)
            inp_date.setVisible(not checked)
        chk_daily.toggled.connect(_toggle_daily)

        v.addWidget(QLabel("Nota (opcional)"))
        inp_note = SpellCheckTextEdit()
        inp_note.setFixedHeight(64)
        inp_note.setPlaceholderText("Detalhes do lembrete...")
        v.addWidget(inp_note)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setAutoDefault(False)
        btn_cancel.clicked.connect(dlg.reject)
        btn_save = QPushButton("Salvar")
        btn_save.setObjectName("btn_primary")
        btn_save.setAutoDefault(False)
        btn_save.clicked.connect(dlg.accept)
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        v.addLayout(btns)

        if dlg.exec():
            title = inp_title.text().strip()
            if not title:
                return
            is_daily = chk_daily.isChecked()
            qd = inp_date.date()
            new_r = Reminder(
                id=0, demand_id=self.demand.id,
                title=title,
                remind_at=date.today() if is_daily else date(qd.year(), qd.month(), qd.day()),
                note=inp_note.toPlainText().strip(),
                daily=is_daily,
            )
            self._uc.save_reminder(new_r)
            self._render_reminders()

    def _edit_reminder(self, r):
        dlg = QDialog(self)
        dlg.setWindowTitle("Editar Lembrete")
        dlg.setMinimumWidth(360)
        dlg.setModal(True)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)

        v.addWidget(QLabel("Título *"))
        inp_title = QLineEdit(r.title)
        v.addWidget(inp_title)

        chk_daily = QCheckBox("Repetir diariamente (sem data fixa)")
        chk_daily.setChecked(getattr(r, 'daily', False))
        v.addWidget(chk_daily)

        lbl_date = QLabel("Data do lembrete")
        v.addWidget(lbl_date)
        inp_date = QDateEdit()
        inp_date.setCalendarPopup(True)
        inp_date.setDisplayFormat("dd/MM/yyyy")
        inp_date.setDate(QDate(r.remind_at.year, r.remind_at.month, r.remind_at.day))
        v.addWidget(inp_date)

        def _toggle_daily(checked):
            lbl_date.setVisible(not checked)
            inp_date.setVisible(not checked)
        chk_daily.toggled.connect(_toggle_daily)
        _toggle_daily(chk_daily.isChecked())

        v.addWidget(QLabel("Nota (opcional)"))
        inp_note = SpellCheckTextEdit()
        inp_note.setFixedHeight(64)
        inp_note.setPlaceholderText("Detalhes do lembrete...")
        inp_note.setPlainText(r.note or "")
        v.addWidget(inp_note)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setAutoDefault(False)
        btn_cancel.clicked.connect(dlg.reject)
        btn_save = QPushButton("Salvar")
        btn_save.setObjectName("btn_primary")
        btn_save.setAutoDefault(False)
        btn_save.clicked.connect(dlg.accept)
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        v.addLayout(btns)

        if dlg.exec():
            title = inp_title.text().strip()
            if not title:
                return
            is_daily = chk_daily.isChecked()
            qd = inp_date.date()
            r.title     = title
            r.note      = inp_note.toPlainText().strip()
            r.daily     = is_daily
            r.remind_at = date.today() if is_daily else date(qd.year(), qd.month(), qd.day())
            self._uc.save_reminder(r)
            self._render_reminders()
            self.calendar_refresh.emit()

    def _toggle_reminder(self, r, done: bool):
        r.done = done
        self._uc.save_reminder(r)
        self._render_reminders()
        self.calendar_refresh.emit()

    def _delete_reminder(self, r):
        self._uc.delete_reminder(r.id)
        self._render_reminders()
        self.calendar_refresh.emit()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _change_status(self, new_status: Status):
        self._uc.change_status(self.demand.id, new_status)
        self.demand = self._uc.get(self.demand.id)
        self._update_status_buttons()
        self.demand_updated.emit(self.demand)
        self.refresh_demand()

    def _add_comment(self):
        text = self.comment_input.toPlainText().strip()
        if not text:
            return
        ct = self.comment_type_combo.currentData()
        self._uc.add_comment(self.demand.id, text, ct)
        self.demand = self._uc.get(self.demand.id)
        self.comment_input.clear()
        self._render_comments()
        self.demand_updated.emit(self.demand)
        self.refresh_demand()

    def _add_attachment(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Arquivo", "",
            "Todos os Arquivos (*);;PDF (*.pdf);;Excel (*.xlsx);;Word (*.docx);;Imagens (*.png *.jpg)"
        )
        if path:
            filename = os.path.basename(path)
            ext = os.path.splitext(filename)[1].lower()
            self._uc.add_attachment(self.demand.id, filename, path, ext)
            self.demand = self._uc.get(self.demand.id)
            self._render_files()
            self.demand_updated.emit(self.demand)
            self.refresh_demand()

    def _on_edit(self):
        self.edit_requested.emit(self.demand)

    def _update_servicenow_button(self):
        number = _servicenow_number(self.demand.title)
        self._sn_btn.setVisible(number is not None)
        if number:
            self._sn_btn.setToolTip(f"Abrir {number} no ServiceNow")

    def _open_servicenow(self):
        number = _servicenow_number(self.demand.title)
        if number:
            QDesktopServices.openUrl(QUrl(_servicenow_url(number)))

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())


    def set_dark(self, dark: bool):
        self._dark = dark
        if dark:
            self.setStyleSheet("""
                QDialog                    { background: #0F172A; }
                QTabWidget::pane           { background: #0F172A; border: none; }
                QTabBar                    { background: #1E293B; }
                QTabBar::tab               {
                    background: #1E293B; color: #94A3B8; border: none;
                    border-bottom: 2px solid transparent;
                    padding: 8px 16px; margin-right: 2px;
                }
                QTabBar::tab:selected      { background: #0F172A; color: #E2E8F0; border-bottom: 2px solid #3B82F6; }
                QTabBar::tab:hover         { color: #CBD5E1; }
                QScrollArea                { background: #0F172A; border: none; }
                QScrollArea > QWidget > QWidget { background: #0F172A; }
                QScrollBar:vertical        { background: #1E293B; width: 6px; border: none; }
                QScrollBar::handle:vertical { background: #475569; border-radius: 3px; min-height: 20px; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
                QTableWidget               {
                    background: #0F172A; color: #E2E8F0;
                    gridline-color: #1E293B; alternate-background-color: #1E293B; border: none;
                }
                QTableWidget::item:selected { background: #1E3A5F; color: #E2E8F0; }
                QHeaderView::section       {
                    background: #1E293B; color: #94A3B8;
                    border: none; border-right: 1px solid #334155;
                    padding: 6px 8px; font-weight: 600;
                }
                QComboBox                  {
                    background: #1E293B; color: #E2E8F0;
                    border: 1px solid #334155; border-radius: 8px; padding: 7px 11px;
                }
                QComboBox::drop-down       { border: none; }
                QComboBox QAbstractItemView {
                    background: #1E293B; color: #E2E8F0;
                    selection-background-color: #2563EB;
                    border: 1px solid #334155; outline: none;
                }
                QTextEdit                  {
                    background: #1E293B; color: #E2E8F0;
                    border: 1px solid #334155; border-radius: 8px; padding: 7px 11px;
                }
                QCheckBox                  { color: #E2E8F0; background: transparent; }
                QCheckBox::indicator       {
                    width: 16px; height: 16px;
                    border: 1px solid #475569; border-radius: 3px; background: #1E293B;
                }
                QCheckBox::indicator:checked { background: #3B82F6; border-color: #3B82F6; }
                QLabel                     { color: #E2E8F0; background: transparent; }
                QLabel#label_section       { color: #94A3B8; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
                QLabel#label_muted         { color: #64748B; font-size: 11px; }
                QDateTimeEdit              {
                    background: #0F172A; color: #E2E8F0;
                    border: 1px solid #334155; border-radius: 8px; padding: 7px 11px;
                }
                QDateTimeEdit:focus        { border-color: #3B82F6; }
                QDateTimeEdit::drop-down   { border: none; }
            """)
        else:
            self.setStyleSheet("")
        self._header_frame.setStyleSheet(
            f"QFrame {{ background: {'#1E293B' if dark else '#FFFFFF'}; "
            f"border-bottom: 1px solid {'#334155' if dark else '#E2E8F0'}; }}"
        )
        self.title_lbl.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {'#E2E8F0' if dark else '#0F172A'};"
        )
        self.desc_lbl.setStyleSheet(
            f"color: {'#94A3B8' if dark else '#64748B'}; font-size: 13px;"
        )
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: none; margin-top: 0; "
            f"background: {'#0F172A' if dark else 'transparent'}; }}"
        )
        if hasattr(self, '_wl_summary_frame'):
            self._wl_summary_frame.setStyleSheet(
                f"QFrame {{ background: {'#0F172A' if dark else '#F8FAFC'}; "
                f"border-bottom: 1px solid {'#334155' if dark else '#E2E8F0'}; }}"
            )
            for lbl in self._wl_stat_key_labels.values():
                lbl.setStyleSheet(
                    f"font-size: 10px; font-weight: 700; "
                    f"color: {'#64748B' if dark else '#9CA3AF'};"
                )
        if hasattr(self, '_wl_footer_frame'):
            self._wl_footer_frame.setStyleSheet(
                f"QFrame {{ background: {'#1E293B' if dark else '#F8FAFC'}; "
                f"border-top: 1px solid {'#334155' if dark else '#E2E8F0'}; }}"
            )
        self._update_status_buttons()
        self._render_history()
        self._render_comments()
        self._render_reminders()
        self._render_milestones()
        if hasattr(self, '_note_pad') and self._note_pad:
            self._note_pad.set_dark(dark)
        if hasattr(self, '_file_manager') and self._file_manager:
            self._file_manager.refresh_dark(dark)
    '''
    def refresh_demand(self, demand=None):
        """
        Recarrega a demanda do backend e atualiza a interface inteira.
        Pode receber um Demand novo ou buscar novamente no use case.
        """
        if demand is not None:
            self.demand = demand
        else:
            self.demand = self._uc.get(self.demand.id)

        # Cabeçalho
        self.setWindowTitle(self.demand.title)
        if hasattr(self, "self.title_lbl"):
            self.self.title_lbl.setText(self.demand.title)
        if hasattr(self, "self.desc_lbl"):
            self.self.desc_lbl.setText(self.demand.description)

        # Badges do topo
        if hasattr(self, "self.badges_row"):
            self._clear_layout(self.self.badges_row)
            self.self.badges_row.addWidget(status_badge(self.demand.status))
            self.self.badges_row.addWidget(priority_badge(self.demand.priority))
            if self.demand.is_overdue:
                self.self.badges_row.addWidget(BadgeLabel("Atrasada", "#FEE2E2", "#DC2626"))
            if self.demand.is_inactive:
                self.self.badges_row.addWidget(
                    BadgeLabel(f"Inativa {self.demand.days_since_activity}d", "#FEF3C7", "#D97706")
                )
            self.self.badges_row.addStretch()

        # Status buttons
        self._update_status_buttons()

        # Comentários / histórico / arquivos
        self._render_comments()
        self._render_history()

        if hasattr(self, "_file_manager") and self._file_manager:
            if hasattr(self._file_manager, "refresh"):
                self._file_manager.refresh()
            elif hasattr(self._file_manager, "reload"):
                self._file_manager.reload()

        # Títulos das abas com contagem atualizada
        if hasattr(self, "tabs"):
            self.tabs.setTabText(self.comments_tab_index, f"Comentários ({len(self.demand.comments)})")
            self.tabs.setTabText(self.history_tab_index, f"Histórico ({len(self.demand.history)})")
            self.tabs.setTabText(self.files_tab_index, f"Arquivos ({len(self.demand.attachments)})")

        self.demand_updated.emit(self.demand)
    '''

    def refresh_demand(self, demand=None):
        if demand is not None:
            self.demand = demand
        else:
            self.demand = self._uc.get(self.demand.id)

        self.setWindowTitle(self.demand.title)
        if hasattr(self, "title_lbl"):
            self.title_lbl.setText(self.demand.title)
        if hasattr(self, "desc_lbl"):
            self.desc_lbl.setText(self.demand.description)
        if hasattr(self, "_sn_btn"):
            self._update_servicenow_button()

        # Atualiza só os badges dinâmicos — botões fixos nunca são tocados
        if hasattr(self, "_dynamic_badges_layout"):
            self._clear_layout(self._dynamic_badges_layout)
            self._dynamic_badges_layout.addWidget(status_badge(self.demand.status))
            self._dynamic_badges_layout.addWidget(priority_badge(self.demand.priority))
            if self.demand.is_overdue:
                self._dynamic_badges_layout.addWidget(BadgeLabel("Atrasada", "#FEE2E2", "#DC2626"))
            if self.demand.is_inactive:
                self._dynamic_badges_layout.addWidget(
                    BadgeLabel(f"Inativa {self.demand.days_since_activity}d", "#FEF3C7", "#D97706")
                )

        self._update_status_buttons()
        self._render_history()
        self._wl_refresh()

        if hasattr(self, "_file_manager") and self._file_manager:
            # Propaga o título atual antes de atualizar — senão o file manager
            # continua usando o título antigo (snapshot do momento da abertura)
            # e acaba recriando a pasta antiga ao mover/criar arquivos depois
            # de uma renomeação, em vez de usar a pasta já renomeada.
            if hasattr(self._file_manager, "demand_title"):
                self._file_manager.demand_title = self.demand.title
            if hasattr(self._file_manager, "refresh"):
                self._file_manager.refresh()
            elif hasattr(self._file_manager, "reload"):
                self._file_manager.reload()


        self.demand_updated.emit(self.demand)

    def _on_delete(self):
        from PyQt6.QtWidgets import QMessageBox
        r = QMessageBox.question(
            self, "Confirmar Exclusão",
            f"Remover definitivamente a demanda:\n\"{self.demand.title}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if r == QMessageBox.StandardButton.Yes:
            self.demand_deleted.emit(self.demand.id)
            self.accept()

    def _render_milestones(self):
        while self._milestones_layout.count():
            item = self._milestones_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        milestones = self._uc.get_milestones(self.demand.id)
        for m in milestones:
            row = QFrame()
            row.setStyleSheet(
                f"background: {'#0F172A' if self._dark else '#F8FAFC'}; border-radius: 8px;"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 8, 12, 8)
            rl.setSpacing(8)

            # Checkbox de conclusão
            chk = QCheckBox()
            chk.setChecked(m.done)
            chk.toggled.connect(
                lambda checked, ms=m: self._toggle_milestone(ms, checked)
            )
            rl.addWidget(chk)

            # Área de texto
            text_layout = QVBoxLayout()
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(2)

            title_style = f"font-size: 13px; font-weight: 600; color: {'#E2E8F0' if self._dark else '#1E293B'};"
            if m.done:
                title_style += (
                    f" color: {'#475569' if self._dark else '#94A3B8'};"
                    " text-decoration: line-through;"
                )

            title_lbl = QLabel(m.title)
            title_lbl.setStyleSheet(title_style)
            title_lbl.setWordWrap(True)
            text_layout.addWidget(title_lbl)

            # Dependência
            if m.depends_on_id:
                dep = next(
                    (x for x in milestones if x.id == m.depends_on_id),
                    None
                )

                if dep:
                    dep_lbl = QLabel(f"→ após {dep.title}")
                    dep_lbl.setStyleSheet(
                        f"""
                        font-size: 11px;
                        color: {'#64748B' if self._dark else '#9CA3AF'};
                        """
                    )
                    dep_lbl.setWordWrap(True)
                    text_layout.addWidget(dep_lbl)

            rl.addLayout(text_layout, 1)

            # Data limite
            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("dd/MM/yyyy")
            date_edit.setFixedWidth(115)
            date_edit.setDate(
                QDate(
                    m.deadline.year,
                    m.deadline.month,
                    m.deadline.day
                )
            )

            # editingFinished (não dateChanged) — dateChanged dispara a cada
            # sub-campo editado (dia, depois mês, depois ano), gerando uma
            # alteração/histórico por sub-campo em vez de uma só ao terminar.
            date_edit.editingFinished.connect(
                lambda ms=m, de=date_edit: self._change_milestone_date(
                    ms,
                    date(de.date().year(), de.date().month(), de.date().day())
                )
            )

            rl.addWidget(date_edit)

            # Botão excluir
            del_btn = QPushButton()
            del_btn.setIcon(qta.icon("fa6s.trash", color="white"))
            del_btn.setFixedSize(28, 28)
            del_btn.setIconSize(QSize(16, 16))
            del_btn.setStyleSheet("""
            QPushButton {
                background: #EF4444;
                border: none;
                border-radius: 14px;
                padding: 0px;
            }
            QPushButton:hover {
                background: #DC2626;
            }
            """)

            del_btn.clicked.connect(
                lambda _, ms=m: self._delete_milestone(ms)
            )
            rl.addWidget(del_btn)


            self._milestones_layout.addWidget(row)

    def _toggle_milestone(self, m, done):
        self._uc.change_milestone_status(m.id, done)
        self._render_milestones()
        self.calendar_refresh.emit()
        self.refresh_demand()


    def _change_milestone_date(self, m, new_deadline):
        try:
            self._uc.change_milestone_deadline(m.id, new_deadline)
        except ValueError as exc:
            QMessageBox.warning(self, "Data inválida", str(exc))
        self._render_milestones()
        self.calendar_refresh.emit()
        self.refresh_demand()


    def _delete_milestone(self, m):
        self._uc.delete_milestone(m.id)
        self._render_milestones()
        self.calendar_refresh.emit()
        self.refresh_demand()


    def _add_milestone(self):

        dlg = QDialog(self)
        dlg.setWindowTitle("Novo Milestone")
        dlg.setMinimumWidth(400)

        layout = QVBoxLayout(dlg)

        # Nome
        layout.addWidget(QLabel("Nome"))
        txt_name = QLineEdit()
        layout.addWidget(txt_name)

        # Data
        layout.addWidget(QLabel("Prazo"))

        milestones = self._uc.get_milestones(self.demand.id)

        last_date = max(
            (ms.deadline for ms in milestones),
            default=self.demand.deadline
        )

        dt_deadline = QDateEdit()
        dt_deadline.setCalendarPopup(True)
        dt_deadline.setDate(
            QDate(
                last_date.year,
                last_date.month,
                last_date.day
            )
        )
        layout.addWidget(dt_deadline)

        # Dependência
        layout.addWidget(QLabel("Depende de"))

        cmb_dependency = QComboBox()
        cmb_dependency.addItem("Nenhuma", None)

        for ms in milestones:
            cmb_dependency.addItem(ms.title, ms.id)

        layout.addWidget(cmb_dependency)

        # Botões
        buttons = QHBoxLayout()

        btn_cancel = QPushButton("Cancelar")
        btn_ok = QPushButton("Salvar")

        buttons.addStretch()
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_ok)

        layout.addLayout(buttons)

        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)

        if dlg.exec() == QDialog.DialogCode.Accepted:

            title = txt_name.text().strip()

            if not title:
                return

            deadline = dt_deadline.date().toPyDate()
            depends_on_id = cmb_dependency.currentData()

            new_m = Milestone(
                id=0,
                demand_id=self.demand.id,
                title=title,
                deadline=deadline,
                depends_on_id=depends_on_id
            )

            #self._uc.save_milestone(new_m)
            self._uc.create_milestone(new_m)

        self._render_milestones()
        self.refresh_demand()


    def _build_worklogs_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sumário ───────────────────────────────────────────────────────────
        summary = QFrame()
        self._wl_summary_frame = summary
        summary.setStyleSheet(
            f"QFrame {{ background: {'#0F172A' if self._dark else '#F8FAFC'}; "
            f"border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'}; }}"
        )
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(24, 10, 24, 10)
        sl.setSpacing(32)
        self._wl_stats: dict = {}
        self._wl_stat_key_labels: dict = {}
        for key, label in [
            ("total",     "Total registrado"),
            ("sessions",  "Sessões"),
            ("estimated", "Estimado"),
            ("progress",  "Progresso"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)
            k = QLabel(label.upper())
            k.setStyleSheet(
                f"font-size: 10px; font-weight: 700; "
                f"color: {'#64748B' if self._dark else '#9CA3AF'};"
            )
            self._wl_stat_key_labels[key] = k
            v = QLabel("—")
            v.setStyleSheet("font-size: 16px; font-weight: 700;")
            col.addWidget(k)
            col.addWidget(v)
            sl.addLayout(col)
            self._wl_stats[key] = v
        sl.addStretch()
        root.addWidget(summary)

        # ── Tabs internas: por sessão / por dia ───────────────────────────────
        inner_tabs = QTabWidget()
        inner_tabs.setStyleSheet("QTabWidget::pane { border: none; }")

        # Tabela de sessões
        session_w = QWidget()
        sv = QVBoxLayout(session_w)
        sv.setContentsMargins(0, 0, 0, 0)
        self._wl_table = QTableWidget(0, 6)
        self._wl_table.setHorizontalHeaderLabels(
            ["Data", "Início", "Fim", "Duração", "Nota", ""]
        )
        self._wl_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._wl_table.setColumnWidth(5, 50)
        self._wl_table.setAlternatingRowColors(True)
        self._wl_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._wl_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._wl_table.setToolTip("Duplo clique numa linha para editar o apontamento")
        self._wl_table.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wl_table.itemDoubleClicked.connect(self._wl_on_item_double_clicked)
        sv.addWidget(self._wl_table)
        _idx = inner_tabs.addTab(session_w, "Sessões")
        inner_tabs.setTabIcon(_idx, qta.icon("fa6s.list", color="#64748B"))

        # Tabela por dia
        day_w = QWidget()
        dv = QVBoxLayout(day_w)
        dv.setContentsMargins(0, 0, 0, 0)
        self._wl_day_table = QTableWidget(0, 3)
        self._wl_day_table.setHorizontalHeaderLabels(["Data", "Sessões", "Total"])
        self._wl_day_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._wl_day_table.setAlternatingRowColors(True)
        self._wl_day_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        dv.addWidget(self._wl_day_table)
        _idx = inner_tabs.addTab(day_w, "Por Dia")
        inner_tabs.setTabIcon(_idx, qta.icon("fa6s.calendar-days", color="#64748B"))

        root.addWidget(inner_tabs, 1)

        # ── Adicionar apontamento manual ──────────────────────────────────────
        footer = QFrame()
        self._wl_footer_frame = footer
        footer.setStyleSheet(
            f"QFrame {{ background: {'#1E293B' if self._dark else '#F8FAFC'}; "
            f"border-top: 1px solid {'#334155' if self._dark else '#E2E8F0'}; }}"
        )
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(8)

        sec_lbl = QLabel("NOVO APONTAMENTO")
        sec_lbl.setObjectName("label_section")
        fl.addWidget(sec_lbl)

        # Linha 1: datas lado a lado com label acima
        row1 = QHBoxLayout()
        row1.setSpacing(16)

        start_col = QVBoxLayout()
        start_col.setSpacing(3)
        _l = QLabel("Início"); _l.setObjectName("label_muted"); start_col.addWidget(_l)
        self._wl_inp_start = QDateTimeEdit()
        self._wl_inp_start.setDisplayFormat("dd/MM HH:mm")
        self._wl_inp_start.setDateTime(QDateTime.currentDateTime().addSecs(-3600))
        self._wl_inp_start.setCalendarPopup(True)
        self._wl_inp_start.setMinimumWidth(130)
        start_col.addWidget(self._wl_inp_start)
        row1.addLayout(start_col)

        end_col = QVBoxLayout()
        end_col.setSpacing(3)
        _l = QLabel("Fim"); _l.setObjectName("label_muted"); end_col.addWidget(_l)
        self._wl_inp_end = QDateTimeEdit()
        self._wl_inp_end.setDisplayFormat("dd/MM HH:mm")
        self._wl_inp_end.setDateTime(QDateTime.currentDateTime())
        self._wl_inp_end.setCalendarPopup(True)
        self._wl_inp_end.setMinimumWidth(130)
        end_col.addWidget(self._wl_inp_end)
        row1.addLayout(end_col)

        row1.addStretch()
        fl.addLayout(row1)

        # Linha 2: nota + botão
        row2 = QHBoxLayout()
        row2.setSpacing(12)

        note_col = QVBoxLayout()
        note_col.setSpacing(3)
        _l = QLabel("Nota"); _l.setObjectName("label_muted"); note_col.addWidget(_l)
        self._wl_inp_note = SpellCheckTextEdit()
        self._wl_inp_note.setPlaceholderText("Opcional...")
        self._wl_inp_note.setFixedHeight(36)
        note_col.addWidget(self._wl_inp_note)
        row2.addLayout(note_col, 1)

        add_btn = QPushButton("  Adicionar apontamento")
        add_btn.setIcon(qta.icon("fa6s.plus", color="white"))
        add_btn.setObjectName("btn_primary")
        add_btn.setAutoDefault(False)
        add_btn.clicked.connect(self._wl_add_manual)
        row2.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignBottom)
        fl.addLayout(row2)

        root.addWidget(footer)

        # Carrega dados iniciais
        self._wl_refresh()
        return w
    

    def _wl_refresh(self):

        stats = self._uc.get_worklog_stats(self.demand.id)
        logs  = self._uc.get_work_logs(self.demand.id)
        self._wl_logs_cache = logs

        # Sumário
        total_h = stats["total_hours"]
        est_h   = self.demand.estimated_hours
        pct     = f"{total_h / est_h * 100:.0f}%" if est_h > 0 else "—"
        h, m = int(total_h), int((total_h % 1) * 60)
        self._wl_stats["total"].setText(f"{h}h{m:02d}" if h else f"{m}min")
        self._wl_stats["sessions"].setText(str(stats["sessions"]))
        self._wl_stats["estimated"].setText(f"{est_h:.0f}h")
        self._wl_stats["progress"].setText(pct)

        # Tabela sessões
        self._wl_table.setRowCount(0)
        for wl in logs:
            row = self._wl_table.rowCount()
            self._wl_table.insertRow(row)
            self._wl_table.setItem(row, 0, QTableWidgetItem(wl.started_at.strftime("%d/%m/%Y")))
            self._wl_table.setItem(row, 1, QTableWidgetItem(wl.started_at.strftime("%H:%M")))
            self._wl_table.setItem(row, 2, QTableWidgetItem(
                wl.ended_at.strftime("%H:%M") if wl.ended_at else "—"
            ))
            dur = QTableWidgetItem(wl.duration_display)
            if wl.manual:
                dur.setForeground(QColor("#A78BFA"))
            self._wl_table.setItem(row, 3, dur)
            self._wl_table.setItem(row, 4, QTableWidgetItem(wl.note or ""))

            del_btn = QPushButton()
            del_btn.setIcon(qta.icon("fa6s.trash", color="#EF4444"))
            del_btn.setAutoDefault(False)
            del_btn.setStyleSheet("border: none; background: transparent; padding: 2px 6px;")
            del_btn.clicked.connect(lambda _, w=wl: self._wl_delete(w))
            self._wl_table.setCellWidget(row, 5, del_btn)

        # Tabela por dia
        self._wl_day_table.setRowCount(0)
        for day_str, info in stats.get("by_day", {}).items():
            row = self._wl_day_table.rowCount()
            self._wl_day_table.insertRow(row)
            dt = datetime.fromisoformat(day_str + "T00:00:00")
            self._wl_day_table.setItem(row, 0, QTableWidgetItem(dt.strftime("%d/%m/%Y (%A)")))
            self._wl_day_table.setItem(row, 1, QTableWidgetItem(str(len(info["sessions"]))))
            secs = info["seconds"]
            h2, m2 = secs // 3600, (secs % 3600) // 60
            self._wl_day_table.setItem(row, 2, QTableWidgetItem(
                f"{h2}h{m2:02d}" if h2 else f"{m2}min"
            ))


    def _wl_add_manual(self):
        qs = self._wl_inp_start.dateTime()
        qe = self._wl_inp_end.dateTime()
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
            note=self._wl_inp_note.text().strip(),
            manual=True,
        )
        self._wl_inp_note.clear()
        self._wl_refresh()
        self.demand_updated.emit(self.demand)

    def _wl_delete(self, wl):
        from PyQt6.QtWidgets import QMessageBox
        r = QMessageBox.question(
            self, "Confirmar",
            f"Excluir apontamento de {wl.duration_display} em {wl.started_at.strftime('%d/%m/%Y %H:%M')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if r == QMessageBox.StandardButton.Yes:
            self._uc.delete_work_log(wl.id, self.demand.id)
            self._wl_refresh()
            self.demand_updated.emit(self.demand)

    def _wl_on_item_double_clicked(self, item):
        row = item.row()
        if 0 <= row < len(self._wl_logs_cache):
            self._wl_edit_log(self._wl_logs_cache[row])

    def _wl_edit_log(self, wl):
        dlg = EditWorkLogDialog(self._uc, wl, dark=self._dark, parent=self)
        dlg.saved.connect(self._wl_refresh)
        dlg.saved.connect(lambda: self.demand_updated.emit(self.demand))
        dlg.deleted.connect(self._wl_refresh)
        dlg.deleted.connect(lambda: self.demand_updated.emit(self.demand))
        dlg.exec()

    def _get_tab_index(self, text_prefix: str) -> int:
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).startswith(text_prefix.split(" (")[0]):
                return i
        return -1               