"""
DemandFlow - Serviço de IA multi-provedor com tool use
Suporte: Google Gemini, Anthropic Claude, Groq
"""
import json
import re
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, Iterator, List, Optional

from core.domain.entities import Status, Priority


SYSTEM_PROMPT = """Você é um assistente de produtividade pessoal integrado ao DemandFlow,
um sistema de gestão de demandas técnicas. Você tem acesso ao estado atual de todas as
demandas do usuário e deve ajudá-lo a tomar decisões sobre priorização, planejamento e
execução do trabalho.

Suas respostas devem ser:
- Diretas e práticas, sem enrolação
- Em português do Brasil
- Focadas em ação — sempre termine com sugestões concretas
- Curtas a moderadas (evite respostas enormes a menos que pedido)
- Formatadas com markdown simples (use **negrito**, listas com •, e títulos com ##)

Você tem acesso a ferramentas para buscar dados atualizados do sistema. Use-as sempre
que precisar de informações sobre demandas, horas ou detalhes específicos.
Seja proativo em identificar riscos, gargalos e oportunidades."""


# ── Provedores disponíveis ────────────────────────────────────────────────────
PROVIDERS: Dict[str, tuple] = {
    "gemini": ("Google Gemini",    "aistudio.google.com"),
    "claude": ("Anthropic Claude", "console.anthropic.com"),
    "groq":   ("Groq",             "console.groq.com"),
}


# ── Definição de ferramentas (formato neutro) ─────────────────────────────────
TOOL_DEFINITIONS = [
    {
        "name": "get_demands",
        "description": "Lista demandas em andamento com status, prazos e horas.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_demand_detail",
        "description": "Detalhes de uma demanda: notas, comentários, milestones e histórico.",
        "parameters": {
            "type": "object",
            "properties": {
                "demand_id": {"type": "integer"},
            },
            "required": ["demand_id"],
        },
    },
    {
        "name": "get_work_logs",
        "description": "Apontamentos de horas recentes.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer"},
            },
            "required": [],
        },
    },
    {
        "name": "get_dashboard_stats",
        "description": "Totais por status, prioridade e categoria.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_alerts",
        "description": "Alertas: demandas atrasadas, vencendo em breve e lembretes.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "change_status",
        "description": "Muda o status de uma demanda. Status válidos: nao_iniciada, em_andamento, aguardando, bloqueada, concluida, cancelada.",
        "parameters": {
            "type": "object",
            "properties": {
                "demand_id": {"type": "integer"},
                "status":    {"type": "string"},
            },
            "required": ["demand_id", "status"],
        },
    },
    {
        "name": "add_reminder",
        "description": "Cria lembrete em uma demanda. Data no formato YYYY-MM-DD.",
        "parameters": {
            "type": "object",
            "properties": {
                "demand_id":  {"type": "integer"},
                "title":      {"type": "string"},
                "remind_at":  {"type": "string"},
                "note":       {"type": "string"},
            },
            "required": ["demand_id", "title", "remind_at"],
        },
    },
]

# Tipo dos executores: dict nome → callable(**args) → str
ToolExecutors = Dict[str, Callable]


# ── Classe base ───────────────────────────────────────────────────────────────

