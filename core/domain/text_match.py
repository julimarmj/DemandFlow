"""
Correspondência de texto com tolerância a erro de digitação (estilo busca do
WhatsApp). Função pura, sem I/O — usada tanto pelo repositório (pra decidir
quais demandas aparecem na busca) quanto pela UI (pra destacar o trecho/
palavra que bateu).
"""
import re

WORD_RE = re.compile(r"\w+", re.UNICODE)


def fuzzy_prefix_distance(query: str, word: str, max_dist: int) -> int:
    """Menor distância de edição entre `query` (usada inteira) e ALGUM
    prefixo de `word` — o resto de `word` pode sobrar (sufixo livre). É isso
    que permite "asst" achar "asset" (1 inserção) e "asss" achar "asset"
    (1 substituição), sem exigir que a palavra inteira bata."""
    n = len(query)
    if n == 0:
        return 0
    m = len(word)
    if m == 0:
        return n
    prev = list(range(n + 1))   # dp[0][i] = i (apagar i chars de query pra alinhar com prefixo vazio de word)
    best = prev[n]
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
    return best


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


def find_fuzzy_word(query: str, text: str, max_dist: int):
    """Como `fuzzy_word_match`, mas retorna o `re.Match` da PRIMEIRA palavra
    que bateu (ou None) — usado pra destacar a palavra inteira na UI quando
    não há correspondência exata."""
    if not query or not text:
        return None
    for m in WORD_RE.finditer(text):
        w = m.group(0).lower()
        if len(w) < len(query) - max_dist:
            continue
        if fuzzy_prefix_distance(query.lower(), w, max_dist) <= max_dist:
            return m
    return None
