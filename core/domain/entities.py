"""
DemandFlow - Entidades do Domínio
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from enum import Enum


class Status(str, Enum):
    NAO_INICIADA = "nao_iniciada"
    EM_ANDAMENTO = "em_andamento"
    AGUARDANDO   = "aguardando"
    BLOQUEADA    = "bloqueada"
    CONCLUIDA    = "concluida"
    CANCELADA    = "cancelada"

    @property
    def label(self):
        return {
            "nao_iniciada": "Não Iniciada",
            "em_andamento": "Em Andamento",
            "aguardando":   "Aguardando Terceiros",
            "bloqueada":    "Bloqueada",
            "concluida":    "Concluída",
            "cancelada":    "Cancelada",
        }[self.value]

    @property
    def icon(self):
        return {
            "nao_iniciada": "○",
            "em_andamento": "◐",
            "aguardando":   "⏳",
            "bloqueada":    "⛔",
            "concluida":    "✓",
            "cancelada":    "✕",
        }[self.value]

    @property
    def fa_icon(self) -> str:
        return {
            "nao_iniciada": "mdi.circle-outline",
            "em_andamento": "fa6s.circle-half-stroke",
            "aguardando":   "fa6s.clock",
            "bloqueada":    "fa6s.ban",
            "concluida":    "fa6s.circle-check",
            "cancelada":    "fa6s.circle-xmark",
        }[self.value]

    @property
    def color(self):
        return {
            "nao_iniciada": "#6B7280",
            "em_andamento": "#2563EB",
            "aguardando":   "#D97706",
            "bloqueada":    "#DC2626",
            "concluida":    "#059669",
            "cancelada":    "#9CA3AF",
        }[self.value]


class Priority(str, Enum):
    BAIXA   = "baixa"
    MEDIA   = "media"
    ALTA    = "alta"
    CRITICA = "critica"

    @property
    def label(self):
        return {"baixa": "Baixa", "media": "Média", "alta": "Alta", "critica": "Crítica"}[self.value]

    @property
    def weight(self):
        return {"baixa": 1, "media": 2, "alta": 3, "critica": 4}[self.value]

    @property
    def color(self):
        return {"baixa": "#6B7280", "media": "#2563EB", "alta": "#D97706", "critica": "#DC2626"}[self.value]


class CommentType(str, Enum):
    COMMENT  = "comment"
    NOTE     = "note"
    DECISION = "decision"
    MEETING  = "meeting"

    @property
    def label(self):
        return {"comment": "Comentário", "note": "Nota Técnica",
                "decision": "Decisão", "meeting": "Reunião"}[self.value]


CATEGORIES = [
    "Desenvolvimento", "Automação Industrial", "Gestão de Projetos",
    "Infraestrutura", "Engenharia", "Suporte", "Documentação",
    "Reunião", "Análise", "Outro"
]


@dataclass
class Comment:
    id: int
    demand_id: int
    author: str
    text: str
    comment_type: CommentType
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class HistoryEntry:
    id: int
    demand_id: int
    action: str
    user: str
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Attachment:
    id: int
    demand_id: int
    filename: str
    filepath: str
    file_type: str
    created_at: datetime = field(default_factory=datetime.now)


# Peso de cada fase padrão de uma demanda — usado tanto pra dimensionar as
# janelas dos milestones criados em seed_milestones quanto pra ponderar a
# sugestão de distribuição de horas planejadas por semana (capacity planning).
# Desenvolvimento pesa mais porque historicamente consome mais tempo que as
# outras duas fases.
PHASE_WEIGHT_ESCOPO    = 0.20
PHASE_WEIGHT_DESENV    = 0.55
PHASE_WEIGHT_CONCLUSAO = 0.25


@dataclass
class Milestone:
    id: int
    demand_id: int
    title: str
    deadline: date
    done: bool = False
    depends_on_id: Optional[int] = None


@dataclass
class Reminder:
    id: int
    demand_id: int
    title: str
    remind_at: date
    note: str = ""
    done: bool = False
    daily: bool = False


@dataclass
class WorkLog:
    """
    Representa uma sessão de trabalho.
    demand_id=None indica atividade avulsa (sem demanda associada).
    """
    id: int
    demand_id: Optional[int]
    started_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: int
    note: str = ""
    manual: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    category: str = ""             # ex: "Suporte", "Reunião" — usado em atividades avulsas

    @property
    def duration_hours(self) -> float:
        return self.duration_seconds / 3600

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    @property
    def duration_display(self) -> str:
        """Retorna string formatada ex: 2h30 ou 45min"""
        total = self.duration_seconds
        h = total // 3600
        m = (total % 3600) // 60
        if h > 0:
            return f"{h}h{m:02d}min" if m else f"{h}h"
        return f"{m}min"


@dataclass
class PlannedAllocation:
    """Horas planejadas de uma demanda numa semana específica (capacity planning).
    week_start é sempre a segunda-feira ISO da semana."""
    id: int
    demand_id: int
    week_start: date
    planned_hours: float = 0.0


@dataclass
class Demand:
    id: int
    title: str
    description: str
    status: Status
    priority: Priority
    category: str
    client: str
    responsible: str
    estimated_hours: float
    real_hours: float
    deadline: date
    created_at: date = field(default_factory=date.today)
    last_activity: date = field(default_factory=date.today)
    tags: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    history: list[HistoryEntry] = field(default_factory=list)
    dependency_ids: list[int] = field(default_factory=list)
    notes: str = ""

    @property
    def is_overdue(self) -> bool:
        if self.status in (Status.CONCLUIDA, Status.CANCELADA):
            return False
        return self.deadline < date.today()

    @property
    def days_since_activity(self) -> int:
        return (date.today() - self.last_activity).days

    @property
    def is_inactive(self) -> bool:
        if self.status in (Status.CONCLUIDA, Status.CANCELADA):
            return False
        return self.days_since_activity >= 5

    @property
    def days_until_deadline(self) -> int:
        return (self.deadline - date.today()).days

    @property
    def efficiency(self) -> Optional[float]:
        if self.status != Status.CONCLUIDA or self.estimated_hours == 0:
            return None
        return self.real_hours / self.estimated_hours * 100

    @property
    def progress_pct(self) -> float:
        if self.estimated_hours == 0:
            return 0
        return min(100, self.real_hours / self.estimated_hours * 100)
