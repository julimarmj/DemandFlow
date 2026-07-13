"""
DemandFlow - Serviço de Sistema de Arquivos
"""
import os
import re
import shutil
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
        for entry in self.base_dir.iterdir():
            if entry.is_dir() and entry.name.startswith(prefix):
                return entry
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
    def _get_document_category(self, filename: str):
        name = Path(filename).stem.upper()

        matches = re.findall(r'[A-Z]\d{4}([A-Z][A-Z0-9]{2})\d+', name)

        for match in matches:
            code = match[1:]

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

    def delete_item(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        if p.is_dir():
            shutil.rmtree(str(p))
        else:
            p.unlink()

    def move_item(self, source: str, dest_dir: str) -> Path:
        """Move arquivo ou pasta para outro diretório (drag & drop interno)."""
        src = Path(source)
        dest = self._unique_dest(Path(dest_dir), src.name)
        shutil.move(str(src), str(dest))
        return dest

    def copy_item(self, source: str, dest_dir: str) -> Path:
        """Copia arquivo ou pasta para outro diretório."""
        src = Path(source)
        dest = self._unique_dest(Path(dest_dir), src.name, prefix="cópia de ")
        if src.is_dir():
            shutil.copytree(str(src), str(dest))
        else:
            shutil.copy2(str(src), str(dest))
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
