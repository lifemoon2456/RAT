import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry, NullPool


class Database:
    def __init__(self, path: Path, *, create: bool = False):
        self.path = path.resolve()
        if not create and not path.is_file():
            raise ValueError("Project database does not exist.")
        self.engine: Engine = create_engine(
            URL.create(
                "sqlite+pysqlite",
                database=path.resolve().as_uri(),
                query={"mode": "rwc" if create else "rw", "uri": "true"},
            ),
            connect_args={"timeout": 10},
            poolclass=NullPool,
        )

        @event.listens_for(self.engine, "connect")
        def configure(connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
            # Explicit BEGIN also makes DDL and savepoints transactional on Python 3.11.
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(self.engine, "begin")
        def begin(connection: Connection) -> None:
            connection.exec_driver_sql("BEGIN")

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as connection:
            yield connection

    def close(self) -> None:
        self.engine.dispose()
