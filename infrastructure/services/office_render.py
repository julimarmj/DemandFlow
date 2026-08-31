"""
DemandFlow - Pré-visualização de Word/Excel/PowerPoint via conversão pra PDF

Diferente da tentativa anterior (extrair texto/formatação do próprio
arquivo — abandonada por não preservar bem o layout visual original), este
módulo usa o Office DE VERDADE, instalado na máquina, via automação COM
(pywin32), pra exportar o arquivo pro PDF — a formatação sai idêntica ao
original porque é o próprio Word/Excel/PowerPoint renderizando.

Só abre o arquivo escondido (sem mostrar a janela nem tentar encaixá-la em
lugar nenhum — foi exatamente essa parte, tentada antes pra visualização
"ao vivo", que deixava processo do Word pendurado; abrir→exportar→fechar,
sem mexer na janela, testado várias vezes sem vazar nenhum processo).

Resultado fica em cache (chave = caminho absoluto + data de modificação +
tamanho do arquivo original) — a conversão em si (~4-10s, na maior parte
tempo de abrir o Office, não do tamanho do arquivo) só acontece na primeira
vez; nas próximas é um PDF já pronto. Quem chama (file_preview.py) decide
se roda convert_to_pdf numa thread separada — aqui é tudo bloqueante.

Sem Office instalado (ProgID não registrado) ou qualquer outra falha na
conversão: retorna None, sem levantar exceção — quem chama trata como "sem
pré-visualização", igual todo o resto desse módulo de preview.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".demandflow" / "cache" / "office_pdf"
_CACHE_MAX_BYTES = 300 * 1024 * 1024  # 300MB — poda os mais antigos acima disso

_EXT_APP = {
    ".doc": "word", ".docx": "word",
    ".xls": "excel", ".xlsx": "excel",
    ".ppt": "powerpoint", ".pptx": "powerpoint",
}


def is_supported(ext: str) -> bool:
    return ext.lower() in _EXT_APP


def _cache_path_for(path: str) -> Optional[Path]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = f"{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}"
    digest = hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()
    return _CACHE_DIR / f"{digest}.pdf"


def get_cached_pdf(path: str) -> Optional[str]:
    """Só consulta o cache (rápido, sem converter nada) — usado antes de
    decidir se precisa mostrar o indicador de "convertendo..."."""
    cp = _cache_path_for(path)
    if cp is None:
        return None
    try:
        return str(cp) if cp.stat().st_size > 0 else None
    except OSError:
        return None


def _prune_cache():
    try:
        files = [f for f in _CACHE_DIR.iterdir() if f.is_file() and f.suffix == ".pdf"]
    except OSError:
        return
    total = sum(f.stat().st_size for f in files if f.exists())
    if total <= _CACHE_MAX_BYTES:
        return
    files.sort(key=lambda f: f.stat().st_mtime)  # mais antigos primeiro
    for f in files:
        if total <= _CACHE_MAX_BYTES:
            break
        try:
            size = f.stat().st_size
            f.unlink()
            total -= size
        except OSError:
            pass


def convert_to_pdf(path: str) -> Optional[str]:
    """Bloqueante — rode numa thread separada, nunca na thread da UI (a
    conversão em si demora vários segundos). Retorna o caminho do PDF no
    cache (já existente ou recém-convertido), ou None."""
    if sys.platform != "win32":
        return None
    ext = Path(path).suffix.lower()
    kind = _EXT_APP.get(ext)
    if not kind:
        return None

    cached = get_cached_pdf(path)
    if cached:
        return cached

    cache_path = _cache_path_for(path)
    if cache_path is None:
        return None

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    # O nome tem que terminar em ".pdf" de verdade — testado que o Excel
    # (ExportAsFixedFormat) escreve silenciosamente NADA (sem erro, sem
    # exceção, só não cria o arquivo) se o caminho de saída não termina
    # limpo em ".pdf" — por isso o sufixo de temporário vai ANTES da
    # extensão, não depois.
    tmp_path = str(cache_path.with_suffix(f".tmp{os.getpid()}.pdf"))

    # Copia o arquivo original pra um temporário antes de abrir no Office —
    # se o arquivo já estiver aberto de verdade (o usuário editando), abrir
    # o MESMO caminho faz o Word/Excel mostrarem uma caixa de diálogo
    # perguntando "abrir uma cópia / notificar / cancelar" — visível na tela
    # do usuário do nada, e trava a conversão esperando alguém responder
    # (visto num arquivo real do usuário). DisplayAlerts=False não evita
    # essa caixa especificamente. Abrir uma cópia separada evita o conflito
    # de vez, não importa o que esteja acontecendo com o arquivo original —
    # copiar funciona mesmo com o arquivo aberto em outro programa, porque
    # Word/Excel abrem com compartilhamento de leitura.
    src_copy = None
    try:
        import shutil
        import tempfile
        fd, src_copy = tempfile.mkstemp(suffix=ext, prefix="demandflow_office_")
        os.close(fd)
        shutil.copy2(path, src_copy)
    except OSError:
        src_copy = None
    convert_path = src_copy or path

    try:
        import pythoncom
        pythoncom.CoInitialize()
        try:
            if kind == "word":
                ok = _convert_word(convert_path, tmp_path)
            elif kind == "excel":
                ok = _convert_excel(convert_path, tmp_path)
            else:
                ok = _convert_powerpoint(convert_path, tmp_path)
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        # Até agora essa falha desaparecia sem deixar rastro nenhum — o
        # usuário só via "sem pré-visualização", sem chance de saber se era
        # Office não instalado, arquivo protegido por senha, macro bloqueada,
        # documento corrompido, ou outra coisa qualquer. Loga o motivo real
        # antes de continuar tratando como "sem preview" (comportamento não
        # muda, só passa a ficar registrado o porquê).
        logger.warning("Falha ao converter '%s' (%s) para PDF via Office", path, kind, exc_info=True)
        ok = False
    finally:
        if src_copy:
            try:
                os.remove(src_copy)
            except OSError:
                pass

    if not ok or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return None

    try:
        os.replace(tmp_path, cache_path)
    except OSError:
        logger.warning("Não foi possível mover o PDF convertido pro cache ('%s')", path, exc_info=True)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return None

    _prune_cache()
    return str(cache_path)


def _convert_word(path: str, out_pdf: str) -> bool:
    import win32com.client
    app = win32com.client.DispatchEx("Word.Application")
    try:
        app.Visible = False
        app.DisplayAlerts = 0  # wdAlertsNone
        doc = app.Documents.Open(path, ReadOnly=True, AddToRecentFiles=False)
        try:
            doc.ExportAsFixedFormat(out_pdf, ExportFormat=17)  # wdExportFormatPDF
        finally:
            doc.Close(SaveChanges=False)
        return True
    finally:
        app.Quit()


def _convert_excel(path: str, out_pdf: str) -> bool:
    import win32com.client
    app = win32com.client.DispatchEx("Excel.Application")
    try:
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(path, ReadOnly=True, AddToMru=False)
        try:
            wb.ExportAsFixedFormat(0, out_pdf)  # xlTypePDF
        finally:
            wb.Close(SaveChanges=False)
        return True
    finally:
        app.Quit()


def _convert_powerpoint(path: str, out_pdf: str) -> bool:
    import win32com.client
    app = win32com.client.DispatchEx("PowerPoint.Application")
    try:
        # PowerPoint (diferente de Word/Excel) não deixa setar
        # Application.Visible = False — é documentado assim pela própria
        # Microsoft, a janela do app sempre aparece. O jeito de não abrir
        # janela nenhuma é o parâmetro WithWindow do Presentations.Open, mas
        # passando os 4 argumentos POSICIONAIS (ReadOnly/Untitled/WithWindow)
        # dava erro intermitente de marshalling do pywin32 ("The Python
        # instance can not be converted to a COM object"). Passando só esse
        # como argumento NOMEADO (os outros ficam no padrão) não reproduz o
        # erro — testado repetidas vezes. Se mesmo assim falhar por algum
        # motivo, cai pro modo antigo (janela aparece, mas minimizada, pelo
        # menos não rouba o foco) em vez de travar a conversão inteira.
        try:
            pres = app.Presentations.Open(path, WithWindow=False)
        except Exception:
            pres = app.Presentations.Open(path)
            try:
                pres.Windows(1).WindowState = 2  # ppWindowMinimized
            except Exception:
                pass
        try:
            pres.SaveAs(out_pdf, 32)  # ppSaveAsPDF
        finally:
            pres.Close()
        return True
    finally:
        app.Quit()
