"""
DemandFlow - Estilos QSS
Tema profissional para PyQt6 (Light e Dark).
"""

COLORS_LIGHT = {
    "bg_primary":    "#FFFFFF",
    "bg_secondary":  "#F8FAFC",
    "bg_tertiary":   "#F1F5F9",
    "bg_sidebar":    "#FFFFFF",
    "border":        "#E2E8F0",
    "text_primary":  "#1E293B",
    "text_secondary":"#64748B",
    "text_muted":    "#94A3B8",
    "accent":        "#3B82F6",
    "accent_hover":  "#2563EB",
    "success":       "#059669",
    "warning":       "#D97706",
    "danger":        "#DC2626",
    "critical_bg":   "#FEE2E2",
    "inactive_bg":   "#FEF3C7",
    "nav_active_bg": "#EFF6FF",
    "nav_active_fg": "#3B82F6",
    "card_border":   "#E2E8F0",
}

COLORS_DARK = {
    "bg_primary":    "#1E293B",
    "bg_secondary":  "#0F172A",
    "bg_tertiary":   "#0F172A",
    "bg_sidebar":    "#1E293B",
    "border":        "#334155",
    "text_primary":  "#E2E8F0",
    "text_secondary":"#94A3B8",
    "text_muted":    "#64748B",
    "accent":        "#3B82F6",
    "accent_hover":  "#60A5FA",
    "success":       "#10B981",
    "warning":       "#F59E0B",
    "danger":        "#EF4444",
    "critical_bg":   "#450A0A",
    "inactive_bg":   "#422006",
    "nav_active_bg": "#1E3A5F",
    "nav_active_fg": "#60A5FA",
    "card_border":   "#334155",
}


