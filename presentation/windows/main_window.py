"""
DemandFlow - Janela Principal
Orquestra todas as views: Dashboard, Lista, Kanban, Calendário, Relatórios.
"""
import sys
import ctypes
import ctypes.wintypes
from datetime import date, datetime
import qtawesome as qta
from itertools import groupby
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSplitter, QLineEdit, QComboBox, QStatusBar,
    QSizePolicy, QApplication, QTextEdit,
    QDialog, QTabWidget, QCalendarWidget, QMessageBox,
)
from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal, QDate, QSettings
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QTextCharFormat, QPainter, QPen, QCursor

from core.domain.entities import (
    Demand, Status, Priority, CATEGORIES, CommentType
)
from core.domain.entities import Reminder
from core.usecases.demand_usecases import DemandUseCases
from presentation.widgets.common_widgets import (
    DemandPreviewPanel, MilestoneCalendarItem, ReminderCalendarItem, StatCard, MiniBarChart, DemandListItem, KanbanCard, BadgeLabel,
    status_badge, priority_badge, _highlight_html, highlight_matches_in_text_edit
)
from core.domain.text_match import fuzzy_word_match
from presentation.styles.stylesheet import get_stylesheet
from presentation.dialogs.demand_form import DemandFormDialog
from presentation.dialogs.demand_detail import DemandDetailDialog
from presentation.dialogs.assistant_dialog import AssistantDialog
from presentation.widgets.calendar_delegate import IconCalendarWidget
from presentation.dialogs.worklog_dialog import WorkLogDialog
from presentation.dialogs.general_worklog_dialog import GeneralWorkLogDialog, EditWorkLogDialog
from presentation.widgets.worklog_gantt import WorklogGanttWidget
from presentation.widgets.capacity_grid import CapacityGridWidget
from presentation.widgets.spell_check import SpellCheckLineEdit
from infrastructure.services.updater import (
    UpdateChecker, UpdateDownloader, apply_update,
    save_pending_changelog, pop_pending_changelog,
)
from presentation.dialogs.whats_new_dialog import WhatsNewDialog
from version import __version__

_MONTHS_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
_WEEKDAYS_PT = [
    "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
    "Sexta-feira", "Sábado", "Domingo",
]


def _format_date_pt(d: date, with_weekday: bool = True) -> str:
    """Formata data em português, sem depender do locale do sistema operacional."""
    base = f"{d.day} de {_MONTHS_PT[d.month - 1]} de {d.year}"
    return f"{_WEEKDAYS_PT[d.weekday()]}, {base}" if with_weekday else base


