"""
DemandFlow - Log da aplicação

Centraliza tudo relacionado a log/erro num único lugar, pra ser chamado uma
vez, bem no início do main.py:

    from infrastructure.services.logging_service import setup_logging
    setup_logging()

O que isso configura:

1. Log em arquivo (~/.demandflow/logs/demandflow.log), com rotação por
   tamanho (nunca cresce sem limite) — todo o resto do app usa
   `logging.getLogger(__name__)` normalmente e cai aqui.

2. Um `sys.excepthook` global: até agora, qualquer exceção não tratada
   dentro de um clique/ação simplesmente derrubava o app inteiro sem deixar
   nenhum rastro (nem no console, já que é um .exe sem terminal). Isso passa
   a: (a) gravar o erro completo (com a pilha de chamadas) no log, e (b)
   mostrar um aviso pro usuário em vez de fechar sem explicação nenhuma —
   na maioria dos casos o app consegue continuar rodando depois, só aquela
   ação específica que falhou.

3. Um `threading.excepthook`, pro mesmo tratamento cobrir também exceções
   que aconteçam dentro de QThreads/threads de fundo (essas não passam pelo
   sys.excepthook da thread principal).

Tudo fica só na máquina do usuário — nenhum log é enviado pra lugar nenhum.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import traceback
from pathlib import Path

_LOG_DIR = Path.home() / ".demandflow" / "logs"
_LOG_FILE = _LOG_DIR / "demandflow.log"
_MAX_BYTES = 2 * 1024 * 1024   # 2MB por arquivo
_BACKUP_COUNT = 3              # + 3 arquivos antigos (.1, .2, .3) — 8MB no total, no máximo

_configured = False


def setup_logging():
    """Idempotente — pode ser chamado mais de uma vez sem duplicar handlers."""
    global _configured
    if _configured:
        return
    _configured = True

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Sem como escrever log em arquivo — segue só com o excepthook (o
        # diálogo pro usuário continua funcionando de qualquer forma).
        pass

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        handler = logging.handlers.RotatingFileHandler(
            _LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        pass

    sys.excepthook = _handle_uncaught_exception
    threading.excepthook = _handle_thread_exception

    logging.getLogger(__name__).info("=== DemandFlow iniciado ===")


def log_file_path() -> Path:
    return _LOG_FILE


def _handle_uncaught_exception(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    logging.getLogger("uncaught").error(
        "Exceção não tratada:\n%s",
        "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
    )
    _show_error_dialog(exc_value)


def _handle_thread_exception(args):
    # args: threading.ExceptHookArgs (exc_type, exc_value, exc_traceback, thread)
    if issubclass(args.exc_type, SystemExit):
        return
    logging.getLogger("uncaught").error(
        "Exceção não tratada na thread '%s':\n%s",
        args.thread.name if args.thread else "?",
        "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
    )


def _show_error_dialog(exc_value):
    """Melhor esforço — nunca deixa o próprio aviso de erro derrubar o app."""
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        if app is None:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("DemandFlow — Erro inesperado")
        box.setText(
            "Ocorreu um erro inesperado nessa ação. O DemandFlow tenta continuar "
            "rodando normalmente — se algo parecer errado, é mais seguro fechar e "
            "abrir de novo.\n\n"
            f"Detalhes técnicos foram salvos em:\n{_LOG_FILE}"
        )
        box.setDetailedText(f"{type(exc_value).__name__}: {exc_value}")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
    except Exception:
        pass
