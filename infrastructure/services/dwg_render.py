"""
DemandFlow - Renderização "de verdade" de DWG (via dwg2SVG do LibreDWG)

Diferente de dwg_preview.py (que só extrai a miniatura estática salva no
arquivo), este módulo chama um conversor externo — dwg2SVG.exe, parte da
distribuição oficial Windows do LibreDWG (GPLv3, ver resources/libredwg/
NOTICE.txt) — que lê a geometria de verdade do DWG (linhas, círculos, texto,
polylines etc. do model space) e devolve um SVG. É bem melhor que a
miniatura, mas cobre só elementos 2D básicos: hachuras, blocos aninhados,
cotas e entidades mais recentes podem sair incompletos ou faltando.

Roda como processo externo (não linkado no app) com timeout, sem abrir
janela de console, e qualquer falha (executável ausente, timeout, DWG que o
LibreDWG não consegue ler, SVG vazio) vira None — quem chama trata isso como
"sem preview", sem propagar erro pro usuário.
"""
from __future__ import annotations

import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

_TIMEOUT_SECONDS = 12

_STROKE_WIDTH_RE = re.compile(r"stroke-width:([0-9.]+)px")
_VIEWBOX_RE = re.compile(r'viewBox="[-\d.eE]+\s+[-\d.eE]+\s+([-\d.eE]+)\s+([-\d.eE]+)"')
_VIEWBOX_FULL_RE = re.compile(
    r'viewBox="([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)"'
)
# Extração "de verdade" de pontos, sem contaminar com parâmetros que NÃO
# são coordenada — descoberto num arquivo real: o comando de arco do SVG
# ("A rx,ry rotação flag,flag x,y") tem "rx,ry" no formato "num,num", igual
# um ponto — um raio pequeno (tipo "347.77,347.77") parecia um ponto normal
# no meio de uma entidade toda com coordenadas absurdas, dando a falsa
# impressão de corrupção "misturada" dentro da mesma entidade.
_PATH_D_RE = re.compile(r'<path[^>]*\bd="([^"]+)"')
_PATH_ML_RE = re.compile(r"[ML]\s*(-?\d+\.\d+),(-?\d+\.\d+)")
_POLY_POINTS_RE = re.compile(r'<poly(?:gon|line)[^>]*\bpoints="([^"]+)"')


def _extract_points(svg_text: str):
    """Pontos de verdade (não raio de arco, não ângulo) de path e polygon/
    polyline — só isso, de propósito: são a esmagadora maioria do conteúdo
    e o que já foi testado e validado em vários arquivos reais. circle/
    ellipse/text ficam de fora dessa análise (testado: incluir cx/cy de
    círculo revelou alguns bem fora da área normal num arquivo que já
    renderizava perfeito — não corrompidos, só não fazem parte do "miolo"
    de referência; incluí-los só piorava a estimativa de área normal, sem
    ganhar nada, já que eles continuam desenhados na posição certa mesmo
    sem entrar nessa conta)."""
    pts = []
    for d in _PATH_D_RE.findall(svg_text):
        pts.extend((float(a), float(b)) for a, b in _PATH_ML_RE.findall(d))
    for points_str in _POLY_POINTS_RE.findall(svg_text):
        nums = re.findall(r"(-?\d+\.\d+)", points_str)
        pts.extend((float(nums[i]), float(nums[i + 1])) for i in range(0, len(nums) - 1, 2))
    return pts

# O dwg2SVG colore as entidades pensando no viewport escuro clássico do
# AutoCAD — muito desenho real usa branco como cor "padrão" de traço
# (confirmado com arquivo real: 94% dos traços de um DWG de teste eram
# brancos). Um canvas branco fixo deixava esse tipo de arquivo invisível;
# um canvas preto fixo funciona pra esses mas fica estranho pros desenhos
# que já usam cores normais (visível em qualquer fundo) — o usuário achou o
# preto sempre ligado estranho. Em vez de fixar uma cor, decide por
# arquivo: conta quantos traços/preenchimentos são "quase branco" vs "quase
# preto" (cores saturadas tipo vermelho/azul/verde não contam pra nenhum
# dos dois lado, já que aparecem bem em qualquer fundo) e escolhe o fundo
# que deixa mais coisa visível — com viés pro branco (mais "papel") quando
# empatar ou não tiver sinal suficiente.
_LIGHT_BG = "#ffffff"
_DARK_BG = "#111111"