def get_stylesheet(dark: bool = False) -> str:
    C = COLORS_DARK if dark else COLORS_LIGHT

    return f"""
    /* ── Global ────────────────────────────────── */
    QWidget {{
        background-color: {C['bg_secondary']};
        color: {C['text_primary']};
        font-family: 'Segoe UI', 'SF Pro Display', 'Inter', sans-serif;
        font-size: 13px;
    }}

    /* ── Main Window ─────────────────────────── */
    QMainWindow {{
        background-color: {C['bg_secondary']};
    }}

    /* ── Sidebar ─────────────────────────────── */
    #sidebar {{
        background-color: {C['bg_sidebar']};
        border-right: 1px solid {C['border']};
        padding-right: 2px;
    }}

    #logo_label {{
        color: {C['text_primary']};
        font-size: 15px;
        font-weight: 700;
    }}

    #version_label {{
        color: {C['text_muted']};
        font-size: 10px;
    }}

    /* ── Nav Buttons ─────────────────────────── */
    QPushButton#nav_btn {{
        background-color: transparent;
        border: none;
        border-radius: 8px;
        padding: 9px 14px;
        text-align: left;
        color: {C['text_secondary']};
        font-size: 13px;
        font-weight: 400;
    }}
    QPushButton#nav_btn:hover {{
        background-color: {C['bg_tertiary']};
    }}
    QPushButton#nav_btn[active="true"] {{
        background-color: {C['nav_active_bg']};
        color: {C['nav_active_fg']};
        font-weight: 600;
    }}

    /* ── Top Bar ─────────────────────────────── */
    #topbar {{
        background-color: {C['bg_primary']};
        border-bottom: 2px solid {C['border']};
    }}

    #page_title {{
        font-size: 18px;
        font-weight: 700;
        color: {C['text_primary']};
    }}

    #page_subtitle {{
        font-size: 11px;
        color: {C['text_muted']};
    }}

    /* ── Search ──────────────────────────────── */
    QLineEdit#search_input {{
        background-color: {C['bg_secondary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
        padding: 8px 12px;
        color: {C['text_primary']};
        font-size: 13px;
    }}
    QLineEdit#search_input:focus {{
        border-color: {C['accent']};
    }}

    /* ── Inputs ──────────────────────────────── */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {C['bg_secondary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
        padding: 7px 11px;
        color: {C['text_primary']};
        selection-background-color: {C['accent']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {C['accent']};
    }}

    QComboBox {{
        background-color: {C['bg_secondary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
        padding: 7px 11px;
        color: {C['text_primary']};
        min-width: 120px;
        font-size: 13px;
    }}
    QComboBox:focus {{ border-color: {C['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background-color: {C['bg_primary']};
        border: 1px solid {C['border']};
        selection-background-color: {C['accent']};
        font-size: 13px;
    }}
    QListView, QTreeView {{
        font-size: 13px;
    }}

    QSpinBox, QDoubleSpinBox {{
        background-color: {C['bg_secondary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
        padding: 7px 11px;
        color: {C['text_primary']};
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {C['accent']}; }}

    QDateEdit, QDateTimeEdit {{
        background-color: {C['bg_secondary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
        padding: 7px 11px;
        color: {C['text_primary']};
    }}
    QDateEdit:focus, QDateTimeEdit:focus {{ border-color: {C['accent']}; }}
    QDateEdit::drop-down, QDateTimeEdit::drop-down {{ border: none; }}
    QCalendarWidget {{
        background-color: {C['bg_primary']};
        color: {C['text_primary']};
        font-size: 9pt;
    }}
    QCalendarWidget QWidget {{
        font-size: 9pt;
    }}
    QCalendarWidget QAbstractItemView {{
        font-size: 9pt;
    }}

    /* ── Buttons ─────────────────────────────── */
    QPushButton {{
        background-color: {C['bg_tertiary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
        padding: 8px 16px;
        color: {C['text_secondary']};
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {C['border']};
        color: {C['text_primary']};
    }}
    QPushButton:pressed {{ background-color: {C['border']}; }}

    QPushButton#btn_primary {{
        background-color: {C['accent']};
        border: none;
        color: #FFFFFF;
        padding: 4px 12px;
    }}
    QPushButton#btn_primary:hover {{ background-color: {C['accent_hover']}; }}

    QPushButton#btn_danger {{
        background-color: {C['danger']};
        border: none;
        color: #FFFFFF;
    }}
    QPushButton#btn_danger:hover {{ background-color: #B91C1C; }}

    QPushButton#btn_success {{
        background-color: {C['success']};
        border: none;
        color: #FFFFFF;
    }}

    /* ── Scroll Bars ─────────────────────────── */
    QScrollBar:vertical {{
        background: {'#0F172A' if dark else '#F1F5F9'};
        width: 8px;
        margin: 0;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {'#475569' if dark else '#CBD5E1'};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {'#64748B' if dark else '#94A3B8'};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    QScrollBar:horizontal {{
        background: {'#0F172A' if dark else '#F1F5F9'};
        height: 8px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {'#475569' if dark else '#CBD5E1'};
        border-radius: 4px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {'#64748B' if dark else '#94A3B8'};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

    /* ── Cards ───────────────────────────────── */
    QFrame#card {{
        background-color: {C['bg_primary']};
        border: 1px solid {C['card_border']};
        border-radius: 12px;
    }}

    /* ── Table ───────────────────────────────── */
    QTableWidget {{
        background-color: {C['bg_primary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
        gridline-color: {C['border']};
        alternate-background-color: {C['bg_secondary']};
        outline: none;
    }}
    QTableWidget::item {{
        padding: 8px;
        border: none;
    }}
    QTableWidget::item:selected {{
        background-color: {C['nav_active_bg']};
        color: {C['nav_active_fg']};
    }}
    QTableWidget::item:focus {{
        outline: none;
        border: none;
    }}
    QHeaderView::section {{
        background-color: {C['bg_secondary']};
        color: {C['text_secondary']};
        font-weight: 600;
        font-size: 11px;
        padding: 8px;
        border: none;
        border-bottom: 1px solid {C['border']};
    }}

    /* ── Tab Widget ──────────────────────────── */
    QTabWidget::pane {{
        border: 1px solid {C['border']};
        border-radius: 8px;
        background-color: {C['bg_primary']};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {C['text_secondary']};
        padding: 8px 16px;
        border: none;
        font-size: 13px;
    }}
    QTabBar::tab:selected {{
        color: {C['accent']};
        border-bottom: 2px solid {C['accent']};
        font-weight: 600;
    }}
    QTabBar::tab:hover {{ color: {C['text_primary']}; }}

    /* ── Labels ──────────────────────────────── */
    QLabel {{
        background-color: transparent;
        color: {C['text_primary']};
    }}
    QLabel#label_muted {{
        color: {C['text_muted']};
        font-size: 11px;
    }}
    QLabel#label_section {{
        color: {C['text_secondary']};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1px;
    }}

    /* ── Splitter ─────────────────────────────── */
    QSplitter::handle {{
        background-color: {C['border']};
        width: 1px;
    }}

    /* ── Progress Bar ────────────────────────── */
    QProgressBar {{
        border: none;
        border-radius: 4px;
        background-color: {C['bg_tertiary']};
        height: 6px;
        text-align: center;
        font-size: 1px;
    }}
    QProgressBar::chunk {{
        background-color: {C['accent']};
        border-radius: 4px;
    }}

    /* ── Message Box ─────────────────────────── */
    QMessageBox {{
        background-color: {C['bg_primary']};
    }}
    QMessageBox QLabel {{
        color: {C['text_primary']};
    }}

    /* ── Dialog ──────────────────────────────── */
    QDialog {{
        background-color: {C['bg_primary']};
    }}

    /* ── Tooltip ─────────────────────────────── */
    QToolTip {{
        background-color: {C['bg_primary']};
        color: {C['text_primary']};
        border: 1px solid {C['border']};
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
    }}

    /* ── Status Bar ──────────────────────────── */
    QStatusBar {{
        background-color: {C['bg_primary']};
        color: {C['text_muted']};
        border-top: 1px solid {C['border']};
        font-size: 11px;
    }}

    /* ── List Widget ─────────────────────────── */
    QListWidget {{
        background-color: {C['bg_primary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
    }}
    QListWidget::item {{
        padding: 6px 10px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background-color: {C['nav_active_bg']};
        color: {C['nav_active_fg']};
    }}
    QListWidget::item:hover {{
        background-color: {C['bg_tertiary']};
    }}

    QLabel#kanban_title {{
        color: {C['text_primary']};
        font-size: 13px;
        font-weight: 600;
    }}

    QLabel#kanban_meta {{
        font-size: 11px;
        color: #64748B;
    }}

    QLabel#kanban_deadline {{
        font-size: 11px;
        font-weight: 600;
        color: #3B82F6;
    }}

    QLabel#kanban_overdue {{
        background-color: {C['critical_bg']};
        color: {C['danger']};
        border-radius: 6px;
        padding: 2px 6px;
        font-size: 10px;
        font-weight: 700;
    }}

    /* ── Dialog Header / Footer ──────────────────────────────────────────── */
    QFrame#dialog_header {{
        background-color: {C['bg_primary']};
        border-bottom: 1px solid {C['border']};
    }}
    QFrame#dialog_footer {{
        background-color: {C['bg_secondary']};
        border-top: 1px solid {C['border']};
    }}

    /* ── Dialog Typography ───────────────────────────────────────────────── */
    QLabel#dialog_title {{
        font-size: 20px;
        font-weight: 700;
        color: {C['text_primary']};
        background: transparent;
    }}
    QLabel#dialog_subtitle {{
        font-size: 11px;
        color: {C['text_muted']};
        background: transparent;
    }}

    /* ── Icon Buttons (28×28, transparent) ──────────────────────────────── */
    QPushButton#btn_icon {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 4px;
        min-width: 28px; max-width: 28px;
        min-height: 28px; max-height: 28px;
    }}
    QPushButton#btn_icon:hover {{
        background-color: {C['bg_tertiary']};
    }}
    QPushButton#btn_icon_danger {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 4px;
        min-width: 28px; max-width: 28px;
        min-height: 28px; max-height: 28px;
    }}
    QPushButton#btn_icon_danger:hover {{
        background-color: {C['critical_bg']};
    }}

    /* ── Chip Buttons ────────────────────────────────────────────────────── */
    QPushButton#btn_chip {{
        background-color: {C['bg_tertiary']};
        color: {C['text_secondary']};
        border: none;
        border-radius: 4px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 500;
    }}
    QPushButton#btn_chip:hover {{
        background-color: {C['accent']};
        color: #FFFFFF;
    }}

    /* ── Badge / Pill (contagem, tags) ──────────────────────────────────── */
    QLabel#badge_count {{
        border-radius: 10px;
        padding: 1px 8px;
        font-size: 11px;
        font-weight: 600;
    }}

    /* ── Update Banner ──────────────────────────────────────────────────── */
    QFrame#update_banner {{
        background-color: {'#ECFDF5' if not dark else '#052e16'};
        border-bottom: 1px solid {'#6EE7B7' if not dark else '#166534'};
    }}
    QLabel#update_banner_lbl {{
        color: {'#065F46' if not dark else '#6EE7B7'};
        font-size: 12px;
        background: transparent;
    }}
    QPushButton#btn_secondary {{
        background-color: {C['bg_tertiary']};
        border: 1px solid {C['border']};
        color: {C['text_primary']};
        border-radius: 6px;
        padding: 4px 12px;
        font-size: 13px;
    }}
    QPushButton#btn_secondary:hover {{ background-color: {C['border']}; }}

    /* ── Warning Config Banner ───────────────────────────────────────────── */
    QFrame#config_banner_warning {{
        background-color: {'#FEF3C7' if not dark else '#422006'};
        border-bottom: 1px solid {'#FCD34D' if not dark else '#78350F'};
    }}
    QLabel#config_banner_text {{
        color: {'#92400E' if not dark else '#FCD34D'};
        font-size: 12px;
        background: transparent;
    }}
    QPushButton#config_banner_btn {{
        background-color: {'#D97706' if not dark else '#F59E0B'};
        color: white;
        border: none;
        border-radius: 8px;
        padding: 4px 12px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton#config_banner_btn:hover {{
        background-color: {'#B45309' if not dark else '#D97706'};
    }}

    /* ── AI Prompt Popup ─────────────────────────────────────────────────── */
    QFrame#ai_prompt_popup {{
        background-color: {C['bg_primary']};
        border: 1px solid {C['accent']};
        border-radius: 8px;
    }}
    QFrame#ai_prompt_popup QLabel {{
        color: {C['text_muted']};
        font-size: 11px;
        background: transparent;
    }}
    QFrame#ai_prompt_popup QLineEdit {{
        background-color: {C['bg_secondary']};
        color: {C['text_primary']};
        border: 1px solid {C['border']};
        border-radius: 8px;
        padding: 7px 11px;
        font-size: 13px;
    }}
    QFrame#ai_prompt_popup QLineEdit:focus {{
        border-color: {C['accent']};
    }}

    /* ── Spell Check Suggestion Popup ────────────────────────────────────── */
    QFrame#suggestion_popup {{
        background-color: {C['bg_primary']};
        border: 1px solid {C['border']};
        border-radius: 6px;
    }}
    QLabel#suggestion_header {{
        color: {C['text_muted']};
        font-size: 10px;
        padding: 4px 12px 2px 12px;
        background: transparent;
    }}
    QPushButton#suggestion_item {{
        background: transparent;
        color: {C['text_primary']};
        border: none;
        padding: 5px 14px;
        text-align: left;
        font-size: 12px;
        border-radius: 4px;
        min-width: 110px;
    }}
    QPushButton#suggestion_item:hover {{
        background-color: {C['accent']};
        color: #FFFFFF;
    }}

    /* ── Reminder Calendar Item ──────────────────────────────────────────── */
    QFrame#reminder_cal_item {{
        background-color: {'#FAF5FF' if not dark else '#2E1065'};
        border-left: 3px solid #C084FC;
        border-radius: 8px;
    }}
    QFrame#reminder_cal_item:hover {{
        background-color: {'#F3E8FF' if not dark else '#3B0764'};
    }}
    """

    
