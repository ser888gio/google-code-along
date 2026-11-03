"""Document-level machine: owns one section actor per field and the navigation between them."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum
from typing import TypedDict

from logger import get_logger

from spec_machine.model import (
    AgentProposal,
    AgentProposalFor,
    DocumentEvent,
    ExportRequest,
    Finalize,
    GoTo,
    LoadedDocument,
    MachineServices,
    MarkStale,
    Next,
    OpenItem,
    PersistedSection,
    Prev,
    ProposalOutput,
    ReloadSection,
    Reopen,
    Resume,
    ReviewRequest,
    SectionConfig,
    SectionState,
    Skip,
    TbdInfo,
    ToCurrent,
    build_dependents,
    empty_section,
)
from spec_machine.section import SectionActor, SectionSnapshot

logger = get_logger(__name__)


class DocumentState(StrEnum):
    ACTIVE = "active"
    REVIEWING_OPEN_ITEMS = "reviewingOpenItems"
    COMPLETED = "completed"


class OpenItemView(TypedDict):
    section_id: str
    label: str
    reason: str
    tbd: TbdInfo | None


class DocumentSnapshot(TypedDict):
    state: str
    cursor: str
    current: SectionSnapshot
    sections: list[SectionSnapshot]
    open_items: list[OpenItemView]
    finalize_blocked: list[str]


class DocumentActor:
    def __init__(
        self,
        configs: Sequence[SectionConfig],
        services: MachineServices,
        loaded: LoadedDocument,
        *,
        allow_tbd_on_finalize: bool = False,
    ) -> None:
        if not configs:
            raise ValueError("A document needs at least one section.")
        self.services = services
        self.allow_tbd_on_finalize = allow_tbd_on_finalize
        self.configs: dict[str, SectionConfig] = {c.id: c for c in configs}
        self.order: list[str] = [c.id for c in configs]
        self._dependents: dict[str, tuple[str, ...]] = build_dependents(configs)
        self.sections: dict[str, SectionActor] = {
            c.id: self._spawn(c, loaded.sections.get(c.id) or empty_section()) for c in configs
        }
        self.cursor: str = loaded.cursor if loaded.cursor in self.configs else self.order[0]
        self.state = DocumentState.ACTIVE
        self.queued: dict[str, ProposalOutput] = {}
        self.open_items: list[OpenItem] = []
        self.finalize_blocked: list[str] = []
        self._background: set[asyncio.Task[None]] = set()

    @classmethod
    async def load(
        cls,
        configs: Sequence[SectionConfig],
        services: MachineServices,
        *,
        allow_tbd_on_finalize: bool = False,
    ) -> DocumentActor:
        loaded = await services.load_document()
        return cls(configs, services, loaded, allow_tbd_on_finalize=allow_tbd_on_finalize)

    def _spawn(self, config: SectionConfig, persisted: PersistedSection) -> SectionActor:
        return SectionActor(
            config,
            persisted,
            self.services,
            dependents=self._dependents[config.id],
            on_committed=self._on_section_committed,
            other_values=lambda: self.committed_values(exclude=config.id),
        )

    # --- public API ---

    @property
    def current(self) -> SectionActor:
        return self.sections[self.cursor]

    def committed_values(self, *, exclude: str | None = None) -> dict[str, str]:
        return {
            key: actor.ctx.value
            for key, actor in self.sections.items()
            if key != exclude and actor.ctx.status == "filled" and actor.ctx.value is not None
        }

    def send(self, event: DocumentEvent) -> bool:
        """Apply one event. Returns False when it was ignored (busy section, guard failed, wrong state)."""
        match event:
            case AgentProposalFor():
                return self._on_agent_proposal(event)
            case ReloadSection(section_id=section_id) if section_id in self.sections:
                self._spawn_background(lambda: self._reload(section_id), "reload_section")
                return True

        if self.state is DocumentState.ACTIVE:
            match event:
                case Next():
                    return self._navigate(1)
                case Prev():
                    return self._navigate(-1)
                case GoTo(section_id=section_id):
                    return self._go_to(section_id)
                case ToCurrent(event=section_event):
                    return self.current.send(section_event)
        elif self.state is DocumentState.REVIEWING_OPEN_ITEMS:
            match event:
                case GoTo(section_id=section_id) if section_id in self.sections:
                    self.state = DocumentState.ACTIVE
                    self._move_to(section_id)
                    return True
                case Finalize():
                    return self._finalize()
        elif self.state is DocumentState.COMPLETED:
            match event:
                case Reopen():
                    self._enter_review()
                    return True
        return False

    async def settle(self) -> None:
        """Wait for every section invocation and background hook to finish (tests, request handlers)."""
        while True:
            for actor in list(self.sections.values()):
                await actor.settle()
            pending = [t for t in self._background if not t.done()]
            if not pending:
                if not any(actor.has_pending for actor in self.sections.values()):
                    return
                continue
            done, _ = await asyncio.wait(pending)
            for task in done:
                if not task.cancelled() and (exc := task.exception()) is not None:
                    raise exc

    def snapshot(self) -> DocumentSnapshot:
        sections = [
            self.sections[key].snapshot(queued_proposal=q.proposal if (q := self.queued.get(key)) else None)
            for key in self.order
        ]
        return {
            "state": str(self.state),
            "cursor": self.cursor,
            "current": sections[self.order.index(self.cursor)],
            "sections": sections,
            "open_items": [
                {"section_id": item.section_id, "label": item.label, "reason": item.reason, "tbd": item.tbd}
                for item in self.open_items
            ],
            "finalize_blocked": list(self.finalize_blocked),
        }

    # --- navigation ---

    def _navigate(self, step: int) -> bool:
        if self.current.busy:
            return False
        target = self.order.index(self.cursor) + step
        if target < 0:
            return False
        self._leave(self.current)
        if target >= len(self.order):
            self._enter_review()
        else:
            self._move_to(self.order[target])
        return True

    def _go_to(self, section_id: str) -> bool:
        if section_id not in self.sections or section_id == self.cursor or self.current.busy:
            return False
        self._leave(self.current)
        self._move_to(section_id)
        return True

    def _leave(self, actor: SectionActor) -> None:
        # Auto-skip keeps the open-items summary honest: anything unfinished becomes an explicit skip.
        if actor.ctx.status not in ("filled", "tbd") and actor.state is not SectionState.SKIPPED:
            actor.send(Skip())

    def _move_to(self, section_id: str) -> None:
        self.cursor = section_id
        cursor = section_id
        self._spawn_background(lambda: self.services.save_cursor(cursor), "save_cursor")
        actor = self.sections[section_id]
        queued = self.queued.get(section_id)
        if queued is not None and actor.can_accept_proposal():
            del self.queued[section_id]
            actor.send(AgentProposal(proposal=queued.proposal, rationale=queued.rationale))
        elif actor.state is SectionState.SKIPPED:
            actor.send(Resume())

    # --- review & finalize ---

    def _enter_review(self) -> None:
        self.state = DocumentState.REVIEWING_OPEN_ITEMS
        self.finalize_blocked = []
        self.open_items = self._collect_open_items()

    def _collect_open_items(self) -> list[OpenItem]:
        items: list[OpenItem] = []
        for key in self.order:
            actor = self.sections[key]
            label = actor.config.label or key
            status = actor.ctx.status
            if actor.state is SectionState.SKIPPED or status == "skipped":
                items.append(OpenItem(key, label, "skipped"))
            elif status == "tbd":
                items.append(OpenItem(key, label, "tbd", actor.ctx.tbd))
            elif status == "filled" and actor.ctx.stale:
                items.append(OpenItem(key, label, "stale"))
            elif status == "empty" and actor.config.required:
                items.append(OpenItem(key, label, "missing"))
        return items

    def _finalize_blockers(self) -> list[str]:
        blockers: list[str] = []
        for key in self.order:
            actor = self.sections[key]
            status = actor.ctx.status
            ok = status == "filled" or (status == "tbd" and self.allow_tbd_on_finalize)
            if actor.busy or (actor.config.required and not ok):
                blockers.append(key)
        return blockers

    def _finalize(self) -> bool:
        self.finalize_blocked = self._finalize_blockers()
        if self.finalize_blocked:
            return False
        self.state = DocumentState.COMPLETED
        request = ExportRequest(
            values=self.committed_values(),
            open_items=[item for item in self._collect_open_items() if item.reason == "tbd"],
        )
        self._spawn_background(lambda: self.services.export_spec(request), "export_spec")
        return True

    # --- agent proposals & dependency staleness ---

    def _on_agent_proposal(self, event: AgentProposalFor) -> bool:
        actor = self.sections.get(event.section_id)
        if actor is None or not actor.is_ai:
            return False
        is_current = self.state is DocumentState.ACTIVE and event.section_id == self.cursor
        if is_current and actor.can_accept_proposal():
            actor.send(AgentProposal(proposal=event.proposal, rationale=event.rationale))
        else:
            # Never steal focus (especially in voice mode): show a badge, deliver on entry.
            self.queued[event.section_id] = ProposalOutput(event.proposal, event.rationale)
        return True

    def _on_section_committed(self, section_id: str) -> None:
        self.queued.pop(section_id, None)
        for dependent in self._dependents[section_id]:
            actor = self.sections[dependent]
            actor.send(MarkStale())
            if actor.ctx.status in ("tbd", "skipped") and actor.is_ai:
                request = ReviewRequest(
                    changed_section_id=section_id,
                    dependent=actor.config,
                    dependent_status=actor.ctx.status,
                    dependent_tbd=actor.ctx.tbd,
                    other_values=self.committed_values(exclude=dependent),
                )
                self._spawn_background(lambda r=request: self._review_dependent(r), "review_dependent")

    async def _review_dependent(self, request: ReviewRequest) -> None:
        result = await self.services.review_dependent(request)
        if result is not None and result.proposal.strip():
            self.send(AgentProposalFor(request.dependent.id, result.proposal, result.rationale))

    async def _reload(self, section_id: str) -> None:
        # Load before stopping so a failed read leaves the old actor usable (the user can retry the reload).
        persisted = await self.services.load_section(section_id)
        self.sections[section_id].stop()
        self.sections[section_id] = self._spawn(self.configs[section_id], persisted)

    def _spawn_background(self, make: Callable[[], Awaitable[None]], label: str) -> None:
        async def run() -> None:
            try:
                await make()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — hooks run in the background and must not break the session
                logger.warning(f"{label} failed: error={type(exc).__name__}: {exc}")

        task = asyncio.get_running_loop().create_task(run())
        self._background.add(task)
        task.add_done_callback(self._background.discard)