class BaseAIService(ABC):

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Faz uma requisição leve para verificar se a chave é válida.
        Retorna (ok, mensagem_erro)."""
        ...

    @abstractmethod
    def stream_response(
        self,
        user_message: str,
        history: List[dict],
        context: Optional[str] = None,
        tool_executors: Optional[ToolExecutors] = None,
        on_tool_call: Optional[Callable[[str], None]] = None,
    ) -> Iterator[str]: ...

    @abstractmethod
    def rewrite_text(self, text: str, context: str = "") -> str: ...

    def build_context(self, demands: list) -> str:
        today = date.today()
        demands = [d for d in demands if d.status == Status.EM_ANDAMENTO]

        lines = [
            f"DATA ATUAL: {today.strftime('%d/%m/%Y (%A)')}",
            f"TOTAL DE DEMANDAS EM ANDAMENTO: {len(demands)}",
            "",
        ]

        open_d    = demands
        overdue   = [d for d in open_d if d.is_overdue]
        inactive  = [d for d in open_d if d.is_inactive]
        critical  = [d for d in open_d if d.priority == Priority.CRITICA]
        due_today = [d for d in open_d if d.deadline == today]
        due_week  = [d for d in open_d if 0 <= (d.deadline - today).days <= 7]

        lines += [
            "## RESUMO GERAL",
            f"• Em andamento: {len(open_d)}",
            f"• Atrasadas: {len(overdue)}",
            f"• Vencem hoje: {len(due_today)}",
            f"• Vencem esta semana: {len(due_week)}",
            f"• Críticas: {len(critical)}",
            f"• Inativas há +5 dias: {len(inactive)}",
            "",
        ]

        sorted_demands = sorted(
            open_d,
            key=lambda d: (not d.is_overdue, d.priority.weight * -1, d.deadline)
        )

        lines.append("## DEMANDAS EM ANDAMENTO (ordenadas por urgência)")
        for d in sorted_demands:
            days_to = (d.deadline - today).days
            deadline_str = (
                f"ATRASADA {abs(days_to)}d" if d.is_overdue
                else "vence hoje" if days_to == 0
                else f"vence em {days_to}d ({d.deadline.strftime('%d/%m')})"
            )
            inactive_str = f" | INATIVA {d.days_since_activity}d" if d.is_inactive else ""
            lines += [
                f"\n### [ID:{d.id}] [{d.priority.label.upper()}] {d.title}",
                f"  Status: {d.status.label} | {deadline_str}{inactive_str}",
                f"  Responsável: {d.responsible or '—'} | Cliente: {d.client or '—'}",
                f"  Categoria: {d.category} | Horas: {d.real_hours}/{d.estimated_hours}h",
            ]
            if d.tags:
                lines.append(f"  Tags: {', '.join(d.tags)}")
            if d.description:
                lines.append(f"  Descrição: {d.description[:200]}")
            if d.comments:
                last = d.comments[-1]
                lines.append(f"  Último comentário ({last.created_at.strftime('%d/%m')}): {last.text[:150]}")

        week_deadlines = {d.deadline for d in due_week}
        free_days = []
        for i in range(1, 8):
            day = date.fromordinal(today.toordinal() + i)
            if day.weekday() < 5 and day not in week_deadlines:
                free_days.append(day.strftime("%d/%m (%a)"))
        if free_days:
            lines += ["", "## DIAS ÚTEIS SEM ENTREGA ESTA SEMANA", *[f"• {d}" for d in free_days]]

        return "\n".join(lines)


# ── Google Gemini ─────────────────────────────────────────────────────────────

class GeminiService(BaseAIService):

    _STREAM_URL = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/gemini-flash-latest:streamGenerateContent"
    )
    _URL = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/gemini-flash-latest:generateContent"
    )

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def is_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "sua-chave-aqui"

    def test_connection(self) -> tuple:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DemandFlow/1.0"})
            with urllib.request.urlopen(req, timeout=10):
                return (True, "")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(body).get("error", {}).get("message", body)
            except Exception:
                msg = body
            return (False, msg)
        except Exception as e:
            return (False, str(e))

    def _gemini_tools(self, tool_executors: ToolExecutors) -> list:
        return [{
            "function_declarations": [
                {"name": td["name"], "description": td["description"], "parameters": td["parameters"]}
                for td in TOOL_DEFINITIONS if td["name"] in tool_executors
            ]
        }]

    def stream_response(self, user_message, history, context=None, tool_executors=None, on_tool_call=None):
        contents = []
        if context:
            first_text = f"[CONTEXTO DAS DEMANDAS]\n{context}\n\n[INSTRUÇÃO DO SISTEMA]\n{SYSTEM_PROMPT}"
            contents.append({"role": "user",  "parts": [{"text": first_text}]})
            contents.append({"role": "model", "parts": [{"text": "Entendido. Tenho o contexto e estou pronto para ajudar."}]})

        for msg in history:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        while True:
            payload: dict = {
                "contents": contents,
                "generationConfig": {"maxOutputTokens": 4000, "temperature": 0.7},
            }
            if tool_executors:
                payload["tools"] = self._gemini_tools(tool_executors)

            url = f"{self._STREAM_URL}?key={self.api_key}&alt=sse"
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )

            function_calls = []
            model_parts = []

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    for raw_line in resp:
                        line = raw_line.decode("utf-8").strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        for part in parts:
                            if "text" in part:
                                model_parts.append(part)
                                yield part["text"]
                            elif "functionCall" in part:
                                model_parts.append(part)
                                function_calls.append(part["functionCall"])

            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                try:
                    msg = json.loads(body).get("error", {}).get("message", body)
                except Exception:
                    msg = body
                raise RuntimeError(f"Erro da API Gemini ({e.code}): {msg}")
            except urllib.error.URLError as e:
                raise RuntimeError(f"Erro de conexão: {e.reason}")

            if not function_calls or not tool_executors:
                break

            # Adiciona turno do model com as tool calls
            contents.append({"role": "model", "parts": model_parts})

            # Executa e adiciona resultados
            result_parts = []
            for fc in function_calls:
                name = fc.get("name", "")
                args = fc.get("args", {})
                if on_tool_call:
                    on_tool_call(name)
                result = tool_executors[name](**args) if name in tool_executors else f"Ferramenta '{name}' não encontrada."
                print(f"[TOOL RESULT][Gemini] {name}({args}) → {str(result)[:120]}...")
                result_parts.append({
                    "functionResponse": {
                        "name": name,
                        "response": {"content": str(result)},
                    }
                })

            contents.append({"role": "user", "parts": result_parts})

    def rewrite_text(self, text: str, context: str = "") -> str:
        prompt = (
            f"Reescreva o texto abaixo de forma mais clara, profissional e objetiva. "
            f"Contexto: {context or 'texto profissional'}. "
            f"Mantenha o mesmo significado e idioma. Retorne APENAS o texto reescrito, "
            f"sem explicações, sem aspas, sem prefácio.\n\nTEXTO ORIGINAL:\n{text}"
        )
        contents = [{"role": "user", "parts": [{"text": f"[INSTRUÇÃO]\n{SYSTEM_PROMPT}\n\n{prompt}"}]}]
        payload = json.dumps({
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 800, "temperature": 0.4},
        }).encode("utf-8")

        url = f"{self._URL}?key={self.api_key}"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(body).get("error", {}).get("message", body)
            except Exception:
                msg = body
            raise RuntimeError(f"Erro da API ({e.code}): {msg}")
        except (KeyError, IndexError):
            raise RuntimeError("Resposta inesperada da API")


# ── Anthropic Claude ──────────────────────────────────────────────────────────

class ClaudeService(BaseAIService):

    _URL     = "https://api.anthropic.com/v1/messages"
    _MODEL   = "claude-haiku-4-5-20251001"
    _VERSION = "2023-06-01"

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def test_connection(self) -> tuple:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": self.api_key, "anthropic-version": self._VERSION,
                     "User-Agent": "DemandFlow/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                return (True, "")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(body).get("error", {}).get("message", body)
            except Exception:
                msg = body
            return (False, msg)
        except Exception as e:
            return (False, str(e))

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self._VERSION,
        }

    def _claude_tools(self, tool_executors: ToolExecutors) -> list:
        return [
            {"name": td["name"], "description": td["description"], "input_schema": td["parameters"]}
            for td in TOOL_DEFINITIONS if td["name"] in tool_executors
        ]

    def stream_response(self, user_message, history, context=None, tool_executors=None, on_tool_call=None):
        system = SYSTEM_PROMPT
        if context:
            system = f"{SYSTEM_PROMPT}\n\n[CONTEXTO DAS DEMANDAS]\n{context}"

        messages = []
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        while True:
            payload: dict = {
                "model": self._MODEL,
                "max_tokens": 4000,
                "temperature": 1,
                "system": system,
                "messages": messages,
                "stream": True,
            }
            if tool_executors:
                payload["tools"] = self._claude_tools(tool_executors)

            req = urllib.request.Request(
                self._URL, data=json.dumps(payload).encode(),
                headers=self._headers(), method="POST",
            )

            # Acumula blocos de conteúdo para re-envio
            current_tool_id   = None
            current_tool_name = None
            current_tool_json = ""
            tool_calls_turn: List[dict] = []   # {id, name, args}
            text_this_turn = ""

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    for raw_line in resp:
                        line = raw_line.decode("utf-8").strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        etype = data.get("type")

                        if etype == "content_block_start":
                            block = data.get("content_block", {})
                            if block.get("type") == "tool_use":
                                current_tool_id   = block.get("id")
                                current_tool_name = block.get("name")
                                current_tool_json = ""

                        elif etype == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                chunk = delta.get("text", "")
                                if chunk:
                                    text_this_turn += chunk
                                    yield chunk
                            elif delta.get("type") == "input_json_delta":
                                current_tool_json += delta.get("partial_json", "")

                        elif etype == "content_block_stop":
                            if current_tool_name:
                                try:
                                    args = json.loads(current_tool_json) if current_tool_json else {}
                                    if not isinstance(args, dict):
                                        args = {}
                                except json.JSONDecodeError:
                                    args = {}
                                tool_calls_turn.append({
                                    "id": current_tool_id,
                                    "name": current_tool_name,
                                    "args": args,
                                })
                                current_tool_id = current_tool_name = None
                                current_tool_json = ""

            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                try:
                    msg = json.loads(body).get("error", {}).get("message", body)
                except Exception:
                    msg = body
                raise RuntimeError(f"Erro da API Claude ({e.code}): {msg}")
            except urllib.error.URLError as e:
                raise RuntimeError(f"Erro de conexão: {e.reason}")

            if not tool_calls_turn or not tool_executors:
                break

            # Monta o bloco do assistente para re-envio (texto + tool_use)
            assistant_content = []
            if text_this_turn:
                assistant_content.append({"type": "text", "text": text_this_turn})
            for tc in tool_calls_turn:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["args"],
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Executa ferramentas e envia resultados
            tool_result_blocks = []
            for tc in tool_calls_turn:
                if on_tool_call:
                    on_tool_call(tc["name"])
                result = (
                    tool_executors[tc["name"]](**tc["args"])
                    if tc["name"] in tool_executors
                    else f"Ferramenta '{tc['name']}' não encontrada."
                )
                print(f"[TOOL RESULT][Claude] {tc['name']}({tc['args']}) → {str(result)[:120]}...")
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": str(result),
                })

            messages.append({"role": "user", "content": tool_result_blocks})

    def rewrite_text(self, text: str, context: str = "") -> str:
        prompt = (
            f"Reescreva o texto abaixo de forma mais clara, profissional e objetiva. "
            f"Contexto: {context or 'texto profissional'}. "
            f"Mantenha o mesmo significado e idioma. Retorne APENAS o texto reescrito, "
            f"sem explicações, sem aspas, sem prefácio.\n\nTEXTO ORIGINAL:\n{text}"
        )
        payload = json.dumps({
            "model": self._MODEL,
            "max_tokens": 800,
            "temperature": 1,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(self._URL, data=payload, headers=self._headers(), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["content"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(body).get("error", {}).get("message", body)
            except Exception:
                msg = body
            raise RuntimeError(f"Erro da API ({e.code}): {msg}")
        except (KeyError, IndexError):
            raise RuntimeError("Resposta inesperada da API")


# ── Groq ──────────────────────────────────────────────────────────────────────

class GroqService(BaseAIService):

    _URL   = "https://api.groq.com/openai/v1/chat/completions"
    _MODEL = "llama-3.3-70b-versatile"

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def test_connection(self) -> tuple:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": "DemandFlow/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                return (True, "")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(body).get("error", {}).get("message", body)
            except Exception:
                msg = body
            return (False, msg)
        except Exception as e:
            return (False, str(e))

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "DemandFlow/1.0",
        }

    def _groq_tools(self, tool_executors: ToolExecutors) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": td["name"],
                    "description": td["description"],
                    "parameters": td["parameters"],
                }
            }
            for td in TOOL_DEFINITIONS if td["name"] in tool_executors
        ]

    def stream_response(self, user_message, history, context=None, tool_executors=None, on_tool_call=None):
        system = SYSTEM_PROMPT
        if context:
            system = f"{SYSTEM_PROMPT}\n\n[CONTEXTO DAS DEMANDAS]\n{context}"

        # Groq free tier tem limite baixo de TPM — mantém só as últimas 6 mensagens
        trimmed = history[-6:] if len(history) > 6 else history
        messages = [{"role": "system", "content": system}]
        for msg in trimmed:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        empty_retries = 0
        while True:
            payload: dict = {
                "model": self._MODEL,
                "messages": messages,
                "max_tokens": 1500,   # Groq free tier: 12k TPM — contexto já ocupa ~10k
                "temperature": 0.7,
                "stream": True,
            }
            if tool_executors:
                payload["tools"] = self._groq_tools(tool_executors)
                payload["tool_choice"] = "auto"

            req = urllib.request.Request(
                self._URL, data=json.dumps(payload).encode(),
                headers=self._headers(), method="POST",
            )

            # Acumula tool calls por índice (chegam em chunks)
            tool_calls_acc: dict = {}   # index → {id, name, arguments}
            finish_reason = None
            text_this_turn = ""

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    for raw_line in resp:
                        line = raw_line.decode("utf-8").strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choice = data.get("choices", [{}])[0]
                        delta  = choice.get("delta", {})
                        finish_reason = choice.get("finish_reason") or finish_reason

                        chunk = delta.get("content", "")
                        if chunk:
                            text_this_turn += chunk
                            yield chunk

                        for tc_delta in delta.get("tool_calls", []):
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc_delta.get("id"):
                                tool_calls_acc[idx]["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                tool_calls_acc[idx]["name"] = fn["name"]
                            tool_calls_acc[idx]["arguments"] += fn.get("arguments", "")

            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                try:
                    msg = json.loads(body).get("error", {}).get("message", body)
                except Exception:
                    msg = body
                if e.code == 429:
                    # Extrai o delay sugerido pela API ("try again in X.XXs")
                    match = re.search(r"try again in ([\d.]+)s", msg)
                    wait = float(match.group(1)) + 1.0 if match else 10.0
                    print(f"[GROQ] Rate limit — aguardando {wait:.1f}s e tentando novamente...")
                    time.sleep(wait)
                    continue   # retry automático
                raise RuntimeError(f"Erro da API Groq ({e.code}): {msg}")
            except urllib.error.URLError as e:
                raise RuntimeError(f"Erro de conexão: {e.reason}")

            print(f"[GROQ] finish_reason={finish_reason} | tool_calls={list(tool_calls_acc.keys())} | text_len={len(text_this_turn)}")

            # Resposta vazia sem motivo claro — tenta até 2x antes de desistir
            if finish_reason is None and not text_this_turn and not tool_calls_acc:
                empty_retries += 1
                if empty_retries <= 2:
                    print(f"[GROQ] Resposta vazia — tentativa {empty_retries}/2, repetindo...")
                    time.sleep(1.5)
                    continue
                break

            empty_retries = 0  # reset ao receber resposta válida

            if finish_reason != "tool_calls" or not tool_calls_acc or not tool_executors:
                break

            # Monta lista de tool calls finais
            tool_calls_list = []
            for idx in sorted(tool_calls_acc.keys()):
                tc = tool_calls_acc[idx]
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls_list.append({"id": tc["id"], "name": tc["name"], "args": args, "raw_args": tc["arguments"]})

            # Adiciona mensagem do assistente com tool_calls
            messages.append({
                "role": "assistant",
                "content": text_this_turn or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["raw_args"]},
                    }
                    for tc in tool_calls_list
                ],
            })

            # Executa e adiciona resultados
            for tc in tool_calls_list:
                if on_tool_call:
                    on_tool_call(tc["name"])
                result = (
                    tool_executors[tc["name"]](**tc["args"])
                    if tc["name"] in tool_executors
                    else f"Ferramenta '{tc['name']}' não encontrada."
                )
                print(f"[TOOL RESULT][Groq] {tc['name']}({tc['args']}) → {str(result)[:120]}...")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                })

    def rewrite_text(self, text: str, context: str = "") -> str:
        prompt = (
            f"Reescreva o texto abaixo de forma mais clara, profissional e objetiva. "
            f"Contexto: {context or 'texto profissional'}. "
            f"Mantenha o mesmo significado e idioma. Retorne APENAS o texto reescrito, "
            f"sem explicações, sem aspas, sem prefácio.\n\nTEXTO ORIGINAL:\n{text}"
        )
        payload = json.dumps({
            "model": self._MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 800,
            "temperature": 0.7,
        }).encode("utf-8")

        req = urllib.request.Request(self._URL, data=payload, headers=self._headers(), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(body).get("error", {}).get("message", body)
            except Exception:
                msg = body
            raise RuntimeError(f"Erro da API ({e.code}): {msg}")
        except (KeyError, IndexError):
            raise RuntimeError("Resposta inesperada da API")


# ── Factory ───────────────────────────────────────────────────────────────────

def create_ai_service(provider: str, api_key: str) -> BaseAIService:
    if provider == "claude":
        return ClaudeService(api_key)
    if provider == "groq":
        return GroqService(api_key)
    return GeminiService(api_key)


# Alias de compatibilidade
AIService = GeminiService
