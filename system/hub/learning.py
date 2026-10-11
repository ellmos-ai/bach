"""Learning-source previews and draft storage shared by CLI and HTTP API."""
from __future__ import annotations
import json
from pathlib import Path
from .base import BaseHandler
from ._services.learning_source_service import LearningSourceService, _read, MAX_REQUEST_BYTES


class LearningHandler(BaseHandler):
    @property
    def profile_name(self):
        return "learning"

    @property
    def target_file(self):
        return self._canonical_db

    def get_operations(self):
        return {
            "analyze": "Begrenzte Lernquelle und Vorschlag aus einer JSON-Auftragsdatei prüfen",
            "store": "Geprüften Vorschlag als inaktiven, versionierten Kandidaten speichern",
        }

    @staticmethod
    def analyze_payload(payload, *, db_path, actor, persist=False):
        return LearningSourceService(db_path).analyze(payload, actor=actor, persist=persist)

    def handle(self, operation, args, dry_run=False):
        args = list(args or ())
        dry_run_flags = {"--dry-run", "-n"}
        dry_run = bool(dry_run or any(arg in dry_run_flags for arg in args))
        args = [arg for arg in args if arg not in dry_run_flags]
        if (operation not in self.get_operations() or len(args) != 1
                or not isinstance(args[0], str) or args[0].startswith("-")):
            return False, "bach learning analyze|store <JSON-Auftragsdatei>"
        try:
            request_path = Path(args[0]).expanduser().absolute()
            _, raw, _ = _read(request_path.parent, request_path.name, maximum=MAX_REQUEST_BYTES)
            try:
                payload = json.loads(raw)
            except RecursionError as exc:
                raise ValueError("JSON-Auftragsdatei ist zu tief verschachtelt") from exc
            result = self.analyze_payload(payload, db_path=self._canonical_db,
                actor="local-cli", persist=operation == "store" and not dry_run)
            return True, json.dumps(result, ensure_ascii=False)
        except (OSError, ValueError, PermissionError) as exc:
            return False, str(exc)
