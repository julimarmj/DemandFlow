"""
Helpers compartilhados de integração com o ServiceNow.

Demandas importadas do ServiceNow têm o número do chamado como prefixo do
título (ex: "T2DMND0049050 - Elaborar plano..."). Usado pra montar o link de
abrir no ServiceNow e pra detectar demandas já conhecidas na importação via
CSV — sem precisar do sys_id (que não é derivável do número, são
identificadores independentes).
"""
import re
from typing import Optional

SERVICENOW_NUMBER_RE = re.compile(r"^(T\dDMND\d+)")
_DEMAND_URL_TEMPLATE = "https://arcelorbr.service-now.com/tsp2_demand.do?sysparm_query=number={}"


def extract_number(title: str) -> Optional[str]:
    m = SERVICENOW_NUMBER_RE.match(title or "")
    return m.group(1) if m else None


def demand_url(number: str) -> str:
    return _DEMAND_URL_TEMPLATE.format(number)
