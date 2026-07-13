"""
DemandFlow - Serviço Centralizado de Ícones
Todos os ícones da aplicação passam por aqui.
Suporte automático a tema claro/escuro.
Usa qtawesome quando disponível, com fallback para strings unicode.
"""
from typing import Optional
from PyQt6.QtGui import QIcon, QColor
from PyQt6.QtCore import QSize

try:
    import qtawesome as qta
    _HAS_QTA = True
except ImportError:
    _HAS_QTA = False


# ── Paleta de cores por tema ──────────────────────────────────────────────────

class IconColors:
    LIGHT = {
        "default":  "#64748B",
        "primary":  "#3B82F6",
        "success":  "#059669",
        "warning":  "#D97706",
        "danger":   "#DC2626",
        "muted":    "#94A3B8",
        "purple":   "#7C3AED",
        "white":    "#FFFFFF",
    }
    DARK = {
        "default":  "#94A3B8",
        "primary":  "#60A5FA",
        "success":  "#10B981",
        "warning":  "#F59E0B",
        "danger":   "#EF4444",
        "muted":    "#64748B",
        "purple":   "#A78BFA",
        "white":    "#FFFFFF",
    }

    @classmethod
    def get(cls, name: str, dark: bool = False) -> str:
        palette = cls.DARK if dark else cls.LIGHT
        return palette.get(name, palette["default"])


# ── Mapeamento de ícones ──────────────────────────────────────────────────────
# Formato: "nome_logico": ("fa5s.icon_name", "fallback_unicode")

_ICON_MAP = {
    # Ações gerais
    "new":          ("fa5s.plus",           "＋"),
    "edit":         ("fa5s.edit",           "✏️"),
    "delete":       ("fa5s.trash",          "🗑"),
    "save":         ("fa5s.save",           "💾"),
    "close":        ("fa5s.times",          "✕"),
    "refresh":      ("fa5s.sync-alt",       "🔄"),
    "search":       ("fa5s.search",         "🔍"),
    "filter":       ("fa5s.filter",         "⚡"),
    "settings":     ("fa5s.cog",            "⚙"),
    "copy":         ("fa5s.copy",           "📋"),
    "cut":          ("fa5s.cut",            "✂️"),
    "paste":        ("fa5s.paste",          "📥"),
    "rename":       ("fa5s.i-cursor",       "✏️"),
    "open":         ("fa5s.external-link-alt", "↗"),
    "export":       ("fa5s.file-export",    "📤"),
    "import":       ("fa5s.file-import",    "📥"),

    # Navegação
    "dashboard":    ("fa5s.th-large",       "⊞"),
    "demands":      ("fa5s.list",           "☰"),
    "kanban":       ("fa5s.columns",        "⊡"),
    "calendar":     ("fa5s.calendar-alt",   "📅"),
    "reports":      ("fa5s.chart-bar",      "📊"),
    "knowledge":    ("fa5s.book",           "📚"),

    # Status
    "alert":        ("fa5s.bell",           "🔔"),
    "alert_off":    ("fa5s.bell-slash",     "🔕"),
    "overdue":      ("fa5s.exclamation-triangle", "⚠️"),
    "blocked":      ("fa5s.ban",            "⛔"),
    "inactive":     ("fa5s.moon",           "💤"),
    "done":         ("fa5s.check-circle",   "✅"),

    # Arquivos
    "folder":       ("fa5s.folder",         "📁"),
    "folder_open":  ("fa5s.folder-open",    "📂"),
    "folder_new":   ("fa5s.folder-plus",    "📁"),
    "file":         ("fa5s.file",           "📎"),
    "file_upload":  ("fa5s.file-upload",    "📎"),
    "file_pdf":     ("fa5s.file-pdf",       "📄"),
    "file_excel":   ("fa5s.file-excel",     "📊"),
    "file_word":    ("fa5s.file-word",      "📝"),
    "file_ppt":     ("fa5s.file-powerpoint","📽"),
    "file_image":   ("fa5s.file-image",     "🖼"),
    "file_zip":     ("fa5s.file-archive",   "🗜"),
    "network":      ("fa5s.network-wired",  "🔗"),
    "link":         ("fa5s.link",           "🔗"),

    # Tempo / tracker
    "play":         ("fa5s.play",           "▶"),
    "stop":         ("fa5s.stop",           "⏹"),
    "pause":        ("fa5s.pause",          "⏸"),
    "clock":        ("fa5s.clock",          "⏱"),
    "timer":        ("fa5s.stopwatch",      "⏱"),
    "history":      ("fa5s.history",        "📋"),
    "worklog":      ("fa5s.business-time",  "⏱"),

    # Pessoas
    "user":         ("fa5s.user",           "👤"),
    "users":        ("fa5s.users",          "👥"),
    "client":       ("fa5s.building",       "🏢"),

    # IA
    "ai":           ("fa5s.robot",          "🤖"),
    "magic":        ("fa5s.magic",          "✨"),

    # Misc
    "theme_dark":   ("fa5s.moon",           "🌙"),
    "theme_light":  ("fa5s.sun",            "☀️"),
    "tag":          ("fa5s.tag",            "#"),
    "priority":     ("fa5s.exclamation",    "!"),
    "milestone":    ("fa5s.flag",           "🚩"),
    "comment":      ("fa5s.comment-alt",    "💬"),
    "note":         ("fa5s.sticky-note",    "📝"),
    "decision":     ("fa5s.check-square",   "✅"),
    "meeting":      ("fa5s.handshake",      "🤝"),
}


class IconService:
    """
    Factory central de ícones. Uso:
        icon = IconService.get("edit")
        icon = IconService.get("delete", color="danger", dark=True)
        text = IconService.text("new")  # retorna o fallback unicode
    """

    _dark: bool = False

    @classmethod
    def set_theme(cls, dark: bool):
        cls._dark = dark

    @classmethod
    def get(
        cls,
        name: str,
        color: str = "default",
        dark: Optional[bool] = None,
        size: int = 16,
    ) -> QIcon:
        is_dark = dark if dark is not None else cls._dark
        hex_color = IconColors.get(color, is_dark)

        if _HAS_QTA and name in _ICON_MAP:
            fa_name, _ = _ICON_MAP[name]
            try:
                return qta.icon(fa_name, color=hex_color)
            except Exception:
                pass

        # Fallback: ícone vazio (o texto unicode é usado diretamente no botão)
        return QIcon()

    @classmethod
    def text(cls, name: str) -> str:
        """Retorna o emoji/unicode fallback para uso em QPushButton.setText()."""
        if name in _ICON_MAP:
            return _ICON_MAP[name][1]
        return ""

    @classmethod
    def btn(cls, name: str, label: str = "", color: str = "default",
            dark: Optional[bool] = None) -> tuple[QIcon, str]:
        """Retorna (QIcon, texto) para configurar um QPushButton."""
        return cls.get(name, color, dark), label or cls.text(name)
