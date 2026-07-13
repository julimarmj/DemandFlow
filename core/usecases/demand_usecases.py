"""
DemandFlow - Casos de Uso
Regras de negócio puras — orquestram entidades e repositórios.
"""
from datetime import date, timedelta
from typing import Optional
from core.domain.entities import (
    Demand, Comment, HistoryEntry, Attachment, Milestone,
    Status, Priority, CommentType, PlannedAllocation,
    PHASE_WEIGHT_ESCOPO, PHASE_WEIGHT_DESENV, PHASE_WEIGHT_CONCLUSAO,
)
from core.ports.repositories import DemandRepository

# Capacidade semanal assumida pra comparação na aba de Planejamento.
# Constante simples e fácil de ajustar — sem tela de configuração por enquanto.
WEEKLY_CAPACITY_HOURS = 40.0


def _is_conclusion_milestone(milestone) -> bool:
    return milestone.title.strip().lower() == "conclusão"


def _iso_week_start(d: date) -> date:
    """Segunda-feira da semana ISO que contém d."""
    return d - timedelta(days=d.weekday())


def _round_preserving_total(values: dict, step: int = 4) -> dict:
    """Arredonda cada valor pro múltiplo de `step` mais próximo por baixo, mas
    sem perder horas no total: o que sobra de cada semana (a parte fracionária
    descartada no floor) é redistribuído em blocos de `step` pras semanas com
    maior sobra primeiro (método dos maiores restos). Se ainda restar um
    pedaço menor que `step`, ele é somado na semana de maior sobra em vez de
    descartado — preferência por múltiplos de 4h, mas nada de hora perdida."""
    if not values:
        return {}

    total = sum(values.values())
    bases = {wk: int(h // step) * step for wk, h in values.items()}
    remainders = {wk: values[wk] - bases[wk] for wk in values}
    leftover = round(total - sum(bases.values()), 6)

    order = sorted(values.keys(), key=lambda wk: remainders[wk], reverse=True)
    n_bumps = int(leftover // step)
    for wk in order[:n_bumps]:
        bases[wk] += step
    leftover = round(leftover - n_bumps * step, 6)

    if leftover > 1e-6 and order:
        bases[order[0]] += leftover

    return {wk: round(v, 2) for wk, v in bases.items()}


class DemandUseCases:

    def __init__(self, repo: DemandRepository):
        self._repo = repo

    # ── CRUD ────────────────────────────────────────────────────────────────

    def list_all(self) -> list[Demand]:
        return self._repo.get_all()

    def get(self, id: int) -> Optional[Demand]:
        return self._repo.get_by_id(id)

    def create(
        self,
        title: str,
        description: str,
        status: Status,
        priority: Priority,
        category: str,
        client: str,
        responsible: str,
        estimated_hours: float,
        deadline: date,
        tags: list[str],
    ) -> Demand:
        demand = Demand(
            id=0,
            title=title.strip(),
            description=description.strip(),
            status=status,
            priority=priority,
            category=category,
            client=client.strip(),
            responsible=responsible.strip(),
            estimated_hours=estimated_hours,
            real_hours=0,
            deadline=deadline,
            tags=tags,
        )
        saved = self._repo.save(demand)


        self._repo.seed_milestones(
            saved.id,
            saved.deadline
        )

        self._repo.add_history(HistoryEntry(
            id=0, demand_id=saved.id,
            action="Demanda criada", user="Usuário",
        ))
        return saved

    def update_notes(self, demand_id: int, notes: str) -> None:
        d = self._repo.get_by_id(demand_id)
        if d:
            changed = d.notes != notes
            d.notes = notes
            if changed:
                d.last_activity = date.today()
            self._repo.save(d)

    def update(self, demand: Demand, user: str = "Usuário") -> Demand:
        demand.last_activity = date.today()
        saved = self._repo.save(demand)
        self._repo.add_history(HistoryEntry(
            id=0, demand_id=saved.id,
            action="Demanda atualizada", user=user,
        ))
        return saved

    def delete(self, id: int) -> bool:
        return self._repo.delete(id)

    # ── STATUS ───────────────────────────────────────────────────────────────

    def change_status(self, id: int, new_status: Status, user: str = "Usuário") -> Demand:
        demand = self._repo.get_by_id(id)
        if not demand:
            raise ValueError(f"Demanda {id} não encontrada")
        old = demand.status.label
        demand.status = new_status
        demand.last_activity = date.today()
        saved = self._repo.save(demand)
        self._repo.add_history(HistoryEntry(
            id=0, demand_id=id,
            action=f"Status: {old} → {new_status.label}",
            user=user,
        ))

        return saved

    def update_hours(self, id: int, real_hours: float, user: str = "Usuário") -> Demand:
        demand = self._repo.get_by_id(id)
        if not demand:
            raise ValueError(f"Demanda {id} não encontrada")
        demand.real_hours = real_hours
        demand.last_activity = date.today()
        saved = self._repo.save(demand)
        self._repo.add_history(HistoryEntry(
            id=0, demand_id=id,
            action=f"Horas atualizadas: {real_hours}h",
            user=user,
        ))
        return saved

    def update_estimated_hours(self, id: int, estimated_hours: float, user: str = "Usuário") -> Demand:
        demand = self._repo.get_by_id(id)
        if not demand:
            raise ValueError(f"Demanda {id} não encontrada")
        old = demand.estimated_hours
        demand.estimated_hours = max(estimated_hours, 0.0)
        demand.last_activity = date.today()
        saved = self._repo.save(demand)
        self._repo.add_history(HistoryEntry(
            id=0, demand_id=id,
            action=f"Estimativa de horas alterada de {old:.0f}h para {demand.estimated_hours:.0f}h",
            user=user,
        ))
        return saved

    # ── COMMENTS ─────────────────────────────────────────────────────────────

    def add_comment(self, demand_id: int, text: str,
                    comment_type: CommentType, author: str = "Usuário") -> Comment:
        comment = Comment(
            id=0, demand_id=demand_id,
            author=author, text=text.strip(), comment_type=comment_type,
        )
        saved = self._repo.add_comment(comment)
        demand = self._repo.get_by_id(demand_id)
        if demand:
            demand.last_activity = date.today()
            self._repo.save(demand)
        self._repo.add_history(HistoryEntry(
            id=0, demand_id=demand_id,
            action=f"Comentário adicionado ({comment_type.label})", user=author,
        ))
        return saved

    def get_comments(self, demand_id: int) -> list[Comment]:
        return self._repo.get_comments(demand_id)

    # ── ATTACHMENTS ───────────────────────────────────────────────────────────

    def add_attachment(self, demand_id: int, filename: str,
                       filepath: str, file_type: str) -> Attachment:
        att = Attachment(
            id=0, demand_id=demand_id,
            filename=filename, filepath=filepath, file_type=file_type,
        )
        saved = self._repo.add_attachment(att)
        demand = self._repo.get_by_id(demand_id)
        if demand:
            demand.last_activity = date.today()
            self._repo.save(demand)
        self._repo.add_history(HistoryEntry(
            id=0, demand_id=demand_id,
            action=f"Anexo adicionado: {filename}", user="Usuário",
        ))
        return saved

    # ── SEARCH ───────────────────────────────────────────────────────────────

    def search(self, **kwargs) -> list[Demand]:
        return self._repo.search(**kwargs)

    # ── ANALYTICS ────────────────────────────────────────────────────────────

    def get_dashboard_stats(self) -> dict:
        demands = self._repo.get_all()
        open_d  = [d for d in demands if d.status not in (Status.CONCLUIDA, Status.CANCELADA)]
        done_d  = [d for d in demands if d.status == Status.CONCLUIDA]
        return {
            "total":           len(demands),
            "open":            len(open_d),
            "overdue":         sum(1 for d in open_d if d.is_overdue),
            "done":            len(done_d),
            "critical":        sum(1 for d in open_d if d.priority == Priority.CRITICA),
            "inactive":        sum(1 for d in open_d if d.is_inactive),
            "total_hours":     sum(d.real_hours for d in demands),
            "estimated_hours": sum(d.estimated_hours for d in demands),
            "by_status":       {s: sum(1 for d in demands if d.status == s) for s in Status},
            "by_priority":     {p: sum(1 for d in demands if d.priority == p) for p in Priority},
            "by_category":     self._count_by(demands, "category"),
        }

    def get_alerts(self) -> list[dict]:
        alerts = []
        for d in self._repo.get_all():
            if d.status in (Status.CONCLUIDA, Status.CANCELADA):
                continue
            if d.is_overdue:
                alerts.append({"demand": d, "type": "overdue",
                               "msg": f"Prazo vencido em {d.deadline.strftime('%d/%m/%Y')}"})
            elif d.is_inactive:
                alerts.append({"demand": d, "type": "inactive",
                               "msg": f"Inativa há {d.days_since_activity} dias"})
            elif d.status == Status.BLOQUEADA:
                alerts.append({"demand": d, "type": "blocked", "msg": "Demanda bloqueada"})
        return alerts

    def get_productivity_insights(self) -> dict:
        demands = self._repo.get_all()
        today_d    = date.today()
        open_d     = [d for d in demands if d.status not in (Status.CONCLUIDA, Status.CANCELADA)]
        due_today  = [d for d in open_d if d.deadline == today_d]
        overdue    = sorted([d for d in open_d if d.is_overdue],
                            key=lambda d: (today_d - d.deadline).days, reverse=True)
        forgotten  = [d for d in open_d if d.days_since_activity >= 10]
        critical   = [d for d in open_d if d.priority == Priority.CRITICA]
        time_heavy = sorted(demands, key=lambda d: d.real_hours, reverse=True)[:5]
        return {
            "due_today":   due_today,
            "overdue":     overdue,
            "forgotten":   forgotten,
            "critical":    critical,
            "time_heavy":  time_heavy,
        }

    @staticmethod
    def _count_by(demands: list[Demand], attr: str) -> dict:
        result = {}
        for d in demands:
            key = getattr(d, attr)
            result[key] = result.get(key, 0) + 1
        return result

    # ── MILESTONES ───────────────────────────────────────────────────────────────
    def get_milestones(self, demand_id: int) -> list:
        return self._repo.get_milestones(demand_id)

    def save_milestone(self, milestone) -> object:
        return self._repo.save_milestone(milestone)

    def change_milestone_status(self,milestone_id: int,done: bool,user: str = "Usuário"):
        milestone = self._repo.get_milestone(milestone_id)

        if not milestone:
            raise ValueError("Milestone não encontrado")

        old = milestone.done

        milestone.done = done
        self.save_milestone(milestone)

        if old != done:
            self._repo.add_history(
                HistoryEntry(
                    id=0,
                    demand_id=milestone.demand_id,
                    action=f"Milestone {'concluído' if done else 'reaberto'}: {milestone.title}",
                    user=user,
                )
            )

            # O milestone de Conclusão espelha o status da demanda.
            if _is_conclusion_milestone(milestone):
                demand = self._repo.get_by_id(milestone.demand_id)
                if demand is not None:
                    if done and demand.status != Status.CONCLUIDA:
                        self.change_status(demand.id, Status.CONCLUIDA, user=user)
                    elif not done and demand.status == Status.CONCLUIDA:
                        self.change_status(demand.id, Status.EM_ANDAMENTO, user=user)

        return milestone

    def change_milestone_deadline(self, milestone_id: int, new_deadline: date, user: str = "Usuário"):
        milestone = self._repo.get_milestone(milestone_id)
        if not milestone:
            raise ValueError("Milestone não encontrado")

        if new_deadline == milestone.deadline:
            return milestone   # nada mudou — evita log/recálculo redundante

        all_milestones = self._repo.get_milestones(milestone.demand_id)

        # Bloqueia datas que não respeitam a dependência (ex.: Conclusão
        # antes de Desenvolvimento).
        if milestone.depends_on_id is not None:
            dep = next((m for m in all_milestones if m.id == milestone.depends_on_id), None)
            if dep is not None and new_deadline < dep.deadline:
                raise ValueError(
                    f"A data de '{milestone.title}' não pode ser anterior à de "
                    f"'{dep.title}' ({dep.deadline:%d/%m/%Y})."
                )

        old_deadline = milestone.deadline

        milestone.deadline = new_deadline

        self._repo.save_milestone(milestone)

        # Empurra quem depende deste milestone pela mesma diferença de dias.
        self.shift_dependent_milestones(all_milestones, milestone.id, new_deadline)

        # A Conclusão representa o prazo final da demanda — mantém sincronizado.
        # Registrado numa ÚNICA entrada de histórico junto com a mudança do
        # milestone (não duas), já que pro usuário é uma ação só.
        demand_synced = False
        if _is_conclusion_milestone(milestone):
            demand = self._repo.get_by_id(milestone.demand_id)
            if demand is not None and demand.deadline != new_deadline:
                demand.deadline = new_deadline
                self._repo.save(demand)
                demand_synced = True

        action = (
            f"Prazo do milestone '{milestone.title}' "
            f"alterado de {old_deadline:%d/%m/%Y} "
            f"para {new_deadline:%d/%m/%Y}"
        )
        if demand_synced:
            action += " (prazo da demanda atualizado junto, por ser o milestone de Conclusão)"

        self._repo.add_history(HistoryEntry(
            id=0, demand_id=milestone.demand_id, action=action, user=user,
        ))

        return milestone

    def create_milestone(self, milestone: Milestone, user: str = "Usuário"):
        saved = self._repo.save_milestone(milestone)

        self._repo.add_history(
            HistoryEntry(
                id=0,
                demand_id=milestone.demand_id,
                action=f"Milestone criado: {milestone.title}",
                user=user,
            )
        )

        return saved
    
    #def delete_milestone(self, milestone_id: int):
        #self._repo.delete_milestone(milestone_id)

    def delete_milestone(self, milestone_id: int, user: str = "Usuário"):
        milestone = self._repo.get_milestone(milestone_id)

        self._repo.delete_milestone(milestone_id)

        self._repo.add_history(
            HistoryEntry(
                id=0,
                demand_id=milestone.demand_id,
                action=f"Milestone removido: {milestone.title}",
                user=user,
            )
        )

    def shift_dependent_milestones(self, all_milestones: list, changed_id: int, new_deadline: date):
        """
        Quando um milestone muda de data, empurra todos os que dependem
        dele (direta ou indiretamente) pela mesma diferença de dias.
        """
        original = next((m for m in all_milestones if m.id == changed_id), None)
        if not original:
            return
        delta = new_deadline - original.deadline
        if delta.days == 0:
            return

        # BFS sobre dependentes
        visited = set()
        queue   = [changed_id]
        while queue:
            current_id = queue.pop(0)
            for m in all_milestones:
                if m.depends_on_id == current_id and m.id not in visited:
                    visited.add(m.id)
                    m.deadline = m.deadline + delta
                    self._repo.save_milestone(m)
                    queue.append(m.id)  

    def get_reminders(self, demand_id: int) -> list:
        return self._repo.get_reminders(demand_id)

    def get_all_reminders(self) -> list:
        return self._repo.get_all_reminders()

    def save_reminder(self, reminder) -> object:
        saved = self._repo.save_reminder(reminder)
        if reminder.id == 0 or reminder.done:
            demand = next(
                (d for d in self._repo.get_all() if d.id == reminder.demand_id),
                None
            )
            if demand:
                demand.last_activity = date.today()
                self._repo.save(demand)
        return saved

    def delete_reminder(self, reminder_id: int):
        self._repo.delete_reminder(reminder_id)

    def get_due_reminders(self) -> list:
        """Lembretes de hoje ou atrasados ainda não concluídos."""
        today = date.today()
        return [
            r for r in self._repo.get_all_reminders()
            if not r.done and r.remind_at <= today
        ]
    # ── WORK LOGS ─────────────────────────────────────────────────────────────

    def get_work_logs(self, demand_id: int) -> list:
        return self._repo.get_work_logs(demand_id)

    def get_all_work_logs(self) -> list:
        return self._repo.get_all_work_logs()

    def add_work_log(
        self,
        demand_id,               # int ou None (atividade avulsa)
        started_at,
        ended_at,
        duration_seconds: int,
        note: str = "",
        manual: bool = False,
        category: str = "",      # categoria quando demand_id é None
    ):
        from core.domain.entities import WorkLog
        wl = WorkLog(
            id=0,
            demand_id=demand_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            note=note,
            manual=manual,
            category=category,
        )
        saved = self._repo.save_work_log(wl)

        if demand_id is not None:
            self._sync_real_hours(demand_id)
            self._repo.add_history(HistoryEntry(
                id=0, demand_id=demand_id,
                action=f"Apontamento registrado: {wl.duration_display}" + (f" — {note}" if note else ""),
                user="Sistema",
            ))
        return saved

    def update_work_log(self, worklog):
        self._repo.save_work_log(worklog)
        self._sync_real_hours(worklog.demand_id)
        if worklog.demand_id is not None:
            self._repo.add_history(HistoryEntry(
                id=0, demand_id=worklog.demand_id,
                action=f"Apontamento editado: {worklog.duration_display}" + (f" — {worklog.note}" if worklog.note else ""),
                user="Sistema",
            ))

    def delete_work_log(self, worklog_id: int, demand_id):
        wl = None
        if demand_id is not None:
            wl = next((w for w in self._repo.get_work_logs(demand_id) if w.id == worklog_id), None)
        self._repo.delete_work_log(worklog_id)
        if demand_id is not None:
            self._sync_real_hours(demand_id)
            if wl is not None:
                self._repo.add_history(HistoryEntry(
                    id=0, demand_id=demand_id,
                    action=f"Apontamento removido: {wl.duration_display}" + (f" — {wl.note}" if wl.note else ""),
                    user="Sistema",
                ))

    def _sync_real_hours(self, demand_id: int):
        """Mantém real_hours sincronizado com a soma dos work_logs."""
        total_hours = self._repo.get_total_logged_hours(demand_id)
        demand = self._repo.get_by_id(demand_id)
        if demand:
            demand.real_hours = round(total_hours, 2)
            demand.last_activity = date.today()
            self._repo.save(demand)

    def get_worklog_stats(self, demand_id: int) -> dict:
        """Estatísticas agregadas para exibição."""
        logs = self._repo.get_work_logs(demand_id)
        if not logs:
            return {"total_seconds": 0, "total_hours": 0.0, "sessions": 0, "by_day": {}}

        total_sec = sum(w.duration_seconds for w in logs)
        by_day: dict = {}
        for w in logs:
            day = w.started_at.date().isoformat()
            by_day.setdefault(day, {"seconds": 0, "sessions": []})
            by_day[day]["seconds"] += w.duration_seconds
            by_day[day]["sessions"].append(w)

        return {
            "total_seconds": total_sec,
            "total_hours":   total_sec / 3600,
            "sessions":      len(logs),
            "by_day":        dict(sorted(by_day.items(), reverse=True)),
        }

    def get_worklog_report(
        self,
        demand_ids: list[int] = None,
        date_from=None,
        date_to=None,
    ) -> list:
        """Retorna work_logs filtrados para relatórios."""
        from datetime import datetime
        logs = self._repo.get_all_work_logs()
        result = []
        for w in logs:
            if demand_ids and w.demand_id not in demand_ids:
                continue
            if date_from and w.started_at.date() < date_from:
                continue
            if date_to and w.started_at.date() > date_to:
                continue
            result.append(w)
        return result

    # ── CAPACITY PLANNING ───────────────────────────────────────────────────────

    def get_planned_allocations(self, demand_id: int) -> list:
        return self._repo.get_planned_allocations(demand_id)

    def get_capacity_grid(self, n_weeks: int = 10, week0: date = None) -> dict:
        """
        Monta os dados agregados pra grade de planejamento: demandas ativas x
        semanas, total por semana, e quais semanas excedem WEEKLY_CAPACITY_HOURS.
        """
        week0 = week0 or _iso_week_start(date.today())
        weeks = [week0 + timedelta(weeks=i) for i in range(n_weeks)]

        demands = [
            d for d in self._repo.get_all()
            if d.status not in (Status.CONCLUIDA, Status.CANCELADA, Status.NAO_INICIADA)
        ]
        demand_ids = {d.id for d in demands}

        rows = self._repo.get_all_planned_allocations(week_from=weeks[0], week_to=weeks[-1])
        allocations = {
            (r.demand_id, r.week_start): r.planned_hours
            for r in rows if r.demand_id in demand_ids
        }

        totals_by_week = {w: 0.0 for w in weeks}
        for (_, wk), hours in allocations.items():
            totals_by_week[wk] = totals_by_week.get(wk, 0.0) + hours

        return {
            "weeks": weeks,
            "demands": demands,
            "allocations": allocations,
            "totals_by_week": totals_by_week,
            "capacity": WEEKLY_CAPACITY_HOURS,
            "over_capacity_weeks": [w for w in weeks if totals_by_week[w] > WEEKLY_CAPACITY_HOURS],
        }

    @staticmethod
    def _compute_suggestion(milestones: list, remaining_hours: float) -> dict:
        """Função pura — distribui remaining_hours pelas semanas ISO com base
        nas janelas dos 3 milestones padrão, ponderadas por PHASE_WEIGHT_*."""
        today = date.today()
        by_title = {m.title.strip().lower(): m for m in milestones}
        m1 = by_title.get("estudo de escopo")
        m2 = by_title.get("desenvolvimento")
        m3 = by_title.get("conclusão")
        if not (m1 and m2 and m3):
            raise ValueError(
                "Demanda sem os 3 milestones padrão (Estudo de Escopo/"
                "Desenvolvimento/Conclusão) — não é possível sugerir distribuição."
            )

        windows = [
            (today,       m1.deadline, PHASE_WEIGHT_ESCOPO),
            (m1.deadline, m2.deadline, PHASE_WEIGHT_DESENV),
            (m2.deadline, m3.deadline, PHASE_WEIGHT_CONCLUSAO),
        ]
        # Descarta janelas totalmente no passado/invertidas; clampa início em hoje.
        windows = [(max(s, today), e, w) for (s, e, w) in windows if e > max(s, today)]

        if not windows:
            # Demanda atrasada nas 3 janelas — concentra na semana ISO atual
            # inteira (não só "hoje + 7 dias", que poderia vazar pra próxima
            # semana se hoje não for segunda-feira).
            wk = _iso_week_start(today)
            windows = [(wk, wk + timedelta(days=7), 1.0)]

        weighted = [(s, e, w * max((e - s).days, 1)) for (s, e, w) in windows]
        total_weight = sum(ww for _, _, ww in weighted) or 1.0

        result: dict = {}
        for start, end, ww in weighted:
            window_hours = remaining_hours * (ww / total_weight)
            week_days: dict = {}
            cur = start
            while cur < end:
                wk = _iso_week_start(cur)
                week_end_excl = min(end, wk + timedelta(days=7))
                days_in_week = max((week_end_excl - cur).days, 0)
                week_days[wk] = week_days.get(wk, 0) + days_in_week
                cur = week_end_excl
            total_days = sum(week_days.values()) or 1
            for wk, nd in week_days.items():
                result[wk] = result.get(wk, 0.0) + window_hours * (nd / total_days)

        # Prefere múltiplos de 4h (meio turno de trabalho) — números redondos
        # são mais fáceis de planejar — mas sem perder horas no total.
        return _round_preserving_total(result, step=4)

    def _other_demands_totals(self, exclude_demand_id: int, week_from: date, week_to: date) -> dict:
        """Soma, por semana, o que as OUTRAS demandas ativas já têm planejado
        — usado pra saber quanto de capacidade ainda resta em cada semana."""
        active_ids = {
            d.id for d in self._repo.get_all()
            if d.status not in (Status.CONCLUIDA, Status.CANCELADA, Status.NAO_INICIADA)
            and d.id != exclude_demand_id
        }
        totals: dict = {}
        for r in self._repo.get_all_planned_allocations(week_from=week_from, week_to=week_to):
            if r.demand_id in active_ids:
                totals[r.week_start] = totals.get(r.week_start, 0.0) + r.planned_hours
        return totals

    @staticmethod
    def _spread_respecting_capacity(ideal: dict, other_totals: dict, deadline_wk: date) -> dict:
        """Empurra o excesso de uma semana que bateria no teto de capacidade
        (considerando o que outras demandas já têm planejado) pra semana
        seguinte. Na última semana disponível (prazo da demanda) não há mais
        pra onde empurrar, então o que sobrar fica ali mesmo."""
        week0 = min(ideal.keys())
        effective_end = max(deadline_wk, week0)   # cobre o caso de prazo já vencido

        weeks = []
        cur = week0
        while cur <= effective_end:
            weeks.append(cur)
            cur += timedelta(weeks=1)

        result: dict = {}
        carry = 0.0
        for i, wk in enumerate(weeks):
            desired = ideal.get(wk, 0.0) + carry
            if i == len(weeks) - 1:
                allocated = desired
            else:
                available = max(WEEKLY_CAPACITY_HOURS - other_totals.get(wk, 0.0), 0.0)
                allocated = min(desired, available)
            result[wk] = round(allocated)
            carry = desired - allocated
        return result

    def suggest_allocation(self, demand_id: int, user: str = "Usuário") -> list:
        """
        Recalcula e SOBRESCREVE a distribuição de horas planejadas da demanda
        com base nas janelas dos milestones, empurrando pra semana seguinte o
        que não couber na capacidade já ocupada pelas outras demandas. Só
        roda quando pedido explicitamente.
        """
        demand = self._repo.get_by_id(demand_id)
        if not demand:
            raise ValueError(f"Demanda {demand_id} não encontrada")

        milestones = self._repo.get_milestones(demand_id)
        remaining_hours = max(demand.estimated_hours - demand.real_hours, 0.0)

        ideal = self._compute_suggestion(milestones, remaining_hours)
        deadline_wk = _iso_week_start(demand.deadline)
        other_totals = self._other_demands_totals(demand_id, min(ideal.keys()), deadline_wk)
        suggestion = self._spread_respecting_capacity(ideal, other_totals, deadline_wk)

        self._repo.delete_planned_allocations_for_demand(demand_id)
        saved = []
        for week_start, hours in sorted(suggestion.items()):
            if hours <= 0:
                continue
            saved.append(self._repo.save_planned_allocation(
                PlannedAllocation(id=0, demand_id=demand_id,
                                   week_start=week_start, planned_hours=hours)
            ))

        self._repo.add_history(HistoryEntry(
            id=0, demand_id=demand_id,
            action=f"Sugestão de planejamento recalculada ({len(saved)} semana(s))",
            user=user,
        ))
        return saved

    def clear_allocation(self, demand_id: int, user: str = "Usuário") -> None:
        """Remove todas as horas planejadas da demanda. Ação discreta e
        intencional (botão dedicado), por isso gera histórico — diferente do
        ajuste fino de uma única célula."""
        existing = self._repo.get_planned_allocations(demand_id)
        if not existing:
            return
        self._repo.delete_planned_allocations_for_demand(demand_id)
        self._repo.add_history(HistoryEntry(
            id=0, demand_id=demand_id,
            action=f"Horas planejadas removidas ({len(existing)} semana(s))",
            user=user,
        ))

    def adjust_planned_hours(self, demand_id: int, week_start: date, new_hours: float) -> dict:
        """
        Ajuste manual de uma célula (demanda x semana). Bloqueia edições que não
        fazem sentido. A validação é pelo TOTAL agregado da demanda (não só
        "semanas futuras relativas a esta célula") — mover horas de uma semana
        pra outra (reduzir uma, depois aumentar outra) nunca deve disparar
        bloqueio indevido, mesmo que a semana reduzida fique antes da semana
        aumentada. Se o total ainda assim passar da estimativa, tenta absorver
        reduzindo proporcionalmente outras semanas editáveis (qualquer
        direção no tempo); se nem isso for suficiente, BLOQUEIA — o total
        planejado nunca pode passar da estimativa de horas da demanda. Pra
        alocar mais do que isso, é preciso primeiro aumentar a estimativa da
        demanda (e só então mudar no gráfico), não o contrário.
        Não gera entrada de histórico (ajuste fino, diferente de mudar
        status/deadline/milestone, que são eventos de negócio relevantes) —
        ver `log_planning_changes` para o resumo consolidado dessas edições.
        """
        demand = self._repo.get_by_id(demand_id)
        if not demand:
            raise ValueError(f"Demanda {demand_id} não encontrada")
        if demand.status in (Status.CONCLUIDA, Status.CANCELADA):
            raise ValueError("Demanda concluída/cancelada não participa do planejamento.")

        today_week = _iso_week_start(date.today())
        if week_start < today_week:
            raise ValueError("Não é possível alterar semanas passadas.")

        deadline_week = _iso_week_start(demand.deadline)
        if week_start > deadline_week:
            raise ValueError(
                f"Semana está após o prazo da demanda ({demand.deadline:%d/%m/%Y})."
            )

        new_hours = round(max(new_hours, 0.0))   # sempre hora inteira — sem valor quebrado
        rows = {r.week_start: r for r in self._repo.get_planned_allocations(demand_id)}
        old_hours = rows[week_start].planned_hours if week_start in rows else 0.0
        delta = new_hours - old_hours

        # Calcula ANTES de salvar se o aumento cabe, com base no TOTAL agregado
        # da demanda — não em "semanas futuras", já que reduzir uma semana e
        # aumentar outra (em qualquer ordem/direção) é uma operação válida
        # desde que o total continue dentro da estimativa.
        cuts: dict[date, float] = {}
        if delta > 0:
            remaining_hours = max(demand.estimated_hours - demand.real_hours, 0.0)
            current_total = sum(r.planned_hours for r in rows.values())
            projected_total = current_total - old_hours + new_hours

            if projected_total > remaining_hours + 0.01:
                excess = projected_total - remaining_hours
                other_weeks = [
                    w for w in rows
                    if w != week_start and today_week <= w <= deadline_week
                ]
                other_total = sum(rows[w].planned_hours for w in other_weeks)
                remaining_to_absorb = excess

                if other_total > 0:
                    for w in sorted(other_weeks):
                        share = rows[w].planned_hours / other_total
                        cut = min(rows[w].planned_hours, excess * share)
                        cuts[w] = cut
                        remaining_to_absorb -= cut

                if remaining_to_absorb > 0.01:
                    raise ValueError(
                        f"Isso passaria das {remaining_hours:.0f}h restantes estimadas para "
                        "essa demanda. Aumente a estimativa de horas da demanda antes de "
                        "alocar mais nessa semana."
                    )

        updated = [self._repo.save_planned_allocation(
            PlannedAllocation(id=0, demand_id=demand_id, week_start=week_start, planned_hours=new_hours)
        )]
        for w, cut in cuts.items():
            new_val = round(max(rows[w].planned_hours - cut, 0.0))   # hora inteira
            updated.append(self._repo.save_planned_allocation(
                PlannedAllocation(id=0, demand_id=demand_id, week_start=w, planned_hours=new_val)
            ))

        return {"updated": updated, "warning": None}

    def log_planning_changes(self, demand_id: int, changes: dict, user: str = "Usuário") -> None:
        """
        Loga 1 entrada de histórico resumindo as semanas alteradas no
        planejamento de horas desde o último flush. `changes` é
        {week_start: (horas_antigas, horas_novas)}. Pensado pra ser chamado
        pela UI de forma "debounced" — não a cada arraste, e sim quando o
        usuário troca de demanda, sai da aba de Planejamento, ou fica um
        tempo sem editar — pra não encher o histórico de entradas miúdas.
        Semanas que voltaram ao valor original (sem mudança líquida) são
        ignoradas.
        """
        parts = [
            f"{wk:%d/%m}: {old:.0f}h→{new:.0f}h"
            for wk, (old, new) in sorted(changes.items())
            if old != new
        ]
        if not parts:
            return
        self._repo.add_history(HistoryEntry(
            id=0, demand_id=demand_id,
            action="Planejamento de horas ajustado (" + "; ".join(parts) + ")",
            user=user,
        ))
