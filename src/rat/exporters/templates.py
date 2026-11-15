import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from rat.database.tables import template_snapshots
from rat.exporters.safe_io import checked_path, relative_export_path
from rat.security.safe_paths import read_source_bytes


class TemplateCatalog:
    """Immutable official-template snapshots keyed to the exact imported source/provenance."""

    @staticmethod
    def key(report):
        payload = {
            "sources": sorted(unit.source_sha256 for unit in report.units),
            "origins": sorted(
                (origin.template_path or "", origin.template_line or 0, origin.source_verified)
                for origin in report.origins
            ),
            "inventory": report.inventory.model_dump(mode="json"),
            "sdk_version": report.sdk_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def load(self, session, report):
        key = self.key(report)
        with session.database.transaction() as connection:
            rows = (
                connection.execute(
                    select(template_snapshots).where(
                        template_snapshots.c.project_id == session.project.project_id,
                        template_snapshots.c.snapshot_key == key,
                    )
                )
                .mappings()
                .all()
            )
        if rows:
            result = {}
            for row in rows:
                if hashlib.sha256(row["content"].encode("utf-8")).hexdigest() != row["sha256"]:
                    raise ValueError("template_snapshot_corrupt")
                result[relative_export_path(row["path"])] = row["content"]
            return result
        # Seed snapshots only while the original source/template hashes still match.
        game_root = Path(report.inventory.game_dir)
        for item in report.inventory.files:
            if item.sha256 and item.extension in {".rpy", ".rpym"}:
                data = read_source_bytes(checked_path(game_root, item.relpath))
                if hashlib.sha256(data).hexdigest() != item.sha256:
                    raise ValueError("source_changed_reimport_first")
        root = Path(report.template_dir) if report.template_dir else game_root
        if report.template_dir and not root.resolve().is_relative_to(session.path / "staging"):
            raise ValueError("unsafe_template_root")
        paths = {origin.template_path for origin in report.origins if origin.template_path}
        result = {}
        for path in sorted(paths):
            if not path.startswith("game/tl/arabic/") or Path(path).suffix not in {".rpy", ".rpym"}:
                raise ValueError("unsupported_template_path")
            result[path] = read_source_bytes(checked_path(root, path)).decode("utf-8-sig")
        with session.database.transaction() as connection:
            for path, text in result.items():
                connection.execute(
                    template_snapshots.insert().values(
                        project_id=session.project.project_id,
                        snapshot_key=key,
                        path=path,
                        content=text,
                        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                )
        return result
