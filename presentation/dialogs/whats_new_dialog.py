"""
Diálogo "Novidades desta versão" — exibido uma vez, na primeira abertura
do app depois de um auto-update.
"""
import re

import qtawesome as qta
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit,
)
from PyQt6.QtCore import Qt


def _notes_to_html(notes: str) -> str:
    """Converte o corpo do release (linhas '- item') num HTML simples,
    mantendo parágrafos soltos como texto normal."""
    html_parts = []
    in_list = False
    for line in notes.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_parts.append("<ul style='margin:4px 0 12px 0; padding-left:18px;'>")
                in_list = True
            item = re.sub(r"^[-*]\s+", "", stripped)
            html_parts.append(f"<li style='margin-bottom:6px;'>{item}</li>")
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            if stripped:
                html_parts.append(f"<p style='margin:4px 0;'>{stripped}</p>")
    if in_list:
        html_parts.append("</ul>")
    return "".join(html_parts) or "<p>Sem detalhes para esta versão.</p>"


class WhatsNewDialog(QDialog):
    """Mostra as notas de uma versão recém-instalada."""

    def __init__(self, version: str, notes: str, dark: bool = False, parent=None):
        super().__init__(parent)
        self._dark = dark
        self.setWindowTitle("Novidades do DemandFlow")
        self.setMinimumWidth(460)
        self.setMinimumHeight(320)
        self._build(version, notes)

    def _build(self, version: str, notes: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame {{ background: {'#1E293B' if self._dark else '#FFFFFF'}; "
            f"border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'}; }}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 16, 24, 16)
        ic = QLabel()
        ic.setPixmap(qta.icon("fa6s.circle-arrow-up", color="#10B981").pixmap(20, 20))
        hl.addWidget(ic)
        ttl = QLabel(f"Atualizado para a versão {version}")
        ttl.setStyleSheet("font-size: 15px; font-weight: 700;")
        hl.addWidget(ttl, 1)
        root.addWidget(hdr)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setFrameShape(QFrame.Shape.NoFrame)
        text_color = "#E2E8F0" if self._dark else "#1E293B"
        bg_color = "#0F172A" if self._dark else "#FFFFFF"
        body.setStyleSheet(
            f"QTextEdit {{ background: {bg_color}; color: {text_color}; "
            f"font-size: 13px; padding: 20px 24px; border: none; }}"
        )
        body.setHtml(_notes_to_html(notes))
        root.addWidget(body, 1)

        footer = QFrame()
        footer.setObjectName("dialog_footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 12, 24, 12)
        fl.addStretch()
        ok_btn = QPushButton("  Entendi")
        ok_btn.setIcon(qta.icon("fa6s.check", color="#FFFFFF"))
        ok_btn.setObjectName("btn_primary")
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(self.accept)
        fl.addWidget(ok_btn)
        root.addWidget(footer)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(event)
