"""
DemandFlow - Serviço de Sistema de Arquivos
"""
import os
import re
import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import QFileIconProvider
from PyQt6.QtCore import QFileInfo


import ctypes
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

# GlobalAlloc
k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = ctypes.c_void_p

# GlobalLock
k32.GlobalLock.argtypes = [ctypes.c_void_p]
k32.GlobalLock.restype = ctypes.c_void_p

# GlobalUnlock
k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
k32.GlobalUnlock.restype = wintypes.BOOL

# GlobalFree
k32.GlobalFree.argtypes = [ctypes.c_void_p]
k32.GlobalFree.restype = ctypes.c_void_p

# Clipboard
u32.OpenClipboard.argtypes = [wintypes.HWND]
u32.OpenClipboard.restype = wintypes.BOOL

u32.EmptyClipboard.argtypes = []
u32.EmptyClipboard.restype = wintypes.BOOL

u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
u32.SetClipboardData.restype = wintypes.HANDLE

u32.CloseClipboard.argtypes = []
u32.CloseClipboard.restype = wintypes.BOOL

u32.GetClipboardData.argtypes = [wintypes.UINT]
u32.GetClipboardData.restype  = wintypes.HANDLE

sh32 = ctypes.WinDLL("shell32", use_last_error=True)
sh32.DragQueryFileW.argtypes = [
    wintypes.HANDLE, wintypes.UINT,
    ctypes.c_wchar_p, wintypes.UINT,
]
sh32.DragQueryFileW.restype = wintypes.UINT

# ── Exclusão via Shell (mesma API que o Explorer usa) ───────────────────────
# Path.unlink()/os.remove() chamam DeleteFileW diretamente — o Explorer usa
# IFileOperation/SHFileOperation, que passa pela Lixeira e tolera melhor
# certas condições de compartilhamento/lock passageiro. Serve de fallback
# quando o unlink direto (com retry) ainda assim dá Acesso Negado, mesmo o
# arquivo não estando realmente bloqueado (o caso "Explorer consegue, o app
# não consegue").

class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd",   wintypes.HWND),
        ("wFunc",  wintypes.UINT),
        ("pFrom",  ctypes.c_wchar_p),
        ("pTo",    ctypes.c_wchar_p),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]

sh32.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
sh32.SHFileOperationW.restype = ctypes.c_int

_FO_DELETE          = 0x0003
_FOF_SILENT         = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO      = 0x0040   # manda pra Lixeira em vez de apagar direto
_FOF_NOERRORUI      = 0x0400


def _shell_delete_to_recycle_bin(path: str) -> bool:
    """True se apagou com sucesso via Shell (Lixeira). False se a própria
    API do Shell também recusou — aí o erro é mesmo real."""
    # pFrom precisa ser terminado em \0\0 (lista de um único item).
    buf = ctypes.create_unicode_buffer(path + "\0\0")
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = _FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_wchar_p)
    op.pTo = None
    op.fFlags = _FOF_SILENT | _FOF_NOCONFIRMATION | _FOF_ALLOWUNDO | _FOF_NOERRORUI
    result = sh32.SHFileOperationW(ctypes.byref(op))
    return result == 0 and not op.fAnyOperationsAborted


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[_\-]+", "_", text)
    return text[:max_len].strip("_")


