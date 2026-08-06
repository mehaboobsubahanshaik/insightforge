"""PostgreSQL source connector. Identifiers are regex-validated AND quoted;
values never interpolated; host allow-listing blocks SSRF into private infra
unless explicitly permitted for local development."""

import re

import asyncpg

IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}


class PostgresConnector:
    type_name = "postgresql"

    def _validate(self, config):
        host = str(config.get("host", ""))
        if host in BLOCKED_HOSTS:
            raise ValueError("Host not allowed")
        for key in ("table", "cursor_column"):
            v = config.get(key)
            if v is not None and not IDENT.match(str(v)):
                raise ValueError(f"Invalid identifier for {key}: {v!r}")
        return host

    async def _connect(self, config, credentials):
        host = self._validate(config)
        sslmode = str(config.get("sslmode", "prefer"))
        ssl = {"require": True, "disable": False}.get(sslmode, None)
        return await asyncpg.connect(
            host=host, port=int(config.get("port", 5432)),
            database=str(config.get("database", "")),
            user=credentials.get("user", ""), password=credentials.get("password", ""),
            timeout=10, ssl=ssl,
        )

    async def test_connection(self, config, credentials):
        conn = await self._connect(config, credentials)
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()

    async def extract(self, config, credentials, cursor):
        conn = await self._connect(config, credentials)
        try:
            table = f'"{config["table"]}"'
            cursor_col = config.get("cursor_column")
            if cursor_col and cursor is not None:
                # Numeric cursors must compare numerically (text ordering would
                # put '2' after '15'); ISO dates/timestamps are order-correct
                # as text.
                if re.fullmatch(r"-?\d+(\.\d+)?", str(cursor)):
                    comparison = f'"{cursor_col}"::numeric > $1::numeric'
                else:
                    comparison = f'"{cursor_col}"::text > $1'
                sql = (f'SELECT * FROM {table} WHERE {comparison} '  # noqa: S608 - identifiers regex-validated + quoted
                       f'ORDER BY "{cursor_col}" LIMIT 10000')
                rows = await conn.fetch(sql, str(cursor))
            elif cursor_col:
                sql = f'SELECT * FROM {table} ORDER BY "{cursor_col}" LIMIT 10000'  # noqa: S608
                rows = await conn.fetch(sql)
            else:
                sql = f"SELECT * FROM {table} LIMIT 10000"  # noqa: S608
                rows = await conn.fetch(sql)
            if not rows:
                from .base import ExtractResult

                return ExtractResult([], [], cursor)
            headers = list(rows[0].keys())
            data = [["" if v is None else str(v) for v in r.values()] for r in rows]
            new_cursor = cursor
            if cursor_col:
                idx = headers.index(cursor_col)
                new_cursor = data[-1][idx]
            from .base import ExtractResult

            return ExtractResult(headers, data, new_cursor)
        finally:
            await conn.close()
