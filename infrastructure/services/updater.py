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
import ssl
import json
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

def _no_verify_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def _pac_proxies(url: str):
    """Resolve o proxy avaliando o script PAC/WPAD configurado no Windows
    (AutoConfigURL), do mesmo jeito que o navegador faz. Cobre redes onde não
    há proxy fixo em variável de ambiente nem no registro (ProxyServer vazio
    com ProxyEnable=0) — só o .pac dita o proxy correto por domínio. Retorna
    None se não houver PAC configurado ou a resolução falhar."""
    try:
        import pypac
        pac = pypac.get_pac(timeout=8)
        if pac is None:
            return None
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        result = pac.find_proxy_for_url(url, host)
        for entry in result.split(";"):
            entry = entry.strip()
            if entry.upper().startswith("PROXY "):
                addr = entry[6:].strip()
                return {"http": f"http://{addr}", "https": f"http://{addr}"}
        return None
    except Exception:
        return None

def _urlopen(req, timeout=10):
    """Tenta, em ordem: (1) conexão direta/SSL normal; (2) proxy do sistema via
    ProxyHandler (variável de ambiente ou registro estático); (3) proxy
    resolvido via PAC/WPAD.  Redes corporativas podem bloquear
    objects.githubusercontent.com em conexão direta mas liberar via proxy — e
    algumas máquinas só têm o proxy configurado por script .pac, sem variável
    de ambiente nem registro estático, daí a etapa 3.

    As duas primeiras tentativas usam um timeout curto: quando a rede bloqueia
    de verdade (WinError 10060), o SO só desiste depois do timeout completo —
    sem isso, um download de 300s ficaria "pendurado" até 2x nesse valor antes
    de chegar na tentativa que de fato funciona."""
    probe = min(timeout, 8)

    try:
        return urllib.request.urlopen(req, timeout=probe)
    except Exception:
        pass

    ctx = _no_verify_ctx()
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(),          # lê proxy do sistema/env
            urllib.request.HTTPSHandler(context=ctx),
        )
        return opener.open(req, timeout=probe)
    except Exception:
        pass

    proxies = _pac_proxies(req.full_url)
    if not proxies:
        raise RuntimeError(
            "Não foi possível conectar (conexão direta, proxy do sistema e PAC falharam)"
        )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies),
        urllib.request.HTTPSHandler(context=ctx),
    )
    return opener.open(req, timeout=timeout)   # tempo cheio pra tentativa que deve funcionar

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
            with _urlopen(req, timeout=10) as resp:
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

    def _download_urllib(self, zip_path: str):
        req = urllib.request.Request(
            self._url, headers={"User-Agent": "DemandFlow-Updater"}
        )
        with _urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(zip_path, "wb") as f:
                while True:
                    buf = resp.read(8192)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    if total:
                        self.progress.emit(int(downloaded * 100 / total))

    def _download_powershell(self, zip_path: str):
        """Fallback via PowerShell/WinINet: suporta proxy PAC e autenticação NTLM,
        igual ao navegador — resolve WinError 10060 em redes corporativas."""
        cmd = (
            "[Net.ServicePointManager]::SecurityProtocol = "
            "[Net.SecurityProtocolType]::Tls12; "
            f'Invoke-WebRequest -Uri "{self._url}" '
            f'-OutFile "{zip_path}" -UseBasicParsing'
        )
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass",
             "-NonInteractive", "-Command", cmd],
            capture_output=True,
            timeout=350,
        )
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(err or "Falha no download via PowerShell")

    def run(self):
        tmp_dir = tempfile.mkdtemp(prefix="DemandFlow_update_")
        zip_path = os.path.join(tmp_dir, "update.zip")
        self.progress.emit(-1)   # sinaliza fase de conexão (antes de saber o tamanho)
        try:
            try:
                self._download_urllib(zip_path)
            except Exception:
                # Rede corporativa com proxy PAC/NTLM: urllib não consegue
                # autenticar via WinINet; PowerShell usa o mesmo stack do navegador.
                self.progress.emit(0)
                self._download_powershell(zip_path)

            self.progress.emit(100)
            self.progress.emit(101)   # sinaliza fase de extração

            extract_dir = os.path.join(tmp_dir, "extracted")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Se o zip tem arquivos na raiz (nosso formato: exe + _internal/)
            # usa extract_dir diretamente. Só entra na subpasta se o zip
            # tiver UMA única pasta e nenhum arquivo na raiz.
            files_at_root = [f for f in Path(extract_dir).iterdir() if f.is_file()]
            subdirs = [d for d in Path(extract_dir).iterdir() if d.is_dir()]
            if not files_at_root and len(subdirs) == 1:
                source = str(subdirs[0])
            else:
                source = extract_dir

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

    # Localiza o updater.bat: em builds --onedir fica em _internal/
    meipass = Path(getattr(sys, "_MEIPASS", dest_dir))
    bat = meipass / "updater.bat"
    if not bat.exists():
        bat = Path(dest_dir) / "updater.bat"
    if not bat.exists():
        return

    subprocess.Popen(
        [str(bat), source_dir, dest_dir, exe_path],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        close_fds=True,
    )

    from PyQt6.QtWidgets import QApplication
    QApplication.quit()
