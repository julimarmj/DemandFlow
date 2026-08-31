"""
DemandFlow - Painel de Pré-visualização de Arquivo
Mesmo padrão visual/comportamental do DemandPreviewPanel (common_widgets.py):
card com cabeçalho + botão fechar, aparece ao selecionar um item e fica
visível até o usuário fechar.
"""
from __future__ import annotations  # Python 3.9: permite "X | None" nas anotações

from pathlib import Path

import qtawesome as qta
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QWidget, QPlainTextEdit, QSizePolicy, QGraphicsView, QGraphicsScene,
)
from PyQt6.QtGui import QPixmap, QDesktopServices, QPainter, QColor
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QThread
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtSvgWidgets import QGraphicsSvgItem

from infrastructure.services.file_service import DemandFileService
from infrastructure.services.dwg_preview import extract_dwg_thumbnail
from infrastructure.services.dwg_render import render_dwg_to_svg
from infrastructure.services import office_render

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
_PDF_EXTS   = {".pdf"}
_TEXT_EXTS  = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".ini", ".yaml", ".yml",
    ".py", ".js", ".css", ".html", ".htm", ".bat", ".ps1", ".sql",
}
_DWG_EXTS    = {".dwg"}
_OFFICE_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
# Teto de leitura pra texto — evita travar a UI abrindo um log gigante inteiro.
_TEXT_PREVIEW_MAX_BYTES = 300_000

# QtPdf é opcional em tempo de execução (mesmo estando sempre presente no
# PyQt6 >= 6.4) — importa isolado pra o preview de outros tipos continuar
# funcionando mesmo se, por algum motivo, o módulo não estiver disponível.
try:
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPdfWidgets import QPdfView
    _HAS_PDF = True
except ImportError:
    _HAS_PDF = False


class _OfficeConvertWorker(QThread):
    """Roda a conversão Office -> PDF (COM automation, alguns segundos) fora
    da thread da UI — sem isso o app inteiro travaria durante a conversão."""

    finished_convert = pyqtSignal(str, object)  # caminho original, caminho do PDF (ou None)

    def __init__(self, path: str):
        super().__init__()  # sem parent: não acoplado ao ciclo de vida do widget
        self._path = path

    def run(self):
        try:
            result = office_render.convert_to_pdf(self._path)
        except Exception:
            result = None
        self.finished_convert.emit(self._path, result)


class _SvgPreviewWidget(QGraphicsView):
    """Mostra um SVG preservando a proporção (letterbox via fitInView), num
    fundo branco ou preto ESCOLHIDO POR ARQUIVO (não pelo tema do app) — o
    dwg2SVG colore as entidades assumindo o viewport escuro clássico do
    AutoCAD, e muito desenho real usa branco como cor "padrão" de traço
    (confirmado com arquivo real: 94% dos traços de um DWG de teste eram
    brancos — em fundo branco fixo ficavam invisíveis; mas um fundo preto
    fixo incomoda visualmente nos desenhos que já usam cores normais).
    dwg_render.py decide a cor de fundo pra cada arquivo e já reescreve
    qualquer traço/preenchimento que ficaria invisível nela. QGraphicsView +
    QGraphicsSvgItem em vez de desenhar o SVG à mão num paintEvent
    customizado: testado que essa combinação evita um crash nativo do Qt
    (visto ao usar QSvgRenderer.render() direto num paintEvent de widget
    filho, fora do topo da hierarquia).

    Zoom com a roda do mouse (centrado no cursor) + arrastar pra navegar +
    duplo clique pra voltar ao enquadramento padrão — é vetorial (SVG de
    verdade, não uma imagem), então dar zoom REVELA mais nitidez/detalhe de
    verdade, não só amplia pixels borrados."""

    _MAX_ZOOM_OVER_FIT = 25.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gscene = QGraphicsScene(self)
        self.setScene(self._gscene)
        self._item: QGraphicsSvgItem | None = None
        self._renderer: QSvgRenderer | None = None
        self._fit_scale = 1.0
        self._zoomed = False
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                             | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(Qt.GlobalColor.white)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setToolTip("Roda do mouse: zoom · arrastar: navegar · duplo clique: enquadrar de novo")

    def load(self, svg_bytes: bytes, background: str = "#ffffff"):
        self.setBackgroundBrush(QColor(background))
        self._gscene.clear()
        self._item = None
        renderer = QSvgRenderer(svg_bytes)
        if not renderer.isValid():
            self._renderer = None
            return
        self._renderer = renderer
        item = QGraphicsSvgItem()
        item.setSharedRenderer(self._renderer)
        self._gscene.addItem(item)
        self._gscene.setSceneRect(item.boundingRect())
        self._item = item
        self._fit()

    def _fit(self):
        if self._item is not None:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
            self._fit_scale = self.transform().m11()
        self._zoomed = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._zoomed:
            self._fit()

    def wheelEvent(self, event):
        if self._item is None:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.0015 ** delta
        current = self.transform().m11()
        target = current * factor
        min_scale = self._fit_scale
        max_scale = self._fit_scale * self._MAX_ZOOM_OVER_FIT
        if target < min_scale:
            factor = min_scale / current
        elif target > max_scale:
            factor = max_scale / current
        if factor != 1.0:
            self.scale(factor, factor)
            self._zoomed = abs(self.transform().m11() - self._fit_scale) > self._fit_scale * 0.01
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self._fit()
        event.accept()


