"""
Correspondência de texto com tolerância a erro de digitação (estilo busca do
WhatsApp). Função pura, sem I/O — usada tanto pelo repositório (pra decidir
quais demandas aparecem na busca) quanto pela UI (pra destacar o trecho/
palavra que bateu).
"""
import re
import unicodedata

WORD_RE = re.compile(r"\w+", re.UNICODE)


def strip_accents(text: str) -> str:
    """Remove acentos/cedilha (á→a, ç→c, õ→o...) pra permitir busca exata
    accent-insensitive — digitar "gas" precisa achar "gás" mesmo em buscas
    curtas, onde a tolerância a erro de digitação (fuzzy) nem entra em jogo."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


_ACCENT_VARIANTS = {
    'a': 'aáàâãä', 'e': 'eéèêë', 'i': 'iíìîï',
    'o': 'oóòôõö', 'u': 'uúùûü', 'c': 'cç',
}


def accent_insensitive_pattern(query: str) -> str:
    """Monta um regex que acha `query` no texto original ignorando acento
    (ex.: "gas" acha "gás") — ao contrário de strip_accents(), que perde a
    posição original do trecho, isso permite destacar o trecho exato como
    apareceu no texto (com acento e tudo)."""
    parts = []
    for ch in query:
        variants = _ACCENT_VARIANTS.get(ch.lower())
        if variants:
            cls = variants + variants.upper()
            parts.append(f"[{re.escape(cls)}]")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def fuzzy_prefix_match(query: str, word: str, max_dist: int) -> tuple[int, int]:
    """Menor distância de edição entre `query` (usada inteira) e ALGUM
    prefixo de `word` — o resto de `word` pode sobrar (sufixo livre). É isso
    que permite "asst" achar "asset" (1 inserção) e "asss" achar "asset"
    (1 substituição), sem exigir que a palavra inteira bata.
    Retorna (distância, tamanho do prefixo de `word` que alcançou essa
    distância) — o tamanho é usado pra destacar só o trecho que realmente
    correspondeu à busca, em vez da palavra inteira."""
    n = len(query)
    if n == 0:
        return 0, 0
    m = len(word)
    if m == 0:
        return n, 0
    prev = list(range(n + 1))   # dp[0][i] = i (apagar i chars de query pra alinhar com prefixo vazio de word)
    best = prev[n]
    best_len = 0
    for j in range(1, m + 1):
        wc = word[j - 1]
        cur = [j] + [0] * n
        for i in range(1, n + 1):
            cost = 0 if query[i - 1] == wc else 1
            cur[i] = min(
                prev[i] + 1,         # pula um char de word
                cur[i - 1] + 1,      # query "sobra" aqui (inserção)
                prev[i - 1] + cost,  # casa ou substitui
            )
        prev = cur
        if cur[n] < best:
            best = cur[n]
            best_len = j
    return best, best_len


def fuzzy_prefix_distance(query: str, word: str, max_dist: int) -> int:
    """Só a distância de fuzzy_prefix_match — mantido separado porque é o
    caso de uso mais comum (filtro de busca, que só precisa do número)."""
    return fuzzy_prefix_match(query, word, max_dist)[0]


def fuzzy_word_match(query: str, text: str, max_dist: int) -> bool:
    """True se alguma palavra de `text` corresponde (com até max_dist erros
    de digitação) a um prefixo do tamanho de `query`."""
    if not query or not text:
        return False
    for w in WORD_RE.findall(text.lower()):
        if len(w) < len(query) - max_dist:
            continue   # nem o prefixo mais longo de w chega perto do tamanho de query
        if fuzzy_prefix_distance(query, w, max_dist) <= max_dist:
            return True
    return False


def find_fuzzy_match_span(query: str, text: str, max_dist: int):
    """Como `find_fuzzy_word`, mas em vez do `re.Match` da palavra inteira
    retorna (match, tamanho_do_trecho) — o trecho é só a parte do começo da
    palavra que efetivamente correspondeu à busca (ex.: buscar "cronogrma"
    e achar "cronograma" destaca só "cronogram", não a palavra toda), pra
    deixar claro pro usuário POR QUE aquilo bateu."""
    if not query or not text:
        return None
    q = query.lower()
    for m in WORD_RE.finditer(text):
        w = m.group(0).lower()
        if len(w) < len(query) - max_dist:
            continue
        dist, span_len = fuzzy_prefix_match(q, w, max_dist)
        if dist <= max_dist:
            return m, span_len
    return None