class DemandFileService:

    DEFAULT_SUBFOLDERS = ["Documentos", "Imagens", "Backups", "Emails", "Outros"]

    DOCUMENT_SUBFOLDERS = ["Projetos", "Relatorios", "Planilhas", "Notas", "Apresentacoes"]

    IMAGE_SUBFOLDERS = ["Campo", "Diagramas", "Evidencias"]

    EXT_MAP = {
        # Documentos
        ".pdf":  "Documentos/Relatorios",
        ".doc":  "Documentos/Relatorios",
        ".docx": "Documentos/Relatorios",
        ".txt":  "Documentos/Notas",
        ".md":   "Documentos/Notas",
        # Planilhas
        ".xls":  "Documentos/Projetos",
        ".xlsx": "Documentos/Projetos",
        ".csv":  "Documentos/Projetos",
        # Apresentações
        ".ppt":  "Documentos/Apresentacoes",
        ".pptx": "Documentos/Apresentacoes",
        # Imagens
        ".png":  "Imagens/Evidencias",
        ".jpg":  "Imagens/Evidencias",
        ".jpeg": "Imagens/Evidencias",
        ".bmp":  "Imagens/Evidencias",
        ".gif":  "Imagens/Evidencias",
        ".webp": "Imagens/Evidencias",
        ".svg":  "Imagens/Diagramas",
        # CAD / Engenharia
        ".dwg":  "Documentos/Projetos",
        ".dxf":  "Documentos/Projetos",
        ".step": "Documentos/Projetos",
        ".stp":  "Documentos/Projetos",
        # Compactados / Backups
        ".zip":  "Backups",
        ".rar":  "Backups",
        ".7z":   "Backups",
        # Rockwell
        ".acd":  "Backups", ".apa": "Backups",
        ".l5k":  "Backups", ".l5x": "Backups",
        ".dmk":  "Backups",
        # Siemens
        ".zap":  "Backups", ".s7p": "Backups",
        ".ap13": "Backups", ".ap14": "Backups",
        ".ap16": "Backups", ".ap17": "Backups",
        ".ap18": "Backups", ".ap19": "Backups",
        # Elipse / Ignition / InTouch
        ".prj":   "Backups", ".lib":   "Backups",
        ".gwbk":  "Backups", ".bak":   "Backups",
        ".backup":"Backups", ".app":   "Backups",
        # Emails
        ".msg":  "Emails", ".eml": "Emails",
        # Vídeos
        ".mp4":  "Imagens/Evidencias",
        ".avi":  "Imagens/Evidencias",
        ".mov":  "Imagens/Evidencias",
    }

    # Códigos documentais no nome do arquivo → subpasta dentro de Documentos/
    DOCUMENT_CODE_MAP = {
        "DF": "Relatorios",     "DC": "Relatorios",     "EV": "Relatorios",
        "ET": "Relatorios",     "ER": "Relatorios",     "KD": "Projetos",
        "KE": "Relatorios",     "KM": "Projetos",       "KT": "Relatorios",
        "LE": "Planilhas",      "LI": "Planilhas",      "LO": "Planilhas",
        "LT": "Planilhas",      "AP": "Relatorios",     "CC": "Relatorios",
        "MC": "Relatorios",     "MD": "Relatorios",     "FP": "Planilhas",
        "MF": "Relatorios",     "DM": "Projetos",       "DB": "Relatorios",
        "RT": "Relatorios",     "DE": "Projetos",       "FD": "Planilhas",
        "K0": "Projetos",       "X0": "Projetos",       "LD": "Planilhas",
        "LM": "Planilhas",
    }

    ICON_MAP = {
        ".pdf":  "📄", ".docx": "📝", ".doc":  "📝",
        ".xlsx": "📊", ".xls":  "📊", ".csv":  "📊",
        ".pptx": "📽", ".ppt":  "📽",
        ".png":  "🖼", ".jpg":  "🖼", ".jpeg": "🖼",
        ".gif":  "🖼", ".bmp":  "🖼", ".svg":  "🖼",
        ".zip":  "🗜", ".rar":  "🗜", ".7z":   "🗜",
        ".mp4":  "🎬", ".avi":  "🎬", ".mov":  "🎬",
        ".txt":  "📃", ".md":   "📃",
        ".dwg":  "📐", ".dxf":  "📐",
        ".step": "🔩", ".stp":  "🔩",
        ".msg":  "📧", ".eml":  "📧",
        ".url":  "🔗",
    }

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.icon_provider = QFileIconProvider()

    # ── Pasta da Demanda ──────────────────────────────────────────────────────

    def demand_root(self, demand_id: int, title: str) -> Path:
        folder_name = f"{demand_id:04d}_{_slugify(title)}"
        root = self.base_dir / folder_name
        root.mkdir(parents=True, exist_ok=True)

        for sub in self.DEFAULT_SUBFOLDERS:
            (root / sub).mkdir(exist_ok=True)
        for sub in self.DOCUMENT_SUBFOLDERS:
            (root / "Documentos" / sub).mkdir(parents=True, exist_ok=True)
        for sub in self.IMAGE_SUBFOLDERS:
            (root / "Imagens" / sub).mkdir(parents=True, exist_ok=True)

        return root

    def find_demand_root(self, demand_id: int) -> Optional[Path]:
        prefix = f"{demand_id:04d}_"

        def _scan() -> Optional[Path]:
            matches = [
                e for e in self.base_dir.iterdir()
                if e.is_dir() and e.name.startswith(prefix)
            ]
            if not matches:
                return None
            if len(matches) == 1:
                return matches[0]
            # Duplicata órfã (não deveria acontecer mais com o retry abaixo,
            # mas se acontecer): o bug sempre se manifesta como uma pasta nova
            # vazia criada ao lado da pasta real, que já tem os arquivos —
            # prefere quem tem mais conteúdo em vez de mtime (não confiável;
            # uma limpeza ou sincronização pode "tocar" a pasta errada) ou
            # ordem alfabética (arbitrário).
            return max(matches, key=lambda e: sum(1 for f in e.rglob("*") if f.is_file()))

        found = _scan()
        if found is not None:
            return found

        # Nada encontrado de primeira: pode ser um soluço passageiro de
        # sincronização (ex: OneDrive listando a pasta com atraso) em vez da
        # pasta realmente não existir — tenta mais duas vezes antes de deixar
        # o chamador criar uma pasta nova (o que gera duplicata órfã).
        for _ in range(2):
            time.sleep(0.3)
            found = _scan()
            if found is not None:
                return found
        return None

    def rename_demand_folder(self, demand_id: int, new_title: str) -> Optional[Path]:
        old = self.find_demand_root(demand_id)
        if not old:
            return self.demand_root(demand_id, new_title)
        new_name = f"{demand_id:04d}_{_slugify(new_title)}"
        new_path = self.base_dir / new_name
        if old == new_path:
            return new_path
        try:
            old.rename(new_path)
            return new_path
        except OSError:
            # Pasta em uso (ex: sync OneDrive) — retorna o caminho antigo sem criar novo
            return old

    # ── Roteamento automático ─────────────────────────────────────────────────

    # Prefixo comum a todo código documental: 1 letra + 4 dígitos (ex.: "B4130").
    # O código de 2 caracteres (DOCUMENT_CODE_MAP) que vem depois às vezes cola
    # direto nesse prefixo (ex.: "K1234DF0001") e às vezes tem 1 letra de
    # disciplina no meio (ex.: "B4130JX00063" — "J" de disciplina, "X0" é o
    # código real) — tenta os dois deslocamentos em vez de presumir um só.
    _DOC_PREFIX_RE = re.compile(r'[A-Z]\d{4}')

    def _get_document_category(self, filename: str):
        name = Path(filename).stem.upper()

        for pm in self._DOC_PREFIX_RE.finditer(name):
            tail = name[pm.end():]
            for offset in (0, 1):
                if offset == 1 and not (tail and tail[0].isalpha()):
                    continue   # só pula 1 caractere se for mesmo uma letra (disciplina)
                code = tail[offset:offset + 2]
                rest = tail[offset + 2:offset + 3]
                if len(code) == 2 and code[0].isalpha() and rest.isdigit():
                    if code in self.DOCUMENT_CODE_MAP:
                        return self.DOCUMENT_CODE_MAP[code]
        return None

    def _get_target_subfolder(self, src: Path) -> str:
        """
        Determina subpasta destino pela seguinte ordem de prioridade:
        1. Código documental no nome do arquivo
        2. Extensão do arquivo (EXT_MAP)
        3. Fallback: Documentos/Notas
        """
        # 1 - Código documental tem prioridade máxima
        category = self._get_document_category(src.name)
        if category:
            return f"Documentos/{category}"

        # 2 - Extensão
        ext = src.suffix.lower()
        return self.EXT_MAP.get(ext, "Documentos/Notas")

    # ── Operações de Arquivo ──────────────────────────────────────────────────

    def move_file_to_demand(
        self,
        demand_id: int,
        demand_title: str,
        source_path: str,
        target_subfolder: Optional[str] = None,
    ) -> Path:
        src = Path(source_path)
        if not src.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {source_path}")

        root = self.demand_root(demand_id, demand_title)

        if target_subfolder:
            dest_dir = root / target_subfolder
        else:
            sub = self._get_target_subfolder(src)
            dest_dir = root / sub

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = self._unique_dest(dest_dir, src.name)
        shutil.move(str(src), str(dest))
        return dest

    def add_network_link(
        self,
        demand_id: int,
        demand_title: str,
        link: str,
        subfolder: Optional[str] = None,
    ) -> Path:
        root = self.demand_root(demand_id, demand_title)
        dest_dir = root / (subfolder or "Outros")
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[\\/:*?"<>|]', "", link)[:50] or "link"
        link_file = dest_dir / f"{name}.url"
        link_file.write_text(f"[InternetShortcut]\nURL={link}\n", encoding="utf-8")
        return link_file

    # ── Operações de Pasta/Arquivo ────────────────────────────────────────────

    def create_subfolder(self, parent_path: str, name: str) -> Path:
        safe = re.sub(r'[\\/:*?"<>|]', "", name).strip()
        if not safe:
            raise ValueError("Nome de pasta inválido")
        new = Path(parent_path) / safe
        new.mkdir(parents=True, exist_ok=True)
        return new

    def rename_item(self, path: str, new_name: str) -> Path:
        p = Path(path)
        safe = re.sub(r'[\\/:*?"<>|]', "", new_name).strip()
        if not safe:
            raise ValueError("Nome inválido")
        dest = p.parent / safe
        p.rename(dest)
        return dest

    @staticmethod
    def _retry_on_lock(op, name: str, verb: str):
        """Tenta `op()` algumas vezes antes de desistir — um WinError 5
        (Acesso negado) em arquivo/pasta que o próprio usuário está mexendo
        quase sempre é um lock passageiro (antivírus escaneando, indexador do
        Windows, OneDrive sincronizando), não falta de permissão de verdade.
        Se persistir depois das tentativas, troca a mensagem crua do Windows
        por uma que diz o que fazer."""
        last_err = None
        for attempt in range(4):
            try:
                return op()
            except PermissionError as e:
                last_err = e
                if attempt < 3:
                    time.sleep(0.3 * (attempt + 1))
        raise PermissionError(
            f'Não foi possível {verb} "{name}" — o arquivo pode estar aberto em '
            f"outro programa (leitor de PDF, Word, etc.) ou sendo usado por "
            f"antivírus/sincronização. Feche-o e tente de novo."
        ) from last_err

    def delete_item(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        try:
            self._retry_on_lock(
                lambda: shutil.rmtree(str(p)) if p.is_dir() else p.unlink(),
                p.name, "excluir",
            )
        except PermissionError:
            # Fallback: mesma API do Shell que o Explorer usa pra deletar
            # (manda pra Lixeira) — tolera uma condição de compartilhamento
            # que a chamada direta (DeleteFileW, usada por Path.unlink) às
            # vezes não tolera no mesmo arquivo.
            if not _shell_delete_to_recycle_bin(str(p)):
                raise

    def move_item(self, source: str, dest_dir: str) -> Path:
        """Move arquivo ou pasta para outro diretório (drag & drop interno)."""
        src = Path(source)
        dest = self._unique_dest(Path(dest_dir), src.name)
        self._retry_on_lock(lambda: shutil.move(str(src), str(dest)), src.name, "mover")
        return dest

    def copy_item(self, source: str, dest_dir: str) -> Path:
        """Copia arquivo ou pasta para outro diretório."""
        src = Path(source)
        dest = self._unique_dest(Path(dest_dir), src.name, prefix="cópia de ")
        op = (lambda: shutil.copytree(str(src), str(dest))) if src.is_dir() \
            else (lambda: shutil.copy2(str(src), str(dest)))
        self._retry_on_lock(op, src.name, "copiar")
        return dest

    # ── Clipboard — copia para área de transferência do SO ───────────────────

    @staticmethod
    def _win32_set_cf_hdrop(paths: list[str]) -> bool:
        """
        Escreve CF_HDROP diretamente via Win32.
        Qt usa delayed-rendering (o dado só é gerado quando outra app pede),
        o que faz Teams e WhatsApp não enxergarem o arquivo.
        Com Win32 direto o dado fica imediatamente na memória do clipboard.
        """
        import sys
        if sys.platform != "win32":
            return False
        import struct, ctypes

        CF_HDROP      = 15
        GMEM_MOVEABLE = 0x0002

        # DROPFILES header (20 bytes): pFiles=20, pt=(0,0), fNC=0, fWide=1
        header     = struct.pack("<IIIII", 20, 0, 0, 0, 1)
        # Lista de caminhos: cada um terminado com \0, mais \0 extra no final
        file_bytes = "".join(p + "\0" for p in paths).encode("utf-16-le") + b"\x00\x00"
        payload    = header + file_bytes

        hmem = k32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
        if not hmem:
            raise ctypes.WinError(ctypes.get_last_error())

        ptr = k32.GlobalLock(hmem)

        if ptr is None:
            err = ctypes.get_last_error()

            print("GlobalAlloc =", hex(hmem))
            print("GlobalLock failed. LastError =", err)

            k32.GlobalFree(hmem)

            raise RuntimeError(
                f"GlobalLock falhou. LastError={err}"
            )

        ctypes.memmove(ptr, payload, len(payload))
        k32.GlobalUnlock(hmem)

        if not u32.OpenClipboard(None):
            k32.GlobalFree(hmem)
            return False
        u32.EmptyClipboard()
        ok = bool(u32.SetClipboardData(CF_HDROP, hmem))
        u32.CloseClipboard()
        return ok

    @staticmethod
    def copy_path_to_clipboard(path: str):
        """Coloca um arquivo na área de transferência — compatível com Teams e WhatsApp."""
        DemandFileService.copy_paths_to_clipboard([path])

    @staticmethod
    def copy_paths_to_clipboard(paths: list[str]):
        """Coloca um ou mais arquivos na área de transferência."""
        if not DemandFileService._win32_set_cf_hdrop(paths):
            # Fallback para macOS / Linux ou se Win32 falhar
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QMimeData, QUrl
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
            QApplication.clipboard().setMimeData(mime)

    @staticmethod
    def get_clipboard_files() -> list[str]:
        """Lê arquivos da área de transferência (do Explorer, Teams, WhatsApp, etc.)."""
        import sys
        if sys.platform == "win32":
            CF_HDROP = 15
            if u32.OpenClipboard(None):
                hmem  = u32.GetClipboardData(CF_HDROP)
                files: list[str] = []
                if hmem:
                    count = sh32.DragQueryFileW(hmem, 0xFFFFFFFF, None, 0)
                    for i in range(count):
                        buf = ctypes.create_unicode_buffer(32768)
                        sh32.DragQueryFileW(hmem, i, buf, ctypes.sizeof(buf))
                        if buf.value:
                            files.append(buf.value)
                u32.CloseClipboard()
                if files:
                    return files
        # Fallback Qt (não-Windows)
        from PyQt6.QtWidgets import QApplication
        mime = QApplication.clipboard().mimeData()
        if mime.hasUrls():
            return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        return []

    # ── Leitura de Estrutura ──────────────────────────────────────────────────

    def list_tree(self, demand_id: int, demand_title: str) -> list[dict]:
        root = self.demand_root(demand_id, demand_title)
        return [self._build_node(root, is_root=True)]

    def _build_node(self, path: Path, is_root: bool = False) -> dict:
        try:
            stat = path.stat()
            size = stat.st_size if path.is_file() else 0
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M")
        except OSError:
            size = 0
            modified = ""
        node: dict = {
            "name":     path.name,
            "path":     str(path),
            "is_dir":   path.is_dir(),
            "is_root":  is_root,
            "children": [],
            "icon":     self.icon_provider.icon(QFileInfo(str(path))),
            "size":     size,
            "modified": modified,
        }
        if path.is_dir():
            try:
                entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            except OSError:
                entries = []
            children = []
            for e in entries:
                try:
                    children.append(self._build_node(e))
                except OSError:
                    pass
            node["children"] = children
        return node

    def search_files(self, demand_id: int, demand_title: str, query: str) -> list[dict]:
        """Busca recursiva por nome de arquivo/pasta."""
        root = self.demand_root(demand_id, demand_title)
        q = query.lower().strip()
        results = []
        for p in root.rglob("*"):
            if q in p.name.lower():
                try:
                    stat = p.stat()
                    size = stat.st_size if p.is_file() else 0
                    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M")
                except OSError:
                    size = 0
                    modified = ""
                results.append({
                    "name":     p.name,
                    "path":     str(p),
                    "is_dir":   p.is_dir(),
                    "is_root":  False,
                    "children": [],
                    "icon":     self.icon_provider.icon(QFileInfo(str(p))),
                    "size":     size,
                    "modified": modified,
                    "relative": str(p.relative_to(root)),
                })
        return sorted(results, key=lambda x: (x["is_dir"], x["name"].lower()))

    def count_files(self, demand_id: int, demand_title: str) -> int:
        root = self.find_demand_root(demand_id)
        if not root:
            return 0
        return sum(1 for p in root.rglob("*") if p.is_file())

    def total_size(self, demand_id: int) -> int:
        root = self.find_demand_root(demand_id)
        if not root:
            return 0
        return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _unique_dest(dest_dir: Path, name: str, prefix: str = "") -> Path:
        """Retorna caminho sem colisão, adicionando sufixo numérico se necessário."""
        p = Path(name)
        stem, suffix = p.stem, p.suffix
        candidate = dest_dir / f"{prefix}{name}"
        i = 1
        while candidate.exists():
            candidate = dest_dir / f"{prefix}{stem} ({i}){suffix}"
            i += 1
        return candidate

    @staticmethod
    def format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 ** 2:
            return f"{size_bytes/1024:.1f} KB"
        return f"{size_bytes/1024**2:.1f} MB"

    @staticmethod
    def open_file(path: str):
        import subprocess, sys
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        if sys.platform == "win32":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])

    @staticmethod
    def open_in_explorer(path: str):
        import subprocess, sys
        p = Path(path)
        if sys.platform == "win32":
            if p.is_file():
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                os.startfile(str(p if p.is_dir() else p.parent))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p if p.is_dir() else p.parent)])
        else:
            subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)])
