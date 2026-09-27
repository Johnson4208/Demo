"""Create, verify, and safely stage SolvAI backup archives.

The SQLite online-backup API is used instead of copying the live database.
Backups contain private account metadata and may contain reports. Restore never
overwrites the active data directory: it creates a new inspection directory
that can be validated before an operator deliberately switches storage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from config import APP_VERSION, DATA_ROOT, DB_PATH, REPORTS_DIR


FORMAT = "solvai-backup-v2"
DATABASE_MEMBER = "storage/financial_ai.sqlite3"
MANIFEST_MEMBER = "backup-manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_database(path: Path) -> None:
    with sqlite3.connect(path, timeout=30) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {result[0] if result else 'no result'}")


def _report_files(reports_dir: Path):
    if not reports_dir.exists():
        return []
    root = reports_dir.resolve()
    files = []
    for candidate in sorted(reports_dir.rglob("*")):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            candidate.resolve().relative_to(root)
        except ValueError:
            continue
        files.append(candidate)
    return files


def _member_record(path: Path, archive_path: str):
    return {"path": archive_path, "size": path.stat().st_size, "sha256": _sha256(path)}


def create_backup(
    db_path: Path = DB_PATH,
    reports_dir: Path = REPORTS_DIR,
    output_dir: Path | None = None,
    *,
    include_reports: bool = True,
) -> Path:
    db_path = Path(db_path)
    reports_dir = Path(reports_dir)
    output_dir = Path(output_dir or (DATA_ROOT / "backups"))
    if not db_path.exists():
        raise FileNotFoundError(f"SolvAI database was not found: {db_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_path = output_dir / f"solvai-backup-{stamp}.zip"

    with tempfile.TemporaryDirectory(prefix="solvai-backup-") as temp_dir:
        snapshot_path = Path(temp_dir) / "financial_ai.sqlite3"
        source_uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(source_uri, uri=True, timeout=30) as source:
            source.execute("PRAGMA busy_timeout=30000")
            with sqlite3.connect(snapshot_path, timeout=30) as target:
                source.backup(target)
        _check_database(snapshot_path)

        reports = _report_files(reports_dir) if include_reports else []
        archive_files = [(snapshot_path, DATABASE_MEMBER)]
        for report in reports:
            relative = report.resolve().relative_to(reports_dir.resolve()).as_posix()
            archive_files.append((report, f"reports/Companies_reports/{relative}"))
        file_records = [_member_record(path, name) for path, name in archive_files]
        manifest = {
            "format": FORMAT,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "application_version": APP_VERSION,
            "database": DATABASE_MEMBER,
            "database_sha256": file_records[0]["sha256"],
            "reports_included": bool(include_reports),
            "report_file_count": len(reports),
            "files": file_records,
        }

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for path, name in archive_files:
                archive.write(path, name)
            archive.writestr(MANIFEST_MEMBER, json.dumps(manifest, indent=2, ensure_ascii=False))

    try:
        os.chmod(archive_path, 0o600)
    except OSError:
        pass
    return archive_path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)


def _validated_members(archive: zipfile.ZipFile):
    maximum = max(1, int(os.getenv("SOLVAI_BACKUP_MAX_EXPANDED_MB", "10000"))) * 1024 * 1024
    seen, members, expanded = set(), {}, 0
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or _is_symlink(info):
            raise RuntimeError("Backup contains an unsafe archive member.")
        if name in seen:
            raise RuntimeError("Backup contains duplicate archive members.")
        seen.add(name)
        if info.is_dir():
            continue
        allowed = name in {MANIFEST_MEMBER, DATABASE_MEMBER} or name.startswith("reports/Companies_reports/")
        if not allowed:
            raise RuntimeError("Backup contains an unexpected archive member.")
        expanded += int(info.file_size)
        if expanded > maximum:
            raise RuntimeError("Backup exceeds the configured expanded-size limit.")
        members[name] = info
    if MANIFEST_MEMBER not in members or DATABASE_MEMBER not in members:
        raise RuntimeError("Backup is missing its manifest or database.")
    return members


def _zip_member_hash(archive: zipfile.ZipFile, member: str):
    digest = hashlib.sha256()
    size = 0
    with archive.open(member) as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_backup(archive_path: Path) -> dict:
    archive_path = Path(archive_path)
    with tempfile.TemporaryDirectory(prefix="solvai-verify-") as temp_dir:
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = _validated_members(archive)
            if members[MANIFEST_MEMBER].file_size > 1024 * 1024:
                raise RuntimeError("Backup manifest is unexpectedly large.")
            manifest = json.loads(archive.read(MANIFEST_MEMBER))
            backup_format = manifest.get("format")
            if backup_format not in {FORMAT, "solvai-backup-v1"} or manifest.get("database") != DATABASE_MEMBER:
                raise RuntimeError("Unsupported SolvAI backup format.")
            if backup_format == FORMAT:
                records = manifest.get("files")
                if not isinstance(records, list) or not records:
                    raise RuntimeError("Backup manifest does not contain a file inventory.")
                expected = {}
                for record in records:
                    if not isinstance(record, dict) or set(record) != {"path", "size", "sha256"}:
                        raise RuntimeError("Backup manifest contains an invalid file record.")
                    name = str(record["path"])
                    if name in expected:
                        raise RuntimeError("Backup manifest contains duplicate file records.")
                    expected[name] = record
                if set(members) != set(expected) | {MANIFEST_MEMBER}:
                    raise RuntimeError("Backup contents do not match the manifest inventory.")
                for name, record in expected.items():
                    size, digest = _zip_member_hash(archive, name)
                    if size != int(record["size"]) or digest != str(record["sha256"]):
                        raise RuntimeError("Backup file checksum or size does not match the manifest.")
                if expected[DATABASE_MEMBER]["sha256"] != manifest.get("database_sha256"):
                    raise RuntimeError("Database checksum does not match the backup manifest.")
                manifest["verification_level"] = "all_files"
            else:
                # Phase 1 archives hash only the database. They remain usable so
                # an operator can upgrade safely, but the weaker scope is explicit.
                _, digest = _zip_member_hash(archive, DATABASE_MEMBER)
                if digest != manifest.get("database_sha256"):
                    raise RuntimeError("Database checksum does not match the backup manifest.")
                manifest["verification_level"] = "legacy_database_only"
            snapshot_path = Path(temp_dir) / "financial_ai.sqlite3"
            with archive.open(DATABASE_MEMBER) as source, snapshot_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        _check_database(snapshot_path)
    return manifest


def restore_backup(archive_path: Path, target_data_dir: Path) -> Path:
    """Stage a verified backup into a new directory; never overwrite live data."""
    archive_path = Path(archive_path).resolve()
    target = Path(target_data_dir).resolve()
    if target.exists():
        raise FileExistsError("Restore target already exists. Choose a new empty path.")
    manifest = verify_backup(archive_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-staging-", dir=target.parent))
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = _validated_members(archive)
            names = ([record["path"] for record in manifest["files"]]
                     if manifest.get("format") == FORMAT
                     else [name for name in members if name != MANIFEST_MEMBER])
            for name in names:
                destination = staging.joinpath(*PurePosixPath(name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(members[name]) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        _check_database(staging / DATABASE_MEMBER)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def _main() -> int:
    parser = argparse.ArgumentParser(description="Create, verify, or safely stage a SolvAI backup archive.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create", help="Create a consistent database and report backup.")
    create_parser.add_argument("--output-dir", type=Path, default=DATA_ROOT / "backups")
    create_parser.add_argument("--database-only", action="store_true")
    verify_parser = subparsers.add_parser("verify", help="Verify every file and the SQLite database in a backup ZIP.")
    verify_parser.add_argument("archive", type=Path)
    restore_parser = subparsers.add_parser("restore-preview", help="Restore into a new directory for inspection; never overwrite live data.")
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("--target-dir", type=Path, required=True)
    subparsers.add_parser("list", help="List backup archives stored in the configured data directory.")
    args = parser.parse_args()

    if args.command == "create":
        archive = create_backup(output_dir=args.output_dir, include_reports=not args.database_only)
        print(f"Created: {archive}")
        print("Contains account metadata and reports; keep this archive private.")
        return 0
    if args.command == "verify":
        manifest = verify_backup(args.archive)
        print(f"Verified: {args.archive} (app {manifest.get('application_version')}, reports {manifest.get('report_file_count')})")
        return 0
    if args.command == "restore-preview":
        target = restore_backup(args.archive, args.target_dir)
        print(f"Restored safely for inspection: {target}")
        print("The active SolvAI data directory was not changed.")
        return 0

    backup_dir = DATA_ROOT / "backups"
    for archive in sorted(backup_dir.glob("solvai-backup-*.zip")) if backup_dir.exists() else []:
        print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
