"""
DemandFlow - Ports (Interfaces)
Contratos que a camada de domínio expõe — independente de implementação.
"""
from abc import ABC, abstractmethod
from typing import Optional
from core.domain.entities import Demand, Comment, HistoryEntry, Attachment, Status, Priority


class DemandRepository(ABC):

    @abstractmethod
    def get_all(self) -> list[Demand]: ...

    @abstractmethod
    def get_by_id(self, id: int) -> Optional[Demand]: ...

    @abstractmethod
    def save(self, demand: Demand) -> Demand: ...

    @abstractmethod
    def delete(self, id: int) -> bool: ...

    @abstractmethod
    def search(
        self,
        query: str = "",
        status: Optional[Status] = None,
        priority: Optional[Priority] = None,
        category: str = "",
        responsible: str = "",
        client: str = "",
    ) -> list[Demand]: ...

    @abstractmethod
    def add_comment(self, comment: Comment) -> Comment: ...

    @abstractmethod
    def add_history(self, entry: HistoryEntry) -> HistoryEntry: ...

    @abstractmethod
    def add_attachment(self, attachment: Attachment) -> Attachment: ...

    @abstractmethod
    def get_comments(self, demand_id: int) -> list[Comment]: ...

    @abstractmethod
    def get_history(self, demand_id: int) -> list[HistoryEntry]: ...

    @abstractmethod
    def get_attachments(self, demand_id: int) -> list[Attachment]: ...
