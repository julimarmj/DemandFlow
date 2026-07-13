"""
Verificador e instalador de atualizações via GitHub Releases.

Fluxo:
  1. UpdateChecker roda em background e emite `update_available(versao, url)`.
  2. MainWindow mostra um banner; ao clicar em "Atualizar", chama `start_update()`.
  3. UpdateDownloader baixa o zip, extrai em %TEMP% e emite `ready(pasta_temp)`.
  4. MainWindow chama `apply_update(pasta_temp)` que lança updater.bat e fecha o app.
"""
import os
import sys
import json
import shutil
import zipfile
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

try:
    from version import __version__, GITHUB_REPO
except ImportError:
    __version__ = "0.0.0"
    GITHUB_REPO = ""


def _parse_version(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def _api_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class UpdateChecker(QThread):
    """Verifica silenciosamente se há nova versão no startup."""
    update_available = pyqtSignal(str, str)   # (nova_versao, download_url)

    def run(self):
        if not GITHUB_REPO:
            return
        try:
            req = urllib.request.Request(
                _api_url(),
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "DemandFlow-Updater",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            latest = data.get("tag_name", "").lstrip("v")
            if not latest:
                return

            download_url = next(
                (a["browser_download_url"] for a in data.get("assets", [])
                 if a["name"].endswith(".zip")),
                None,
            )
            if not download_url:
                return

            if _parse_version(latest) > _parse_version(__version__):
                self.update_available.emit(latest, download_url)
        except Exception:
            pass


class UpdateDownloader(QThread):
    """Baixa e extrai o zip da nova versão em background."""
    progress    = pyqtSignal(int)        # 0-100
    ready       = pyqtSignal(str)        # pasta extraída
    failed      = pyqtSignal(str)        # mensagem de erro

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        tmp_dir = tempfile.mkdtemp(prefix="DemandFlow_update_")
        zip_path = os.path.join(tmp_dir, "update.zip")
        try:
            req = urllib.request.Request(
                self._url,
                headers={"User-Agent": "DemandFlow-Updater"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk = 8192
                with open(zip_path, "wb") as f:
                    while True:
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        f.write(buf)
                        downloaded += len(buf)
                        if total:
                            self.progress.emit(int(downloaded * 100 / total))

            self.progress.emit(100)

            extract_dir = os.path.join(tmp_dir, "extracted")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # O zip deve conter uma pasta raiz "DemandFlow" — procura ela
            subdirs = [d for d in Path(extract_dir).iterdir() if d.is_dir()]
            source = str(subdirs[0]) if subdirs else extract_dir

            self.ready.emit(source)
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            self.failed.emit(str(e))


def apply_update(source_dir: str):
    """
    Lança o updater.bat em background e encerra o app.
    O bat aguarda o processo principal sair, copia os novos
    arquivos por cima dos antigos e reinicia o executável.
    """
    if getattr(sys, "frozen", False):
        dest_dir = str(Path(sys.executable).parent)
        exe_path = sys.executable
    else:
        # Em desenvolvimento não substitui nada — só avisa
        print(f"[UPDATER] Modo dev: nova versão em {source_dir}")
        return

    # Localiza o updater.bat ao lado do executável
    bat = Path(dest_dir) / "updater.bat"
    if not bat.exists():
        return

    import subprocess
    subprocess.Popen(
        [str(bat), source_dir, dest_dir, exe_path],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        close_fds=True,
    )

    from PyQt6.QtWidgets import QApplication
    QApplication.quit()
