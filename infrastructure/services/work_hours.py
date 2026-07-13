"""
DemandFlow - Cálculo de horas úteis
Usado por apontamentos manuais (descontando almoço e fora do expediente).
"""
from datetime import datetime, time, timedelta

# ── Configuração de expediente ────────────────────────────────────────────────

WORK_START  = time(8,  0)   # 08:00
LUNCH_START = time(12, 0)   # 12:00
LUNCH_END   = time(13, 0)   # 13:00
WORK_END    = time(17, 0)   # 17:00


def effective_seconds(start: datetime, end: datetime) -> int:
    """
    Calcula segundos trabalhados entre start e end,
    descontando almoço (12-13) e fora do expediente (antes 08 / depois 17).
    Suporta spans de múltiplos dias.
    """
    if end <= start:
        return 0

    total = 0
    cursor = start

    while cursor.date() <= end.date():
        day_start = datetime.combine(cursor.date(), WORK_START)
        day_lunch_start = datetime.combine(cursor.date(), LUNCH_START)
        day_lunch_end   = datetime.combine(cursor.date(), LUNCH_END)
        day_end   = datetime.combine(cursor.date(), WORK_END)

        seg_start = max(cursor, day_start)
        seg_end   = min(end, day_end)

        if seg_end > seg_start:
            # Desconta almoço
            overlap_lunch = max(
                timedelta(0),
                min(seg_end, day_lunch_end) - max(seg_start, day_lunch_start)
            )
            total += int((seg_end - seg_start - overlap_lunch).total_seconds())

        # Avança para o início do próximo dia útil
        cursor = datetime.combine(cursor.date() + timedelta(days=1), WORK_START)

    return max(0, total)
