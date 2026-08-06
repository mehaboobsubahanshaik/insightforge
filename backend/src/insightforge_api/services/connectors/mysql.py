"""MySQL-wire source connector (MySQL, MariaDB, cloud MySQL platforms).
Same posture as the PostgreSQL connector: identifiers regex-validated AND
backtick-quoted, values never interpolated, private metadata hosts blocked,
numeric-aware incremental cursor."""

import re
import ssl as ssl_mod

import aiomysql

IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}
_NUM = re.compile(r"-?\d+(\.\d+)?")


class MySQLConnector:
    type_name = "mysql"

    def _validate(self, config):
        host = str(config.get("host", ""))
        if host in BLOCKED_HOSTS:
            raise ValueError("Host not allowed")
        for key in ("database", "table", "cursor_column"):
            v = config.get(key)
            if v is not None and not IDENT.match(str(v)):
                raise ValueError(f"Invalid identifier for {key}: {v!r}")
        return host

    async def _connect(self, config, credentials):
        host = self._validate(config)
        use_ssl = bool(config.get("ssl", False))
        ctx = ssl_mod.create_default_context() if use_ssl else None
        return await aiomysql.connect(
            host=host, port=int(config.get("port", 3306)),
            db=str(config.get("database", "")),
            user=credentials.get("user", ""), password=credentials.get("password", ""),
            connect_timeout=10, ssl=ctx)

    async def test_connection(self, config, credentials):
        conn = await self._connect(config, credentials)
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
        finally:
            conn.close()

    async def extract(self, config, credentials, cursor):
        from .base import ExtractResult

        conn = await self._connect(config, credentials)
        try:
            table = f"`{config['table']}`"
            cursor_col = config.get("cursor_column")
            async with conn.cursor() as cur:
                if cursor_col and cursor is not None:
                    if _NUM.fullmatch(str(cursor)):
                        comparison = (f"CAST(`{cursor_col}` AS DECIMAL(30,10)) > "
                                      f"CAST(%s AS DECIMAL(30,10))")
                    else:
                        comparison = f"CAST(`{cursor_col}` AS CHAR) > %s"
                    sql = (f"SELECT * FROM {table} WHERE {comparison} "  # noqa: S608 - identifiers regex-validated + quoted
                           f"ORDER BY `{cursor_col}` LIMIT 10000")
                    await cur.execute(sql, (str(cursor),))
                elif cursor_col:
                    sql = (f"SELECT * FROM {table} "  # noqa: S608
                           f"ORDER BY `{cursor_col}` LIMIT 10000")
                    await cur.execute(sql)
                else:
                    await cur.execute(f"SELECT * FROM {table} LIMIT 10000")  # noqa: S608
                rows = await cur.fetchall()
                headers = [d[0] for d in cur.description]
            if not rows:
                return ExtractResult([], [], cursor)
            data = [["" if v is None else str(v) for v in row] for row in rows]
            new_cursor = cursor
            if cursor_col and cursor_col in headers:
                new_cursor = data[-1][headers.index(cursor_col)]
            return ExtractResult(headers, data, new_cursor)
        finally:
            conn.close()
