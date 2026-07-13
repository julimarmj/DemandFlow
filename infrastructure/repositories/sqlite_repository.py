"""
DemandFlow - Repositório SQLite
Implementação concreta do DemandRepository usando SQLite.
Preparado para migração para PostgreSQL (troca apenas esta camada).
"""
import sqlite3
import json
from datetime import date, datetime, timedelta
from typing import Optional
from pathlib import Path

from core.domain.entities import (
    Demand, Comment, HistoryEntry, Attachment,
    Status, Priority, CommentType
)
from core.ports.repositories import DemandRepository
from core.domain.entities import Milestone, Reminder, PlannedAllocation
from core.domain.entities import PHASE_WEIGHT_ESCOPO, PHASE_WEIGHT_DESENV
from core.domain.text_match import fuzzy_word_match as _fuzzy_word_match


def _parse_date(s) -> date:
    if isinstance(s, date):
        return s
    if not s:
        return date.today()
    return date.fromisoformat(str(s))

def _parse_datetime(s) -> datetime:
    if isinstance(s, datetime):
        return s

    if not s:
        return datetime.now()

    return datetime.fromisoformat(str(s))
class SQLiteDemandRepository(DemandRepository):

    def __init__(self, db_path: str = "demandflow.db"):
        self._db_path = db_path
        self._init_db()
        self._migrate_worklog_general_support()
        self._migrate_demand_notes()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS demands (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    title           TEXT    NOT NULL,
                    description     TEXT    DEFAULT '',
                    status          TEXT    NOT NULL DEFAULT 'nao_iniciada',
                    priority        TEXT    NOT NULL DEFAULT 'media',
                    category        TEXT    DEFAULT '',
                    client          TEXT    DEFAULT '',
                    responsible     TEXT    DEFAULT '',
                    estimated_hours REAL    DEFAULT 0,
                    real_hours      REAL    DEFAULT 0,
                    deadline        TEXT    NOT NULL,
                    created_at      TEXT    NOT NULL,
                    last_activity   TEXT    NOT NULL,
                    tags            TEXT    DEFAULT '[]',
                    dependency_ids  TEXT    DEFAULT '[]',
                    notes           TEXT    DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS comments (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_id    INTEGER NOT NULL REFERENCES demands(id) ON DELETE CASCADE,
                    author       TEXT    NOT NULL,
                    text         TEXT    NOT NULL,
                    comment_type TEXT    NOT NULL DEFAULT 'comment',
                    created_at   TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS history (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_id  INTEGER NOT NULL REFERENCES demands(id) ON DELETE CASCADE,
                    action     TEXT    NOT NULL,
                    user       TEXT    NOT NULL DEFAULT 'Usuário',
                    created_at TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS attachments (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_id  INTEGER NOT NULL REFERENCES demands(id) ON DELETE CASCADE,
                    filename   TEXT    NOT NULL,
                    filepath   TEXT    NOT NULL,
                    file_type  TEXT    DEFAULT '',
                    created_at TEXT    NOT NULL
                );
                CREATE TABLE IF NOT EXISTS milestones (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_id     INTEGER NOT NULL REFERENCES demands(id) ON DELETE CASCADE,
                    title         TEXT    NOT NULL,
                    deadline      TEXT    NOT NULL,
                    done          INTEGER NOT NULL DEFAULT 0,
                    depends_on_id INTEGER REFERENCES milestones(id) ON DELETE SET NULL,
                    sort_order    INTEGER NOT NULL DEFAULT 0
                );
                    CREATE TABLE IF NOT EXISTS reminders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_id  INTEGER NOT NULL REFERENCES demands(id) ON DELETE CASCADE,
                    title      TEXT    NOT NULL,
                    remind_at  TEXT    NOT NULL,
                    note       TEXT    DEFAULT '',
                    done       INTEGER NOT NULL DEFAULT 0,
                    daily      INTEGER NOT NULL DEFAULT 0
                );
            """)
            # Migração: adiciona coluna daily se ainda não existir
            cols = [r[1] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()]
            if "daily" not in cols:
                conn.execute("ALTER TABLE reminders ADD COLUMN daily INTEGER NOT NULL DEFAULT 0")
            #self._seed_demo_data(conn)

    def _seed_demo_data(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM demands").fetchone()[0]
        if count > 0:
            return
        today = date.today().isoformat()
        samples = [
            ("Implementar módulo de relatórios PDF",
             "Desenvolver sistema de geração de relatórios em PDF com filtros personalizáveis e templates corporativos.",
             "em_andamento", "alta", "Desenvolvimento", "TechCorp SA", "Carlos Silva",
             16, 8, "2025-06-05", today, "2025-05-28", '["backend","pdf","reports"]'),
            ("Calibração de sensores PLC Linha 3",
             "Calibrar todos os sensores de temperatura e pressão da linha de produção 3 após manutenção preventiva.",
             "aguardando", "critica", "Automação Industrial", "Indústria Alfa", "Ana Ferreira",
             8, 2, "2025-05-31", today, "2025-05-22", '["plc","sensores","manutenção"]'),
            ("Migração servidor de banco de dados",
             "Migrar PostgreSQL do servidor legado para nova infraestrutura AWS RDS com alta disponibilidade.",
             "bloqueada", "critica", "Infraestrutura", "Interno", "Ricardo Lima",
             24, 4, "2025-06-10", today, "2025-05-18", '["aws","postgresql","migração"]'),
            ("Dashboard KPIs produção mensal",
             "Criar dashboard interativo com indicadores de produção para apresentação ao board executivo.",
             "concluida", "alta", "Gestão de Projetos", "Diretoria", "Mariana Costa",
             12, 14, "2025-05-25", today, "2025-05-25", '["dashboard","kpi","powerbi"]'),
            ("Atualização documentação técnica SCADA",
             "Atualizar toda a documentação do sistema SCADA com as alterações realizadas no último trimestre.",
             "nao_iniciada", "media", "Documentação", "Indústria Alfa", "João Mendes",
             20, 0, "2025-06-20", today, "2025-05-28", '["scada","documentação"]'),
            ("Treinamento equipe NR-12",
             "Organizar e ministrar treinamento de segurança NR-12 para operadores da linha de produção.",
             "nao_iniciada", "alta", "Engenharia", "RH - Interno", "Fernanda Rocha",
             8, 0, "2025-06-15", today, "2025-05-26", '["treinamento","segurança","nr12"]'),
        ]
        '''
        for s in samples:
            conn.execute(
                "INSERT INTO demands (title,description,status,priority,category,client,responsible,"
                "estimated_hours,real_hours,deadline,created_at,last_activity,tags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                s
            )

        conn.execute(
            "INSERT INTO history (demand_id,action,user,created_at) VALUES (?,?,?,?)",
            (1, "Demanda criada", "Sistema", today)
        )
        conn.execute(
            "INSERT INTO comments (demand_id,author,text,comment_type,created_at) VALUES (?,?,?,?,?)",
            (1, "Carlos Silva", "API de templates concluída, iniciando geração de dados.", "comment", today)
        )

        '''
        first_demand_id = None
        for s in samples:
            cur = conn.execute(
                "INSERT INTO demands (title,description,status,priority,category,client,responsible,"
                "estimated_hours,real_hours,deadline,created_at,last_activity,tags)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                s
            )

            if first_demand_id is None:
                first_demand_id = cur.lastrowid
                
        conn.execute(
            "INSERT INTO history (demand_id,action,user,created_at) VALUES (?,?,?,?)",
            (first_demand_id, "Demanda criada", "Sistema", today)
        )

        conn.execute(
            "INSERT INTO comments (demand_id,author,text,comment_type,created_at) VALUES (?,?,?,?,?)",
            (
                first_demand_id,
                "Carlos Silva",
                "API de templates concluída, iniciando geração de dados.",
                "comment",
                today
            )
        )

    # ── Row → Entity ─────────────────────────────────────────────────────────

    def _row_to_demand(self, row) -> Demand:
        return Demand(
            id=row["id"],
            title=row["title"],
            description=row["description"] or "",
            status=Status(row["status"]),
            priority=Priority(row["priority"]),
            category=row["category"] or "",
            client=row["client"] or "",
            responsible=row["responsible"] or "",
            estimated_hours=row["estimated_hours"] or 0,
            real_hours=row["real_hours"] or 0,
            deadline=_parse_date(row["deadline"]),
            created_at=_parse_date(row["created_at"]),
            last_activity=_parse_date(row["last_activity"]),
            tags=json.loads(row["tags"] or "[]"),
            dependency_ids=json.loads(row["dependency_ids"] or "[]"),
            notes=row["notes"] or "",
        )

    def _row_to_comment(self, row) -> Comment:
        return Comment(
            id=row["id"], demand_id=row["demand_id"],
            author=row["author"], text=row["text"],
            comment_type=CommentType(row["comment_type"]),
            created_at=_parse_datetime(row["created_at"]),
        )

    def _row_to_history(self, row) -> HistoryEntry:
        return HistoryEntry(
            id=row["id"], demand_id=row["demand_id"],
            action=row["action"], user=row["user"],
            created_at=_parse_datetime(row["created_at"]),
        )

    def _row_to_attachment(self, row) -> Attachment:
        return Attachment(
            id=row["id"], demand_id=row["demand_id"],
            filename=row["filename"], filepath=row["filepath"],
            file_type=row["file_type"] or "",
            created_at=_parse_datetime(row["created_at"]),
        )

    # ── DemandRepository impl ────────────────────────────────────────────────

    def get_all(self) -> list[Demand]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM demands ORDER BY "
                "CASE priority WHEN 'critica' THEN 1 WHEN 'alta' THEN 2 "
                "WHEN 'media' THEN 3 ELSE 4 END, deadline ASC"
            ).fetchall()
            return [self._row_to_demand(r) for r in rows]

    def get_by_id(self, id: int) -> Optional[Demand]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM demands WHERE id=?", (id,)).fetchone()
            if not row:
                return None
            demand = self._row_to_demand(row)
            demand.comments    = self.get_comments(id)
            demand.history     = self.get_history(id)
            demand.attachments = self.get_attachments(id)
            return demand

    def save(self, demand: Demand) -> Demand:
        today = date.today().isoformat()
        with self._conn() as conn:
            if demand.id == 0:
                cur = conn.execute(
                    "INSERT INTO demands (title,description,status,priority,category,client,responsible,"
                    "estimated_hours,real_hours,deadline,created_at,last_activity,tags,dependency_ids,notes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (demand.title, demand.description, demand.status.value, demand.priority.value,
                     demand.category, demand.client, demand.responsible,
                     demand.estimated_hours, demand.real_hours,
                     demand.deadline.isoformat(), today, today,
                     json.dumps(demand.tags), json.dumps(demand.dependency_ids), demand.notes)
                )
                demand.id = cur.lastrowid
            else:
                conn.execute(
                    "UPDATE demands SET title=?,description=?,status=?,priority=?,category=?,client=?,"
                    "responsible=?,estimated_hours=?,real_hours=?,deadline=?,last_activity=?,tags=?,dependency_ids=?,notes=? "
                    "WHERE id=?",
                    (demand.title, demand.description, demand.status.value, demand.priority.value,
                     demand.category, demand.client, demand.responsible,
                     demand.estimated_hours, demand.real_hours,
                     demand.deadline.isoformat(), demand.last_activity.isoformat(),
                     json.dumps(demand.tags), json.dumps(demand.dependency_ids), demand.notes, demand.id)
                )
        return demand

    def delete(self, id: int) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM demands WHERE id=?", (id,))
        return True

    def search(self, query="", status=None, priority=None,
               category="", responsible="", client="") -> list[Demand]:
        all_d = self.get_all()
        result = []
        q = query.lower().strip()
        # Tolerância a erro de digitação só entra como fallback pra buscas de
        # 3+ caracteres — abaixo disso a correspondência aproximada vira ruído
        # (quase tudo "parece" parecido com 1-2 letras).
        allow_fuzzy = len(q) >= 3
        for d in all_d:
            if q:
                fields = [d.title, d.description, d.client, d.responsible, *d.tags]
                matched = any(q in x.lower() for x in fields)
                if not matched and allow_fuzzy:
                    matched = (
                        _fuzzy_word_match(q, d.title, 1)
                        or any(_fuzzy_word_match(q, t, 1) for t in d.tags)
                    )
                if not matched:
                    continue
            if status   and d.status    != status:   continue
            if priority and d.priority  != priority: continue
            if category and d.category  != category: continue
            if responsible and responsible.lower() not in d.responsible.lower(): continue
            if client      and client.lower()      not in d.client.lower():      continue
            result.append(d)
        return result

    def add_comment(self, comment: Comment) -> Comment:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO comments (demand_id,author,text,comment_type,created_at) VALUES (?,?,?,?,?)",
                (comment.demand_id, comment.author, comment.text,
                 comment.comment_type.value, date.today().isoformat())
            )
            comment.id = cur.lastrowid
        return comment
    '''
    def add_history(self, entry: HistoryEntry) -> HistoryEntry:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO history (demand_id,action,user,created_at) VALUES (?,?,?,?)",
                (entry.demand_id, entry.action, entry.user, date.today().isoformat())
            )
            entry.id = cur.lastrowid
        return entry
    '''

    def add_history(self, entry: HistoryEntry) -> HistoryEntry:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO history (demand_id,action,user,created_at) VALUES (?,?,?,?)",
                (
                    entry.demand_id,
                    entry.action,
                    entry.user,
                    entry.created_at.isoformat()
                )
            )
            entry.id = cur.lastrowid
        return entry
    
    def add_attachment(self, att: Attachment) -> Attachment:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO attachments (demand_id,filename,filepath,file_type,created_at) VALUES (?,?,?,?,?)",
                (att.demand_id, att.filename, att.filepath, att.file_type, date.today().isoformat())
            )
            att.id = cur.lastrowid
        return att

    def get_comments(self, demand_id: int) -> list[Comment]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM comments WHERE demand_id=? ORDER BY created_at", (demand_id,)
            ).fetchall()
            return [self._row_to_comment(r) for r in rows]

    def get_history(self, demand_id: int) -> list[HistoryEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM history WHERE demand_id=? ORDER BY created_at DESC", (demand_id,)
            ).fetchall()
            return [self._row_to_history(r) for r in rows]

    def get_attachments(self, demand_id: int) -> list[Attachment]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE demand_id=? ORDER BY created_at", (demand_id,)
            ).fetchall()
            return [self._row_to_attachment(r) for r in rows]

    def get_milestones(self, demand_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM milestones WHERE demand_id=? ORDER BY sort_order, id",
                (demand_id,)
            ).fetchall()
            return [self._row_to_milestone(r) for r in rows]
        
    def get_milestone(self, milestone_id: int):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM milestones WHERE id=?",
                (milestone_id,)
            ).fetchone()

            return self._row_to_milestone(row) if row else None

    def save_milestone(self, m) -> object:
        with self._conn() as conn:
            if m.id == 0:
                cur = conn.execute(
                    "INSERT INTO milestones (demand_id,title,deadline,done,depends_on_id,sort_order)"
                    " VALUES (?,?,?,?,?,?)",
                    (m.demand_id, m.title, m.deadline.isoformat(),
                    int(m.done), m.depends_on_id, m.id)
                )
                m.id = cur.lastrowid
            else:
                conn.execute(
                    "UPDATE milestones SET title=?,deadline=?,done=?,depends_on_id=? WHERE id=?",
                    (m.title, m.deadline.isoformat(), int(m.done), m.depends_on_id, m.id)
                )
        return m

    def delete_milestone(self, milestone_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM milestones WHERE id=?", (milestone_id,))

    def seed_milestones(self, demand_id: int, demand_deadline: date):
        """Cria os 3 milestones padrão se a demanda ainda não tiver nenhum."""
        with self._conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM milestones WHERE demand_id=?", (demand_id,)
            ).fetchone()[0]
            if count > 0:
                return
            today = date.today()
            span  = max((demand_deadline - today).days, 9)
            dates = [
                today + timedelta(days=round(span * PHASE_WEIGHT_ESCOPO)),
                today + timedelta(days=round(span * (PHASE_WEIGHT_ESCOPO + PHASE_WEIGHT_DESENV))),
                demand_deadline,
            ]
            defaults = ["Estudo de Escopo", "Desenvolvimento", "Conclusão"]
            for i, (title, dl) in enumerate(zip(defaults, dates)):
                conn.execute(
                    "INSERT INTO milestones (demand_id,title,deadline,done,depends_on_id,sort_order)"
                    " VALUES (?,?,?,0,?,?)",
                    (demand_id, title, dl.isoformat(), None if i == 0 else None, i)
                )
            # define dependências em cadeia: 2 depende de 1, 3 depende de 2
            rows = conn.execute(
                "SELECT id FROM milestones WHERE demand_id=? ORDER BY sort_order",
                (demand_id,)
            ).fetchall()
            ids = [r[0] for r in rows]
            for i in range(1, len(ids)):
                conn.execute(
                    "UPDATE milestones SET depends_on_id=? WHERE id=?",
                    (ids[i-1], ids[i])
                )

    def _row_to_milestone(self, row) -> object:
        return Milestone(
            id=row["id"], demand_id=row["demand_id"],
            title=row["title"], deadline=_parse_date(row["deadline"]),
            done=bool(row["done"]), depends_on_id=row["depends_on_id"],
        )
    
    def get_reminders(self, demand_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE demand_id=? ORDER BY remind_at",
                (demand_id,)
            ).fetchall()
            return [self._row_to_reminder(r) for r in rows]

    def get_all_reminders(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders ORDER BY remind_at"
            ).fetchall()
            return [self._row_to_reminder(r) for r in rows]

    def save_reminder(self, r) -> object:
        with self._conn() as conn:
            if r.id == 0:
                cur = conn.execute(
                    "INSERT INTO reminders (demand_id,title,remind_at,note,done,daily)"
                    " VALUES (?,?,?,?,?,?)",
                    (r.demand_id, r.title, r.remind_at.isoformat(), r.note, int(r.done), int(r.daily))
                )
                r.id = cur.lastrowid
            else:
                conn.execute(
                    "UPDATE reminders SET title=?,remind_at=?,note=?,done=?,daily=? WHERE id=?",
                    (r.title, r.remind_at.isoformat(), r.note, int(r.done), int(r.daily), r.id)
                )
        return r

    def delete_reminder(self, reminder_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))

    def _row_to_reminder(self, row) -> object:
        return Reminder(
            id=row["id"], demand_id=row["demand_id"],
            title=row["title"], remind_at=_parse_date(row["remind_at"]),
            note=row["note"] or "", done=bool(row["done"]),
            daily=bool(row["daily"]),
        )
    # ── WORK LOGS ─────────────────────────────────────────────────────────────

    def _migrate_demand_notes(self):
        """Adiciona coluna notes à tabela demands se ainda não existir."""
        with self._conn() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(demands)").fetchall()}
            if "notes" not in cols:
                conn.execute("ALTER TABLE demands ADD COLUMN notes TEXT DEFAULT ''")

    def _migrate_worklog_general_support(self):
        """Recria work_logs permitindo demand_id NULL e coluna category."""
        conn = sqlite3.connect(self._db_path)
        try:
            cols = {r[1]: r for r in conn.execute("PRAGMA table_info(work_logs)").fetchall()}
            if not cols:
                return  # tabela ainda não existe, será criada com schema correto
            needs_nullable = cols.get("demand_id") and cols["demand_id"][3] == 1
            needs_category = "category" not in cols
            if not needs_nullable and not needs_category:
                return
            conn.executescript("""
                PRAGMA foreign_keys = OFF;
                CREATE TABLE work_logs_v2 (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_id        INTEGER REFERENCES demands(id) ON DELETE CASCADE,
                    started_at       TEXT    NOT NULL,
                    ended_at         TEXT,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    note             TEXT    DEFAULT '',
                    manual           INTEGER NOT NULL DEFAULT 0,
                    created_at       TEXT    NOT NULL,
                    category         TEXT    NOT NULL DEFAULT ''
                );
                INSERT INTO work_logs_v2
                    (id,demand_id,started_at,ended_at,duration_seconds,note,manual,created_at)
                SELECT id,demand_id,started_at,ended_at,duration_seconds,note,manual,created_at
                FROM work_logs;
                DROP TABLE work_logs;
                ALTER TABLE work_logs_v2 RENAME TO work_logs;
                PRAGMA foreign_keys = ON;
            """)
        finally:
            conn.close()

    def _ensure_worklog_table(self):
        """Cria tabela se não existir (schema atual: demand_id nullable + category)."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS work_logs (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_id        INTEGER REFERENCES demands(id) ON DELETE CASCADE,
                    started_at       TEXT    NOT NULL,
                    ended_at         TEXT,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    note             TEXT    DEFAULT '',
                    manual           INTEGER NOT NULL DEFAULT 0,
                    created_at       TEXT    NOT NULL,
                    category         TEXT    NOT NULL DEFAULT ''
                )
            """)

    def get_work_logs(self, demand_id: int) -> list:
        self._ensure_worklog_table()
        from core.domain.entities import WorkLog
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM work_logs WHERE demand_id=? ORDER BY started_at DESC",
                (demand_id,)
            ).fetchall()
            return [self._row_to_worklog(r) for r in rows]

    def get_all_work_logs(self) -> list:
        self._ensure_worklog_table()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM work_logs ORDER BY started_at DESC"
            ).fetchall()
            return [self._row_to_worklog(r) for r in rows]

    def save_work_log(self, wl) -> object:
        self._ensure_worklog_table()
        cat = getattr(wl, "category", "")
        with self._conn() as conn:
            if wl.id == 0:
                cur = conn.execute(
                    "INSERT INTO work_logs "
                    "(demand_id,started_at,ended_at,duration_seconds,note,manual,created_at,category)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (
                        wl.demand_id,
                        wl.started_at.isoformat(),
                        wl.ended_at.isoformat() if wl.ended_at else None,
                        wl.duration_seconds,
                        wl.note,
                        int(wl.manual),
                        wl.created_at.isoformat(),
                        cat,
                    )
                )
                wl.id = cur.lastrowid
            else:
                conn.execute(
                    "UPDATE work_logs SET started_at=?,ended_at=?,duration_seconds=?,"
                    "note=?,manual=?,category=? WHERE id=?",
                    (
                        wl.started_at.isoformat(),
                        wl.ended_at.isoformat() if wl.ended_at else None,
                        wl.duration_seconds,
                        wl.note,
                        int(wl.manual),
                        cat,
                        wl.id,
                    )
                )
        return wl

    def delete_work_log(self, worklog_id: int):
        self._ensure_worklog_table()
        with self._conn() as conn:
            conn.execute("DELETE FROM work_logs WHERE id=?", (worklog_id,))

    def get_total_logged_hours(self, demand_id: int) -> float:
        """Soma de todos os work_logs em horas."""
        self._ensure_worklog_table()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(duration_seconds),0) FROM work_logs WHERE demand_id=?",
                (demand_id,)
            ).fetchone()
            return row[0] / 3600

    def _row_to_worklog(self, row) -> object:
        from core.domain.entities import WorkLog
        keys = row.keys()
        return WorkLog(
            id=row["id"],
            demand_id=row["demand_id"],  # pode ser None (atividade avulsa)
            started_at=_parse_datetime(row["started_at"]),
            ended_at=_parse_datetime(row["ended_at"]) if row["ended_at"] else None,
            duration_seconds=row["duration_seconds"],
            note=row["note"] or "",
            manual=bool(row["manual"]),
            created_at=_parse_datetime(row["created_at"]),
            category=row["category"] if "category" in keys else "",
        )

    # ── PLANNED ALLOCATIONS (capacity planning) ─────────────────────────────────

    def _ensure_planned_allocation_table(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS planned_allocations (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    demand_id     INTEGER NOT NULL REFERENCES demands(id) ON DELETE CASCADE,
                    week_start    TEXT    NOT NULL,
                    planned_hours REAL    NOT NULL DEFAULT 0,
                    UNIQUE(demand_id, week_start)
                )
            """)

    def get_planned_allocations(self, demand_id: int) -> list:
        self._ensure_planned_allocation_table()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM planned_allocations WHERE demand_id=? ORDER BY week_start",
                (demand_id,)
            ).fetchall()
            return [self._row_to_planned_allocation(r) for r in rows]

    def get_all_planned_allocations(self, week_from: date = None, week_to: date = None) -> list:
        """Carrega de todas as demandas de uma vez — usado pela grade de capacidade
        pra evitar uma query por demanda."""
        self._ensure_planned_allocation_table()
        with self._conn() as conn:
            q = "SELECT * FROM planned_allocations WHERE 1=1"
            params: list = []
            if week_from:
                q += " AND week_start >= ?"
                params.append(week_from.isoformat())
            if week_to:
                q += " AND week_start <= ?"
                params.append(week_to.isoformat())
            rows = conn.execute(q, params).fetchall()
            return [self._row_to_planned_allocation(r) for r in rows]

    def save_planned_allocation(self, pa) -> object:
        """Upsert por (demand_id, week_start) — chave natural da tabela, não o id."""
        self._ensure_planned_allocation_table()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO planned_allocations (demand_id,week_start,planned_hours) "
                "VALUES (?,?,?) "
                "ON CONFLICT(demand_id,week_start) DO UPDATE SET planned_hours=excluded.planned_hours",
                (pa.demand_id, pa.week_start.isoformat(), pa.planned_hours)
            )
            row = conn.execute(
                "SELECT id FROM planned_allocations WHERE demand_id=? AND week_start=?",
                (pa.demand_id, pa.week_start.isoformat())
            ).fetchone()
            pa.id = row[0]
        return pa

    def delete_planned_allocations_for_demand(self, demand_id: int):
        self._ensure_planned_allocation_table()
        with self._conn() as conn:
            conn.execute("DELETE FROM planned_allocations WHERE demand_id=?", (demand_id,))

    def _row_to_planned_allocation(self, row) -> object:
        return PlannedAllocation(
            id=row["id"],
            demand_id=row["demand_id"],
            week_start=_parse_date(row["week_start"]),
            planned_hours=row["planned_hours"] or 0.0,
        )
