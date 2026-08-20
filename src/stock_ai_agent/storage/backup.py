from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class SQLiteBackup:
    path: Path
    created_at: datetime


@dataclass(frozen=True)
class SQLiteRestore:
    source_backup: Path
    rollback_backup: Path | None


def backup_sqlite_database(database: str | Path, backup_dir: str | Path) -> SQLiteBackup:
    source = Path(database)
    if not source.exists():
        raise ValueError(f"SQLite 数据库不存在，无法备份：{source}")
    _validate_sqlite_database(source)
    created_at = datetime.now(timezone.utc)
    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{source.stem}-{created_at.strftime('%Y%m%dT%H%M%S%fZ')}.sqlite3"
    temporary = destination.with_suffix(".sqlite3.tmp")
    try:
        _copy_sqlite_database(source, temporary)
        _validate_sqlite_database(temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return SQLiteBackup(destination, created_at)


def restore_sqlite_database(
    database: str | Path,
    backup_file: str | Path,
    backup_dir: str | Path,
) -> SQLiteRestore:
    target = Path(database)
    source = Path(backup_file)
    if not source.exists():
        raise ValueError(f"备份文件不存在：{source}")
    _validate_sqlite_database(source)

    rollback_backup = backup_sqlite_database(target, backup_dir).path if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.restore-{uuid4().hex}.sqlite3")
    try:
        _copy_sqlite_database(source, temporary)
        _validate_sqlite_database(temporary)
        os.replace(temporary, target)
        _remove_sqlite_sidecars(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return SQLiteRestore(source, rollback_backup)


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def _validate_sqlite_database(path: Path) -> None:
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"SQLite 文件不可用：{path}") from exc
    if not result or result[0] != "ok":
        raise ValueError(f"SQLite 文件完整性校验失败：{path}")


def _remove_sqlite_sidecars(database: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{database}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
