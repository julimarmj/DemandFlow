"""
Spell-check para QTextEdit e QLineEdit.
Usa cyhunspell (bindings para a biblioteca Hunspell em C/C++) com dicionários
pt_BR + en_US (LibreOffice) — ordens de magnitude mais rápido que uma
reimplementação em Python puro, especialmente em suggest().
Os dicionários são carregados em background: a UI abre imediatamente
e o sublinhado/popup ativa sozinho quando o carregamento terminar.
"""
import html as _html
import os
import re
import sys
import threading
from PyQt6.QtWidgets import (
    QTextEdit, QLineEdit, QFrame, QVBoxLayout, QPushButton, QLabel, QApplication,
    QWidget, QRubberBand,
)
from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QTextCursor, QImage, QPixmap,
    QDesktopServices, QCursor, QPainter, QPen, QTextObjectInterface, QTextFormat,
    QTextDocument,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QRect, QThread, pyqtSignal, QBuffer, QIODevice, QUrl,
    QObject, QSizeF, QRectF,
)

# ── Dicionários ───────────────────────────────────────────────────────────────
# Carregados em thread daemon para não atrasar a inicialização da UI.
# _dict_pt / _dict_en ficam None até o carregamento terminar.
_dict_pt = None
_dict_en = None

def _load_dicts():
    global _dict_pt, _dict_en
    try:
        import hunspell   # pacote cyhunspell — binding para a lib Hunspell em C++
        if getattr(sys, "frozen", False):
            # Empacotado (PyInstaller): os arquivos de --add-data ficam sob
            # sys._MEIPASS, não junto do .py (que vira bytecode dentro do bundle).
            _base = sys._MEIPASS
        else:
            _base = os.path.dirname(                        # widgets/
                        os.path.dirname(                    # presentation/
                            os.path.dirname(                # projeto/
                                os.path.abspath(__file__))))
        _dir = os.path.join(_base, "resources", "dictionaries")
        _dict_pt = hunspell.Hunspell("pt_BR", hunspell_data_dir=_dir)
        _dict_en = hunspell.Hunspell("en_US", hunspell_data_dir=_dir)
    except Exception as exc:
        print(f"[spell_check] dicionários não carregados: {exc}")

threading.Thread(target=_load_dicts, daemon=True, name="spell-loader").start()

# Define quais idiomas participam da verificação.
# False = dicionário carregado mas não usado ainda (reservado para troca de idioma).
_CHECK_EN = False

# ── Lista de termos técnicos ignorados ────────────────────────────────────────
_IGNORE: set[str] = {
    "backend", "frontend", "deploy", "sprint", "release", "commit",
    "branch", "merge", "api", "sql", "html", "css", "json", "xml",
    "http", "https", "url", "id", "ids", "ui", "ux", "ok", "log",
    "logs", "setup", "update", "upload", "download", "bug", "bugs",
    "git", "token", "sdk", "lib", "dev", "prod", "staging", "fix",
    "mail", "email",
}

# Palavras com hífen (ex.: "pré-requisito", "guarda-chuva", "e-mail") são
# capturadas como um único token — inclusive com segmentos de 1 letra
# (ex.: o "e" de "e-mail") — em vez de quebrar em partes separadas.
_WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ]+(?:-[a-zA-ZÀ-ÿ]+)+|[a-zA-ZÀ-ÿ]{2,}")


def _is_wrong(word: str) -> bool:
    if _dict_pt is None:
        return False                        # ainda carregando
    if word[0].isupper():
        return False                        # sigla (TUDO MAIÚSCULO) ou nome próprio — não verifica
    if "-" in word:
        # Composto: errado se qualquer uma das partes for errada.
        return any(_is_wrong(part) for part in word.split("-") if part)
    w = word.lower()
    if w in _IGNORE:
        return False
    if _dict_pt.spell(w):
        return False
    if _CHECK_EN and _dict_en is not None and _dict_en.spell(w):
        return False
    return True


