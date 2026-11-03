"""Minimal dict-backed Firestore fake: documents, subcollections, merge writes and atomic transactions."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

Path = tuple[str, ...]


class FakeSnapshot:
    def __init__(self, doc_id: str, data: dict[str, Any] | None) -> None:
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self._data) if self._data is not None else None


class FakeDocRef:
    def __init__(self, db: FakeFirestore, path: Path) -> None:
        self._db = db
        self.path = path
        self.id = path[-1]

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self._db, (*self.path, name))

    def get(self, transaction: FakeTransaction | None = None) -> FakeSnapshot:
        return FakeSnapshot(self.id, self._db.docs.get(self.path))

    def set(self, data: dict[str, Any], merge: bool = False) -> None:
        self._db.apply(self.path, data, merge)


class FakeCollection:
    def __init__(self, db: FakeFirestore, path: Path) -> None:
        self._db = db
        self.path = path

    def document(self, doc_id: str | None = None) -> FakeDocRef:
        return FakeDocRef(self._db, (*self.path, doc_id or uuid.uuid4().hex))

    def stream(self) -> list[FakeSnapshot]:
        depth = len(self.path) + 1
        return [
            FakeSnapshot(path[-1], dict(data))
            for path, data in self._db.docs.items()
            if len(path) == depth and path[:-1] == self.path
        ]


class FakeTransaction:
    def __init__(self, db: FakeFirestore) -> None:
        self._db = db
        self._writes: list[tuple[Path, dict[str, Any], bool]] = []

    def set(self, ref: FakeDocRef, data: dict[str, Any], merge: bool = False) -> None:
        self._writes.append((ref.path, data, merge))

    def commit(self) -> None:
        for path, data, merge in self._writes:
            self._db.apply(path, data, merge)


class FakeFirestore:
    def __init__(self) -> None:
        self.docs: dict[Path, dict[str, Any]] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, (name,))

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def apply(self, path: Path, data: dict[str, Any], merge: bool) -> None:
        if merge and path in self.docs:
            self.docs[path] = {**self.docs[path], **data}
        else:
            self.docs[path] = dict(data)


def fake_transactional(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run `fn` and apply its buffered writes only if it returns — mirrors Firestore's all-or-nothing commit."""

    def run(transaction: FakeTransaction, *args: Any) -> Any:
        result = fn(transaction, *args)
        transaction.commit()
        return result

    return run