class _SnapOverlay(QWidget):
    """Ghost semi-transparente que mostra onde a janela vai encaixar ao soltar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(59, 130, 246, 38))
        painter.setPen(QPen(QColor(59, 130, 246, 170), 2))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 8, 8)


class _DemandFrame(QFrame):
    """Janela de demanda flutuante dentro de content_area, com arrastar, redimensionar, snap e maximizar."""
    closed    = pyqtSignal(int)
    minimized = pyqtSignal(int)

    _M = 4   # largura da zona de redimensionamento (px)

    def __init__(self, demand_id: int, title: str, dlg, dark: bool, parent=None):
        super().__init__(parent)
        self.demand_id     = demand_id
        self._dlg          = dlg
        self._title        = title
        self._dark         = dark
        self._drag_pos     = None
        self._resize_dir   = 0          # 0=none 1=W 2=E 3=S 4=SW 5=SE
        self._resize_start = None       # (globalQPoint, x, y, w, h)
        self._maximized    = False
        self._pre_max      = None       # (x, y, w, h) antes de maximizar
        self._original_geom = None      # (x, y, w, h) na primeira exibição
        self._snap_rect    = None       # snap target durante arraste
        self._snap_overlay = None       # _SnapOverlay lazy-criado
        self._cursor_override = False   # se há um override cursor global ativo

        self._cursor_check_timer = QTimer(self)
        self._cursor_check_timer.setInterval(120)
        self._cursor_check_timer.timeout.connect(self._check_cursor_still_valid)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("demand_frame")
        self.setMouseTracking(True)

        bg  = "#1E293B" if dark else "#FFFFFF"
        brd = "#334155" if dark else "#CBD5E1"
        self.setStyleSheet(
            f"QFrame#demand_frame {{ background: {bg}; border: 1px solid {brd}; }}"
        )

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(self._M, 0, self._M, self._M)
        vbox.setSpacing(0)

        # ── Barra de título ──────────────────────────────────────────────
        bar_bg  = "#0F172A" if dark else "#F1F5F9"
        bar_brd = "#334155" if dark else "#E2E8F0"
        self._bar = QFrame()
        self._bar.setObjectName("df_titlebar")
        self._bar.setFixedHeight(36)
        self._bar.setStyleSheet(
            f"QFrame#df_titlebar {{ background: {bar_bg};"
            f" border-bottom: 1px solid {bar_brd}; }}"
        )
        bh = QHBoxLayout(self._bar)
        bh.setContentsMargins(12, 0, 8, 0)
        bh.setSpacing(4)

        ico = QLabel("⚡")
        ico.setStyleSheet("font-size: 12px; background: transparent; border: none;")
        bh.addWidget(ico)

        self._title_bar_lbl = QLabel(title)
        self._title_bar_lbl.setStyleSheet(
            f"color: {'#E2E8F0' if dark else '#1E293B'}; font-size: 13px; font-weight: 600;"
            " background: transparent; border: none;"
        )
        bh.addWidget(self._title_bar_lbl, 1)

        _btn_ss = (
            "QPushButton { background: transparent; border: none; border-radius: 12px; }"
            "QPushButton:hover { background: #475569; }"
        )
        for icon_name, tip, handler in [
            ("fa6s.minus",  "Minimizar",  lambda: self.minimized.emit(self.demand_id)),
            ("fa6s.expand", "Maximizar",  self._toggle_maximize),
            ("fa6s.xmark",  "Fechar",     self.close),
        ]:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.setIcon(qta.icon(icon_name, color="#94A3B8"))
            btn.setToolTip(tip)
            btn.setStyleSheet(_btn_ss)
            btn.clicked.connect(handler)
            bh.addWidget(btn)
            if icon_name == "fa6s.expand":
                self._max_btn = btn

        self._bar.mousePressEvent       = self._bar_press
        self._bar.mouseMoveEvent        = self._bar_move
        self._bar.mouseReleaseEvent     = self._bar_release
        self._bar.mouseDoubleClickEvent = lambda _: self._titlebar_double_click()
        vbox.addWidget(self._bar)

        # ── Diálogo embutido ─────────────────────────────────────────────
        dlg.setParent(self)
        dlg.setWindowFlags(Qt.WindowType.Widget)
        dlg.setMinimumSize(420, 300)
        dlg.setCursor(Qt.CursorShape.ArrowCursor)  # impede herança do cursor de redimensionamento do frame
        dlg.show()
        vbox.addWidget(dlg, 1)
        dlg.finished.connect(lambda _: self.close())

    # ── Maximizar / restaurar ─────────────────────────────────────────────
    def _toggle_maximize(self):
        if self._maximized:
            if self._pre_max:
                self.setGeometry(*self._pre_max)
            self._maximized = False
            self._max_btn.setIcon(qta.icon("fa6s.expand", color="#94A3B8"))
            self._max_btn.setToolTip("Maximizar")
        else:
            g = self.geometry()
            self._pre_max = (g.x(), g.y(), g.width(), g.height())
            if self.parent():
                r = self.parent().rect()
                self.setGeometry(r.x(), r.y(), r.width(), r.height())
            self._maximized = True
            self._max_btn.setIcon(qta.icon("fa6s.compress", color="#94A3B8"))
            self._max_btn.setToolTip("Restaurar")

    def _restore_original(self):
        if self._original_geom:
            self.setGeometry(*self._original_geom)
            self._maximized = False
            self._max_btn.setIcon(qta.icon("fa6s.expand", color="#94A3B8"))
            self._max_btn.setToolTip("Maximizar")

    def _titlebar_double_click(self):
        """Duplo-clique na barra: expande se estiver no tamanho normal; se já
        estiver expandida, volta pro tamanho ORIGINAL (não pro tamanho de
        antes de maximizar — diferente do botão de maximizar/restaurar, que
        guarda e restaura a posição/tamanho anteriores)."""
        if self._maximized:
            self._restore_original()
        else:
            self._toggle_maximize()

    # ── Eventos de mouse ─────────────────────────────────────────────────
    def mousePressEvent(self, event):
        self.raise_()
        d = self._resize_zone(event.pos())
        if d:
            g = self.geometry()
            self._resize_dir   = d
            self._resize_start = (
                event.globalPosition().toPoint(),
                g.x(), g.y(), g.width(), g.height(),
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_start:
            gp = event.globalPosition().toPoint()
            dx = gp.x() - self._resize_start[0].x()
            dy = gp.y() - self._resize_start[0].y()
            ox, oy, ow, oh = self._resize_start[1:]
            nx, ny, nw, nh = ox, oy, ow, oh
            d = self._resize_dir
            if d in (1, 4):    # W / SW — move left edge
                nx = ox + dx
                nw = ow - dx
            if d in (2, 5):    # E / SE — move right edge
                nw = ow + dx
            if d in (3, 4, 5): # S / SW / SE — move bottom edge
                nh = oh + dy
            if nw >= 520 and nh >= 400:
                self.setGeometry(nx, ny, nw, nh)
            event.accept()
            return
        self._set_resize_cursor(event.pos())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if not self._resize_start:
            self._clear_cursor_override()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resize_start = None
        self._resize_dir   = 0
        self._clear_cursor_override()
        super().mouseReleaseEvent(event)

    def _resize_zone(self, pos):
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        m = self._M
        bl = x <= m and y >= h - m
        br = x >= w - m and y >= h - m
        if bl: return 4
        if br: return 5
        if x <= m:     return 1
        if x >= w - m: return 2
        if y >= h - m: return 3
        return 0

    # Cursor de redimensionamento usa override global (QApplication), não
    # setCursor por widget — evita "vazamento" por herança para irmãos/filhos
    # (ex.: topbar) quando o mouse passa pela borda e sai do frame.
    def _set_resize_cursor(self, pos):
        _C = Qt.CursorShape
        cursors = {
            1: _C.SizeHorCursor,
            2: _C.SizeHorCursor,
            3: _C.SizeVerCursor,
            4: _C.SizeBDiagCursor,
            5: _C.SizeFDiagCursor,
        }
        d = self._resize_zone(pos)
        if d:
            cursor = cursors[d]
            if self._cursor_override:
                QApplication.changeOverrideCursor(cursor)
            else:
                QApplication.setOverrideCursor(cursor)
                self._cursor_override = True
                self._cursor_check_timer.start()
        else:
            self._clear_cursor_override()

    def _clear_cursor_override(self):
        if self._cursor_override:
            QApplication.restoreOverrideCursor()
            self._cursor_override = False
        self._cursor_check_timer.stop()

    def _check_cursor_still_valid(self):
        """Rede de segurança: confirma que o mouse ainda está na zona de
        resize. Cobre casos em que o evento de saída não chega a tempo
        (comum em cantos, onde a zona é pequena e o mouse 'salta' para fora)."""
        if self._resize_start:
            return  # redimensionando ativamente — não interfere
        global_pos = QCursor.pos()
        local_pos  = self.mapFromGlobal(global_pos)
        if not self.rect().contains(local_pos) or self._resize_zone(local_pos) == 0:
            self._clear_cursor_override()

    # ── Arrastar pela barra ───────────────────────────────────────────────
    def _bar_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            self._clip_cursor_to_parent()

    def _bar_move(self, event):
        if self._drag_pos and (event.buttons() & Qt.MouseButton.LeftButton):
            if self._maximized:
                return
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)
            self._update_snap(event.globalPosition().toPoint())

    def _bar_release(self, _):
        self._drag_pos = None
        self._unclip_cursor()
        if self._snap_rect:
            self.setGeometry(*self._snap_rect)
            self._maximized = False
            self._snap_rect = None
        ov = self._snap_overlay
        if ov:
            ov.hide()

    def _clip_cursor_to_parent(self):
        p = self.parent()
        if not p:
            return
        tl = p.mapToGlobal(p.rect().topLeft())
        br = p.mapToGlobal(p.rect().bottomRight())
        rect = ctypes.wintypes.RECT(tl.x(), tl.y(), br.x(), br.y())
        ctypes.windll.user32.ClipCursor(ctypes.byref(rect))

    def _unclip_cursor(self):
        ctypes.windll.user32.ClipCursor(None)

    def closeEvent(self, event):
        self._unclip_cursor()
        super().closeEvent(event)

    def set_dark(self, dark: bool):
        self._dark = dark
        bg  = "#1E293B" if dark else "#FFFFFF"
        brd = "#334155" if dark else "#CBD5E1"
        self.setStyleSheet(
            f"QFrame#demand_frame {{ background: {bg}; border: 1px solid {brd}; }}"
        )
        bar_bg  = "#0F172A" if dark else "#F1F5F9"
        bar_brd = "#334155" if dark else "#E2E8F0"
        self._bar.setStyleSheet(
            f"QFrame#df_titlebar {{ background: {bar_bg};"
            f" border-bottom: 1px solid {bar_brd}; }}"
        )
        self._title_bar_lbl.setStyleSheet(
            f"color: {'#E2E8F0' if dark else '#1E293B'}; font-size: 13px; font-weight: 600;"
            " background: transparent; border: none;"
        )

    def _ensure_snap_overlay(self):
        if self._snap_overlay is None and self.parent():
            self._snap_overlay = _SnapOverlay(self.parent())
        return self._snap_overlay

    def _update_snap(self, global_pos):
        p = self.parent()
        if not p:
            return
        lp  = p.mapFromGlobal(global_pos)
        px, py = lp.x(), lp.y()
        pw, ph = p.width(), p.height()
        THRESH  = 20
        nl = px <= THRESH
        nr = px >= pw - THRESH
        nt = py <= THRESH
        nb = py >= ph - THRESH
        hw, hh = pw // 2, ph // 2

        if   nl and nt: snap = (0,   0,   hw,       hh)
        elif nr and nt: snap = (hw,  0,   pw - hw,  hh)
        elif nl and nb: snap = (0,   hh,  hw,       ph - hh)
        elif nr and nb: snap = (hw,  hh,  pw - hw,  ph - hh)
        elif nl:        snap = (0,   0,   hw,       ph)
        elif nr:        snap = (hw,  0,   pw - hw,  ph)
        elif nt:        snap = (0,   0,   pw,       hh)
        else:           snap = None

        self._snap_rect = snap
        ov = self._ensure_snap_overlay()
        if ov is None:
            return
        if snap:
            ov.setGeometry(*snap)
            ov.show()
            self.raise_()   # mantém a janela arrastada acima do ghost
        else:
            ov.hide()

    def closeEvent(self, event):
        self._clear_cursor_override()
        if self._snap_overlay:
            self._snap_overlay.hide()
        self.closed.emit(self.demand_id)
        super().closeEvent(event)


class MainWindow(QMainWindow):

    def __init__(self, use_cases: DemandUseCases, file_service=None, ai_service=None):
        super().__init__()
        self._uc   = use_cases
        self._fs   = file_service
        self._ai = ai_service

        _s = QSettings("DemandFlow", "DemandFlow")
        self._dark = _s.value("dark_mode", False, type=bool)
        geom = _s.value("window_geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.setWindowState(Qt.WindowState.WindowMaximized)
        self._current_view = "dashboard"
        self._assistant_dialog = None
        self._detail_windows: dict[int, _DemandFrame] = {}   # demand_id -> floating frame
        self._demand_pills:   dict[int, QFrame] = {}   # demand_id -> pill frame
        self._gantt_zoom = 1.0                 # multiplicador de pixels-por-hora no Gantt
        self._gantt_pinned: set[int] = set()   # demandas fixadas no Gantt sem apontamentos ainda
        self._missing_hours_checked_date = None   # último dia em que já avisamos sobre horas faltantes

        # Histórico "debounced" dos ajustes na grade de Planejamento — acumula
        # as mudanças da demanda em edição e só grava 1 entrada consolidada
        # quando troca de demanda, sai da aba, ou fica um tempo sem editar.
        self._planning_active_demand_id = None
        self._planning_pending: dict = {}   # {week_start: (horas_antigas, horas_novas)}
        self._planning_flush_timer = QTimer(self)
        self._planning_flush_timer.setSingleShot(True)
        self._planning_flush_timer.setInterval(20000)   # 20s sem editar -> grava
        self._planning_flush_timer.timeout.connect(self._flush_planning_history)

        self.setWindowTitle("DemandFlow — Gestão de Demandas")
        self.setMinimumSize(1200, 720)
        self.resize(1440, 860)

        self._update_banner  = None   # QFrame criado sob demanda
        self._update_url     = ""
        self._update_version = ""
        self._update_notes   = ""
        self._downloader     = None

        self._build_ui()
        self._apply_theme()
        self._show_view("dashboard")
        self._start_alert_timer()
        QTimer.singleShot(900, self._maybe_check_missing_hours)
        QTimer.singleShot(3000, self._start_update_check)
        QTimer.singleShot(600, self._maybe_show_whats_new)

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_h = QHBoxLayout(central)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        self._build_sidebar(main_h)

        right = QWidget()
        right.setObjectName("right_panel")
        self._right_panel = right
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(0)

        self._build_topbar(right_v)

        # Banner de atualização (oculto até update_available)
        self._update_banner = self._build_update_banner()
        right_v.addWidget(self._update_banner)

        # Content area (stack via show/hide)
        self.content_area = QWidget()
        content_layout = QVBoxLayout(self.content_area)
        content_layout.setContentsMargins(28, 24, 28, 24)
        content_layout.setSpacing(0)

        self._views: dict[str, QWidget] = {}
        self._views["dashboard"] = self._build_dashboard_view()
        self._views["demands"]   = self._build_demands_view()
        self._views["kanban"]    = self._build_kanban_view()
        self._views["calendar"]  = self._build_calendar_view()
        self._views["reports"]   = self._build_reports_view()
        self._views["planning"]  = self._build_planning_view()
        self._views["knowledge"] = self._build_knowledge_view()

        for v in self._views.values():
            content_layout.addWidget(v)
            v.hide()

        self.content_area.installEventFilter(self)
        right_v.addWidget(self.content_area)
        main_h.addWidget(right)

        self.statusBar().showMessage(f"DemandFlow v{__version__} — Pronto")

    # ── Sidebar ────────────────────────────────────────────────────────────────

    def _build_sidebar(self, parent_layout):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sb_v = QVBoxLayout(sidebar)
        sb_v.setContentsMargins(0, 0, 0, 0)
        sb_v.setSpacing(0)

        # Logo
        logo_frame = QFrame()
        logo_frame.setStyleSheet("padding: 5px 4px 4px;")
        #logo_frame.setStyleSheet("padding: 20px 16px 16px;")
        logo_v = QHBoxLayout(logo_frame)
        logo_v.setSpacing(10)

        logo_icon = QLabel("⚡")
        logo_icon.setStyleSheet("font-size: 24px;")
        logo_icon.setFixedWidth(60)
        logo_v.addWidget(logo_icon)

        logo_text = QWidget()
        lt_v = QVBoxLayout(logo_text)
        lt_v.setContentsMargins(0, 0, 0, 0)
        lt_v.setSpacing(0)
        name_lbl = QLabel("DemandFlow")
        name_lbl.setObjectName("logo_label")
        ver_lbl = QLabel(f"v{__version__}")
        ver_lbl.setObjectName("version_label")
        lt_v.addWidget(name_lbl)
        lt_v.addWidget(ver_lbl)
        logo_v.addWidget(logo_text)
        logo_v.addStretch()
        sb_v.addWidget(logo_frame)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sb_v.addWidget(sep)

        # Nav
        nav_container = QWidget()
        nav_v = QVBoxLayout(nav_container)
        nav_v.setContentsMargins(8, 8, 8, 8)
        nav_v.setSpacing(2)

        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_icon_names: dict[str, str] = {
            "dashboard": "fa6s.gauge-high",
            "demands":   "fa6s.list-check",
            "kanban":    "fa6s.table-columns",
            "calendar":  "fa6s.calendar-days",
            "reports":   "fa6s.clock",
            "planning":  "fa6s.chart-column",
            "knowledge": "fa6s.book-open",
        }

        nav_items = [
            ("dashboard", "Dashboard"),
            ("demands",   "Demandas"),
            ("kanban",    "Kanban"),
            ("calendar",  "Calendário"),
            ("reports",   "Horas"),
            ("planning",  "Planejamento"),
            ("knowledge", "Base Conhecimento"),
        ]

        _nav_c = "#64748B"  # cor inicial (modo claro)
        for key, label in nav_items:
            btn = QPushButton(label)
            btn.setIcon(qta.icon(self._nav_icon_names[key], color=_nav_c))
            btn.setObjectName("nav_btn")
            btn.setFixedHeight(38)
            btn.clicked.connect(lambda _, k=key: self._show_view(k))
            nav_v.addWidget(btn)
            self._nav_buttons[key] = btn

        nav_v.addStretch()
        sb_v.addWidget(nav_container, 1)

        # Bottom area
        bottom = QFrame()
        bottom.setStyleSheet("border-top: 1px solid rgba(0,0,0,0.1); padding: 12px 16px;")
        bot_v = QVBoxLayout(bottom)
        bot_v.setSpacing(8)
        bot_v.setContentsMargins(0, 0, 0, 0)

        self.alert_btn = QPushButton("0 Alertas")
        self.alert_btn.setIcon(qta.icon("fa6s.bell", color="#64748B"))
        self.alert_btn.clicked.connect(self._show_alerts)
        bot_v.addWidget(self.alert_btn)

        self._theme_btn = QPushButton("  Tema Escuro")
        self._theme_btn.setIcon(qta.icon("fa6s.moon", color="#64748B"))
        self._theme_btn.clicked.connect(self._toggle_theme)
        bot_v.addWidget(self._theme_btn)

        sb_v.addWidget(bottom)
        parent_layout.addWidget(sidebar)

    # ── Topbar ─────────────────────────────────────────────────────────────────

    def _build_topbar(self, parent_layout):
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(64)
        tb_h = QHBoxLayout(topbar)
        tb_h.setContentsMargins(1, 0, 24, 2)
        tb_h.setSpacing(12)

        title_block = QWidget()
        title_block.setStyleSheet("background: transparent;")
        tb_v = QVBoxLayout(title_block)
        tb_v.setContentsMargins(0, 0, 0, 0)
        tb_v.setSpacing(0)
        self.page_title = QLabel("Dashboard")
        self.page_title.setObjectName("page_title")

        self.page_subtitle = QLabel(_format_date_pt(date.today()))
        self.page_subtitle.setObjectName("page_subtitle")
                                   
        tb_v.addWidget(self.page_title)
        tb_v.addWidget(self.page_subtitle)
        tb_h.addWidget(title_block)
        tb_h.addStretch()

        # Pills para demandas abertas (alinhadas à base, estilo aba)
        pills_container = QWidget()
        pills_container.setStyleSheet("background: transparent;")
        pills_container.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self._demand_pills_layout = QHBoxLayout(pills_container)
        self._demand_pills_layout.setContentsMargins(0, 0, 0, 0)
        self._demand_pills_layout.setSpacing(6)
        self._demand_pills_layout.setAlignment(Qt.AlignmentFlag.AlignBottom)
        tb_h.addWidget(pills_container, 0, Qt.AlignmentFlag.AlignBottom)

        # Assistant
        self._assist_btn = QPushButton("  Assistente IA")
        self._assist_btn.setIcon(qta.icon("fa6s.robot", color="#64748B"))
        self._assist_btn.clicked.connect(self._show_assistant)
        tb_h.addWidget(self._assist_btn)

        # New demand
        self._new_btn = QPushButton("  Nova Demanda")
        self._new_btn.setObjectName("btn_primary")
        self._new_btn.setIcon(qta.icon("fa6s.plus", color="#FFFFFF"))
        self._new_btn.clicked.connect(self._open_new_demand)
        tb_h.addWidget(self._new_btn)

        parent_layout.addWidget(topbar)

    # ── Dashboard View ────────────────────────────────────────────────────────

    def _build_dashboard_view(self):
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        v = QVBoxLayout(container)
        v.setSpacing(20)
        v.setContentsMargins(0, 0, 0, 0)

        # Stats row
        self.stats_grid = QWidget()
        self.stats_layout = QHBoxLayout(self.stats_grid)
        self.stats_layout.setSpacing(16)
        self.stats_layout.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.stats_grid)

        # Charts row
        charts_row = QHBoxLayout()
        charts_row.setSpacing(16)

        self.chart_priority_frame = QFrame()
        self.chart_priority_frame.setObjectName("card")
        self.chart_priority_frame.setMinimumHeight(200)
        charts_row.addWidget(self.chart_priority_frame)

        self.chart_status_frame = QFrame()
        self.chart_status_frame.setObjectName("card")
        self.chart_status_frame.setMinimumHeight(200)
        charts_row.addWidget(self.chart_status_frame)

        self.chart_category_frame = QFrame()
        self.chart_category_frame.setObjectName("card")
        self.chart_category_frame.setMinimumHeight(200)
        charts_row.addWidget(self.chart_category_frame)

        v.addLayout(charts_row)

        # Recent + KPIs
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(16)

        self.kpi_frame = QFrame()
        self.kpi_frame.setObjectName("card")
        self.kpi_frame.setFixedWidth(280)
        bottom_row.addWidget(self.kpi_frame)

        self.recent_frame = QFrame()
        self.recent_frame.setObjectName("card")
        bottom_row.addWidget(self.recent_frame)

        v.addLayout(bottom_row)

        v.addStretch()

        w.setWidget(container)
        return w

    def _refresh_dashboard(self):
        stats = self._uc.get_dashboard_stats()
        demands = self._uc.list_all()

        # Clear and rebuild stats
        while self.stats_layout.count():
            item = self.stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for label, val, color, icon in [
            ("Em Aberto",     stats["open"],     "#3B82F6", "📋"),
            ("Atrasadas",     stats["overdue"],  "#EF4444", "⚠️"),
            ("Concluídas",    stats["done"],     "#10B981", "✅"),
            ("Críticas",      stats["critical"], "#DC2626", "🔴"),
        ]:
            card = StatCard(label, str(val), color, icon, self._dark)
            self.stats_layout.addWidget(card)

        # Charts
        def rebuild_chart(frame, data, title, on_click=None):
            layout = frame.layout()

            if layout is None:
                layout = QVBoxLayout(frame)
                layout.setContentsMargins(16, 16, 16, 16)

            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            chart = MiniBarChart(data, title, self._dark)
            if on_click:
                chart.bar_clicked.connect(on_click)
            layout.addWidget(chart)

        priority_data = [
            {"label": p.label, "value": stats["by_priority"].get(p, 0), "color": p.color, "key": p}
            for p in Priority
        ]
        rebuild_chart(self.chart_priority_frame, priority_data, "Por Prioridade", on_click=self._filter_by_priority)

        status_data = [
            {"label": s.label, "value": stats["by_status"].get(s, 0), "color": s.color, "key": s}
            for s in Status
        ]
        rebuild_chart(self.chart_status_frame, status_data, "Por Status", on_click=self._filter_by_status)

        cat_data = sorted(
            [{"label": k, "value": v, "key": k} for k, v in stats["by_category"].items()],
            key=lambda x: -x["value"]
        )[:6]
        rebuild_chart(self.chart_category_frame, cat_data, "Por Categoria", on_click=self._filter_by_category)

        # KPIs
        kpi_l = self.kpi_frame.layout()

        if kpi_l is None:
            kpi_l = QVBoxLayout(self.kpi_frame)
            kpi_l.setContentsMargins(16, 16, 16, 16)
            kpi_l.setSpacing(16)

        while kpi_l.count():
            item = kpi_l.takeAt(0)

            if item.widget():
                item.widget().deleteLater()
                
        total_h = stats["total_hours"]
        done_d  = [d for d in demands if d.status == Status.CONCLUIDA and d.estimated_hours > 0]
        eff_vals = [d.real_hours / d.estimated_hours * 100 for d in done_d]
        eff = f"{sum(eff_vals)/len(eff_vals):.0f}%" if eff_vals else "—"
        inactive = stats["inactive"]
        est_total = sum(d.estimated_hours for d in demands)
        done_all  = [d for d in demands if d.status == Status.CONCLUIDA]
        taxa = f"{len(done_all)/len(demands)*100:.0f}%" if demands else "—"

        for lbl, val, color in [
            ("Total horas trabalhadas", f"{total_h:.0f}h",    "#3B82F6"),
            ("Horas estimadas total",   f"{est_total:.0f}h",  "#8B5CF6"),
            ("Taxa de conclusão",       taxa,                  "#10B981"),
            ("Eficiência estimativa",   eff,                  "#F59E0B"),
            ("Demandas inativas",       str(inactive),        "#EF4444" if inactive > 0 else "#10B981"),
        ]:
            block = QWidget()
            block.setStyleSheet("background: transparent;")
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)
            l = QLabel(lbl)
            l.setStyleSheet(f"font-size: 11px; color: {'#94A3B8' if self._dark else '#64748B'}; font-weight: 500; background: transparent;")
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet(f"font-size: 24px; font-weight: 700; color: {color}; background: transparent;")
            bl.addWidget(l)
            bl.addWidget(v_lbl)
            kpi_l.addWidget(block)
        kpi_l.addStretch()

        # Recent
        rec_l = self.recent_frame.layout()

        if rec_l is None:
            rec_l = QVBoxLayout(self.recent_frame)
            rec_l.setContentsMargins(16, 16, 16, 16)
            rec_l.setSpacing(8)

        while rec_l.count():
            item = rec_l.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

        hdr = QLabel("Demandas Recentes")
        hdr.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {'#94A3B8' if self._dark else '#64748B'};")
        rec_l.addWidget(hdr)

        recent_demands = sorted(demands, key=lambda d: d.last_activity, reverse=True)[:6]
        if not recent_demands:
            empty = QLabel("Nenhuma demanda recente.")
            empty.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 12px;")
            rec_l.addWidget(empty)

        for d in recent_demands:
            item_frame = QFrame()
            item_frame.setObjectName("recent_item")
            item_frame.setCursor(Qt.CursorShape.PointingHandCursor)
            item_frame.setStyleSheet(
                "QFrame#recent_item { background: transparent; border-radius: 6px; }"
                f"QFrame#recent_item:hover {{ background: {'#1E293B' if self._dark else '#F8FAFC'}; }}"
            )
            row = QHBoxLayout(item_frame)
            row.setContentsMargins(4, 4, 4, 4)
            row.setSpacing(10)
            sb = status_badge(d.status)
            name = QLabel(d.title[:52] + ("…" if len(d.title) > 52 else ""))
            name.setStyleSheet("font-size: 12px; background: transparent;")
            row.addWidget(sb)
            row.addWidget(name)
            row.addStretch()
            item_frame.mouseDoubleClickEvent = lambda _, demand=d: self._open_demand_detail(demand)
            rec_l.addWidget(item_frame)
        rec_l.addStretch()

    # ── Links dos gráficos do dashboard para a lista de Demandas ───────────────

    def _filter_by_priority(self, priority: Priority):
        self._apply_demand_filter(priority=priority)

    def _filter_by_status(self, status: Status):
        self._apply_demand_filter(status=status)

    def _filter_by_category(self, category: str):
        self._apply_demand_filter(category=category)

    def _apply_demand_filter(self, status=None, priority=None, category=None):
        """Reseta os filtros da view Demandas e aplica apenas o filtro indicado
        (vindo de um clique nos gráficos/lista do dashboard), depois navega para lá."""
        widgets = (self.filter_status, self.filter_priority, self.filter_category, self.search_input)
        for w in widgets:
            w.blockSignals(True)

        self.filter_status.setCurrentIndex(0)
        self.filter_priority.setCurrentIndex(0)
        self.filter_category.setCurrentIndex(0)
        self.search_input.clear()

        if status is not None:
            idx = self.filter_status.findData(status)
            if idx >= 0:
                self.filter_status.setCurrentIndex(idx)
        if priority is not None:
            idx = self.filter_priority.findData(priority)
            if idx >= 0:
                self.filter_priority.setCurrentIndex(idx)
        if category is not None:
            idx = self.filter_category.findData(category)
            if idx >= 0:
                self.filter_category.setCurrentIndex(idx)

        for w in widgets:
            w.blockSignals(False)

        self._show_view("demands")

    # ── Demands View ───────────────────────────────────────────────────────────

    def _build_demands_view(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # ── Filtros — ficam FORA do splitter, ocupam só o necessário ─────────
        filters = QHBoxLayout()
        filters.setSpacing(8)

        self.filter_status = QComboBox()
        self.filter_status.addItem("Todos os Status", "")
        for s in Status:
            self.filter_status.addItem(qta.icon(s.fa_icon, color=s.color), s.label, s)
        self.filter_status.currentIndexChanged.connect(self._refresh_demands)
        filters.addWidget(self.filter_status)

        self.filter_priority = QComboBox()
        self.filter_priority.addItem("Todas as Prioridades", "")
        for p in Priority:
            self.filter_priority.addItem(p.label, p)
        self.filter_priority.currentIndexChanged.connect(self._refresh_demands)
        filters.addWidget(self.filter_priority)

        self.filter_category = QComboBox()
        self.filter_category.addItem("Todas as Categorias", "")
        for c in CATEGORIES:
            self.filter_category.addItem(c, c)
        self.filter_category.currentIndexChanged.connect(self._refresh_demands)
        filters.addWidget(self.filter_category)

                # Search
        self.search_input = QLineEdit()
        self.search_input.setObjectName("search_input")
        self.search_input.setPlaceholderText("🔍  Buscar demandas...")
        self.search_input.setFixedWidth(280)
        self.search_input.textChanged.connect(self._on_search)
        filters.addWidget(self.search_input)

        filters.addStretch()
        self.demand_count_lbl = QLabel("")
        self.demand_count_lbl.setStyleSheet(
            f"color: {'#94A3B8' if self._dark else '#9CA3AF'}; font-size: 12px;"
        )
        filters.addWidget(self.demand_count_lbl)

        # Linha de filtros tem altura fixa (só o necessário)
        filters_widget = QWidget()
        filters_widget.setLayout(filters)
        filters_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed      # <- não expande verticalmente
        )
        v.addWidget(filters_widget)

        # ── Splitter — ocupa o resto do espaço ───────────────────────────────
        self.demands_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.demands_splitter.setChildrenCollapsible(False)

        # Lista de demandas
        self.demands_scroll = QScrollArea()
        self.demands_scroll.setWidgetResizable(True)
        self.demands_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.demands_scroll.viewport().installEventFilter(self)
        self.demands_container = QWidget()
        self.demands_list_layout = QVBoxLayout(self.demands_container)
        self.demands_list_layout.setContentsMargins(0, 0, 6, 0)
        self.demands_list_layout.setSpacing(0)
        self.demands_list_layout.addStretch()
        self.demands_scroll.setWidget(self.demands_container)
        self.demands_splitter.addWidget(self.demands_scroll)

        # Preview panel
        self._preview_panel = DemandPreviewPanel(self._dark, parent=self)
        self._preview_panel.open_requested.connect(self._open_demand_detail)
        self._preview_panel.setVisible(False)
        self.demands_splitter.addWidget(self._preview_panel)

        # Lista ocupa quase tudo; preview tem largura inicial fixa de 320px
        self.demands_splitter.setSizes([99999, 320])
        self.demands_splitter.setStretchFactor(0, 1)
        self.demands_splitter.setStretchFactor(1, 0)  # preview não cresce sozinho

        v.addWidget(self.demands_splitter, 1)  # stretch=1 → ocupa o resto
        self._restore_demand_filters()
        return w
    
    def eventFilter(self, obj, event):
        if obj is self.content_area and event.type() == QEvent.Type.Resize:
            old = event.oldSize()
            new = event.size()
            if old.isValid() and old.width() > 0 and old.height() > 0:
                rw = new.width()  / old.width()
                rh = new.height() / old.height()
                for frame in list(self._detail_windows.values()):
                    try:
                        if frame._maximized:
                            frame.setGeometry(0, 0, new.width(), new.height())
                        else:
                            g = frame.geometry()
                            frame.setGeometry(
                                round(g.x() * rw),
                                round(g.y() * rh),
                                max(520, round(g.width()  * rw)),
                                max(400, round(g.height() * rh)),
                            )
                    except RuntimeError:
                        pass

        if (
            obj == self.demands_scroll.viewport()
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            child = self.demands_scroll.childAt(event.pos())
            if child is None:
                self._hide_preview()

        return super().eventFilter(obj, event)

    def _refresh_demands(self):
        # Collect filters
        status_data   = self.filter_status.currentData()
        priority_data = self.filter_priority.currentData()
        category_data = self.filter_category.currentData()
        #resp_text     = self.filter_resp.text().strip()
        #free_text = self.filter_text.text().strip()
        search_text   = self.search_input.text().strip()

        demands = self._uc.search(
            query       = search_text,
            status      = status_data if isinstance(status_data, Status) else None,
            priority    = priority_data if isinstance(priority_data, Priority) else None,
            category    = category_data if category_data else "",
            #responsible = resp_text,
        )

        # Concluídas vivem na Base de Conhecimento; só mostra aqui se filtro explícito
        if not isinstance(status_data, Status):
            demands = [d for d in demands if d.status != Status.CONCLUIDA]

        demands = sorted(
            demands,
            key=lambda d: (
                not d.is_overdue,               # atrasadas primeiro
                -d.priority.weight,             # crítica > alta > média > baixa
                d.deadline,                     # prazo mais próximo
                d.last_activity                 # mais antigas sem atividade primeiro
            )
        )
        
        # Clear
        while self.demands_list_layout.count():
            item = self.demands_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.demand_count_lbl.setText(f"{len(demands)} demanda{'s' if len(demands) != 1 else ''}")

        if not demands:
            empty = QLabel("Nenhuma demanda encontrada")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 14px; padding: 60px;")
            self.demands_list_layout.addWidget(empty)
        else:
            for d in demands:
                item = DemandListItem(d, self._dark, search_query=search_text)
                item.selected.connect(self._on_demand_selected)
                item.double_clicked.connect(self._open_demand_detail)
                self.demands_list_layout.addWidget(item)

        self.demands_list_layout.addStretch()
        self._save_demand_filters()

    def _save_demand_filters(self):
        s = QSettings("DemandFlow", "DemandFlow")
        st = self.filter_status.currentData()
        pr = self.filter_priority.currentData()
        cat = self.filter_category.currentData()
        s.setValue("filters/status",   st.value if isinstance(st, Status) else "")
        s.setValue("filters/priority", pr.value if isinstance(pr, Priority) else "")
        s.setValue("filters/category", cat if isinstance(cat, str) else "")
        s.setValue("filters/search",   self.search_input.text())

    def _restore_demand_filters(self):
        s = QSettings("DemandFlow", "DemandFlow")
        for widget in (self.filter_status, self.filter_priority,
                       self.filter_category, self.search_input):
            widget.blockSignals(True)
        try:
            st_val = s.value("filters/status", "")
            if st_val:
                try:
                    idx = self.filter_status.findData(Status(st_val))
                    if idx >= 0:
                        self.filter_status.setCurrentIndex(idx)
                except ValueError:
                    pass

            pr_val = s.value("filters/priority", "")
            if pr_val:
                try:
                    idx = self.filter_priority.findData(Priority(pr_val))
                    if idx >= 0:
                        self.filter_priority.setCurrentIndex(idx)
                except ValueError:
                    pass

            cat_val = s.value("filters/category", "")
            if cat_val:
                idx = self.filter_category.findData(cat_val)
                if idx >= 0:
                    self.filter_category.setCurrentIndex(idx)

            self.search_input.setText(s.value("filters/search", ""))
        finally:
            for widget in (self.filter_status, self.filter_priority,
                           self.filter_category, self.search_input):
                widget.blockSignals(False)

    def _on_demand_selected(self, demand):
        full = self._uc.get(demand.id)
        if not full:
            return
        self._preview_panel.set_demand(full, self._fs)
        if not self._preview_panel.isVisible():
            self._preview_panel.setVisible(True)
            # Só força o tamanho na primeira vez que abre
            total = self.demands_splitter.width()
            self.demands_splitter.setSizes([total - 340, 340])

    def _hide_preview(self):
        if not self._preview_panel.isVisible():
            return

        self._preview_panel.setVisible(False)

        total = self.demands_splitter.width()
        self.demands_splitter.setSizes([total, 0])

    # ── Kanban View ────────────────────────────────────────────────────────────

    def _build_kanban_view(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        self.kanban_scroll = QScrollArea()
        self.kanban_scroll.setWidgetResizable(True)
        self.kanban_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.kanban_container = QWidget()
        self.kanban_layout = QHBoxLayout(self.kanban_container)
        self.kanban_layout.setSpacing(16)
        self.kanban_layout.setContentsMargins(0, 0, 0, 16)

        self.kanban_scroll.setWidget(self.kanban_container)
        v.addWidget(self.kanban_scroll)
        return w

    def _refresh_kanban(self):
        while self.kanban_layout.count():
            item = self.kanban_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        demands = self._uc.list_all()

        for status in Status:
            col_demands = [d for d in demands if d.status == status]

            col_frame = QFrame()
            col_frame.setMinimumWidth(240)
            col_frame.setMaximumWidth(300)
            col_frame.setObjectName("kanban_column")
            col_frame.setStyleSheet(f"""
                QFrame#kanban_column {{
                    border: 1px solid {'#334155' if self._dark else '#E2E8F0'};
                    border-radius: 12px;
                }}
            """)
            '''
            col_frame.setStyleSheet(f"""
                QFrame {{
                    background: transparent;
                    border: none;
                }}
            """)
            col_frame.setStyleSheet(f"""
                QFrame {{
                    background: {'#0F172A' if self._dark else '#F8FAFC'};
                    border: 1px solid {'#334155' if self._dark else '#E2E8F0'};
                    border-radius: 12px;
                }}
            """)
            '''
            col_v = QVBoxLayout(col_frame)
            col_v.setContentsMargins(10, 10, 10, 10)
            col_v.setSpacing(8)

            # Column header
            hdr = QHBoxLayout()
            icon_lbl = QLabel()
            icon_lbl.setPixmap(qta.icon(status.fa_icon, color=status.color).pixmap(16, 16))
            name_lbl = QLabel(status.label)
            name_lbl.setStyleSheet("font-weight: 600; font-size: 13px;")
            count_lbl = QLabel(str(len(col_demands)))
            count_lbl.setStyleSheet(f"""
                background: {'#334155' if self._dark else '#E2E8F0'};
                border-radius: 10px; padding: 1px 8px; font-size: 11px;
            """)
            hdr.addWidget(icon_lbl)
            hdr.addWidget(name_lbl)
            hdr.addStretch()
            hdr.addWidget(count_lbl)
            col_v.addLayout(hdr)

            # Cards
            col_scroll = QScrollArea()
            col_scroll.setWidgetResizable(True)
            col_scroll.setFrameShape(QFrame.Shape.NoFrame)
            col_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

            cards_container = QWidget()
            cards_v = QVBoxLayout(cards_container)
            cards_v.setContentsMargins(0, 0, 0, 0)
            cards_v.setSpacing(6)

            for d in col_demands:
                card = KanbanCard(d, self._dark)
                card.clicked.connect(self._open_demand_detail)
                cards_v.addWidget(card)

            if not col_demands:
                empty = QLabel("—")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setStyleSheet(f"color: {'#475569' if self._dark else '#CBD5E1'}; font-size: 12px; padding: 20px;")
                cards_v.addWidget(empty)

            cards_v.addStretch()
            col_scroll.setWidget(cards_container)
            col_v.addWidget(col_scroll)

            self.kanban_layout.addWidget(col_frame)

        self.kanban_layout.addStretch()

    # ── Calendar View ──────────────────────────────────────────────────────────

    def _build_calendar_view(self):
        w = QWidget()
        v = QHBoxLayout(w)
        v.setSpacing(20)
        v.setContentsMargins(0, 0, 0, 0)

        # Calendar widget
        cal_frame = QFrame()
        cal_frame.setObjectName("card")
        cal_layout = QVBoxLayout(cal_frame)
        cal_layout.setContentsMargins(6, 6, 6, 6)

        self.calendar_widget = IconCalendarWidget()
        self.calendar_widget.setGridVisible(True)
        self.calendar_widget.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar_widget.clicked.connect(self._on_calendar_date_clicked)
        cal_layout.addWidget(self.calendar_widget)
        v.addWidget(cal_frame, 2)

        self._refresh_calendar_marks()

        # Side panel: demand list for selected date
        side_frame = QFrame()
        side_frame.setObjectName("card")
        side_frame.setFixedWidth(300)

        side_v = QVBoxLayout(side_frame)
        side_v.setContentsMargins(6, 6, 6, 6)

        self.cal_date_lbl = QLabel("Selecione uma data")
        self.cal_date_lbl.setStyleSheet(
            "font-weight: 700; font-size: 15px;"
        )
        side_v.addWidget(self.cal_date_lbl)

        # Área de scroll
        self.cal_demands_scroll = QScrollArea()
        self.cal_demands_scroll.setWidgetResizable(True)
        self.cal_demands_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.cal_demands_container = QWidget()
        self.cal_demands_layout = QVBoxLayout(self.cal_demands_container)
        self.cal_demands_layout.setSpacing(6)
        self.cal_demands_layout.setContentsMargins(4, 6, 8, 6)
        self.cal_demands_layout.addStretch()

        self.cal_demands_scroll.setWidget(self.cal_demands_container)

        side_v.addWidget(self.cal_demands_scroll, 1)

        v.addWidget(side_frame)

        return w
    
    def _refresh_calendar_marks(self):

        self.calendar_widget.setDateTextFormat(QDate(), QTextCharFormat())

        # Coleta apenas eventos pendentes por data (milestones concluídos são omitidos)
        # estrutura: { QDate: {"milestone": bool, "reminder": bool} }
        events: dict[QDate, dict] = {}
        counts: dict[QDate, int]  = {}

        for d in self._uc.list_all():
            for m in self._uc.get_milestones(d.id):
                if m.done:
                    continue
                qd = QDate(m.deadline.year, m.deadline.month, m.deadline.day)
                if qd not in events:
                    events[qd] = {}
                events[qd]["milestone"] = True
                counts[qd] = counts.get(qd, 0) + 1

            for r in self._uc.get_reminders(d.id):
                if r.done:
                    continue
                if getattr(r, 'daily', False):
                    qd = QDate.currentDate()
                else:
                    qd = QDate(r.remind_at.year, r.remind_at.month, r.remind_at.day)
                if qd not in events:
                    events[qd] = {}
                events[qd]["reminder"] = True
                counts[qd] = counts.get(qd, 0) + 1

        for qd, kinds in events.items():
            fmt = QTextCharFormat()
            has_reminder  = kinds.get("reminder", False)
            has_milestone = kinds.get("milestone", False)

            if has_reminder and has_milestone:
                fmt.setBackground(QColor("#DBEAFE"))
                fmt.setForeground(QColor("#1D4ED8"))
            elif has_reminder:
                fmt.setBackground(QColor("#F3E8FF"))
                fmt.setForeground(QColor("#7C3AED"))
            else:
                fmt.setBackground(QColor("#DBEAFE"))
                fmt.setForeground(QColor("#1D4ED8"))

            fmt.setFontPointSize(9.0)
            fmt.setFontWeight(700)
            self.calendar_widget.setDateTextFormat(qd, fmt)

        # Destaca hoje com borda
        today_fmt = self.calendar_widget.dateTextFormat(QDate.currentDate())
        today_fmt.setFontPointSize(9.0)
        today_fmt.setFontUnderline(True)
        today_fmt.setFontWeight(700)
        self.calendar_widget.setDateTextFormat(QDate.currentDate(), today_fmt)

        # Alimenta os ícones por célula — tuplas (símbolo, cor)
        icon_map: dict[QDate, list[tuple[str, str]]] = {}
        for qd, kinds in events.items():
            day_icons = []
            if kinds.get("milestone"):
                day_icons.append(("●", "#2563EB"))     # azul — milestone pendente
            if kinds.get("reminder"):
                day_icons.append(("●", "#D97706"))     # âmbar — lembrete
            if day_icons:
                icon_map[qd] = day_icons
        self.calendar_widget.set_day_icons(icon_map)
        self.calendar_widget.set_day_counts(counts)

    def _on_calendar_date_clicked(self, qdate: QDate):
        selected = date(qdate.year(), qdate.month(), qdate.day())
        self.cal_date_lbl.setText(_format_date_pt(selected, with_weekday=False))

        # Limpa painel
        while self.cal_demands_layout.count():
            item = self.cal_demands_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        found = False

        # ── Lembretes ─────────────────────────────────────────────────────────
        all_demands   = self._uc.list_all()
        demands_by_id = {d.id: d for d in all_demands}

        for d in all_demands:
            for r in self._uc.get_reminders(d.id):
                if r.done:
                    continue
                is_daily = getattr(r, 'daily', False)
                if not is_daily and r.remind_at != selected:
                    continue
                item = ReminderCalendarItem(d, r, self._dark)
                item.clicked.connect(self._open_demand_detail)
                self.cal_demands_layout.addWidget(item)
                found = True

        # Separador se houver os dois tipos
        has_milestones = any(
            m.deadline == selected
            for d in all_demands
            for m in self._uc.get_milestones(d.id)
        )
        has_reminders = found

        if has_reminders and has_milestones:
            sep_lbl = QLabel("── Milestones ──")
            sep_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sep_lbl.setStyleSheet(
                f"font-size: 10px; font-weight: 600; "
                f"color: {'#475569' if self._dark else '#94A3B8'}; "
                f"margin: 4px 0;"
            )
            self.cal_demands_layout.addWidget(sep_lbl)

        # ── Milestones ────────────────────────────────────────────────────────
        for d in all_demands:
            for m in self._uc.get_milestones(d.id):
                if m.deadline != selected or m.done:
                    continue
                item = MilestoneCalendarItem(d, m, self._dark)
                item.clicked.connect(self._open_demand_detail)
                self.cal_demands_layout.addWidget(item)
                found = True

        if not found:
            lbl = QLabel("Nenhum evento nesta data")
            lbl.setStyleSheet(
                f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 12px;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cal_demands_layout.addWidget(lbl)

        # ── Legenda no rodapé ─────────────────────────────────────────────────
        legend = QFrame()
        legend.setStyleSheet(
            f"background: {'#0F172A' if self._dark else '#F8FAFC'}; border-radius: 6px;"
        )
        ll = QHBoxLayout(legend)
        ll.setContentsMargins(8, 6, 8, 6)
        ll.setSpacing(12)
        for icon_name, color, label in [
            ("fa6s.flag",        "#2563EB", "Milestone"),
            ("fa6s.circle-check","#059669", "Concluído"),
            ("fa6s.bell",        "#D97706", "Lembrete"),
        ]:
            dot_lbl = QLabel()
            dot_lbl.setPixmap(qta.icon(icon_name, color=color).pixmap(12, 12))
            txt = QLabel(label)
            txt.setStyleSheet(
                f"font-size: 10px; color: {'#94A3B8' if self._dark else '#64748B'};"
            )
            ll.addWidget(dot_lbl)
            ll.addWidget(txt)
        ll.addStretch()
        self.cal_demands_layout.addStretch()
        self.cal_demands_layout.addWidget(legend)

    # ── Reports View ───────────────────────────────────────────────────────────

    def _build_reports_view(self):
        self._hours_period = "month"   # week | month | all

        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        v = QVBoxLayout(container)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        # ── Filtro de período ─────────────────────────────────────────────────
        period_row = QHBoxLayout()
        period_row.setSpacing(6)
        self._period_btns: dict[str, QPushButton] = {}
        for key, label in [("week", "Esta Semana"), ("month", "Este Mês"), ("all", "Todo o Período")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._hours_period)
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda _, k=key: self._set_hours_period(k))
            period_row.addWidget(btn)
            self._period_btns[key] = btn
        period_row.addStretch()

        v.addLayout(period_row)

        # ── Sumário ───────────────────────────────────────────────────────────
        self._hours_summary_row = QHBoxLayout()
        self._hours_summary_row.setSpacing(8)
        self._hours_summary_widget = QWidget()
        self._hours_summary_widget.setLayout(self._hours_summary_row)
        v.addWidget(self._hours_summary_widget)

        # ── Zoom do gráfico Gantt (precisão para alocar horas arrastando) ──────
        # Alinhado à direita, imediatamente acima do gráfico.
        gantt_toolbar = QHBoxLayout()
        gantt_toolbar.setSpacing(6)

        avulsa_btn = QPushButton("  Atividades Avulsas")
        avulsa_btn.setIcon(qta.icon("fa6s.bolt", color="#F59E0B"))
        avulsa_btn.setAutoDefault(False)
        avulsa_btn.setToolTip("Ver, registrar e excluir atividades sem demanda associada")
        avulsa_btn.clicked.connect(self._open_general_worklog)
        gantt_toolbar.addWidget(avulsa_btn)

        gantt_toolbar.addStretch()

        zoom_out_btn = QPushButton()
        zoom_out_btn.setIcon(qta.icon("fa6s.magnifying-glass-minus", color="#64748B"))
        zoom_out_btn.setFixedSize(30, 30)
        zoom_out_btn.setAutoDefault(False)
        zoom_out_btn.setToolTip("Diminuir zoom do gráfico")
        zoom_out_btn.clicked.connect(self._gantt_zoom_out)
        gantt_toolbar.addWidget(zoom_out_btn)

        self._gantt_zoom_lbl = QLabel(f"{int(self._gantt_zoom * 100)}%")
        self._gantt_zoom_lbl.setFixedWidth(42)
        self._gantt_zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gantt_zoom_lbl.setStyleSheet("font-size: 11px; font-weight: 600;")
        gantt_toolbar.addWidget(self._gantt_zoom_lbl)

        zoom_in_btn = QPushButton()
        zoom_in_btn.setIcon(qta.icon("fa6s.magnifying-glass-plus", color="#64748B"))
        zoom_in_btn.setFixedSize(30, 30)
        zoom_in_btn.setAutoDefault(False)
        zoom_in_btn.setToolTip("Aumentar zoom do gráfico (mais precisão para alocar horas)")
        zoom_in_btn.clicked.connect(self._gantt_zoom_in)
        gantt_toolbar.addWidget(zoom_in_btn)

        # ── Gantt + toolbar agrupados para ficar sempre colados ──────────────
        # Preferred/Maximum + AlignTop: sem isso, com poucas linhas o Gantt
        # (altura fixa) fica centralizado dentro do espaço sobrando do
        # QScrollArea em vez de colado no topo, abrindo um vão acima dele.
        gantt_section = QWidget()
        gantt_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        gs_layout = QVBoxLayout(gantt_section)
        gs_layout.setContentsMargins(0, 0, 0, 0)
        gs_layout.setSpacing(2)
        gs_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        gs_layout.addLayout(gantt_toolbar)

        self._hours_gantt_frame = QWidget()
        self._hours_gantt_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        gs_layout.addWidget(self._hours_gantt_frame)

        v.addWidget(gantt_section)
        v.addStretch()

        w.setWidget(container)
        return w

    def _set_hours_period(self, period: str):
        self._hours_period = period
        for k, btn in self._period_btns.items():
            btn.setChecked(k == period)
        self._refresh_reports()

    def _refresh_reports(self):
        from datetime import timedelta

        today = date.today()
        if self._hours_period == "week":
            date_from = today - timedelta(days=today.weekday())
        elif self._hours_period == "month":
            date_from = today.replace(day=1)
        else:
            date_from = None

        logs = self._uc.get_worklog_report(date_from=date_from, date_to=today)
        demands_map = {d.id: d for d in self._uc.list_all()}

        # ── Sumário ───────────────────────────────────────────────────────────
        while self._hours_summary_row.count():
            item = self._hours_summary_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_secs   = sum(w.duration_seconds for w in logs)
        total_h      = total_secs / 3600
        n_sessions   = len(logs)
        active_days  = len({w.started_at.date() for w in logs})
        avg_h        = total_h / active_days if active_days else 0

        muted = "#94A3B8" if self._dark else "#64748B"
        bg    = "#1E293B" if self._dark else "#FFFFFF"
        brd   = "#334155" if self._dark else "#E2E8F0"
        for label, value, color in [
            ("Total de Horas", f"{total_h:.1f}h",  "#3B82F6"),
            ("Sessões",        str(n_sessions),     "#8B5CF6"),
            ("Média por Dia",  f"{avg_h:.1f}h",     "#10B981"),
        ]:
            card = QFrame()
            card.setFixedHeight(62)
            card.setStyleSheet(
                f"QFrame {{ background:{bg}; border:1px solid {brd}; "
                f"border-left: 4px solid {color}; border-radius:8px; }}"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 8, 12, 8)
            cl.setSpacing(2)
            l_lbl = QLabel(label)
            l_lbl.setStyleSheet(f"font-size:10px; font-weight:500; color:{muted}; border:none;")
            l_val = QLabel(value)
            l_val.setStyleSheet(f"font-size:18px; font-weight:700; color:{color}; border:none;")
            cl.addWidget(l_lbl)
            cl.addWidget(l_val)
            self._hours_summary_row.addWidget(card)
        self._hours_summary_row.addStretch()

        # ── Gantt ─────────────────────────────────────────────────────────────
        gf = self._hours_gantt_frame
        gl = gf.layout()
        if gl is None:
            gl = QVBoxLayout(gf)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(0)
            gl.setAlignment(Qt.AlignmentFlag.AlignTop)
        while gl.count():
            item = gl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if date_from is None:
            gantt_from = min((w.started_at.date() for w in logs), default=today)
        else:
            gantt_from = date_from
        gantt_to = today

        gantt = WorklogGanttWidget(
            logs, demands_map, gantt_from, gantt_to, dark=self._dark,
            zoom=self._gantt_zoom, extra_demand_ids=list(self._gantt_pinned),
        )
        gantt.log_requested.connect(self._on_gantt_log_requested)
        gantt.demand_pinned.connect(self._on_gantt_demand_pinned)
        gantt.demand_unpinned.connect(self._on_gantt_demand_unpinned)
        gantt.demand_label_clicked.connect(self._on_gantt_demand_label_clicked)
        gantt.log_edit_requested.connect(self._on_gantt_log_edit_requested)
        gl.addWidget(gantt)

    # Horário de almoço descontado automaticamente nos apontamentos via Gantt
    _LUNCH_START_H = 12
    _LUNCH_END_H   = 13

    def _effective_duration(self, start, end) -> int:
        """Segundos líquidos entre start e end, descontando o almoço de cada dia coberto."""
        from datetime import timedelta
        total = int((end - start).total_seconds())
        d = start.date()
        while d <= end.date():
            ls = datetime(d.year, d.month, d.day, self._LUNCH_START_H)
            le = datetime(d.year, d.month, d.day, self._LUNCH_END_H)
            ov_s = max(start, ls)
            ov_e = min(end, le)
            if ov_e > ov_s:
                total -= int((ov_e - ov_s).total_seconds())
            d += timedelta(days=1)
        return max(0, total)

    def _on_gantt_log_requested(self, demand_id, start, end):
        duration = self._effective_duration(start, end)
        if duration <= 0:
            return

        category, note = "", ""
        if demand_id is None:
            result = self._prompt_avulsa_details(start, end)
            if result is None:
                return
            category, note = result
        else:
            result = self._prompt_demand_log_note(start, end)
            if result is None:
                return
            note = result

        self._uc.add_work_log(
            demand_id=demand_id, started_at=start, ended_at=end,
            duration_seconds=duration, manual=True, category=category, note=note,
        )
        self._refresh_reports()
        h, m = duration // 3600, (duration % 3600) // 60
        raw = int((end - start).total_seconds())
        deducted = raw - duration
        suffix = f" (almoço -{deducted // 60}min descontado)" if deducted > 0 else ""
        dur_str = f"{h}h{m:02d}min" if h else f"{m}min"
        self.statusBar().showMessage(f"Apontamento registrado: {dur_str}{suffix}", 4000)

    def _prompt_avulsa_details(self, start, end):
        """Pede categoria (editável, texto livre) e descrição para uma atividade
        avulsa criada via clique-e-arraste no Gantt. Retorna (categoria, nota) ou None se cancelado."""
        from presentation.dialogs.general_worklog_dialog import _CATEGORIES

        dlg = QDialog(self)
        dlg.setWindowTitle("Atividade Avulsa")
        dlg.setMinimumWidth(380)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        info = QLabel(f"{start.strftime('%d/%m %H:%M')} → {end.strftime('%H:%M')}")
        info.setStyleSheet("font-weight: 600; font-size: 13px;")
        v.addWidget(info)

        v.addWidget(QLabel("Categoria:"))
        cat_combo = QComboBox()
        cat_combo.setEditable(True)
        cat_combo.addItems(_CATEGORIES)
        cat_combo.setCurrentIndex(0)
        v.addWidget(cat_combo)

        v.addWidget(QLabel("Descrição:"))
        note_input = SpellCheckLineEdit()
        note_input.setPlaceholderText("Opcional...")
        v.addWidget(note_input)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(dlg.reject)
        btns.addWidget(cancel_btn)
        ok_btn = QPushButton("Registrar")
        ok_btn.setObjectName("btn_primary")
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(dlg.accept)
        btns.addWidget(ok_btn)
        v.addLayout(btns)

        cat_combo.setFocus()

        if dlg.exec():
            return cat_combo.currentText().strip(), note_input.text().strip()
        return None

    def _prompt_demand_log_note(self, start, end):
        """Pede descrição opcional para um apontamento de demanda criado no Gantt.
        Retorna a nota (str, pode ser vazia) ou None se o usuário cancelou."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Apontamento")
        dlg.setMinimumWidth(340)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        info = QLabel(f"{start.strftime('%d/%m %H:%M')} → {end.strftime('%H:%M')}")
        info.setStyleSheet("font-weight: 600; font-size: 13px;")
        v.addWidget(info)

        v.addWidget(QLabel("Descrição:"))
        note_input = SpellCheckLineEdit()
        note_input.setPlaceholderText("Opcional...")
        v.addWidget(note_input)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(dlg.reject)
        btns.addWidget(cancel_btn)
        ok_btn = QPushButton("Registrar")
        ok_btn.setObjectName("btn_primary")
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(dlg.accept)
        btns.addWidget(ok_btn)
        v.addLayout(btns)

        note_input.setFocus()

        if dlg.exec():
            return note_input.text().strip()
        return None

    def _on_gantt_demand_label_clicked(self, demand_id: int):
        demand = self._uc.get(demand_id)
        if demand:
            self._open_demand_detail(demand, open_worklogs=True)

    def _on_gantt_demand_pinned(self, demand_id: int):
        self._gantt_pinned.add(demand_id)
        self._refresh_reports()

    def _on_gantt_demand_unpinned(self, demand_id: int):
        self._gantt_pinned.discard(demand_id)
        self._refresh_reports()

    def _gantt_zoom_in(self):
        self._gantt_zoom = min(3.0, round(self._gantt_zoom * 1.25, 3))
        self._gantt_zoom_lbl.setText(f"{int(self._gantt_zoom * 100)}%")
        self._refresh_reports()

    def _gantt_zoom_out(self):
        self._gantt_zoom = max(0.4, round(self._gantt_zoom * 0.8, 3))
        self._gantt_zoom_lbl.setText(f"{int(self._gantt_zoom * 100)}%")
        self._refresh_reports()

    def _open_general_worklog(self):
        dlg = GeneralWorkLogDialog(self._uc, dark=self._dark, parent=self)
        dlg.log_added.connect(self._refresh_reports)
        dlg.show()

    def _on_gantt_log_edit_requested(self, worklog):
        dlg = EditWorkLogDialog(self._uc, worklog, dark=self._dark, parent=self)
        dlg.saved.connect(self._refresh_reports)
        dlg.deleted.connect(self._refresh_reports)
        dlg.exec()

    # ── Planning View (capacidade/carga de horas por semana) ───────────────────

    def _build_planning_view(self):
        self._planning_weeks = 10   # 8 | 10 | 12

        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        v = QVBoxLayout(container)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        info_lbl = QLabel("Horas planejadas por demanda, comparadas à capacidade semanal.")
        info_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        toolbar.addWidget(info_lbl)
        toolbar.addStretch()

        self._planning_weeks_btns: dict[int, QPushButton] = {}
        for n in (8, 10, 12):
            btn = QPushButton(f"{n} semanas")
            btn.setCheckable(True)
            btn.setChecked(n == self._planning_weeks)
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda _, k=n: self._set_planning_weeks(k))
            toolbar.addWidget(btn)
            self._planning_weeks_btns[n] = btn
        v.addLayout(toolbar)

        self._planning_grid_frame = QWidget()
        v.addWidget(self._planning_grid_frame)
        v.addStretch()

        w.setWidget(container)
        return w

    def _set_planning_weeks(self, n: int):
        self._planning_weeks = n
        for k, btn in self._planning_weeks_btns.items():
            btn.setChecked(k == n)
        self._refresh_planning()

    def _refresh_planning(self):
        grid_data = self._uc.get_capacity_grid(n_weeks=self._planning_weeks)

        gf = self._planning_grid_frame
        gl = gf.layout()
        if gl is None:
            gl = QVBoxLayout(gf)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(0)
        while gl.count():
            item = gl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not grid_data["demands"]:
            empty_lbl = QLabel("Nenhuma demanda ativa para planejar.")
            empty_lbl.setStyleSheet("color: #94A3B8; padding: 24px;")
            gl.addWidget(empty_lbl)
            return

        grid = CapacityGridWidget(grid_data, dark=self._dark)
        grid.hours_adjusted.connect(self._on_planning_hours_adjusted)
        grid.demand_label_clicked.connect(self._on_planning_demand_clicked)
        grid.suggest_requested.connect(self._on_planning_suggest)
        grid.clear_requested.connect(self._on_planning_clear)
        grid.estimated_hours_changed.connect(self._on_planning_estimate_changed)
        gl.addWidget(grid)

    def _on_planning_hours_adjusted(self, demand_id: int, week_start, new_hours: float):
        before = {a.week_start: a.planned_hours for a in self._uc.get_planned_allocations(demand_id)}
        try:
            result = self._uc.adjust_planned_hours(demand_id, week_start, new_hours)
        except ValueError as exc:
            QMessageBox.warning(self, "Ajuste inválido", str(exc))
            self._refresh_planning()
            return

        # Acumula no histórico "debounced": grava a entrada anterior se o
        # usuário trocou de demanda; senão só estende a janela de inatividade.
        if demand_id != self._planning_active_demand_id:
            self._flush_planning_history()
            self._planning_active_demand_id = demand_id
        for row in result["updated"]:
            old = before.get(row.week_start, 0.0)
            if row.week_start in self._planning_pending:
                first_old, _ = self._planning_pending[row.week_start]
                self._planning_pending[row.week_start] = (first_old, row.planned_hours)
            else:
                self._planning_pending[row.week_start] = (old, row.planned_hours)
        self._planning_flush_timer.start()

        self._refresh_planning()

    def _flush_planning_history(self):
        """Grava 1 entrada de histórico consolidando as mudanças acumuladas
        na grade de Planejamento desde o último flush — chamado ao trocar de
        demanda, sair da aba, ou após um tempo sem editar (timer)."""
        if self._planning_active_demand_id is not None and self._planning_pending:
            self._uc.log_planning_changes(self._planning_active_demand_id, self._planning_pending)
        self._planning_active_demand_id = None
        self._planning_pending = {}
        self._planning_flush_timer.stop()

    def _on_planning_demand_clicked(self, demand_id: int):
        demand = self._uc.get(demand_id)
        if demand:
            self._open_demand_detail(demand)

    def _on_planning_suggest(self, demand_id: int):
        self._flush_planning_history()
        try:
            self._uc.suggest_allocation(demand_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Sugestão indisponível", str(exc))
            return
        self._refresh_planning()

    def _on_planning_clear(self, demand_id: int):
        self._flush_planning_history()
        self._uc.clear_allocation(demand_id)
        self._refresh_planning()

    def _on_planning_estimate_changed(self, demand_id: int, new_value: float):
        self._flush_planning_history()
        try:
            self._uc.update_estimated_hours(demand_id, new_value)
        except ValueError as exc:
            QMessageBox.warning(self, "Estimativa inválida", str(exc))
        self._refresh_planning()

    def _check_missing_hours(self):
        """Avisa se o dia útil anterior teve menos horas do que o expediente (8h líquidas)."""
        from datetime import timedelta
        _WORK_DAY_SEC = 8 * 3600
        today = date.today()
        prev  = today - timedelta(days=1)
        while prev.weekday() >= 5:   # pula fim de semana
            prev -= timedelta(days=1)

        logs = self._uc.get_worklog_report(date_from=prev, date_to=prev)
        total_sec = sum(w.duration_seconds for w in logs)
        if total_sec >= _WORK_DAY_SEC:
            return

        missing_sec = _WORK_DAY_SEC - total_sec
        mh = missing_sec // 3600
        mm = (missing_sec % 3600) // 60
        missing_str = f"{mh}h{mm:02d}min" if mh else f"{mm}min"

        dow = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"][prev.weekday()]
        if total_sec == 0:
            body = "Nenhuma hora foi registrada neste dia."
        else:
            lh = total_sec // 3600
            lm = (total_sec % 3600) // 60
            logged_str = f"{lh}h{lm:02d}min" if lh else f"{lm}min"
            body = (f"Apenas <b>{logged_str}</b> registradas — "
                    f"faltam <b>{missing_str}</b> para completar o expediente.")

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
        dlg = QDialog(self)
        dlg.setWindowTitle("Horas não registradas")
        dlg.setFixedWidth(420)
        dlg.setWindowModality(Qt.WindowModality.NonModal)

        v = QVBoxLayout(dlg)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(16)

        top = QHBoxLayout()
        ic  = QLabel()
        ic.setPixmap(qta.icon("fa6s.triangle-exclamation", color="#F59E0B").pixmap(24, 24))
        top.addWidget(ic)
        lbl = QLabel(f"<b>{dow}, {prev.strftime('%d/%m/%Y')}</b><br>{body}")
        lbl.setWordWrap(True)
        top.addWidget(lbl, 1)
        v.addLayout(top)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #334155;")
        v.addWidget(sep)

        btns = QHBoxLayout()
        btn_go = QPushButton("  Apontar Horas")
        btn_go.setIcon(qta.icon("fa6s.clock", color="#3B82F6"))
        btn_go.setAutoDefault(False)
        btn_go.setObjectName("btn_primary")
        def _go_to_hours():
            dlg.accept()
            self._show_view("reports")
        btn_go.clicked.connect(_go_to_hours)
        btns.addWidget(btn_go)

        btn_ok = QPushButton("Dispensar")
        btn_ok.setAutoDefault(False)
        btn_ok.clicked.connect(dlg.accept)
        btns.addWidget(btn_ok)
        v.addLayout(btns)

        dlg.show()

    # ── Knowledge View ────────────────────────────────────────────────────────

    def _build_knowledge_view(self):
        dark = self._dark
        outer = QWidget()
        outer_v = QVBoxLayout(outer)
        outer_v.setContentsMargins(0, 0, 0, 0)
        outer_v.setSpacing(8)

        # Search bar
        self._kb_search = QLineEdit()
        self._kb_search.setPlaceholderText("Buscar na base de conhecimento...")
        self._kb_search.setFixedHeight(36)
        self._kb_search.textChanged.connect(lambda: self._refresh_knowledge())
        outer_v.addWidget(self._kb_search)

        # Two-panel splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ── Left: index panel ─────────────────────────────────────────────
        left_wrap = QFrame()
        left_wrap.setObjectName("kb_left_panel")
        left_wrap.setStyleSheet(
            f"QFrame#kb_left_panel {{ border-right: 1px solid {'#334155' if dark else '#E2E8F0'}; }}"
        )
        left_wrap.setFixedWidth(264)
        left_v = QVBoxLayout(left_wrap)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_v.setSpacing(0)

        self._kb_list_scroll = QScrollArea()
        self._kb_list_scroll.setWidgetResizable(True)
        self._kb_list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._kb_list_body = QWidget()
        self._kb_list_layout = QVBoxLayout(self._kb_list_body)
        self._kb_list_layout.setContentsMargins(8, 4, 8, 8)
        self._kb_list_layout.setSpacing(1)
        self._kb_list_scroll.setWidget(self._kb_list_body)
        left_v.addWidget(self._kb_list_scroll, 1)
        splitter.addWidget(left_wrap)

        # ── Right: content panel ──────────────────────────────────────────
        self._kb_right = QWidget()
        self._kb_right_layout = QVBoxLayout(self._kb_right)
        self._kb_right_layout.setContentsMargins(0, 0, 0, 0)
        self._kb_right_layout.setSpacing(0)
        splitter.addWidget(self._kb_right)

        splitter.setSizes([264, 900])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer_v.addWidget(splitter, 1)

        self._kb_selected_id = None
        self._kb_content = None  # current content widget in right panel
        return outer

    def _refresh_knowledge(self):
        dark = self._dark
        search_text = self._kb_search.text().strip()
        q = search_text.lower()

        articles = [d for d in self._uc.list_all() if d.status == Status.CONCLUIDA]
        if q:
            # Tolerância a erro de digitação só como fallback (busca exata
            # primeiro, mesma lógica/limites da busca de Demandas).
            allow_fuzzy = len(q) >= 3

            def _matches(d):
                fields = [d.title, d.description, d.notes or "", *d.tags]
                if any(q in x.lower() for x in fields):
                    return True
                if allow_fuzzy:
                    return fuzzy_word_match(q, d.title, 1) or any(
                        fuzzy_word_match(q, t, 1) for t in d.tags
                    )
                return False

            articles = [d for d in articles if _matches(d)]
        articles.sort(key=lambda d: (d.category, d.title))

        # Clear left list
        while self._kb_list_layout.count():
            item = self._kb_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not articles:
            empty = QLabel("Nenhuma demanda concluída encontrada.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {'#64748B' if dark else '#9CA3AF'}; font-size: 13px; padding: 40px;")
            self._kb_list_layout.addWidget(empty)
            self._kb_list_layout.addStretch()
            self._kb_show_placeholder()
            return

        # Group by category
        for cat, grp in groupby(articles, key=lambda d: d.category):
            cat_items = list(grp)

            cat_lbl = QLabel(f"  {cat.upper()}")
            cat_lbl.setStyleSheet(
                f"color: {'#3B82F6' if dark else '#2563EB'}; font-size: 10px;"
                " font-weight: 700; padding: 8px 4px 3px; letter-spacing: 1px;"
            )
            self._kb_list_layout.addWidget(cat_lbl)

            active_bg = "#1E3A5F" if dark else "#DBEAFE"
            active_fg = "#60A5FA" if dark else "#1D4ED8"
            normal_fg = "#CBD5E1" if dark else "#334155"
            hover_bg  = "#1E293B" if dark else "#F1F5F9"

            for d in cat_items:
                selected = d.id == self._kb_selected_id
                item_frame = QFrame()
                item_frame.setObjectName(f"kb_item_{d.id}")
                item_frame.setCursor(Qt.CursorShape.PointingHandCursor)
                item_frame.setStyleSheet(
                    f"QFrame {{ background: {active_bg if selected else 'transparent'};"
                    f" border-radius: 6px; }}"
                    f"QFrame:hover {{ background: {hover_bg}; }}"
                )
                il = QVBoxLayout(item_frame)
                il.setContentsMargins(8, 5, 8, 5)
                il.setSpacing(0)
                item_lbl = QLabel(_highlight_html(d.title, search_text, dark))
                item_lbl.setWordWrap(True)
                item_lbl.setObjectName(f"kb_lbl_{d.id}")
                item_lbl.setStyleSheet(
                    f"color: {active_fg if selected else normal_fg}; font-size: 13px;"
                    f" font-weight: {'600' if selected else 'normal'}; background: transparent;"
                )
                il.addWidget(item_lbl)
                item_frame.mousePressEvent = lambda _, demand=d: self._kb_select_demand(demand)
                self._kb_list_layout.addWidget(item_frame)

        self._kb_list_layout.addStretch()

        # Auto-select: keep existing selection or pick first
        sel = next((d for d in articles if d.id == self._kb_selected_id), None)
        if sel is None:
            self._kb_select_demand(articles[0])
        else:
            self._kb_select_demand(sel)

    def _kb_swap_content(self, new_widget: QWidget):
        """Replace right-panel content immediately (no deleteLater overlap)."""
        if self._kb_content is not None:
            self._kb_content.setParent(None)  # synchronous removal
        self._kb_content = new_widget
        self._kb_right_layout.addWidget(new_widget, 1)

    def _kb_show_placeholder(self):
        ph = QWidget()
        v = QVBoxLayout(ph)
        lbl = QLabel("Selecione um item para visualizar")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color: {'#64748B' if self._dark else '#9CA3AF'}; font-size: 14px;")
        v.addStretch()
        v.addWidget(lbl)
        v.addStretch()
        self._kb_swap_content(ph)

    def _kb_select_demand(self, demand):
        dark = self._dark
        self._kb_selected_id = demand.id

        # Sync selection highlight on left panel items
        active_bg = "#1E3A5F" if dark else "#DBEAFE"
        active_fg = "#60A5FA" if dark else "#1D4ED8"
        normal_fg = "#CBD5E1" if dark else "#334155"
        hover_bg  = "#1E293B" if dark else "#F1F5F9"
        for frame in self._kb_list_body.findChildren(QFrame):
            name = frame.objectName()
            if not name.startswith("kb_item_"):
                continue
            try:
                is_sel = int(name.split("_")[-1]) == demand.id
            except ValueError:
                continue
            frame.setStyleSheet(
                f"QFrame {{ background: {active_bg if is_sel else 'transparent'};"
                f" border-radius: 6px; }}"
                f"QFrame:hover {{ background: {hover_bg}; }}"
            )
            lbl = frame.findChild(QLabel)
            if lbl:
                lbl.setStyleSheet(
                    f"color: {active_fg if is_sel else normal_fg}; font-size: 13px;"
                    f" font-weight: {'600' if is_sel else 'normal'}; background: transparent;"
                )

        # Load full demand (with notes)
        full = self._uc.get(demand.id) or demand

        # Build new content widget (swap replaces old one synchronously)
        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(28, 16, 28, 16)
        v.setSpacing(10)

        # Header: category badge + completion date
        top_row = QHBoxLayout()
        cat_badge = BadgeLabel(full.category, "#DBEAFE", "#2563EB")
        top_row.addWidget(cat_badge)
        date_lbl = QLabel(full.last_activity.strftime("Concluída em %d/%m/%Y"))
        date_lbl.setStyleSheet(f"color: {'#64748B' if dark else '#9CA3AF'}; font-size: 12px;")
        top_row.addWidget(date_lbl)
        top_row.addStretch()
        if full.real_hours > 0:
            h_lbl = QLabel(f"{full.real_hours:.1f}h trabalhadas")
            h_lbl.setStyleSheet(f"color: {'#94A3B8' if dark else '#64748B'}; font-size: 12px;")
            top_row.addWidget(h_lbl)
        v.addLayout(top_row)

        # Title
        title_lbl = QLabel(full.title)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet("font-size: 22px; font-weight: 700;")
        v.addWidget(title_lbl)

        # Meta
        meta_parts = []
        if full.responsible:
            meta_parts.append(f"Responsável: {full.responsible}")
        meta_parts.append(f"Prazo: {full.deadline.strftime('%d/%m/%Y')}")
        if full.client:
            meta_parts.append(f"Cliente: {full.client}")
        meta_lbl = QLabel("  ·  ".join(meta_parts))
        meta_lbl.setStyleSheet(f"color: {'#64748B' if dark else '#9CA3AF'}; font-size: 12px;")
        v.addWidget(meta_lbl)

        # Tags
        if full.tags:
            tags_row = QHBoxLayout()
            for t in full.tags:
                tl = QLabel(f"#{t}")
                tl.setStyleSheet(
                    f"background: {'#334155' if dark else '#F1F5F9'};"
                    f" color: {'#94A3B8' if dark else '#64748B'};"
                    " border-radius: 10px; padding: 2px 10px; font-size: 11px;"
                )
                tags_row.addWidget(tl)
            tags_row.addStretch()
            v.addLayout(tags_row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {'#334155' if dark else '#E2E8F0'};")
        v.addWidget(sep)

        # Notes viewer (read-only rich text)
        notes_view = QTextEdit()
        notes_view.setReadOnly(True)
        notes_view.setFrameShape(QFrame.Shape.NoFrame)
        notes_view.setStyleSheet(
            f"QTextEdit {{ background: transparent;"
            f" color: {'#CBD5E1' if dark else '#1E293B'};"
            f" font-size: 14px; border: none; }}"
        )
        if full.notes and full.notes.strip():
            notes_view.setHtml(full.notes)
        elif full.description:
            notes_view.setPlainText(full.description)
        else:
            notes_view.setPlainText("Sem notas ou descrição registradas.")
        kb_query = self._kb_search.text().strip()
        if kb_query:
            highlight_matches_in_text_edit(notes_view, kb_query, dark)
        v.addWidget(notes_view, 1)

        # Open button
        btn_open = QPushButton("Abrir Detalhes")
        btn_open.setFixedHeight(34)
        btn_open.setStyleSheet(
            "QPushButton { background: #3B82F6; color: white; border: none;"
            " border-radius: 6px; padding: 0 16px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background: #2563EB; }"
        )
        btn_open.clicked.connect(lambda: self._open_demand_detail(full))
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(btn_open)
        v.addLayout(bottom)

        self._kb_swap_content(content)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _show_view(self, view_key: str):
        if self._current_view == "planning" and view_key != "planning":
            self._flush_planning_history()
        for demand_id, frame in list(self._detail_windows.items()):
            try:
                if frame.isVisible():
                    frame.hide()
                    self._add_demand_pill(demand_id, frame._title)
            except RuntimeError:
                pass
        self._current_view = view_key

        for k, v in self._views.items():
            v.setVisible(k == view_key)

        for k, btn in self._nav_buttons.items():
            btn.setProperty("active", k == view_key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._refresh_nav_icons()

        titles = {
            "dashboard": "Dashboard",
            "demands":   "Demandas",
            "kanban":    "Kanban",
            "calendar":  "Calendário",
            "reports":   "Horas Trabalhadas",
            "planning":  "Planejamento",
            "knowledge": "Base de Conhecimento",
        }
        self.page_title.setText(titles.get(view_key, ""))
        self._refresh_view(view_key)

    def _refresh_view(self, view_key: str = None):
        key = view_key or self._current_view
        if key == "dashboard":  self._refresh_dashboard()
        elif key == "demands":  self._refresh_demands()
        elif key == "kanban":   self._refresh_kanban()
        elif key == "planning": self._refresh_planning()
        elif key == "reports":  self._refresh_reports()
        elif key == "knowledge":self._refresh_knowledge()
        self._refresh_alert_count()

    def _refresh_alert_count(self):
        alerts = self._uc.get_alerts()
        due    = self._uc.get_due_reminders()
        n = len(alerts) + len(due)
        self.alert_btn.setText(f"   {n} Alerta{'s' if n != 1 else ''}")
        self.alert_btn.setStyleSheet(
            "background: #FEE2E2; color: #DC2626; font-weight: 600;" if n > 0 else ""
        )

    # ── Dialogs ───────────────────────────────────────────────────────────────

    def _client_suggestions(self) -> list:
        demands = self._uc.list_all()
        seen, result = set(), []
        for d in demands:
            v = (d.client or "").strip()
            if v and v not in seen:
                seen.add(v)
                result.append(v)
        return sorted(result, key=str.casefold)

    def _open_new_demand(self):
        dlg = DemandFormDialog(dark=self._dark, ai_service=self._ai,
                               clients=self._client_suggestions(), parent=self)
        if dlg.exec() and dlg.result_demand:
            data = dlg.result_demand
            d = self._uc.create(**data)
            if self._fs:
                self._fs.demand_root(d.id, d.title)   # cria pasta imediatamente
            self._refresh_view()
            self.statusBar().showMessage("Demanda criada com sucesso!", 3000)

    def _open_demand_detail(self, demand: Demand, open_worklogs: bool = False):
        if demand.id in self._detail_windows:
            try:
                self._restore_demand_window(demand.id)
                if open_worklogs:
                    self._detail_windows[demand.id]._dlg.open_worklogs_tab()
                return
            except RuntimeError:
                del self._detail_windows[demand.id]

        full = self._uc.get(demand.id)
        if not full:
            return

        dlg = DemandDetailDialog(
            full, self._uc, self._fs, self._ai, self._dark,
            parent=None
        )
        dlg.demand_updated.connect(lambda d: self._refresh_view())
        dlg.demand_deleted.connect(lambda id: (self._uc.delete(id), self._refresh_view()))
        dlg.edit_requested.connect(self._open_edit_demand)
        dlg.calendar_refresh.connect(self._refresh_calendar_marks)

        if open_worklogs:
            dlg.open_worklogs_tab()

        n   = len(self._detail_windows)
        w, h = 960, 700
        pw  = max(self.content_area.width(),  w + 60)
        ph  = max(self.content_area.height(), h + 60)
        x   = max(0, min((pw - w) // 2 + n * 30, pw - w))
        y   = max(0, min((ph - h) // 2 + n * 30, ph - h))

        frame = _DemandFrame(demand.id, demand.title, dlg, self._dark, parent=self.content_area)
        frame.closed.connect(self._on_frame_closed)
        frame.minimized.connect(self._on_frame_minimized)
        frame.resize(w, h)
        frame.move(x, y)
        frame._original_geom = (x, y, w, h)
        frame.show()
        frame.raise_()

        self._detail_windows[demand.id] = frame

    def _on_frame_closed(self, demand_id: int):
        self._detail_windows.pop(demand_id, None)
        self._remove_demand_pill(demand_id)

    def _on_frame_minimized(self, demand_id: int):
        frame = self._detail_windows.get(demand_id)
        if frame:
            frame.hide()
            self._add_demand_pill(demand_id, frame._title)

    def _add_demand_pill(self, demand_id: int, title: str):
        if demand_id in self._demand_pills:
            return
        dark  = self._dark
        short = (title[:18] + "…") if len(title) > 18 else title

        bg     = "#0F172A" if dark else "#F8FAFC"   # tom levemente recuado do header
        bg_hov = "#1E293B" if dark else "#F1F5F9"
        fg     = "#CBD5E1" if dark else "#334155"
        brd    = "#334155" if dark else "#E2E8F0"

        # objectName único por demand_id evita que o Qt confunda seletores
        # ao avaliar múltiplas pills simultâneas com o mesmo nome.
        pill_name = f"dp_{demand_id}"
        wrap = QFrame()
        wrap.setObjectName(pill_name)
        wrap.setFixedHeight(30)
        wrap.setMaximumWidth(210)

        def _pill_ss(bg_val, brd_val):
            return (
                f"QFrame#{pill_name} {{"
                f" background: {bg_val};"
                f" border: 1px solid {brd_val};"
                f" border-bottom-width: 0px;"
                f" border-top-left-radius: 8px;"
                f" border-top-right-radius: 8px; }}"
            )

        wrap.setStyleSheet(_pill_ss(bg, brd))
        wrap.enterEvent = lambda _e, w=wrap: w.setStyleSheet(_pill_ss(bg_hov, "#3B82F6"))
        wrap.leaveEvent = lambda _e, w=wrap: w.setStyleSheet(_pill_ss(bg, brd))

        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(2, 0, 2, 0)
        hl.setSpacing(0)

        restore_btn = QPushButton(f" {short}")
        restore_btn.setFlat(True)
        restore_btn.setToolTip(title)
        restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restore_btn.setIcon(qta.icon("fa6s.window-restore", color="#94A3B8"))
        restore_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {fg};"
            f" border: none; padding: 2px 6px; font-size: 12px; }}"
        )
        restore_btn.clicked.connect(lambda: self._restore_demand_window(demand_id))
        hl.addWidget(restore_btn, 1)

        close_btn = QPushButton()
        close_btn.setFlat(True)
        close_btn.setFixedSize(18, 18)
        close_btn.setToolTip("Fechar")
        close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        close_btn.setIcon(qta.icon("fa6s.xmark", color="#94A3B8"))
        _cb_ss_n = "QPushButton { background: transparent; border: none; border-radius: 9px; }"
        _cb_ss_h = "QPushButton { background: #EF4444;     border: none; border-radius: 9px; }"
        close_btn.setStyleSheet(_cb_ss_n)
        close_btn.enterEvent = lambda _e, b=close_btn: b.setStyleSheet(_cb_ss_h)
        close_btn.leaveEvent = lambda _e, b=close_btn: b.setStyleSheet(_cb_ss_n)
        close_btn.clicked.connect(lambda: self._close_minimized_pill(demand_id))
        hl.addWidget(close_btn)

        self._demand_pills[demand_id] = wrap
        self._demand_pills_layout.addWidget(wrap)

    def _close_minimized_pill(self, demand_id: int):
        frame = self._detail_windows.get(demand_id)
        if frame:
            frame.close()   # closeEvent -> closed signal -> _on_frame_closed limpa tudo
        else:
            self._remove_demand_pill(demand_id)

    def _remove_demand_pill(self, demand_id: int):
        pill = self._demand_pills.pop(demand_id, None)
        if pill:
            pill.setParent(None)
            pill.deleteLater()

    def _restore_demand_window(self, demand_id: int):
        frame = self._detail_windows.get(demand_id)
        if not frame:
            return
        try:
            frame.show()
            frame.raise_()
            self._remove_demand_pill(demand_id)
        except RuntimeError:
            self._detail_windows.pop(demand_id, None)
            self._remove_demand_pill(demand_id)

    def _open_edit_demand(self, demand: Demand):
        dlg = DemandFormDialog(demand, self._dark, self._ai,
                               clients=self._client_suggestions(), parent=self)
        if dlg.exec() and dlg.result_demand:
            old_title = demand.title  # guarda título antigo antes de salvar
            saved = self._uc.update(dlg.result_demand)
            # Renomeia a pasta se o título mudou
            if self._fs and saved.title != old_title:
                self._fs.rename_demand_folder(demand.id, saved.title)
            # Atualiza a janela de detalhes já aberta (se houver) — senão ela
            # continua com o título antigo e, ao mover/criar arquivos depois,
            # recria por engano a pasta que acabou de ser renomeada.
            frame = self._detail_windows.get(demand.id)
            if frame:
                try:
                    frame._dlg.refresh_demand(saved)
                except RuntimeError:
                    pass
            self._refresh_view()
            self.statusBar().showMessage("Demanda atualizada!", 3000)

    def _open_worklog_dialog(self, demand_id: int):
        demand = self._uc.get(demand_id)
        if not demand:
            return
        dlg = WorkLogDialog(demand, self._uc, self._dark, parent=self)
        dlg.logs_changed.connect(self._refresh_view)
        dlg.show()

    def _show_alerts(self):
        alerts = self._uc.get_alerts()
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Alertas ({len(alerts)})")
        dlg.setMinimumWidth(520)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)

        hdr = QLabel(f"{len(alerts)} alerta{'s' if len(alerts) != 1 else ''} ativos")
        hdr.setStyleSheet("font-size: 18px; font-weight: 700;")
        v.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        cont = QWidget()
        cl = QVBoxLayout(cont)
        cl.setSpacing(8)

        if not alerts:
            cl.addWidget(QLabel("Nenhum alerta no momento."))
        else:
            for a in alerts:
                d = a["demand"]
                frame = QFrame()
                frame.setStyleSheet(f"background: {'#0F172A' if self._dark else '#F8FAFC'}; border-radius: 8px;")
                frame.setCursor(Qt.CursorShape.PointingHandCursor)
                fl = QVBoxLayout(frame)
                fl.setContentsMargins(14, 10, 14, 10)
                title = QLabel(d.title)
                title.setStyleSheet("font-weight: 600; font-size: 13px;")
                msg   = QLabel(a["msg"])
                color = "#DC2626" if a["type"] == "overdue" else "#D97706" if a["type"] == "inactive" else "#7C3AED"
                msg.setStyleSheet(f"color: {color}; font-size: 12px;")
                fl.addWidget(title)
                fl.addWidget(msg)
                #frame.mousePressEvent = lambda ev, demand=d: (dlg.accept(), self._open_demand_detail(demand))
                def open_demand(event, demand=d):
                    dlg.accept()
                    self._open_demand_detail(demand)

                frame.mousePressEvent = open_demand

                cl.addWidget(frame)
        due_reminders = self._uc.get_due_reminders()
        for r in due_reminders:
            frame = QFrame()
            frame.setStyleSheet(f"background: {'#0F172A' if self._dark else '#FEF3C7'}; border-radius: 8px;")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(14, 10, 14, 10)
            title = QLabel(r.title)
            title.setStyleSheet("font-weight: 600; font-size: 13px; color: #D97706;")
            msg = QLabel(f"Lembrete para {r.remind_at.strftime('%d/%m/%Y')}" + (f" — {r.note}" if r.note else ""))
            msg.setStyleSheet("color: #D97706; font-size: 12px;")
            fl.addWidget(title)
            fl.addWidget(msg)
            cl.addWidget(frame)

        cl.addStretch()
        scroll.setWidget(cont)
        v.addWidget(scroll)

        close = QPushButton("Fechar")
        close.setObjectName("btn_primary")
        close.clicked.connect(dlg.accept)
        v.addWidget(close)
        dlg.exec()

    def _show_assistant(self):
        if self._assistant_dialog is None:
            self._assistant_dialog = AssistantDialog(
                self._uc,
                self._dark,
                parent=self
            )
            self._assistant_dialog.ai_service_changed.connect(self._on_ai_service_changed)

        self._assistant_dialog.show()
        self._assistant_dialog.raise_()
        self._assistant_dialog.activateWindow()

    def _on_ai_service_changed(self, new_service):
        self._ai = new_service

    # ── Search ─────────────────────────────────────────────────────────────────

    def _on_search(self, text: str):
        if self._current_view == "demands":
            self._refresh_demands()

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        self._dark = not self._dark
        QSettings("DemandFlow", "DemandFlow").setValue("dark_mode", self._dark)
        self._apply_theme()
        self._refresh_icons()
        self._preview_panel.set_dark(self._dark)
        for frame in list(self._detail_windows.values()):
            try:
                frame.set_dark(self._dark)
                frame._dlg.set_dark(self._dark)
            except RuntimeError:
                pass
        self._refresh_view()
        # Reconstrói sempre Horas e Planejamento — independente da aba ativa,
        # pois são widgets QPainter com cores hardcoded que precisam ser recriados.
        if self._current_view != "reports":
            self._refresh_reports()
        if self._current_view != "planning":
            self._refresh_planning()

    def _refresh_icons(self):
        c = "#94A3B8" if self._dark else "#64748B"
        self.alert_btn.setIcon(qta.icon("fa6s.bell", color=c))
        self._theme_btn.setIcon(qta.icon("fa6s.sun" if self._dark else "fa6s.moon", color=c))
        self._theme_btn.setText("  Tema Claro" if self._dark else "  Tema Escuro")
        self._assist_btn.setIcon(qta.icon("fa6s.robot", color=c))
        self._new_btn.setIcon(qta.icon("fa6s.plus", color="#FFFFFF"))
        if hasattr(self, "_export_pdf_btn"):
            self._export_pdf_btn.setIcon(qta.icon("fa6s.file", color="#FFFFFF"))
        if hasattr(self, "_export_xl_btn"):
            self._export_xl_btn.setIcon(qta.icon("fa6s.table", color=c))
        self._refresh_nav_icons()

    def _refresh_nav_icons(self):
        accent = "#60A5FA" if self._dark else "#3B82F6"
        normal = "#94A3B8" if self._dark else "#64748B"
        for key, btn in self._nav_buttons.items():
            color = accent if key == self._current_view else normal
            btn.setIcon(qta.icon(self._nav_icon_names[key], color=color))

    def _apply_theme(self):
        QApplication.instance().setStyleSheet(get_stylesheet(self._dark))

    # ── Auto-update ────────────────────────────────────────────────────────────

    def _build_update_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("update_banner")
        banner.setFixedHeight(44)
        banner.hide()
        h = QHBoxLayout(banner)
        h.setContentsMargins(12, 4, 12, 4)
        h.setSpacing(10)

        import qtawesome as _qta
        ic = QLabel()
        ic.setPixmap(_qta.icon("fa6s.circle-arrow-up", color="#10B981").pixmap(16, 16))
        h.addWidget(ic)

        self._update_lbl = QLabel()
        self._update_lbl.setObjectName("update_banner_lbl")
        h.addWidget(self._update_lbl, 1)

        self._update_progress = QLabel("")
        self._update_progress.setObjectName("update_banner_lbl")
        self._update_progress.hide()
        h.addWidget(self._update_progress)

        btn = QPushButton("Atualizar")
        btn.setObjectName("btn_primary")
        btn.setAutoDefault(False)
        btn.clicked.connect(self._do_update)
        self._update_btn = btn
        h.addWidget(btn)

        dismiss = QPushButton("Ignorar")
        dismiss.setObjectName("btn_secondary")
        dismiss.setAutoDefault(False)
        dismiss.clicked.connect(banner.hide)
        h.addWidget(dismiss)

        return banner

    def _start_update_check(self):
        self._checker = UpdateChecker(self)
        self._checker.update_available.connect(self._on_update_available)
        self._checker.start()

    def _on_update_available(self, version: str, url: str, notes: str):
        self._update_url = url
        self._update_version = version
        self._update_notes = notes
        self._update_lbl.setText(f"Nova versão <b>{version}</b> disponível")
        self._update_banner.show()

    def _maybe_show_whats_new(self):
        pending = pop_pending_changelog()
        if not pending:
            return
        dlg = WhatsNewDialog(pending.get("version", ""), pending.get("notes", ""),
                             dark=self._dark, parent=self)
        dlg.exec()

    def _do_update(self):
        self._update_btn.setEnabled(False)
        self._update_btn.setText("Baixando...")
        self._update_progress.show()

        self._downloader = UpdateDownloader(self._update_url, self)
        self._downloader.progress.connect(
            lambda p: self._update_progress.setText(
                "Conectando..." if p < 0 else
                "Extraindo..." if p > 100 else f"{p}%"
            )
        )
        self._downloader.ready.connect(self._on_download_ready)
        self._downloader.failed.connect(self._on_download_failed)
        self._downloader.start()

    def _on_download_ready(self, source_dir: str):
        save_pending_changelog(self._update_version, self._update_notes)
        apply_update(source_dir)

    def _on_download_failed(self, error: str):
        self._update_btn.setEnabled(True)
        self._update_btn.setText("Tentar novamente")
        self._update_progress.setText("Falhou — clique em Tentar novamente")
        QMessageBox.warning(
            self,
            "Erro ao baixar atualização",
            f"Não foi possível baixar a atualização:\n\n{error}\n\n"
            "Verifique sua conexão e tente novamente.\n"
            "Se o problema persistir, baixe manualmente em:\n"
            "github.com/julimarmj/DemandFlow/releases",
        )

    # ── Alert Timer ────────────────────────────────────────────────────────────

    def _start_alert_timer(self):
        timer = QTimer(self)
        timer.timeout.connect(self._refresh_alert_count)
        timer.timeout.connect(self._check_date_rollover)
        timer.timeout.connect(self._maybe_check_missing_hours)
        timer.start(60_000)
        self._last_known_date = date.today()
        self._refresh_alert_count()

    def _check_date_rollover(self):
        """Detecta a virada do dia com o app aberto e atualiza tudo que só
        era calculado uma vez na inicialização (cabeçalho, marcações do
        calendário, view atual)."""
        today = date.today()
        if today == self._last_known_date:
            return
        self._last_known_date = today
        self.page_subtitle.setText(_format_date_pt(today))
        self._refresh_calendar_marks()
        self._refresh_view()

    def _maybe_check_missing_hours(self):
        """Mostra o aviso de horas não registradas no dia útil anterior — uma
        vez por dia, a partir das 8h. Assim funciona tanto na abertura do
        programa quanto se ele ficar aberto durante a virada da noite."""
        now = datetime.now()
        if now.hour < 8:
            return
        today = now.date()
        if self._missing_hours_checked_date == today:
            return
        self._missing_hours_checked_date = today
        self._check_missing_hours()

    def closeEvent(self, event):
        _s = QSettings("DemandFlow", "DemandFlow")
        _s.setValue("window_geometry", self.saveGeometry())
        event.accept()