def _levenshtein(a: str, b: str) -> int:
    """Distância de edição (inserções/remoções/substituições) entre duas strings."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


# Letras acentuadas/cedilha do português — usadas pra ponderar o custo de
# inserção na distância de edição abaixo (ver _weighted_edit_distance).
_ACCENTED = set("áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ")

# Mapa letra-acentuada -> letra-base, pra reconhecer quando uma substituição
# é "só trocou o acento" (ex.: e/é, a/ã) em vez de uma letra totalmente
# diferente — esse é o erro de digitação mais comum em português.
_BASE_LETTER = {
    'á': 'a', 'à': 'a', 'â': 'a', 'ã': 'a', 'ä': 'a',
    'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
    'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
    'ó': 'o', 'ò': 'o', 'ô': 'o', 'õ': 'o', 'ö': 'o',
    'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
    'ç': 'c',
}


def _base_letter(ch: str) -> str:
    return _BASE_LETTER.get(ch, ch)


def _weighted_edit_distance(a: str, b: str) -> float:
    """Como _levenshtein, mas com custos diferentes por tipo de edição —
    reflete os erros de digitação mais comuns em português:
      • substituir só o acento (ex.: "voce"→"você", "e"→"é"):            0.3
      • inserir letra acentuada (ex.: "funao"→"função", faltou o "ç"):   0.6
      • substituir por uma letra totalmente diferente:                   1.0
      • inserir letra comum:                                             1.0
      • remover uma letra (o candidato é mais curto que a palavra):      1.3
    Só usada para ORDENAR candidatos já aceitos pelo corte de _levenshtein
    em _rank_suggestions — não substitui o filtro de distância máxima."""
    n, m = len(a), len(b)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + 1.3
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + (0.6 if b[j - 1] in _ACCENTED else 1.0)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            ins_cost = 0.6 if b[j - 1] in _ACCENTED else 1.0
            ca, cb = a[i - 1], b[j - 1]
            if ca == cb:
                sub_cost = 0.0
            elif _base_letter(ca) == _base_letter(cb):
                sub_cost = 0.3
            else:
                sub_cost = 1.0
            dp[i][j] = min(
                dp[i - 1][j] + 1.3,
                dp[i][j - 1] + ins_cost,
                dp[i - 1][j - 1] + sub_cost,
            )
    return dp[n][m]


def _rank_suggestions(word: str, candidates: list[str]) -> list[str]:
    """Descarta candidatos com mais de 2 letras de diferença (o ranking
    interno do hunspell às vezes deixa palavras "nada a ver" no topo —
    compartilham letras, mas não são parecidas o suficiente pra fazer
    sentido) e ordena os que sobraram pela distância ponderada — que já
    prioriza corrigir só o acento — somada a uma pequena penalidade por
    palavra ter tamanho diferente do digitado (troca de letra no meio é
    mais comum que faltar/sobrar uma, mas não deve enterrar uma correção
    de acento claramente melhor, ex.: "funao"→"função"). Mostra no máximo
    4 sugestões: mais que isso vira ruído."""
    w = word.lower()
    max_dist = 2
    scored = []
    for c in candidates:
        cl = c.lower()
        d = _levenshtein(w, cl)
        if d > max_dist:
            continue
        length_penalty = abs(len(cl) - len(w)) * 0.2
        # Hunspell às vezes sugere separar em duas palavras (ex.: "planeja
        # meto") com custo de edição igual ao de uma correção de uma palavra
        # só — pequeno desempate pra não ganhar de "planejamento" à toa.
        compound_penalty = 0.4 if " " in cl else 0.0
        score = _weighted_edit_distance(w, cl) + length_penalty + compound_penalty
        scored.append((c, score))
    scored.sort(key=lambda t: t[1])
    return [c for c, _ in scored[:4]]


def _suggestions(word: str) -> list[str]:
    if _dict_pt is None:
        return []
    if "-" in word:
        # Sugere substituindo só a(s) parte(s) errada(s), mantendo as corretas.
        parts = word.split("-")
        result: list[str] = []
        for i, part in enumerate(parts):
            if not _is_wrong(part):
                continue
            for s in _suggestions(part):
                candidate = "-".join(s if j == i else parts[j] for j in range(len(parts)))
                if candidate not in result:
                    result.append(candidate)
                if len(result) >= 6:
                    return result
        return result
    w = word.lower()
    seen: set[str] = set()
    candidates: list[str] = []
    for s in _dict_pt.suggest(w):
        if s not in seen:
            seen.add(s)
            candidates.append(s)
    if _CHECK_EN and _dict_en is not None:
        for s in _dict_en.suggest(w):
            if s not in seen:
                seen.add(s)
                candidates.append(s)
    return _rank_suggestions(word, candidates)


# ── Busca de sugestões em background ──────────────────────────────────────────
# Mesmo com cyhunspell (C++) sendo bem mais rápido que uma reimplementação
# pura em Python, suggest() ainda pode levar uma fração de segundo perceptível
# para palavras longas sem correspondências próximas — roda fora da thread da
# UI por segurança, para nunca travar a interface durante o hover/seleção.

class _SuggestWorker(QThread):
    done = pyqtSignal(str, list)   # palavra, sugestões

    def __init__(self, word: str):
        super().__init__()   # sem parent: não acoplado ao ciclo de vida do widget
        self._word = word

    def run(self):
        self.done.emit(self._word, _suggestions(self._word))


# ── Highlighter ───────────────────────────────────────────────────────────────

class SpellCheckHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._fmt = QTextCharFormat()
        self._fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        self._fmt.setUnderlineColor(QColor("#EF4444"))

    def highlightBlock(self, text: str):
        if _dict_pt is None:
            return
        for m in _WORD_RE.finditer(text):
            if _is_wrong(m.group()):
                self.setFormat(m.start(), len(m.group()), self._fmt)


# ── Popup de sugestões ────────────────────────────────────────────────────────

class _SuggestionPopup(QFrame):
    """Popup flutuante estilo Word: botões clicáveis para cada sugestão."""

    suggestion_chosen = pyqtSignal(str)

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("suggestion_popup")
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(4, 4, 4, 4)
        self._box.setSpacing(1)

    def show_for(self, word: str, suggestions: list[str], global_pos: QPoint):
        while self._box.count():
            item = self._box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not suggestions:
            return

        hdr = QLabel("Sugestões")
        hdr.setObjectName("suggestion_header")
        self._box.addWidget(hdr)

        for s in suggestions:
            btn = QPushButton(s)
            btn.setObjectName("suggestion_item")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda _, r=s: self._pick(r))
            self._box.addWidget(btn)

        self.adjustSize()
        self.move(global_pos + QPoint(0, 18))
        self.show()
        self.raise_()

    def _pick(self, replacement: str):
        self.hide()
        self.suggestion_chosen.emit(replacement)


# ── Image selection overlay ──────────────────────────────────────────────────

class _ResizeHandle(QFrame):
    """Handle de redimensionamento — filho do viewport, aparece sobre o texto."""

    resized      = pyqtSignal(str, int, int)   # direction, dx, dy
    drag_started = pyqtSignal(str)             # direction

    _CURSORS = {
        'tl': Qt.CursorShape.SizeFDiagCursor,
        'tr': Qt.CursorShape.SizeBDiagCursor,
        'bl': Qt.CursorShape.SizeBDiagCursor,
        'br': Qt.CursorShape.SizeFDiagCursor,
        't':  Qt.CursorShape.SizeVerCursor,
        'b':  Qt.CursorShape.SizeVerCursor,
        'l':  Qt.CursorShape.SizeHorCursor,
        'r':  Qt.CursorShape.SizeHorCursor,
    }

    def __init__(self, direction: str, parent: QWidget):
        super().__init__(parent)
        self._direction = direction
        self._drag_start: QPoint = QPoint()
        self._dragging = False
        self.setFixedSize(10, 10)
        self.setStyleSheet(
            "QFrame { background: #3B82F6; border: 1px solid white; border-radius: 1px; }"
        )
        self.setCursor(self._CURSORS.get(direction, Qt.CursorShape.SizeAllCursor))
        self.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
            self.drag_started.emit(self._direction)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            cur = event.globalPosition().toPoint()
            dx = cur.x() - self._drag_start.x()
            dy = cur.y() - self._drag_start.y()
            self._drag_start = cur
            self.resized.emit(self._direction, dx, dy)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()


class _ImageSelector:
    """Gerencia o QRubberBand de borda + 8 handles de redimensionamento."""

    _HW = 5   # meia-largura do handle em px

    def __init__(self, viewport: QWidget, on_resize, on_drag_start):
        self._band = QRubberBand(QRubberBand.Shape.Rectangle, viewport)
        self._handles: dict = {}
        for d in ('tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'):
            h = _ResizeHandle(d, viewport)
            h.resized.connect(on_resize)
            h.drag_started.connect(on_drag_start)
            self._handles[d] = h

    def set_rect(self, rect: QRect):
        self._band.setGeometry(rect)
        self._band.show()
        self._band.raise_()
        hw = self._HW
        cx = rect.center().x()
        cy = rect.center().y()
        positions = {
            'tl': (rect.left() - hw,  rect.top() - hw),
            'tr': (rect.right() - hw, rect.top() - hw),
            'bl': (rect.left() - hw,  rect.bottom() - hw),
            'br': (rect.right() - hw, rect.bottom() - hw),
            't':  (cx - hw,           rect.top() - hw),
            'b':  (cx - hw,           rect.bottom() - hw),
            'l':  (rect.left() - hw,  cy - hw),
            'r':  (rect.right() - hw, cy - hw),
        }
        for d, (x, y) in positions.items():
            self._handles[d].move(x, y)
            self._handles[d].show()
            self._handles[d].raise_()

    def clear(self):
        self._band.hide()
        for h in self._handles.values():
            h.hide()


# ── Renderização de imagem com interpolação suave ───────────────────────────
# Por padrão o Qt desenha imagens embutidas no QTextDocument sem interpolação
# suave — em qualquer tamanho que não seja exatamente a resolução nativa do
# recurso (o que na prática quase nunca acontece ao redimensionar arrastando
# o mouse), o resultado sai serrilhado/com moiré. O redimensionamento em si
# NUNCA altera os pixels originais (só o width/height de exibição), então
# registrar esse handler no lugar do padrão do Qt é suficiente pra imagem
# ficar nítida em qualquer tamanho, incluindo de volta ao "como era antes".

class _SmoothImageHandler(QObject, QTextObjectInterface):
    def intrinsicSize(self, doc, pos_in_document, fmt):
        img_fmt = fmt.toImageFormat()
        if img_fmt.width() > 0 and img_fmt.height() > 0:
            return QSizeF(img_fmt.width(), img_fmt.height())
        return QSizeF(0, 0)

    def drawObject(self, painter, rect, doc, pos_in_document, fmt):
        img_fmt = fmt.toImageFormat()
        res = doc.resource(QTextDocument.ResourceType.ImageResource, QUrl(img_fmt.name()))
        if isinstance(res, QImage):
            pix = QPixmap.fromImage(res)
        elif isinstance(res, QPixmap):
            pix = res
        else:
            return
        if pix.isNull():
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(rect, pix, QRectF(pix.rect()))
        painter.restore()


# ── SpellCheckTextEdit ────────────────────────────────────────────────────────

# Teto de resolução para imagens inseridas/coladas — evita que screenshots em
# alta resolução (4K etc.) inchem o HTML salvo no banco. Mantém proporção.
_MAX_IMG_W = 1000
_MAX_IMG_H = 800


# Detecta URLs em texto colado sem HTML (ex.: link copiado de um app que só
# manda text/plain) pra transformar em hyperlink clicável de verdade, em vez
# de virar texto puro.
_URL_RE = re.compile(r'(https?://[^\s<>"\')]+|www\.[^\s<>"\')]+)', re.IGNORECASE)


def _linkify_plain_text(text: str) -> str:
    """Converte URLs dentro de um texto puro em links HTML clicáveis,
    escapando o restante e preservando quebras de linha."""
    out = []
    last = 0
    for m in _URL_RE.finditer(text):
        out.append(_html.escape(text[last:m.start()]).replace("\n", "<br>"))
        url = m.group(0)
        href = url if url.lower().startswith(("http://", "https://")) else f"http://{url}"
        out.append(f'<a href="{_html.escape(href)}">{_html.escape(url)}</a>')
        last = m.end()
    out.append(_html.escape(text[last:]).replace("\n", "<br>"))
    return "".join(out)


class SpellCheckTextEdit(QTextEdit):
    """
    QTextEdit com verificação ortográfica em tempo real.
    • Passa o mouse sobre palavra errada por ~500 ms → popup com sugestões clicáveis
    • Botão direito → menu de contexto com as mesmas sugestões
    O sublinhado ativa automaticamente quando os dicionários terminam de carregar.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._highlighter = SpellCheckHighlighter(self.document())
        self.document().setDefaultStyleSheet(
            "a { color: #3B82F6; text-decoration: underline; }"
        )

        self._popup = _SuggestionPopup()
        self._popup.suggestion_chosen.connect(self._apply_suggestion)
        self._hover_cursor: QTextCursor | None = None
        self._hover_local_pos = QPoint()
        self._pending_word: str | None = None
        self._pending_global_pos = QPoint()
        self._suggest_workers: list = []   # mantém referência forte enquanto a thread roda

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(500)
        self._hover_timer.timeout.connect(self._try_show_popup)

        # Verifica quando os dicionários ficam prontos para religar o sublinhado
        self._ready_timer = QTimer(self)
        self._ready_timer.setInterval(500)
        self._ready_timer.timeout.connect(self._check_ready)
        self._ready_timer.start()

        self.setMouseTracking(True)
        self._init_image_selection()

        # Registra o handler de imagem com interpolação suave (ver
        # _SmoothImageHandler acima) — sem isso o Qt desenha imagens
        # embutidas serrilhadas em qualquer tamanho fora da resolução nativa.
        self._image_handler = _SmoothImageHandler()
        self.document().documentLayout().registerHandler(
            QTextFormat.ObjectTypes.ImageObject.value, self._image_handler
        )

    def text(self) -> str:
        """Alias para toPlainText() — torna SpellCheckTextEdit drop-in de QLineEdit."""
        return self.toPlainText()

    def setText(self, text: str):
        """Alias para setPlainText() — torna SpellCheckTextEdit drop-in de QLineEdit."""
        self.setPlainText(text)

    def _check_ready(self):
        if _dict_pt is not None:
            self._ready_timer.stop()
            self._highlighter.rehighlight()

    # ── Hover ─────────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        self._hover_local_pos = event.pos()
        self._hover_timer.start()
        self._update_link_cursor(event.pos())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_timer.stop()
        super().leaveEvent(event)

    _PLAIN_URL_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)

    def _url_at_cursor(self, cursor: QTextCursor) -> str:
        """Detecta URL em texto simples na posição do cursor."""
        text = cursor.block().text()
        pos  = cursor.positionInBlock()
        for m in self._PLAIN_URL_RE.finditer(text):
            if m.start() <= pos <= m.end():
                return m.group().rstrip('.,;:)!')
        return ""

    def _update_link_cursor(self, viewport_pos: QPoint):
        is_link = bool(self.anchorAt(viewport_pos))
        if not is_link:
            is_link = bool(self._url_at_cursor(self.cursorForPosition(viewport_pos)))
        ctrl_held = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        if is_link and ctrl_held:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    def _open_href(self, href: str):
        url = QUrl.fromUserInput(href)
        if url.isValid():
            QDesktopServices.openUrl(url)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            # Sem isso, o Esc não tratado sobe pro diálogo pai (ex.: detalhes
            # da demanda) e fecha ele inteiro — só porque o cursor estava
            # neste campo de nota. Consome aqui: desseleciona a imagem se
            # houver uma selecionada, senão não faz nada (mas não deixa
            # propagar).
            if self._sel_img_pos >= 0:
                self._deselect_image()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Control:
            self._update_link_cursor(self.viewport().mapFromGlobal(QCursor.pos()))
        # Ao digitar após (ou dentro de) um hyperlink, reseta o formato do
        # cursor para que o texto novo não herde cor e sublinhado do link.
        if event.text() and not (event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            cursor = self.textCursor()
            if cursor.charFormat().anchorHref():
                cursor.setCharFormat(QTextCharFormat())
                self.setTextCursor(cursor)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Control:
            self._update_link_cursor(self.viewport().mapFromGlobal(QCursor.pos()))
        super().keyReleaseEvent(event)


    def _word_at(self, pos: QPoint):
        """Retorna (palavra, cursor_com_seleção) usando o mesmo _WORD_RE do
        highlighter — garante que o popup/menu nunca discorde do sublinhado
        sobre onde uma palavra começa e termina."""
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        text = block.text()
        pos_in_block = cursor.positionInBlock()
        for m in _WORD_RE.finditer(text):
            if m.start() <= pos_in_block <= m.end():
                sel = QTextCursor(block)
                sel.setPosition(block.position() + m.start())
                sel.setPosition(block.position() + m.end(), QTextCursor.MoveMode.KeepAnchor)
                return m.group(), sel
        return None, None

    def _try_show_popup(self):
        if _dict_pt is None or self._popup.isVisible():
            return
        word, cursor = self._word_at(self._hover_local_pos)
        if word and _is_wrong(word):
            self._hover_cursor = cursor
            self._pending_word = word
            self._pending_global_pos = self.mapToGlobal(self._hover_local_pos)
            worker = _SuggestWorker(word)
            self._suggest_workers.append(worker)   # mantém viva enquanto a thread roda
            worker.done.connect(self._on_suggestions_ready)
            worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
            worker.start()

    def _cleanup_worker(self, worker):
        if worker in self._suggest_workers:
            self._suggest_workers.remove(worker)
        worker.deleteLater()

    def _on_suggestions_ready(self, word: str, suggs: list[str]):
        if word != self._pending_word:
            return   # mouse já passou pra outra palavra — descarta resultado obsoleto
        if suggs:
            self._popup.show_for(word, suggs, self._pending_global_pos)

    def _apply_suggestion(self, replacement: str):
        if self._hover_cursor:
            self._hover_cursor.insertText(replacement)
            self._hover_cursor = None

    # ── Contexto (botão direito) ───────────────────────────────────────────────

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()

        if _dict_pt is not None:
            word, cursor = self._word_at(event.pos())

            if word and _is_wrong(word):
                suggs = _suggestions(word)
                menu.addSeparator()
                if suggs:
                    spell_menu = menu.addMenu(f'Sugestões para "{word}"')
                    for s in suggs:
                        act = spell_menu.addAction(s)
                        act.triggered.connect(
                            lambda _, repl=s, cur=cursor: self._replace(cur, repl)
                        )
                else:
                    no_sugg = menu.addAction("Sem sugestões")
                    no_sugg.setEnabled(False)

                menu.addSeparator()
                ignore_act = menu.addAction(f'Ignorar "{word}" sempre')
                ignore_act.triggered.connect(lambda _, w=word: self._ignore(w))

        menu.exec(event.globalPos())

    def _replace(self, cursor: QTextCursor, replacement: str):
        cursor.insertText(replacement)

    def _ignore(self, word: str):
        _IGNORE.add(word.lower())
        self._highlighter.rehighlight()

    # ── Imagens ──────────────────────────────────────────────────────────────

    @staticmethod
    def _scale_image(img: QImage) -> QImage:
        """Reduz a imagem para o teto _MAX_IMG_W/H preservando o aspect ratio.
        Imagens já dentro do limite não são tocadas (sem perda de qualidade)."""
        if img.width() <= _MAX_IMG_W and img.height() <= _MAX_IMG_H:
            return img
        return img.scaled(
            _MAX_IMG_W, _MAX_IMG_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    @staticmethod
    def _image_html(img: QImage) -> str:
        """Serializa a imagem como data-URI base64 embutido no próprio HTML.
        Diferente de cursor.insertImage() puro, isso não depende do cache de
        recursos do QTextDocument em memória — sobrevive ao toHtml()/setHtml()
        quando salvo e recarregado do banco."""
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        b64 = bytes(buf.data().toBase64()).decode("ascii")
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'width="{img.width()}" height="{img.height()}" />'
        )

    def insert_image_from_path(self, path: str) -> bool:
        img = QImage(path)
        if img.isNull():
            return False
        cursor = self.textCursor()
        cursor.insertHtml(self._image_html(self._scale_image(img)))
        self.setTextCursor(cursor)
        return True

    # ── Image selection & resize ──────────────────────────────────────────────

    def _init_image_selection(self):
        self._sel_img_pos: int = -1
        self._resizing: bool = False
        self._drag_orig_w: int = 0
        self._drag_orig_h: int = 0
        self._drag_accum_dx: int = 0
        self._drag_accum_dy: int = 0
        self._img_sel = _ImageSelector(self.viewport(),
                                       self._on_handle_resize,
                                       self._on_drag_start)
        self.document().contentsChanged.connect(self._on_doc_changed)

    def _on_drag_start(self, _direction: str):
        if self._sel_img_pos < 0 or self._sel_img_pos >= self.document().characterCount():
            return
        c = QTextCursor(self.document())
        c.setPosition(self._sel_img_pos)
        fmt = c.charFormat().toImageFormat()
        self._drag_orig_w = max(1, int(fmt.width())  if fmt.width()  > 0 else 200)
        self._drag_orig_h = max(1, int(fmt.height()) if fmt.height() > 0 else 150)
        self._drag_accum_dx = 0
        self._drag_accum_dy = 0

    def _on_doc_changed(self):
        if not self._resizing:
            self._deselect_image()

    def _on_handle_resize(self, direction: str, dx: int, dy: int):
        cc = self.document().characterCount()
        if self._sel_img_pos < 0 or self._sel_img_pos >= cc or self._sel_img_pos + 1 >= cc:
            self._deselect_image()
            return

        self._drag_accum_dx += dx
        self._drag_accum_dy += dy

        ow, oh = self._drag_orig_w, self._drag_orig_h
        w = ow
        h = oh
        if   'r' in direction: w = max(20, ow + self._drag_accum_dx)
        elif 'l' in direction: w = max(20, ow - self._drag_accum_dx)
        if   'b' in direction: h = max(20, oh + self._drag_accum_dy)
        elif 't' in direction: h = max(20, oh - self._drag_accum_dy)

        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            ratio = ow / oh if oh > 0 else 1.0
            if direction in ('l', 'r'):
                h = max(20, round(w / ratio))
            elif direction in ('t', 'b'):
                w = max(20, round(h * ratio))
            else:
                # Canto: eixo com maior deslocamento acumulado lidera
                if abs(self._drag_accum_dx) >= abs(self._drag_accum_dy):
                    h = max(20, round(w / ratio))
                else:
                    w = max(20, round(h * ratio))

        self._resizing = True
        sel = QTextCursor(self.document())
        sel.setPosition(self._sel_img_pos)
        sel.movePosition(QTextCursor.MoveOperation.Right,
                         QTextCursor.MoveMode.KeepAnchor)
        c = QTextCursor(self.document())
        c.setPosition(self._sel_img_pos)
        img_fmt = c.charFormat().toImageFormat()
        img_fmt.setWidth(w)
        img_fmt.setHeight(h)
        sel.setCharFormat(img_fmt)
        self._resizing = False
        self._refresh_handles()

    def _img_pos_at(self, viewport_pos: QPoint) -> int:
        # charFormat() de um QTextCursor reflete o caractere ANTES da posição
        # do cursor, não a posição em si — testar isImageFormat() direto em
        # `pos` checava na verdade o caractere seguinte à imagem. Isso fazia
        # cliques no texto logo depois de uma imagem serem confundidos com um
        # clique na imagem (e, de quebra, a imagem em si só era encontrada
        # por acidente quando havia texto depois dela).
        cc = self.document().characterCount()
        base = self.cursorForPosition(viewport_pos).position()
        for delta in (-1, 0, 1, -2, 2):
            img_pos = base + delta
            if img_pos < 0 or img_pos + 1 >= cc:
                continue
            c = QTextCursor(self.document())
            c.setPosition(img_pos + 1)
            if not c.charFormat().isImageFormat():
                continue
            cb = QTextCursor(self.document()); cb.setPosition(img_pos)
            ca = QTextCursor(self.document()); ca.setPosition(img_pos + 1)
            rb = self.cursorRect(cb)
            ra = self.cursorRect(ca)
            img_rect = QRect(rb.left(), rb.top(),
                             max(1, ra.left() - rb.left()), rb.height())
            if img_rect.adjusted(-2, -2, 2, 2).contains(viewport_pos):
                return img_pos
        return -1

    def _select_image(self, pos: int):
        self._sel_img_pos = pos
        self._refresh_handles()

    def _deselect_image(self):
        self._sel_img_pos = -1
        self._img_sel.clear()

    def _refresh_handles(self):
        if self._sel_img_pos < 0:
            self._img_sel.clear()
            return
        cc = self.document().characterCount()
        if self._sel_img_pos >= cc or self._sel_img_pos + 1 >= cc:
            self._deselect_image()
            return
        cb = QTextCursor(self.document())
        cb.setPosition(self._sel_img_pos)
        ca = QTextCursor(self.document())
        ca.setPosition(self._sel_img_pos + 1)
        rb = self.cursorRect(cb)
        ra = self.cursorRect(ca)
        self._img_sel.set_rect(QRect(rb.left(), rb.top(),
                                     ra.left() - rb.left(), rb.height()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and \
                event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            href = self.anchorAt(event.pos())
            if not href:
                href = self._url_at_cursor(self.cursorForPosition(event.pos()))
            if href:
                self._open_href(href)
                return
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self._img_pos_at(event.pos())
            if pos >= 0:
                self._select_image(pos)
            else:
                self._deselect_image()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self._img_pos_at(event.pos())
            if pos >= 0:
                self._restore_image_native_size(pos)
                return
        super().mouseDoubleClickEvent(event)

    def _restore_image_native_size(self, pos: int):
        """Devolve a imagem ao tamanho nativo do recurso (resolução real dos
        pixels, não o que estava sendo exibido) — arrastar pela alça raramente
        cai de volta exatamente no tamanho original, e mesmo poucos pixels de
        diferença já deixam a imagem visivelmente serrilhada."""
        c = QTextCursor(self.document())
        c.setPosition(pos)
        img_fmt = c.charFormat().toImageFormat()
        res = self.document().resource(QTextDocument.ResourceType.ImageResource, QUrl(img_fmt.name()))
        if res is None or res.isNull():
            return
        img_fmt.setWidth(res.width())
        img_fmt.setHeight(res.height())
        sel = QTextCursor(self.document())
        sel.setPosition(pos)
        sel.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
        sel.setCharFormat(img_fmt)
        self._select_image(pos)

    def scrollContentsBy(self, dx: int, dy: int):
        super().scrollContentsBy(dx, dy)
        self._refresh_handles()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_handles()

    def canInsertFromMimeData(self, source):
        if source.hasImage() or source.hasUrls():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        _IMG_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')
        if source.hasImage():
            img = QImage(source.imageData())
            if not img.isNull():
                cursor = self.textCursor()
                cursor.insertHtml(self._image_html(self._scale_image(img)))
                self.setTextCursor(cursor)
                return
        # Arquivo de imagem copiado do Explorer (tem URL mas não dados de imagem)
        if source.hasUrls():
            for url in source.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if any(path.lower().endswith(ext) for ext in _IMG_EXTS):
                        img = QImage(path)
                        if not img.isNull():
                            cursor = self.textCursor()
                            cursor.insertHtml(self._image_html(self._scale_image(img)))
                            self.setTextCursor(cursor)
                            return
        # Texto sem HTML com URL — vira hyperlink
        if not source.hasHtml() and source.hasText():
            text = source.text()
            if _URL_RE.search(text):
                cursor = self.textCursor()
                cursor.insertHtml(_linkify_plain_text(text))
                self.setTextCursor(cursor)
                return
        super().insertFromMimeData(source)


# ── SpellCheckLineEdit ────────────────────────────────────────────────────────

class SpellCheckLineEdit(QLineEdit):
    """
    QLineEdit com popup de sugestões ortográficas ao passar o mouse por ~500 ms.
    Clique numa sugestão para substituir a palavra.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._popup = _SuggestionPopup()
        self._popup.suggestion_chosen.connect(self._apply_suggestion)
        self._hover_word_range: tuple[int, int] | None = None
        self._hover_local_pos = QPoint()
        self._pending_word: str | None = None
        self._pending_range: tuple[int, int] | None = None
        self._pending_global_pos = QPoint()
        self._suggest_workers: list = []   # mantém referência forte enquanto a thread roda

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(500)
        self._hover_timer.timeout.connect(self._try_show_popup)

        self.setMouseTracking(True)

        # Sublinhado ativa sozinho quando os dicionários terminam de carregar
        # (mesmo padrão do SpellCheckTextEdit) — sem isso, um campo aberto
        # antes do carregamento terminar nunca reavalia o texto já digitado.
        self._ready_timer = QTimer(self)
        self._ready_timer.setInterval(500)
        self._ready_timer.timeout.connect(self._check_ready)
        self._ready_timer.start()

    def _check_ready(self):
        if _dict_pt is not None:
            self._ready_timer.stop()
            self.update()

    def mouseMoveEvent(self, event):
        self._hover_local_pos = event.pos()
        self._hover_timer.start()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_timer.stop()
        super().leaveEvent(event)

    def _cleanup_worker(self, worker):
        if worker in self._suggest_workers:
            self._suggest_workers.remove(worker)
        worker.deleteLater()

    def _try_show_popup(self):
        if _dict_pt is None or self._popup.isVisible():
            return
        char_pos = self.cursorPositionAt(self._hover_local_pos)
        text = self.text()

        word = ""
        w_start = w_end = 0
        for m in _WORD_RE.finditer(text):
            if m.start() <= char_pos <= m.end():
                word = m.group()
                w_start, w_end = m.start(), m.end()
                break

        if len(word) >= 2 and _is_wrong(word):
            self._pending_word = word
            self._pending_range = (w_start, w_end)
            self._pending_global_pos = self.mapToGlobal(self._hover_local_pos)
            worker = _SuggestWorker(word)
            self._suggest_workers.append(worker)   # mantém viva enquanto a thread roda
            worker.done.connect(self._on_suggestions_ready)
            worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
            worker.start()

    def _on_suggestions_ready(self, word: str, suggs: list[str]):
        if word != self._pending_word:
            return   # mouse já passou pra outra palavra — descarta resultado obsoleto
        if suggs:
            self._hover_word_range = self._pending_range
            self._popup.show_for(word, suggs, self._pending_global_pos)

    def _apply_suggestion(self, replacement: str):
        if self._hover_word_range:
            w_start, w_end = self._hover_word_range
            text = self.text()
            self.setText(text[:w_start] + replacement + text[w_end:])
            self.setCursorPosition(w_start + len(replacement))
            self._hover_word_range = None

    # ── Sublinhado ────────────────────────────────────────────────────────────
    # QLineEdit não tem suporte nativo a formatação por trecho (isso é um
    # recurso de QTextDocument/QSyntaxHighlighter, usado no SpellCheckTextEdit)
    # — desenha o sublinhado ondulado manualmente por cima do texto já
    # renderizado pelo Qt.

    def paintEvent(self, event):
        super().paintEvent(event)
        if _dict_pt is None:
            return
        text = self.text()
        if not text:
            return
        wrong_ranges = [
            (m.start(), m.end())
            for m in _WORD_RE.finditer(text)
            if _is_wrong(m.group())
        ]
        if not wrong_ranges:
            return

        fm = self.fontMetrics()
        # Posição x (relativa ao widget) onde o caractere 0 do texto está
        # desenhado — deriva do cursor atual em vez de presumir offset fixo,
        # pra continuar correto mesmo quando o texto não cabe no campo e o
        # QLineEdit rola internamente.
        cur_rect = self.cursorRect()
        base_x = cur_rect.left() - fm.horizontalAdvance(text[:self.cursorPosition()])
        y = cur_rect.bottom() - 1

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#EF4444"))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        for start, end in wrong_ranges:
            x1 = base_x + fm.horizontalAdvance(text[:start])
            x2 = base_x + fm.horizontalAdvance(text[:end])
            self._draw_squiggle(painter, x1, x2, y)
        painter.end()

    @staticmethod
    def _draw_squiggle(painter: QPainter, x1: float, x2: float, y: float):
        step, amp = 3, 1.5
        pts = []
        x, up = x1, True
        while x < x2:
            pts.append(QPoint(int(x), int(y - (amp if up else 0))))
            up = not up
            x += step
        pts.append(QPoint(int(x2), int(y - (amp if up else 0))))
        for i in range(len(pts) - 1):
            painter.drawLine(pts[i], pts[i + 1])
