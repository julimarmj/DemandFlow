
"""
DemandFlow - Janela do Assistente IA
Interface de chat completa com:
  • Streaming de respostas em tempo real
  • Histórico de conversa na sessão
  • Sugestões rápidas com um clique
  • Análise automática ao abrir
  • Configuração de API key
  • Renderização básica de markdown
"""
import re
from datetime import date
from typing import Optional
import qtawesome as qta

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QLineEdit,
    QSizePolicy, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings
from PyQt6.QtGui import QFont, QTextCursor, QColor, QPalette

from core.domain.entities import Demand
from infrastructure.services.ai_service import BaseAIService, PROVIDERS, create_ai_service
from presentation.widgets.spell_check import SpellCheckTextEdit


class _ChatInput(SpellCheckTextEdit):
    """Campo de entrada do chat: Enter envia, Shift+Enter quebra linha."""
    enter_pressed = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.enter_pressed.emit()
                return
        super().keyPressEvent(event)


# ── Worker thread para não travar a UI durante o streaming ───────────────────

class _ConnTestWorker(QThread):
    done = pyqtSignal(bool, str)   # (ok, erro)

    def __init__(self, ai: BaseAIService):
        super().__init__()
        self._ai = ai

    def run(self):
        ok, msg = self._ai.test_connection()
        self.done.emit(ok, msg)


class StreamWorker(QThread):
    chunk_received = pyqtSignal(str)
    tool_called    = pyqtSignal(str)   # nome da ferramenta sendo executada
    finished       = pyqtSignal()
    error          = pyqtSignal(str)

    def __init__(self, ai: BaseAIService, message: str, history: list,
                 context: Optional[str] = None, tool_executors: Optional[dict] = None):
        super().__init__()
        self._ai             = ai
        self._message        = message
        self._history        = history
        self._context        = context
        self._tool_executors = tool_executors
        self._aborted        = False

    def abort(self):
        self._aborted = True

    def run(self):
        print(f"[WORKER] Iniciando stream — provider: {type(self._ai).__name__} | context: {'sim' if self._context else 'não'} | tools: {list(self._tool_executors.keys()) if self._tool_executors else 'nenhuma'}")
        chunk_count = 0
        try:
            for chunk in self._ai.stream_response(
                self._message, self._history, self._context,
                tool_executors=self._tool_executors,
                on_tool_call=lambda name: self.tool_called.emit(name),
            ):
                if self._aborted:
                    break
                chunk_count += 1
                self.chunk_received.emit(chunk)
            print(f"[WORKER] Stream finalizado — {chunk_count} chunks recebidos")
            if chunk_count == 0:
                self.error.emit("A IA não gerou resposta. Tente enviar a mensagem novamente.")
            else:
                self.finished.emit()
        except Exception as e:
            print(f"[WORKER] Erro: {e}")
            self.error.emit(str(e))


# ── Bubble de mensagem ────────────────────────────────────────────────────────