class FilePreviewPanel(QFrame):
    """Pré-visualização de imagem/PDF/texto/DWG (renderização real via
    dwg2SVG quando possível, com a miniatura embutida no arquivo como
    segunda opção) e Word/Excel/PowerPoint (convertido pro PDF de verdade
    via o Office instalado na máquina, com cache — ver office_render.py);
    sem Office instalado ou qualquer outro tipo mostram um aviso com atalho
    pra abrir no programa padrão do Windows.

    Emite expand_toggled(True/False) quando o botão de expandir (ao lado
    do de fechar) é clicado — quem incorpora este painel decide o que
    "expandir" significa (ex.: FileManagerWidget escondendo a árvore e a
    barra de busca, DemandDetailDialog escondendo o cabeçalho e as abas)."""

    expand_toggled = pyqtSignal(bool)

    def __init__(self, dark: bool = False, parent=None):
        super().__init__(parent)
        self._dark = dark
        self._current_path = None
        self._expanded = False
        self._office_worker: _OfficeConvertWorker | None = None
        self.setObjectName("card")
        self.setMinimumWidth(280)
        self._build()

    # ── Build ────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        self._icon_lbl = QLabel()
        hdr.addWidget(self._icon_lbl)
        self._title_lbl = QLabel("—")
        self._title_lbl.setStyleSheet("font-size: 13px; font-weight: 700;")
        self._title_lbl.setWordWrap(True)
        hdr.addWidget(self._title_lbl, 1)

        self._expand_btn = QPushButton()
        self._expand_btn.setFixedSize(24, 24)
        self._expand_btn.setStyleSheet("border: none; background: transparent;")
        self._expand_btn.setAutoDefault(False)
        self._expand_btn.setToolTip("Expandir pré-visualização")
        self._expand_btn.clicked.connect(self._toggle_expand)
        hdr.addWidget(self._expand_btn)

        self._close_btn = QPushButton()
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setStyleSheet("border: none; background: transparent;")
        self._close_btn.setAutoDefault(False)
        self._close_btn.clicked.connect(self._on_close)
        hdr.addWidget(self._close_btn)
        root.addLayout(hdr)

        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(self._sep)
        self._apply_theme_colors()

        # ── Páginas de conteúdo ──────────────────────────────────────────────
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        # Imagem (também usada pra miniatura embutida de DWG, com legenda)
        img_page = QWidget()
        img_page_layout = QVBoxLayout(img_page)
        img_page_layout.setContentsMargins(0, 0, 0, 0)
        img_page_layout.setSpacing(4)
        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._img_pixmap = None
        img_page_layout.addWidget(self._img_lbl, 1)
        self._img_caption_lbl = QLabel("")
        self._img_caption_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_caption_lbl.setWordWrap(True)
        self._img_caption_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self._img_caption_lbl.setVisible(False)
        img_page_layout.addWidget(self._img_caption_lbl)
        self._img_page_idx = self._stack.addWidget(img_page)

        # DWG renderizado de verdade (via dwg2SVG) — vetor, fundo branco fixo
        self._svg_widget = _SvgPreviewWidget()
        self._svg_page_idx = self._stack.addWidget(self._svg_widget)

        # PDF
        if _HAS_PDF:
            self._pdf_doc = QPdfDocument(self)
            self._pdf_view = QPdfView(self)
            self._pdf_view.setDocument(self._pdf_doc)
            self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self._pdf_page_idx = self._stack.addWidget(self._pdf_view)
        else:
            self._pdf_doc = None
            self._pdf_page_idx = -1

        # Texto
        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self._text_page_idx = self._stack.addWidget(self._text_view)

        # Convertendo Office -> PDF (pode levar alguns segundos — quase todo
        # esse tempo é abrir o Office, não o tamanho do arquivo)
        converting = QWidget()
        cv_layout = QVBoxLayout(converting)
        cv_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cv_layout.setSpacing(12)
        cv_icon = QLabel()
        cv_icon.setPixmap(qta.icon("fa6s.file-pdf", color="#94A3B8").pixmap(40, 40))
        cv_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cv_layout.addWidget(cv_icon)
        cv_msg = QLabel("Convertendo para PDF...")
        cv_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cv_msg.setStyleSheet("color: #94A3B8; font-size: 12px;")
        cv_layout.addWidget(cv_msg)
        self._converting_page_idx = self._stack.addWidget(converting)

        # Fallback (sem preview)
        fallback = QWidget()
        fb_layout = QVBoxLayout(fallback)
        fb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fb_layout.setSpacing(12)
        fb_icon = QLabel()
        fb_icon.setPixmap(qta.icon("fa6s.file", color="#94A3B8").pixmap(48, 48))
        fb_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fb_layout.addWidget(fb_icon)
        fb_msg = QLabel("Sem pré-visualização disponível\npara este tipo de arquivo.")
        fb_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fb_msg.setStyleSheet("color: #94A3B8; font-size: 12px;")
        fb_layout.addWidget(fb_msg)
        self._fb_open_btn = QPushButton("  Abrir com programa padrão")
        self._fb_open_btn.setIcon(qta.icon("fa6s.arrow-up-right-from-square", color="white"))
        self._fb_open_btn.setObjectName("btn_primary")
        self._fb_open_btn.setAutoDefault(False)
        self._fb_open_btn.clicked.connect(self._open_externally)
        fb_layout.addWidget(self._fb_open_btn, 0, Qt.AlignmentFlag.AlignCenter)
        self._fallback_page_idx = self._stack.addWidget(fallback)

        # Erro (arquivo não pôde ser lido/renderizado)
        self._error_lbl = QLabel("")
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setStyleSheet("color: #EF4444; font-size: 12px;")
        self._error_page_idx = self._stack.addWidget(self._error_lbl)

    # ── Carregamento ─────────────────────────────────────────────────────────

    def load_file(self, path: str):
        self._current_path = path
        p = Path(path)
        self._title_lbl.setText(p.name)
        self._title_lbl.setToolTip(path)
        icon_name = DemandFileService.ICON_MAP.get(p.suffix.lower(), "📄")
        self._icon_lbl.setText(icon_name)

        ext = p.suffix.lower()
        try:
            if ext in _IMAGE_EXTS:
                self._load_image(p)
            elif ext in _PDF_EXTS and _HAS_PDF:
                self._load_pdf(p)
            elif ext in _TEXT_EXTS:
                self._load_text(p)
            elif ext in _DWG_EXTS:
                self._load_dwg(p)
            elif ext in _OFFICE_EXTS and _HAS_PDF:
                self._load_office(p)
            else:
                self._stack.setCurrentIndex(self._fallback_page_idx)
        except Exception as e:
            self._error_lbl.setText(f"Não foi possível abrir a pré-visualização:\n{e}")
            self._stack.setCurrentIndex(self._error_page_idx)

    def _load_image(self, p: Path):
        pix = QPixmap(str(p))
        if pix.isNull():
            raise ValueError("formato de imagem não suportado")
        self._img_caption_lbl.setVisible(False)
        self._img_pixmap = pix
        self._rescale_image()
        self._stack.setCurrentIndex(self._img_page_idx)

    def _load_dwg(self, p: Path):
        # 1) tenta renderizar a geometria de verdade (dwg2SVG, LibreDWG) —
        #    cobre linhas/círculos/texto/polylines do model space; hachuras,
        #    blocos aninhados e cotas podem sair incompletos.
        rendered = render_dwg_to_svg(str(p))
        if rendered:
            svg_text, background = rendered
            self._svg_widget.load(svg_text.encode("utf-8"), background)
            self._stack.setCurrentIndex(self._svg_page_idx)
            return
        # 2) sem renderização (executável ausente, timeout, ou o LibreDWG não
        #    leu o arquivo) — tenta a miniatura estática salva no arquivo.
        result = extract_dwg_thumbnail(str(p))
        if not result:
            self._stack.setCurrentIndex(self._fallback_page_idx)
            return
        image_bytes, fmt = result
        pix = QPixmap()
        if not pix.loadFromData(image_bytes, fmt.upper()) or pix.isNull():
            self._stack.setCurrentIndex(self._fallback_page_idx)
            return
        self._img_pixmap = pix
        self._rescale_image()
        self._img_caption_lbl.setText(
            "Não foi possível renderizar o desenho — miniatura salva no arquivo."
        )
        self._img_caption_lbl.setVisible(True)
        self._stack.setCurrentIndex(self._img_page_idx)

    def _load_office(self, p: Path):
        # Já convertido antes e ainda válido (arquivo original não mudou)?
        # Mostra na hora, sem passar pela tela de "convertendo".
        cached = office_render.get_cached_pdf(str(p))
        if cached:
            self._load_pdf(Path(cached))
            return
        self._stack.setCurrentIndex(self._converting_page_idx)
        if self._office_worker is not None:
            try:
                self._office_worker.finished_convert.disconnect(self._on_office_converted)
            except TypeError:
                pass
        worker = _OfficeConvertWorker(str(p))
        worker.finished_convert.connect(self._on_office_converted)
        self._office_worker = worker
        worker.start()

    def _on_office_converted(self, original_path: str, pdf_path):
        if original_path != self._current_path:
            return  # usuário já trocou de arquivo enquanto convertia — descarta
        if not pdf_path:
            self._stack.setCurrentIndex(self._fallback_page_idx)
            return
        try:
            self._load_pdf(Path(pdf_path))
        except Exception as e:
            self._error_lbl.setText(f"Não foi possível abrir a pré-visualização:\n{e}")
            self._stack.setCurrentIndex(self._error_page_idx)

    def _rescale_image(self):
        if not self._img_pixmap:
            return
        target = self._img_lbl.size()
        if target.width() > 10 and target.height() > 10:
            scaled = self._img_pixmap.scaled(
                target, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._stack.currentIndex() == self._img_page_idx:
            self._rescale_image()

    def _load_pdf(self, p: Path):
        # load() retorna um QPdfDocument.Error (não um Status) — None_
        # significa sucesso; o carregamento em si é síncrono o bastante pra
        # já valer a pena checar aqui.
        error = self._pdf_doc.load(str(p))
        if error != QPdfDocument.Error.None_:
            raise ValueError(f"não foi possível abrir o PDF ({error.name})")
        self._stack.setCurrentIndex(self._pdf_page_idx)

    def _load_text(self, p: Path):
        raw = p.read_bytes()[:_TEXT_PREVIEW_MAX_BYTES]
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        if p.stat().st_size > _TEXT_PREVIEW_MAX_BYTES:
            text += "\n\n[... arquivo truncado na pré-visualização ...]"
        self._text_view.setPlainText(text)
        self._stack.setCurrentIndex(self._text_page_idx)

    def _open_externally(self):
        if self._current_path:
            try:
                DemandFileService.open_file(self._current_path)
            except Exception:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_path))

    # ── Expandir / Fechar ────────────────────────────────────────────────────

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._update_expand_icon()
        self.expand_toggled.emit(self._expanded)

    def _on_close(self):
        self.setVisible(False)
        if self._expanded:
            # fechar já implica sair do modo expandido — sem isso quem
            # incorporou o painel (ex.: o diálogo de detalhes) ficaria com o
            # cabeçalho/abas escondidos permanentemente, sem preview nenhum
            # visível pra clicar em "restaurar".
            self._expanded = False
            self._update_expand_icon()
            self.expand_toggled.emit(False)

    def _update_expand_icon(self):
        ic = "#94A3B8" if self._dark else "#64748B"
        name = "fa6s.compress" if self._expanded else "fa6s.expand"
        self._expand_btn.setIcon(qta.icon(name, color=ic))
        self._expand_btn.setToolTip(
            "Restaurar" if self._expanded else "Expandir pré-visualização"
        )

    # ── Theme ────────────────────────────────────────────────────────────────

    def set_dark(self, dark: bool):
        self._dark = dark
        self._apply_theme_colors()

    def _apply_theme_colors(self):
        ic = "#94A3B8" if self._dark else "#64748B"
        self._close_btn.setIcon(qta.icon("fa6s.xmark", color=ic))
        self._update_expand_icon()
        self._sep.setStyleSheet(f"color: {'#334155' if self._dark else '#E2E8F0'};")
