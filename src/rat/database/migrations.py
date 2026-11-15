import sqlite3
from uuid import uuid4

from sqlalchemy import inspect, select

from rat.database.session import Database
from rat.database.tables import metadata, schema_version

SCHEMA_VERSION = 4
BASE_TABLES = {"schema_version", "projects", "units", "translations", "translation_revisions"}


def migrate_database(database: Database) -> None:
    with database.transaction() as connection:
        names = set(inspect(connection).get_table_names())
        if not BASE_TABLES.issubset(names):
            raise ValueError("Not a RAT project database.")
        versions = connection.execute(select(schema_version.c.version)).scalars().all()
    if versions == [SCHEMA_VERSION]:
        return
    if versions not in ([1], [2], [3]):
        raise ValueError("Unsupported database version; migration is required.")
    backup = database.path.with_name(f"project.sqlite.before-v{SCHEMA_VERSION}-{uuid4().hex}.bak")
    source = sqlite3.connect(database.path.as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(str(backup))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    with database.transaction() as connection:
        metadata.create_all(connection)
        connection.execute(schema_version.update().values(version=SCHEMA_VERSION))


def initialize_database(database: Database) -> None:
    with database.transaction() as connection:
        if inspect(connection).get_table_names():
            raise ValueError("Refusing to initialize a non-empty database.")
        metadata.create_all(connection)
        connection.execute(schema_version.insert().values(version=SCHEMA_VERSION))
        connection.exec_driver_sql(
            "CREATE TRIGGER immutable_unit_source BEFORE UPDATE ON units "
            "BEGIN SELECT RAISE(ABORT, 'source fields are immutable'); END"
        )
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER preserve_approved_{operation.lower()} "
                f"BEFORE {operation} ON translations WHEN OLD.status = 'approved' "
                "BEGIN SELECT RAISE(ABORT, 'approved translation is protected'); END"
            )


def check_schema(database: Database) -> None:
    # Opening is deliberately read-only at the service level: no implicit migrations.
    with database.transaction() as connection:
        names = set(inspect(connection).get_table_names())
        if not set(metadata.tables).issubset(names):
            raise ValueError("Not a complete RAT project database.")
        versions = connection.execute(select(schema_version.c.version)).scalars().all()
        if versions != [SCHEMA_VERSION]:
            raise ValueError("Unsupported database version; migration is required.")
