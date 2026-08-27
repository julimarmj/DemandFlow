"""
DemandFlow - Extração da miniatura embutida em arquivos DWG

DWG não tem biblioteca Python leve pra ler/desenhar de verdade (equivalente
ao que QtPdf faz com PDF) — precisaria do AutoCAD instalado ou reimplementar
boa parte do parser binário proprietário da Autodesk. O que este módulo faz
é bem mais modesto: a maioria dos DWG salvos pelo AutoCAD guarda, dentro do
próprio arquivo, uma miniatura estática (baixa resolução) usada por visores
de thumbnail — é essa miniatura que extraímos aqui, sem precisar de nenhuma
dependência nova.

Cobertura por formato interno do DWG (a "versão" do arquivo, não a versão do
AutoCAD que abriu por último):
  - AC1012-AC1017 (R13 até R2002): formato antigo, a miniatura fica "solta"
    no arquivo entre dois marcadores de 16 bytes — é só procurar.
  - AC1018 (R2004-2006) e AC1024/AC1027/AC1032 (R2010 em diante, incluindo
    2013/2018/2022/2024 — a Autodesk não mudou mais essa marca de versão de
    contêiner desde 2018): a miniatura fica dentro de uma seção nomeada
    "AcDb:Preview", guardada num contêiner comprimido/ofuscado (não é
    criptografia de verdade, é só ofuscação — o algoritmo é documentado
    publicamente pela Open Design Alliance). Reimplementamos aqui só o
    suficiente pra achar e descomprimir essa seção específica.
  - AC1021 (R2007-2009): usa um terceiro formato de contêiner, diferente
    dos dois acima. Não é coberto — cai no fallback normal.

Referência usada para portar o algoritmo (com verificação linha a linha no
código-fonte, não só documentação): LibreDWG (GPL), especialmente
src/decode.c (decompress_R2004_section, read_R2004_section_map,
read_R2004_section_info, read_2004_compressed_section, dwg_bmp) e
src/common.c (sentinelas). Qualquer arquivo sem essa miniatura salva, ou de
uma versão/variação não coberta, simplesmente não gera preview — sem erro
pro usuário, só cai no "sem pré-visualização disponível".
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional, Tuple

# Marca de 16 bytes que delimita a miniatura no formato antigo (R13-2000) e
# abre a seção "AcDb:Preview" já descomprimida no formato novo (R2004+).
_THUMBNAIL_BEGIN = bytes(
    (0x1F, 0x25, 0x6D, 0x07, 0xD4, 0x36, 0x28, 0x28,
     0x9D, 0x57, 0xCA, 0x3F, 0x9D, 0x44, 0x10, 0x2B)
)
_THUMBNAIL_END = bytes(
    (0xE0, 0xDA, 0x92, 0xF8, 0x2B, 0xC9, 0xD7, 0xD7,
     0x62, 0xA8, 0x35, 0xC0, 0x62, 0xBB, 0xEF, 0xD4)
)

_OLD_VERSIONS = {"AC1012", "AC1013", "AC1014", "AC1015", "AC1016", "AC1017"}
_NEW_VERSIONS = {"AC1018", "AC1024", "AC1027", "AC1032"}

# Nunca escaneia/lê arquivos absurdamente grandes por inteiro na memória —
# isso só se aplica ao caminho "formato antigo" (raw scan do arquivo todo).
_OLD_FORMAT_MAX_SCAN_BYTES = 200 * 1024 * 1024


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _i32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<i", buf, off)[0]


def _u64(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


# ── LZ77 (variante proprietária usada nas seções "sistema" do R2004+) ──────

class _Reader:
    __slots__ = ("data", "pos", "size")

    def __init__(self, data: bytes):
        # Um pouco de folga no fim: o algoritmo original lê de um buffer que
        # sempre tem espaço extra alocado (calloc maior que o necessário) e
        # pode, em condições de borda, ler 1-2 bytes além do fim lógico.
        self.data = data + b"\x00" * 16
        self.pos = 0
        self.size = len(data)

    def read_u8(self) -> int:
        b = self.data[self.pos]
        self.pos += 1
        return b


class _Writer:
    __slots__ = ("data", "pos", "size")

    def __init__(self, data: bytearray, pos: int, size: int):
        self.data = data
        self.pos = pos
        self.size = size  # limite (índice absoluto, exclusivo)


def _copy_bytes(n: int, src: _Reader, dst: _Writer) -> int:
    for _ in range(n):
        dst.data[dst.pos] = src.read_u8()
        dst.pos += 1
    return src.read_u8()


def _read_literal_length(src: _Reader, opcode: int) -> int:
    lowbits = opcode & 0xF
    if lowbits == 0:
        lastbyte = 0
        while True:
            lastbyte = src.read_u8()
            if lastbyte == 0 and src.pos < src.size:
                lowbits += 0xFF
            else:
                break
        lowbits += 0xF + lastbyte
    return lowbits + 3


def _read_compressed_bytes(src: _Reader, opcode: int, bits: int) -> int:
    n = opcode & bits
    if n == 0:
        lastbyte = 0
        while True:
            lastbyte = src.read_u8()
            if lastbyte == 0 and src.pos < src.size:
                n += 0xFF
            else:
                break
        n += lastbyte + bits
    return n + 2


def _two_byte_offset(src: _Reader, plus: int, offset: int) -> Tuple[int, int]:
    first = src.read_u8()
    second = src.read_u8()
    offset |= (first >> 2)
    offset |= (second << 6)
    offset += plus
    return first, offset


def _lz77_decompress(src_bytes: bytes, dst: bytearray, dst_pos: int, dst_end: int) -> None:
    """Descomprime `src_bytes` escrevendo em dst[dst_pos:dst_end] (variante
    LZ77 usada pelas seções de sistema do DWG R2004+). Levanta ValueError em
    qualquer inconsistência — quem chama trata isso como "sem preview"."""
    src = _Reader(src_bytes)
    w = _Writer(dst, dst_pos, dst_end)

    opcode1 = src.read_u8()
    if (opcode1 & 0xF0) == 0:
        opcode1 = _copy_bytes(_read_literal_length(src, opcode1), src, w)

    while src.pos < src.size and w.pos < w.size and opcode1 != 0x11:
        comp_bytes = 0
        comp_offset = 0
        if opcode1 < 0x10 or opcode1 >= 0x40:
            comp_bytes = (opcode1 >> 4) - 1
            opcode2 = src.read_u8()
            comp_offset = (((opcode1 >> 2) & 3) | (opcode2 << 2)) + 1
        elif opcode1 < 0x20:
            comp_bytes = _read_compressed_bytes(src, opcode1, 7)
            comp_offset = (opcode1 & 8) << 11
            opcode1, comp_offset = _two_byte_offset(src, 0x4000, comp_offset)
        elif opcode1 >= 0x20:
            comp_bytes = _read_compressed_bytes(src, opcode1, 0x1F)
            opcode1, comp_offset = _two_byte_offset(src, 1, comp_offset)
        else:
            break  # inalcançável (mantido só espelhando o C)

        pos = w.pos
        end = pos + comp_bytes
        if (end > w.size or pos < comp_offset
                or (pos - comp_offset) >= w.size or comp_offset > w.size):
            raise ValueError("fluxo LZ77 do DWG inconsistente (back-reference fora dos limites)")
        for p in range(pos, end):
            w.data[p] = w.data[p - comp_offset]
        w.pos = end

        lit_length = opcode1 & 3
        if lit_length == 0:
            opcode1 = src.read_u8()
            if (opcode1 & 0xF0) == 0:
                lit_length = _read_literal_length(src, opcode1)
        if lit_length and end + lit_length <= w.size:
            opcode1 = _copy_bytes(lit_length, src, w)
        elif lit_length:
            break


# ── Formato antigo (R13-2000): a miniatura fica solta entre 2 marcadores ──

def _extract_old_format(data: bytes) -> Optional[bytes]:
    begin = data.find(_THUMBNAIL_BEGIN)
    if begin < 0:
        return None
    start = begin + 16
    end = data.find(_THUMBNAIL_END, start)
    if end < 0 or end < start:
        return None
    return data[start:end]


# ── Formato novo (R2004+): seção "AcDb:Preview" dentro do contêiner ───────

def _decrypt_r2004_header(ciphertext: bytes) -> bytes:
    # XOR com um "one-time pad" gerado por um LCG de seed fixa — não é
    # criptografia real, é só ofuscação (documentado publicamente).
    rseed = 1
    out = bytearray(len(ciphertext))
    for i, b in enumerate(ciphertext):
        rseed = (rseed * 0x343FD + 0x269EC3) & 0xFFFFFFFF
        out[i] = b ^ ((rseed >> 0x10) & 0xFF)
    return bytes(out)


def _read_section_map(f, section_map_address: int, section_array_size: int) -> dict:
    """Retorna {numero_da_secao: endereco_absoluto_no_arquivo}."""
    f.seek(section_map_address + 0x100)
    hdr = f.read(20)
    if len(hdr) < 20 or _u32(hdr, 0) != 0x41630E3B:
        raise ValueError("Section Page Map inválido")
    decomp_size = _u32(hdr, 4)
    comp_size = _u32(hdr, 8)
    if decomp_size <= 0 or decomp_size > 0xFF000000 or comp_size <= 0:
        raise ValueError("tamanho de Section Page Map inválido")
    comp_data = f.read(comp_size)
    dec = bytearray(decomp_size + 1024)
    _lz77_decompress(comp_data, dec, 0, decomp_size)

    sections: dict = {}
    section_address = 0x100
    pos = 0
    n = decomp_size
    while n - pos >= 8:
        number = _i32(dec, pos)
        size = _u32(dec, pos + 4)
        pos += 8
        addr = section_address
        if number <= section_array_size:
            section_address += size
        sections[number] = addr
        if number < 0 and (n - pos) >= 16:
            pos += 16
    return sections


def _read_section_info(f, address: int) -> Optional[dict]:
    """Acha o descritor da seção "AcDb:Preview" na tabela de Section Info.
    Retorna {"size": int, "max_decomp_size": int, "compressed": int,
    "pages": [(numero, addr_decomp_alvo), ...]} ou None se não achar."""
    f.seek(address)
    hdr = f.read(20)
    if len(hdr) < 20 or _u32(hdr, 0) != 0x4163003B:
        raise ValueError("Section Info inválido")
    decomp_size = _u32(hdr, 4)
    comp_size = _u32(hdr, 8)
    if decomp_size <= 0 or comp_size <= 0 or decomp_size > 0x2F000000:
        raise ValueError("tamanho de Section Info inválido")
    comp_data = f.read(comp_size)
    dec = bytearray(decomp_size + 1024)
    _lz77_decompress(comp_data, dec, 0, decomp_size)

    num_desc = _u32(dec, 0)
    pos = 20
    for _ in range(num_desc):
        if pos + 32 + 64 > len(dec):
            break
        size8 = _u64(dec, pos)
        num_sections = _u32(dec, pos + 8)
        max_decomp_size = _u32(dec, pos + 12)
        compressed = _u32(dec, pos + 20)
        pos += 32
        name = bytes(dec[pos:pos + 64]).split(b"\x00", 1)[0].decode("ascii", errors="replace")
        pos += 64
        pages = []
        for _j in range(num_sections):
            if pos + 16 > len(dec):
                break
            pnum = _i32(dec, pos)
            paddr = _u64(dec, pos + 8)
            pos += 16
            pages.append((pnum, paddr))
        if name == "AcDb:Preview":
            return {
                "size": size8,
                "max_decomp_size": max_decomp_size,
                "compressed": compressed,
                "pages": pages,
            }
    return None


def _read_preview_section(f, sections: dict, info: dict) -> bytes:
    pages = info["pages"]
    max_decomp_size = info["max_decomp_size"]
    total_size = info["size"]
    capacity = max(total_size, len(pages) * max_decomp_size, 1)
    buf = bytearray(capacity + 1024)

    for pnum, _page_addr_hint in pages:
        # _page_addr_hint (o "address" listado no Section Info) não é usado:
        # a posição real de escrita vem de fields[4] no cabeçalho de 32
        # bytes da própria página (lido abaixo), igual o LibreDWG faz.
        file_addr = sections.get(pnum)
        if file_addr is None:
            raise ValueError(f"página {pnum} da seção Preview não encontrada")
        f.seek(file_addr)
        raw32 = f.read(32)
        if len(raw32) < 32:
            raise ValueError("cabeçalho de página truncado")
        sec_mask = (0x4164536B ^ file_addr) & 0xFFFFFFFF
        fields = [(_u32(raw32, k * 4) ^ sec_mask) & 0xFFFFFFFF for k in range(8)]
        data_size, page_size, page_target_offset = fields[2], fields[3], fields[4]

        if info["compressed"] == 2:
            comp_data = f.read(data_size)
            _lz77_decompress(comp_data, buf, page_target_offset,
                              page_target_offset + max_decomp_size)
        else:
            copy_len = min(total_size - page_target_offset, page_size)
            if copy_len > 0:
                raw = f.read(copy_len)
                buf[page_target_offset:page_target_offset + len(raw)] = raw

    return bytes(buf[:total_size])


def _extract_new_format(f, version: str) -> Optional[bytes]:
    f.seek(0x80)
    ciphertext = f.read(0x6C)
    if len(ciphertext) < 0x6C:
        return None
    header = _decrypt_r2004_header(ciphertext)
    if header[0:11] != b"AcFssFcAJMB":
        return None

    section_map_address = _u64(header, 0x54)
    section_info_id = _i32(header, 0x5C)
    section_array_size = _u32(header, 0x60)

    sections = _read_section_map(f, section_map_address, section_array_size)
    info_address = sections.get(section_info_id)
    if info_address is None:
        return None
    info = _read_section_info(f, info_address)
    if not info or not info["pages"]:
        return None
    preview_section = _read_preview_section(f, sections, info)
    if preview_section[:16] != _THUMBNAIL_BEGIN:
        return None
    return preview_section[16:]


# ── Interpretação do bloco de imagem (comum aos dois formatos) ────────────

def _parse_thumbnail_chain(chain: bytes) -> Optional[Tuple[bytes, int]]:
    """A partir dos bytes logo após a marca de 16 bytes, acha a imagem de
    verdade (BMP=2, WMF=3, PNG=6 — WMF não é suportado). Retorna
    (bytes_da_imagem, tipo) ou None."""
    if len(chain) < 5:
        return None
    osize = _u32(chain, 0)
    if osize > len(chain) - 4:
        return None
    num_headers = chain[4]
    pos = 5
    header_size = 0
    image_size = 0
    image_type = 0
    found_bmp = False
    for _ in range(num_headers):
        if pos + 1 > len(chain):
            break
        htype = chain[pos]
        pos += 1
        if pos + 4 > len(chain):
            break
        pos += 4  # "address" — não usado pra extrair os bytes
        if pos + 4 > len(chain):
            break
        size_field = _u32(chain, pos)
        pos += 4
        if htype == 1:
            header_size += size_field
        elif htype == 2 and not found_bmp:
            image_size = size_field
            image_type = 2
            found_bmp = True
        elif htype in (3, 6):
            image_size = size_field
            image_type = htype
    data_start = pos + header_size
    if image_size <= 0 or data_start + image_size > len(chain):
        return None
    return chain[data_start:data_start + image_size], image_type


def _dib_to_bmp(dib: bytes) -> Optional[bytes]:
    """Os bytes de imagem tipo BMP guardados no DWG são o DIB completo (tudo
    que tem num .bmp, exceto o cabeçalho de arquivo de 14 bytes) — falta só
    prefixar esse cabeçalho pra virar um .bmp de verdade."""
    if len(dib) < 40:
        return None
    bi_size = _u32(dib, 0)
    if bi_size < 40 or bi_size > len(dib):
        return None
    bi_bit_count = _u16(dib, 14)
    bi_clr_used = _u32(dib, 32)
    if bi_clr_used:
        palette_colors = bi_clr_used
    elif bi_bit_count <= 8:
        palette_colors = 1 << bi_bit_count
    else:
        palette_colors = 0
    pixel_offset = 14 + bi_size + palette_colors * 4
    file_size = 14 + len(dib)
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset)
    return file_header + dib


def extract_dwg_thumbnail(path: str) -> Optional[Tuple[bytes, str]]:
    """Tenta extrair a miniatura embutida de um DWG.
    Retorna (bytes_da_imagem, "bmp"|"png") prontos pra carregar num
    QPixmap/QImage, ou None se não achar/não suportar (nunca levanta —
    qualquer falha de parsing vira None, tratado como "sem preview")."""
    p = Path(path)
    try:
        with open(p, "rb") as f:
            version = f.read(6).decode("ascii", errors="replace")
            if version in _OLD_VERSIONS:
                if p.stat().st_size > _OLD_FORMAT_MAX_SCAN_BYTES:
                    return None
                f.seek(0)
                chain = _extract_old_format(f.read())
                if chain is None:
                    return None
            elif version in _NEW_VERSIONS:
                chain = _extract_new_format(f, version)
                if chain is None:
                    return None
            else:
                return None
    except (OSError, ValueError, struct.error, IndexError):
        return None

    try:
        parsed = _parse_thumbnail_chain(chain)
        if not parsed:
            return None
        image_bytes, image_type = parsed
        if image_type == 2:
            bmp = _dib_to_bmp(image_bytes)
            return (bmp, "bmp") if bmp else None
        if image_type == 6:
            return image_bytes, "png"
        return None  # WMF (3) ou tipo desconhecido — não suportado
    except (ValueError, struct.error, IndexError):
        return None
