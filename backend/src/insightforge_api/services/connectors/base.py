"""Connector SDK contract. A connector implements test_connection + extract;
everything downstream (typing, quality, quarantine, scoring, lineage) is the
platform's shared trust pipeline — connectors only fetch rows."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExtractResult:
    headers: list[str]
    rows: list[list[str]]
    cursor: str | None


class Connector(Protocol):
    type_name: str

    async def test_connection(self, config: dict, credentials: dict) -> None: ...
    async def extract(self, config: dict, credentials: dict,
                      cursor: str | None) -> ExtractResult: ...


def demo_extract(headers, fixture, cursor_index, cursor) -> ExtractResult:
    rows = [r for r in fixture if cursor is None or str(r[cursor_index]) > str(cursor)]
    new_cursor = str(rows[-1][cursor_index]) if rows else cursor
    return ExtractResult(headers, [[str(c) for c in r] for r in rows], new_cursor)