class MessageBubble(QFrame):
    def __init__(self, text: str, is_user: bool, dark: bool, parent=None):
        super().__init__(parent)
        self._dark    = dark
        self._is_user = is_user
        self._build(text)

    def _build(self, text: str):
        if self._is_user:
            bg  = "#1D3461" if self._dark else "#EFF6FF"
            brd = "#2563EB" if self._dark else "#BFDBFE"
        else:
            bg  = "#0F2D1F" if self._dark else "#F0FDF4"
            brd = "#065F46" if self._dark else "#A7F3D0"

        author_color = "#60A5FA" if self._is_user else "#10B981"

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"""
            MessageBubble {{
                background: {bg};
                border: 1px solid {brd};
                border-radius: 12px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(3)

        author = QLabel("Você" if self._is_user else "🤖 Assistente IA")
        author.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {author_color}; background: transparent; border: none;")
        layout.addWidget(author)

        self.text_lbl = QLabel()
        self.text_lbl.setWordWrap(True)
        self.text_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.text_lbl.setOpenExternalLinks(False)
        self.text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_lbl.setText(self._md_to_html(text))
        self.text_lbl.setStyleSheet("font-size: 13px; background: transparent; border: none;")
        layout.addWidget(self.text_lbl)

    def set_text(self, text: str):
        self.text_lbl.setText(self._md_to_html(text))

    @staticmethod
    def _md_to_html(text: str) -> str:
        """Converte markdown básico para HTML do Qt."""
        # Escapa HTML especial primeiro
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Blocos de código ```...```
        text = re.sub(
            r"```(?:\w+)?\n?(.*?)```",
            r'<pre style="background:#1E293B;color:#E2E8F0;padding:8px;border-radius:6px;font-family:monospace;font-size:12px;">\1</pre>',
            text, flags=re.DOTALL
        )
        # Código inline `...`
        text = re.sub(
            r"`([^`]+)`",
            r'<code style="background:#334155;color:#E2E8F0;padding:1px 4px;border-radius:3px;font-family:monospace;font-size:12px;">\1</code>',
            text
        )
        # Negrito **...**
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        # Itálico *...*
        text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
        # Títulos ##
        text = re.sub(r"^## (.+)$",  r'<p style="font-size:14px;font-weight:700;margin:8px 0 4px;">\1</p>', text, flags=re.MULTILINE)
        text = re.sub(r"^### (.+)$", r'<p style="font-size:13px;font-weight:700;margin:6px 0 2px;">\1</p>', text, flags=re.MULTILINE)
        # Listas • e -
        text = re.sub(r"^[•\-] (.+)$", r'&nbsp;&nbsp;• \1', text, flags=re.MULTILINE)
        # Quebras de linha
        text = text.replace("\n", "<br>")
        return text


# ── Janela principal do Assistente ────────────────────────────────────────────

class AssistantDialog(QDialog):

    ai_service_changed = pyqtSignal(object)   # emite o novo BaseAIService ao trocar config

    def __init__(self, use_cases, dark: bool = False, parent=None):
        super().__init__(parent)
        self._uc      = use_cases
        self._dark    = dark
        self._history: list[dict] = []   # histórico para a API
        self._worker: Optional[StreamWorker] = None
        self._conn_worker: Optional[_ConnTestWorker] = None
        self._current_bubble: Optional[MessageBubble] = None
        self._current_response: str = ""
        self._ai: Optional[BaseAIService] = None
        self._provider: str = "gemini"
        self._context_injected: bool = False
        self._tool_notes: list = []

        self.setWindowTitle("Assistente IA — DemandFlow")
        self.setMinimumWidth(720)
        self.setMinimumHeight(620)
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._load_ai()
        self._build()
        if self._ai and self._ai.is_configured():
            QTimer.singleShot(200, self._run_connection_test)

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_ai(self):
        settings = QSettings("DemandFlow", "App")
        self._provider = settings.value("ai/provider", "gemini")
        key = settings.value("ai/api_key", "")
        self._ai = create_ai_service(self._provider, key) if key else None

    def _run_connection_test(self):
        if not self._ai:
            return
        self._conn_worker = _ConnTestWorker(self._ai)
        self._conn_worker.done.connect(self._on_connection_test_done)
        self._conn_worker.start()

    def _on_connection_test_done(self, ok: bool, _error_msg: str):
        color = "#10B981" if ok else "#EF4444"
        text  = "Conectado" if ok else "Chave inválida"
        self._status_dot.setStyleSheet(f"color: {color}; font-size: 16px;")
        self._status_lbl.setStyleSheet(f"font-size: 11px; color: {color};")
        self._status_lbl.setText(text)

    def _save_config(self, provider: str, key: str):
        settings = QSettings("DemandFlow", "App")
        settings.setValue("ai/provider", provider)
        settings.setValue("ai/api_key", key.strip())
        self._provider = provider
        self._ai = create_ai_service(provider, key.strip()) if key.strip() else None
        # Reseta conversa ao trocar provider/chave para não misturar históricos
        self._history.clear()
        self._context_injected = False
        self.ai_service_changed.emit(self._ai)
        # Atualiza o nome do provider no cabeçalho
        provider_name = PROVIDERS.get(provider, ("IA", ""))[0]
        self._provider_label.setText(f"Análise inteligente das suas demandas • {provider_name}")

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())

        # Config banner se não configurado
        if not (self._ai and self._ai.is_configured()):
            root.addWidget(self._make_config_banner())

        root.addWidget(self._make_suggestions_bar())
        root.addWidget(self._make_chat_area(), 1)
        root.addWidget(self._make_input_bar())

    def _make_header(self):
        hdr = QFrame()
        hdr.setStyleSheet(
            f"background: {'#1E293B' if self._dark else '#FFFFFF'};"
            f"border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 14, 24, 14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa6s.robot", color="#3B82F6").pixmap(28, 28))
        hl.addWidget(icon_lbl)

        title_block = QWidget()
        tl = QVBoxLayout(title_block)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(1)
        title = QLabel("Assistente IA")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        provider_name = PROVIDERS.get(self._provider, ("IA", ""))[0]
        self._provider_label = QLabel(f"Análise inteligente das suas demandas • {provider_name}")
        self._provider_label.setStyleSheet(f"font-size: 11px; color: {'#94A3B8' if self._dark else '#64748B'};")
        sub = self._provider_label
        tl.addWidget(title)
        tl.addWidget(sub)
        hl.addWidget(title_block)
        hl.addStretch()

        # Status indicator — começa "Verificando..." se há chave; confirmado pelo teste em background
        self._status_dot = QLabel("●")
        has_key = bool(self._ai and self._ai.is_configured())
        dot_color = "#F59E0B" if has_key else "#EF4444"
        status_text = "Verificando..." if has_key else "Sem chave API"
        self._status_dot.setStyleSheet(f"color: {dot_color}; font-size: 16px;")
        self._status_lbl = QLabel(status_text)
        self._status_lbl.setStyleSheet(
            f"font-size: 11px; color: {dot_color};"
        )
        hl.addWidget(self._status_dot)
        hl.addWidget(self._status_lbl)

        _ic = "#94A3B8" if self._dark else "#64748B"
        cfg_btn = QPushButton()
        cfg_btn.setIcon(qta.icon("fa6s.gear", color=_ic))
        cfg_btn.setToolTip("Configurar API Key")
        cfg_btn.setFixedSize(28, 28)
        cfg_btn.clicked.connect(self._show_config)
        hl.addWidget(cfg_btn)

        clr_btn = QPushButton()
        clr_btn.setIcon(qta.icon("fa6s.trash", color="#EF4444"))
        clr_btn.setToolTip("Limpar conversa")
        clr_btn.setFixedSize(28, 28)
        clr_btn.clicked.connect(self._clear_chat)
        hl.addWidget(clr_btn)

        close_btn = QPushButton()
        close_btn.setIcon(qta.icon("fa6s.xmark", color=_ic))
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self.accept)
        hl.addWidget(close_btn)

        return hdr

    def _make_config_banner(self):
        banner = QFrame()
        banner.setObjectName("config_banner_warning")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(20, 8, 20, 8)
        lbl = QLabel("⚠  Configure sua API Key para usar o assistente.")
        lbl.setObjectName("config_banner_text")
        btn = QPushButton("Configurar agora")
        btn.setObjectName("config_banner_btn")
        btn.setAutoDefault(False)
        btn.clicked.connect(self._show_config)
        bl.addWidget(lbl)
        bl.addStretch()
        bl.addWidget(btn)
        return banner

    def _make_suggestions_bar(self):
        bar = QFrame()
        bar.setStyleSheet(
            f"background: {'#0F172A' if self._dark else '#F8FAFC'};"
            f"border-bottom: 1px solid {'#334155' if self._dark else '#E2E8F0'};"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 8, 16, 8)
        bl.setSpacing(6)

        lbl = QLabel("Pergunte:")
        lbl.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {'#64748B' if self._dark else '#9CA3AF'};")
        bl.addWidget(lbl)

        suggestions = [
            ("O que fazer hoje?",       "O que devo fazer hoje? Liste as demandas mais urgentes e explique o porquê da prioridade."),
            ("Plano da semana",         "Analise minha semana e me dê um plano de execução dia a dia, considerando os prazos e prioridades."),
            ("O que está parado?",      "Quais demandas estão paradas há mais tempo e precisam de atenção? Sugira ações para desbloqueá-las."),
            ("Aproveitar dias livres",  "Quais atividades posso executar nos dias livres desta semana para adiantar trabalho importante?"),
            ("Riscos e alertas",        "Analise os principais riscos na minha lista de demandas. O que pode dar errado nas próximas 2 semanas?"),
            ("Resumo executivo",        "Faça um resumo executivo do estado atual das minhas demandas, como se fosse para apresentar para um gestor."),
        ]

        for label, prompt in suggestions:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {'#1E293B' if self._dark else '#FFFFFF'};
                    border: 1px solid {'#334155' if self._dark else '#E2E8F0'};
                    border-radius: 16px;
                    padding: 4px 12px;
                    font-size: 12px;
                    color: {'#94A3B8' if self._dark else '#64748B'};
                }}
                QPushButton:hover {{
                    background: {'#334155' if self._dark else '#EFF6FF'};
                    color: {'#60A5FA' if self._dark else '#2563EB'};
                    border-color: {'#60A5FA' if self._dark else '#93C5FD'};
                }}
            """)
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda _, p=prompt: self._send_message(p))
            bl.addWidget(btn)

        bl.addStretch()
        return bar

    def _make_chat_area(self):
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            f"background: {'#0F172A' if self._dark else '#F8FAFC'};"
        )

        self._chat_container = QWidget()
        self._chat_container.setStyleSheet(
            f"background: {'#0F172A' if self._dark else '#F8FAFC'};"
        )
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(24, 16, 24, 16)
        self._chat_layout.setSpacing(12)
        self._chat_layout.addStretch()

        self._scroll.setWidget(self._chat_container)
        return self._scroll

    def _make_input_bar(self):
        bar = QFrame()
        bar.setStyleSheet(
            f"background: {'#1E293B' if self._dark else '#FFFFFF'};"
            f"border-top: 1px solid {'#334155' if self._dark else '#E2E8F0'};"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(8)

        self._input = _ChatInput()
        self._input.setPlaceholderText("Pergunte qualquer coisa sobre suas demandas… (Enter envia, Shift+Enter quebra linha)")
        self._input.setFixedHeight(42)
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background: {'#0F172A' if self._dark else '#F8FAFC'};
                border: 1px solid {'#475569' if self._dark else '#CBD5E1'};
                border-radius: 8px;
                padding: 7px 11px;
                font-size: 13px;
                color: {'#E2E8F0' if self._dark else '#1E293B'};
            }}
            QTextEdit:focus {{
                border-color: #3B82F6;
            }}
        """)
        self._input.enter_pressed.connect(self._on_enter)
        bl.addWidget(self._input, 1)

        self._send_btn = QPushButton("  Enviar")
        self._send_btn.setIcon(qta.icon("fa6s.paper-plane", color="#FFFFFF"))
        self._send_btn.setObjectName("btn_primary")
        self._send_btn.setAutoDefault(False)
        self._send_btn.setFixedHeight(38)
        self._send_btn.clicked.connect(self._on_enter)
        bl.addWidget(self._send_btn)

        self._stop_btn = QPushButton("  Parar")
        self._stop_btn.setIcon(qta.icon("fa6s.stop", color="#EF4444"))
        self._stop_btn.setFixedHeight(38)
        self._stop_btn.setVisible(False)
        self._stop_btn.setAutoDefault(False)
        self._stop_btn.clicked.connect(self._stop_generation)
        bl.addWidget(self._stop_btn)

        return bar

    # ── Chat Logic ────────────────────────────────────────────────────────────

    def _on_enter(self):
        text = self._input.toPlainText().strip()
        if text:
            self._input.clear()
            self._send_message(text)

    def _send_message(self, text: str):
        if not (self._ai and self._ai.is_configured()):
            self._show_config()
            return

        if self._worker and self._worker.isRunning():
            return

        # Contexto injetado apenas na primeira mensagem; depois a IA usa as ferramentas
        context: Optional[str] = None
        if not self._context_injected:
            demands = self._uc.list_all()
            context = self._ai.build_context(demands)
            self._context_injected = True

        # Adiciona bubble do usuário
        self._add_bubble(text, is_user=True)
        self._history.append({"role": "user", "content": text})

        self._set_loading(True)
        self._current_response = ""
        self._current_bubble = self._add_bubble("", is_user=False)

        self._worker = StreamWorker(
            self._ai, text,
            self._history[:-1],  # histórico sem a mensagem atual
            context,
            self._make_tool_executors(),
        )
        self._worker.chunk_received.connect(self._on_chunk)
        self._worker.tool_called.connect(self._on_tool_called)
        self._worker.finished.connect(self._on_stream_done)
        self._worker.error.connect(self._on_stream_error)
        self._worker.start()

    def _make_tool_executors(self) -> dict:
        from datetime import timedelta
        svc = self._ai
        uc  = self._uc

        def get_demands():
            return svc.build_context(uc.list_all())

        def get_demand_detail(demand_id: int):
            import re as _re
            demand = uc.get(int(demand_id))
            if not demand:
                return f"Demanda com id {demand_id} não encontrada."
            lines = [
                f"DEMANDA ID:{demand.id} — {demand.title}",
                f"Status: {demand.status.label} | Prioridade: {demand.priority.label}",
                f"Prazo: {demand.deadline} | Categoria: {demand.category}",
                f"Responsável: {demand.responsible or '—'} | Cliente: {demand.client or '—'}",
                f"Horas: {demand.real_hours}/{demand.estimated_hours}h",
                f"Descrição: {demand.description or '—'}",
            ]
            if demand.tags:
                lines.append(f"Tags: {', '.join(demand.tags)}")
            if demand.notes and demand.notes.strip():
                plain_notes = _re.sub(r"<[^>]+>", " ", demand.notes)
                plain_notes = _re.sub(r"\s+", " ", plain_notes).strip()
                if plain_notes:
                    lines.append(f"\nNOTAS TÉCNICAS:\n{plain_notes}")
            comments = uc.get_comments(demand.id)
            if comments:
                lines.append(f"\nÚLTIMOS COMENTÁRIOS ({len(comments)} total):")
                for c in comments[-5:]:
                    lines.append(f"  [{c.created_at.strftime('%d/%m/%y %H:%M')}] {c.author}: {c.text}")
            milestones = uc.get_milestones(demand.id)
            if milestones:
                lines.append(f"\nMILESTONES:")
                for m in milestones:
                    done = "✓" if m.done else "○"
                    lines.append(f"  {done} {m.title} — prazo: {m.deadline}")
            logs = uc.get_work_logs(demand.id)
            if logs:
                total_h = sum(l.duration_seconds for l in logs) / 3600
                lines.append(f"\nAPONTAMENTOS ({len(logs)}, total {total_h:.1f}h):")
                for l in logs[-5:]:
                    lines.append(f"  {l.started_at.strftime('%d/%m %H:%M')} — {l.duration_display}: {l.note or '—'}")
            return "\n".join(lines)

        def get_work_logs(days: int = 7):
            from datetime import date
            all_logs = uc.get_all_work_logs()
            cutoff = date.today() - timedelta(days=int(days))
            logs = [l for l in all_logs if l.started_at.date() >= cutoff]
            if not logs:
                return f"Nenhum apontamento nos últimos {days} dias."
            total_h = sum(l.duration_seconds for l in logs) / 3600
            lines = [f"APONTAMENTOS — ÚLTIMOS {days} DIAS ({len(logs)} registros, {total_h:.1f}h total):"]
            for l in sorted(logs, key=lambda x: x.started_at, reverse=True)[:30]:
                lines.append(f"  {l.started_at.strftime('%d/%m %H:%M')} — {l.duration_display}: {l.note or '—'}")
            return "\n".join(lines)

        def get_dashboard_stats():
            stats = uc.get_dashboard_stats()
            lines = [
                f"ESTATÍSTICAS GERAIS:",
                f"  Total: {stats['total']} demandas | Ativas: {stats['open']} | Concluídas: {stats['done']}",
                f"  Atrasadas: {stats['overdue']} | Críticas: {stats['critical']} | Inativas: {stats['inactive']}",
                f"  Horas: {stats['total_hours']:.1f}h realizadas / {stats['estimated_hours']:.1f}h estimadas",
                f"\nPOR STATUS:",
            ]
            for s, count in stats["by_status"].items():
                if count:
                    lines.append(f"  {s.label}: {count}")
            lines.append(f"\nPOR PRIORIDADE:")
            for p, count in stats["by_priority"].items():
                if count:
                    lines.append(f"  {p.label}: {count}")
            lines.append(f"\nPOR CATEGORIA:")
            for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1])[:8]:
                lines.append(f"  {cat}: {count}")
            return "\n".join(lines)

        def get_alerts():
            alerts = uc.get_alerts()
            if not alerts:
                return "Nenhum alerta ativo no momento."
            lines = [f"ALERTAS ATIVOS ({len(alerts)}):"]
            for a in alerts:
                d = a["demand"]
                lines.append(f"  [{a['type'].upper()}] ID:{d.id} {d.title} — {a['msg']}")
            return "\n".join(lines)

        def change_status(demand_id: int, status: str):
            from core.domain.entities import Status as _Status
            status_map = {s.value: s for s in _Status}
            status_map.update({s.label.lower(): s for s in _Status})
            status_map.update({s.value.replace("_", " "): s for s in _Status})
            new_status = status_map.get(str(status).lower().strip())
            if new_status is None:
                valid = ", ".join(s.value for s in _Status)
                return f"Status inválido: '{status}'. Valores válidos: {valid}"
            demand = uc.change_status(int(demand_id), new_status)
            return f"Status da demanda {demand.id} ({demand.title}) alterado para '{new_status.label}'."

        def add_reminder(demand_id: int, title: str, remind_at: str, note: str = ""):
            from core.domain.entities import Reminder
            from datetime import date as _date
            try:
                parts = [int(x) for x in str(remind_at).split("-")]
                remind_date = _date(parts[0], parts[1], parts[2])
            except Exception:
                return f"Data inválida: '{remind_at}'. Use o formato YYYY-MM-DD."
            reminder = Reminder(
                id=0, demand_id=int(demand_id),
                title=str(title), remind_at=remind_date,
                note=str(note) if note else "",
            )
            saved = uc.save_reminder(reminder)
            return f"Lembrete '{saved.title}' criado para {remind_date.strftime('%d/%m/%Y')} na demanda {demand_id}."

        return {
            "get_demands":         get_demands,
            "get_demand_detail":   get_demand_detail,
            "get_work_logs":       get_work_logs,
            "get_dashboard_stats": get_dashboard_stats,
            "get_alerts":          get_alerts,
            "add_reminder":        add_reminder,
            "change_status":       change_status,
        }

    def _on_tool_called(self, tool_name: str):
        print(f"[TOOL CALL] → {tool_name}")
        labels = {
            "get_demands":         "🔧 Buscando demandas...",
            "get_demand_detail":   "🔧 Buscando detalhes da demanda...",
            "get_work_logs":       "🔧 Buscando apontamentos de horas...",
            "get_dashboard_stats": "🔧 Buscando estatísticas...",
            "get_alerts":          "🔧 Verificando alertas...",
            "add_reminder":        "🔧 Criando lembrete...",
            "change_status":       "🔧 Alterando status...",
        }
        self._add_system_note(labels.get(tool_name, f"🔧 Executando {tool_name}..."))

    def _on_chunk(self, chunk: str):
        self._current_response += chunk
        if self._current_bubble:
            self._current_bubble.set_text(self._current_response)
        self._scroll_to_bottom()

    def _on_stream_done(self):
        self._set_loading(False)
        for lbl in self._tool_notes:
            self._chat_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._tool_notes.clear()
        if self._current_response:
            self._history.append({
                "role": "assistant",
                "content": self._current_response
            })
        self._current_bubble = None
        self._current_response = ""

    def _on_stream_error(self, error: str):
        self._set_loading(False)
        for lbl in self._tool_notes:
            self._chat_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._tool_notes.clear()
        if self._current_bubble:
            self._current_bubble.set_text(f"❌ Erro: {error}")
        self._history.append({"role": "assistant", "content": f"Erro: {error}"})
        self._current_bubble = None

    def _stop_generation(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._set_loading(False)

    def _auto_analyze(self):
        """Análise automática ao abrir o assistente."""
        self._send_message(
            "Olá! Analise o estado atual das minhas demandas e me dê um briefing rápido: "
            "o que é mais urgente agora, algum risco que devo ficar de olho, e uma sugestão do que focar hoje."
        )

    # ── UI Helpers ────────────────────────────────────────────────────────────

    def _add_bubble(self, text: str, is_user: bool) -> MessageBubble:
        # Remove o stretch do final, adiciona bubble, recoloca stretch
        count = self._chat_layout.count()
        if count > 0:
            last = self._chat_layout.itemAt(count - 1)
            if last.spacerItem():
                self._chat_layout.removeItem(last)

        bubble = MessageBubble(text, is_user, self._dark)
        self._chat_layout.addWidget(bubble)
        self._chat_layout.addStretch()
        self._scroll_to_bottom()
        return bubble

    def _scroll_to_bottom(self):
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _set_loading(self, loading: bool):
        self._send_btn.setVisible(not loading)
        self._stop_btn.setVisible(loading)
        self._input.setReadOnly(loading)
        self._status_lbl.setText("Gerando..." if loading else "Conectado")
        self._status_dot.setStyleSheet(
            f"color: {'#F59E0B' if loading else '#10B981'}; font-size: 16px;"
        )

    def _add_system_note(self, text: str, temporary: bool = True):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"font-size: 11px; color: {'#64748B' if self._dark else '#94A3B8'};"
            "padding: 2px 0;"
        )
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, lbl)
        if temporary:
            self._tool_notes.append(lbl)

    def _clear_chat(self):
        self._history.clear()
        self._context_injected = False
        while self._chat_layout.count():
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._chat_layout.addStretch()

    # ── Config ────────────────────────────────────────────────────────────────

    def _show_config(self):
        from PyQt6.QtWidgets import QComboBox
        settings = QSettings("DemandFlow", "App")

        dlg = QDialog(self)
        dlg.setWindowTitle("Configurar IA")
        dlg.setMinimumWidth(480)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)

        v.addWidget(QLabel("Provedor de IA"))
        combo = QComboBox()
        for pid, (pname, _) in PROVIDERS.items():
            combo.addItem(pname, pid)
        current_idx = combo.findData(self._provider)
        if current_idx >= 0:
            combo.setCurrentIndex(current_idx)
        v.addWidget(combo)

        info = QLabel()
        info.setStyleSheet(f"font-size: 11px; color: {'#94A3B8' if self._dark else '#64748B'};")
        v.addWidget(info)

        v.addWidget(QLabel("API Key"))
        inp = QLineEdit()
        inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setPlaceholderText("Cole sua API Key aqui...")
        inp.setText(settings.value("ai/api_key", ""))
        v.addWidget(inp)

        def _update_info():
            pid = combo.currentData()
            _, url = PROVIDERS.get(pid, ("", ""))
            info.setText(f"Obtenha sua chave em {url}\nA chave é salva localmente e nunca compartilhada.")

        combo.currentIndexChanged.connect(_update_info)
        _update_info()

        show_btn = QPushButton("Mostrar/ocultar chave")
        show_btn.setAutoDefault(False)
        show_btn.clicked.connect(lambda: inp.setEchoMode(
            QLineEdit.EchoMode.Normal
            if inp.echoMode() == QLineEdit.EchoMode.Password
            else QLineEdit.EchoMode.Password
        ))
        v.addWidget(show_btn)

        btns = QHBoxLayout()
        cancel = QPushButton("Cancelar")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(dlg.reject)
        save = QPushButton("Salvar")
        save.setObjectName("btn_primary")
        save.setAutoDefault(False)
        save.clicked.connect(dlg.accept)
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(save)
        v.addLayout(btns)

        if dlg.exec():
            provider = combo.currentData()
            key = inp.text().strip()
            self._save_config(provider, key)
            if not key:
                self._status_dot.setStyleSheet("color: #EF4444; font-size: 16px;")
                self._status_lbl.setText("Sem chave API")
            else:
                self._status_dot.setStyleSheet("color: #F59E0B; font-size: 16px;")
                self._status_lbl.setText("Verificando...")
                self._run_connection_test()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
    '''
    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(2000)
        super().closeEvent(event)
    '''       