_NAMED_ACHROMATIC = {
    "white": (255, 255, 255), "black": (0, 0, 0),
    "gray": (128, 128, 128), "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169),
    "dimgray": (105, 105, 105), "dimgrey": (105, 105, 105),
    "gainsboro": (220, 220, 220), "whitesmoke": (245, 245, 245),
}
_COLOR_TOKEN_RE = re.compile(
    r'(?:stroke|fill)(?:="|:)\s*([#a-zA-Z0-9]+)'
)


def _classify_color(token: str) -> str:
    """"light" (quase branco), "dark" (quase preto) ou "neutral" (cor
    saturada — legível em fundo claro ou escuro, não pesa na decisão)."""
    token = token.strip().lower()
    rgb = None
    if token.startswith("#"):
        hexs = token[1:]
        if len(hexs) == 3:
            hexs = "".join(c * 2 for c in hexs)
        if len(hexs) == 6:
            try:
                rgb = tuple(int(hexs[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return "neutral"
    elif token in _NAMED_ACHROMATIC:
        rgb = _NAMED_ACHROMATIC[token]
    if rgb is None:
        return "neutral"
    r, g, b = rgb
    if max(r, g, b) - min(r, g, b) > 40:
        return "neutral"  # cor saturada (vermelho, azul, verde...): ok em qualquer fundo
    avg = (r + g + b) / 3
    if avg >= 180:
        return "light"
    if avg <= 70:
        return "dark"
    return "neutral"


def _pick_background(svg_text: str) -> str:
    light = dark = 0
    for token in _COLOR_TOKEN_RE.findall(svg_text):
        cls = _classify_color(token)
        if cls == "light":
            light += 1
        elif cls == "dark":
            dark += 1
    # só muda pro escuro se o branco for claramente dominante — em caso de
    # dúvida/pouco sinal, prefere o "papel" branco, mais natural
    return _DARK_BG if light > dark * 1.2 and light > 5 else _LIGHT_BG


def _recolor_for_background(svg_text: str, bg: str) -> str:
    """Depois de decidir o fundo, reescreve pra cinza médio qualquer
    traço/preenchimento que ficaria invisível nele (branco puro em fundo
    claro, preto puro em fundo escuro)."""
    target_name = "white" if bg == _LIGHT_BG else "black"
    target_hex = "#ffffff" if bg == _LIGHT_BG else "#000000"
    replacement = "#808080"
    stroke_re = re.compile(rf"stroke:({target_name}|{target_hex})\b", re.IGNORECASE)
    fill_attr_re = re.compile(rf'fill="({target_name}|{target_hex})"', re.IGNORECASE)
    fill_style_re = re.compile(rf"fill:({target_name}|{target_hex})\b", re.IGNORECASE)
    svg_text = stroke_re.sub(f"stroke:{replacement}", svg_text)
    svg_text = fill_attr_re.sub(f'fill="{replacement}"', svg_text)
    svg_text = fill_style_re.sub(f"fill:{replacement}", svg_text)
    return svg_text


def _robust_axis_range(values, declared_span: float):
    """Pra um eixo (x ou y, separado): se a extensão bruta de TODOS os
    pontos já bate com o que o dwg2SVG declarou (dentro de uma folga
    generosa), esse eixo está limpo — usa o min/max bruto direto, sem
    filtrar nada (evita cortar conteúdo real só porque é mais esparso, tipo
    a moldura de uma prancha, longe do miolo denso do desenho — visto num
    arquivo real). Só filtra (mediana + desvio absoluto mediano, tolera até
    quase metade dos pontos sendo lixo) quando a extensão bruta é MUITAS
    vezes maior que a declarada — sinal de coordenada corrompida de
    verdade, não de conteúdo real só um pouco mais espalhado (visto em
    outro arquivo real: 20%+ dos pontos saíram na casa dos bilhões, um eixo
    só, o outro eixo desse MESMO arquivo estava limpo). Retorna
    (lo, hi, foi_filtrado)."""
    lo, hi = min(values), max(values)
    raw_span = hi - lo
    if declared_span <= 0 or raw_span <= declared_span * 3.0:
        return lo, hi, False
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values) or max(declared_span, 1.0) * 0.01
    k = 20  # margem generosa: testado estável entre k=10 e k=100 num caso real
    inliers = [v for v in values if abs(v - med) < k * mad]
    if len(inliers) < 10:
        return lo, hi, False
    return min(inliers), max(inliers), True


_PATH_ELEM_RE = re.compile(r'(<path id="[^"]+" d=")([^"]+)(")')
_PATH_CMD_TOKEN_RE = re.compile(r"([MLAZ])")
_ARC_ARGS_RE = re.compile(
    r"\s*(-?\d+\.\d+),(-?\d+\.\d+)\s+(-?\d+\.?\d*)\s+(\d),(\d)\s+(-?\d+\.\d+),(-?\d+\.\d+)\s*"
)
_POINT_ARGS_RE = re.compile(r"\s*(-?\d+\.\d+),(-?\d+\.\d+)\s*")


def _shift_path_d(d: str, dx: float, dy: float) -> str:
    """Desloca todo ponto de verdade (M/L, e só o x,y final do comando de
    arco — não seu raio/rotação/flags) em (dx,dy). Levanta ValueError pra
    qualquer sintaxe que não reconheça — prefere recusar a deslocar
    errado."""
    parts = _PATH_CMD_TOKEN_RE.split(d)
    if len(parts) < 3 or parts[0].strip():
        raise ValueError("d não começa com um comando conhecido")
    out = [parts[0]]
    for i in range(1, len(parts), 2):
        cmd, args = parts[i], parts[i + 1]
        if cmd in ("M", "L"):
            m = _POINT_ARGS_RE.fullmatch(args)
            if not m:
                raise ValueError(f"args inesperados pra {cmd}: {args!r}")
            x, y = float(m.group(1)) + dx, float(m.group(2)) + dy
            out.append(f"{cmd} {x:.6f},{y:.6f}")
        elif cmd == "A":
            m = _ARC_ARGS_RE.fullmatch(args)
            if not m:
                raise ValueError(f"args inesperados pra A: {args!r}")
            rx, ry, rot, large, sweep, x, y = m.groups()
            x2, y2 = float(x) + dx, float(y) + dy
            out.append(f"A {rx},{ry} {rot} {large},{sweep} {x2:.6f},{y2:.6f}")
        elif cmd == "Z":
            if args.strip():
                raise ValueError(f"args inesperados pra Z: {args!r}")
            out.append("Z")
        else:
            raise ValueError(f"comando desconhecido: {cmd!r}")
    return "".join(out)


def _recover_offset_entities(svg_text: str) -> str:
    """Confirmado com um arquivo real: um grupo de pontos (coerente entre
    si — formam segmentos de verdade, não são ruído solto) ficava fora da
    área normal do desenho inteiro só porque faltava subtrair a origem que
    o próprio dwg2SVG declarou pro viewBox (x0,y0) — provavelmente um bug
    do LibreDWG deixando de aplicar essa subtração pra algumas entidades
    específicas. Só mexe em <path> (a maioria do conteúdo); só aplica a
    correção quando TODOS os pontos da entidade primeiro estão fora da
    faixa normal e, depois de corrigidos, caem dentro dela (com folga) —
    senão deixa a entidade como está. Roda antes de _tighten_viewbox, pra
    esse conteúdo recuperado já entrar na conta do enquadramento final."""
    m = _VIEWBOX_FULL_RE.search(svg_text)
    if not m:
        return svg_text
    try:
        x0, y0, w0, h0 = (float(m.group(i)) for i in (1, 2, 3, 4))
    except ValueError:
        return svg_text
    if w0 <= 0 or h0 <= 0:
        return svg_text

    pts = _extract_points(svg_text)
    if len(pts) < 20:
        return svg_text
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    nx_lo, nx_hi, x_filtered = _robust_axis_range(xs, w0)
    ny_lo, ny_hi, y_filtered = _robust_axis_range(ys, h0)
    if not x_filtered and not y_filtered:
        return svg_text  # nenhum sinal de corrupção, nada pra tentar recuperar

    margin_x = (nx_hi - nx_lo) * 0.5 + 1.0
    margin_y = (ny_hi - ny_lo) * 0.5 + 1.0
    dx, dy = -x0, -y0

    def repl(match: "re.Match[str]") -> str:
        prefix, d, suffix = match.group(1), match.group(2), match.group(3)
        entity_pts = _PATH_ML_RE.findall(d)
        if not entity_pts:
            return match.group(0)
        exs = [float(a) for a, _ in entity_pts]
        eys = [float(b) for _, b in entity_pts]
        already_normal = (all(nx_lo <= x <= nx_hi for x in exs)
                           and all(ny_lo <= y <= ny_hi for y in eys))
        if already_normal:
            return match.group(0)
        corrected_x = [x + dx for x in exs]
        corrected_y = [y + dy for y in eys]
        converges = (all(nx_lo - margin_x <= x <= nx_hi + margin_x for x in corrected_x)
                     and all(ny_lo - margin_y <= y <= ny_hi + margin_y for y in corrected_y))
        if not converges:
            return match.group(0)
        try:
            new_d = _shift_path_d(d, dx, dy)
        except ValueError:
            return match.group(0)
        return prefix + new_d + suffix

    return _PATH_ELEM_RE.sub(repl, svg_text)


def _tighten_viewbox(svg_text: str) -> str:
    """Em mais de um arquivo real de teste, um punhado de entidades
    (provavelmente mal interpretadas pelo LibreDWG — não é incomum em DWGs
    mais antigos/atípicos) geraram coordenadas absurdas — em um caso, mais
    de 20% de todos os pontos do arquivo, bem longe (às vezes na casa dos
    bilhões) de onde o desenho de verdade está. O dwg2SVG calcula o viewBox
    a partir do bounding box de TODAS as coordenadas emitidas, então isso
    infla o viewBox inteiro — o desenho de verdade vira um pontinho perdido
    num canto de um canvas gigante e essencialmente em branco.

    X e Y são avaliados INDEPENDENTEMENTE (ver _robust_axis_range) — um
    arquivo real tinha corrupção só no eixo X; filtrar os dois juntos
    cortava a moldura, que só era "esparsa" no eixo Y, não corrompida."""
    m = _VIEWBOX_FULL_RE.search(svg_text)
    if not m:
        return svg_text
    try:
        x0, y0, w0, h0 = (float(m.group(i)) for i in (1, 2, 3, 4))
    except ValueError:
        return svg_text
    if w0 <= 0 or h0 <= 0:
        return svg_text

    pts = _extract_points(svg_text)
    if len(pts) < 20:
        return svg_text
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    x_lo, x_hi, x_filtered = _robust_axis_range(xs, w0)
    y_lo, y_hi, y_filtered = _robust_axis_range(ys, h0)
    if not x_filtered and not y_filtered:
        return svg_text  # nenhum eixo mostrou sinal de corrupção
    w1, h1 = x_hi - x_lo, y_hi - y_lo
    if w1 <= 0 or h1 <= 0:
        return svg_text

    pad_x, pad_y = w1 * 0.08, h1 * 0.08
    new_box = (x_lo - pad_x, y_lo - pad_y, w1 + 2 * pad_x, h1 + 2 * pad_y)
    return _VIEWBOX_FULL_RE.sub(
        f'viewBox="{new_box[0]:.3f} {new_box[1]:.3f} {new_box[2]:.3f} {new_box[3]:.3f}"',
        svg_text,
        count=1,
    )


def _thicken_hairlines(svg_text: str) -> str:
    """O dwg2SVG usa "stroke-width:0.1px" pra praticamente tudo, em unidades
    do próprio desenho — pra um desenho grande isso vira sub-pixel na tela e
    fica invisível. Estabelece um piso proporcional ao tamanho do viewBox
    (não mexe em traços já mais grossos que isso)."""
    m = _VIEWBOX_RE.search(svg_text)
    if not m:
        return svg_text
    try:
        w, h = float(m.group(1)), float(m.group(2))
    except ValueError:
        return svg_text
    if w <= 0 or h <= 0:
        return svg_text
    # O painel de preview mostra o viewBox inteiro encolhido pra caber numa
    # largura de uns ~330px (fitInView) — então "0.1px" nas unidades do
    # desenho vira bem menos que 1 pixel de verdade na tela. Calibra o piso
    # pra ~0.35px nesse tamanho típico de enquadramento — só o suficiente
    # pra não sumir, sem ficar grosso (foram 3 rodadas de ajuste: 1.5px
    # "muito grosso" -> 0.7px ainda grosso -> 0.5px "reduz mais um pouco" ->
    # 0.35px — como agora dá pra dar zoom pra ver detalhe, não precisa
    # mirar em "bem visível de cara", só em "não invisível"). Qt não
    # suporta o vector-effect="non-scaling-stroke" do SVG, então o traço é
    # uma largura fixa nas unidades do desenho — ao dar zoom ele engrossa
    # na tela junto (isso é esperado/correto, não dá pra evitar sem
    # reprocessar o SVG a cada nível de zoom).
    min_stroke = max(w, h) * 0.35 / 330.0

    def repl(match: "re.Match[str]") -> str:
        try:
            val = float(match.group(1))
        except ValueError:
            return match.group(0)
        return f"stroke-width:{min_stroke:.4f}px" if val < min_stroke else match.group(0)

    return _STROKE_WIDTH_RE.sub(repl, svg_text)


def _libredwg_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent.parent  # infrastructure/services/ -> projeto/
    return base / "resources" / "libredwg"


def render_dwg_to_svg(path: str) -> Optional[Tuple[str, str]]:
    """Converte um DWG em SVG chamando o dwg2SVG.exe embutido. Retorna
    (texto_do_svg, cor_de_fundo_recomendada) — com pelo menos um elemento
    desenhável — ou None."""
    exe = _libredwg_dir() / "dwg2SVG.exe"
    if not exe.exists():
        return None
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        proc = subprocess.run(
            [str(exe), "--mspace", path],
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None

    if proc.returncode != 0:
        return None
    svg_text = proc.stdout.decode("utf-8", errors="replace")
    if "<svg" not in svg_text:
        return None
    # dwg2SVG sempre gera um <svg>...</svg> válido mesmo quando não acha
    # nada pra desenhar (só o <g id="symbol-..."> vazio do paper-space) —
    # só vale a pena mostrar se tiver pelo menos um elemento geométrico real.
    drawable_tags = ("<line", "<circle", "<ellipse", "<path", "<polyline",
                      "<polygon", "<rect", "<text", "<image")
    if not any(tag in svg_text for tag in drawable_tags):
        return None
    bg = _pick_background(svg_text)
    svg_text = _recolor_for_background(svg_text, bg)
    svg_text = _recover_offset_entities(svg_text)
    svg_text = _tighten_viewbox(svg_text)
    svg_text = _thicken_hairlines(svg_text)
    return svg_text, bg
