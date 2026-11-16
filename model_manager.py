"""Registry and runtime manager for multiple P-DINA checkpoints."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from cdacdm.service import CDMService, CheckpointNotFoundError, checkpoint_status


class ModelManager:
    """Lazily load model services and persist the administrator's default model."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._services: dict[str, CDMService] = {}
        self._registry = self._load_registry()

    @staticmethod
    def _load_registry() -> dict[str, dict[str, Any]]:
        raw = os.getenv("EDUBRIDGE_MODELS_JSON", "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict) or not parsed:
                    raise ValueError("registry must be a non-empty JSON object")
                return parsed
            except (json.JSONDecodeError, ValueError) as exc:
                raise RuntimeError(f"Invalid EDUBRIDGE_MODELS_JSON: {exc}") from exc
        return {
            "eedi_pdina": {
                "name": "EEDI P-DINA",
                "description": "Matematika EEDI NeurIPS 2020 Task 3/4",
                "artifact_dir": os.getenv("EEDI_ARTIFACT_DIR", "/app/artifacts"),
                "demo_only": False,
            },
            "calculus_pdina": {
                "name": "Calculus P-DINA (Demo)",
                "description": "Kalkulus kelas XI dengan data sintetis",
                "artifact_dir": os.getenv("CALCULUS_ARTIFACT_DIR", "/app/artifacts_calculus"),
                "demo_only": True,
            },
        }

    def _db_path(self) -> Path:
        path = Path(os.getenv("EDUBRIDGE_DB_PATH", "/app/data/edubridge_demo.sqlite3"))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._db_path(), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        return db

    def default_model_id(self) -> str:
        configured = os.getenv("EDUBRIDGE_DEFAULT_MODEL", "eedi_pdina").strip()
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key='default_model_id'"
            ).fetchone()
            return str(row["setting_value"]) if row else configured

    def _entry_status(self, model_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        artifact_dir = Path(str(entry.get("artifact_dir", "")))
        status = checkpoint_status(artifact_dir)
        return {
            "model_id": model_id,
            "name": str(entry.get("name", model_id)),
            "description": str(entry.get("description", "")),
            "artifact_dir": str(artifact_dir),
            "ready": bool(status["ready"]),
            "missing": status["missing"],
            "demo_only": bool(entry.get("demo_only", False)),
        }

    def list_models(self) -> list[dict[str, Any]]:
        return [self._entry_status(model_id, entry) for model_id, entry in self._registry.items()]

    def get_service(self, model_id: str | None = None) -> CDMService:
        selected = (model_id or self.default_model_id()).strip()
        if selected not in self._registry:
            raise KeyError(f"Unknown model_id '{selected}'. Available: {', '.join(self._registry)}")
        with self._lock:
            if selected not in self._services:
                entry = self._registry[selected]
                status = self._entry_status(selected, entry)
                if not status["ready"]:
                    raise CheckpointNotFoundError(
                        f"Model '{selected}' is not ready at {status['artifact_dir']}; missing: {', '.join(status['missing'])}"
                    )
                service = CDMService.load(status["artifact_dir"])
                service.model_id = selected
                self._services[selected] = service
            return self._services[selected]

    def set_default(self, model_id: str) -> dict[str, Any]:
        model_id = model_id.strip()
        if model_id not in self._registry:
            raise KeyError(f"Unknown model_id '{model_id}'")
        status = self._entry_status(model_id, self._registry[model_id])
        if not status["ready"]:
            raise CheckpointNotFoundError(
                f"Model '{model_id}' is not ready; missing: {', '.join(status['missing'])}"
            )
        # Load before changing the setting so a broken checkpoint cannot become active.
        self.get_service(model_id)
        with closing(self._connect()) as db:
            db.execute("""
                INSERT INTO app_settings(setting_key, setting_value, updated_at)
                VALUES ('default_model_id', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value, updated_at=CURRENT_TIMESTAMP
            """, (model_id,))
            db.commit()
        return {"default_model_id": model_id, "model": status}

    def reload(self, model_id: str | None = None) -> dict[str, Any]:
        targets = [model_id] if model_id else list(self._registry)
        results = []
        with self._lock:
            for selected in targets:
                if selected not in self._registry:
                    raise KeyError(f"Unknown model_id '{selected}'")
                self._services.pop(selected, None)
                try:
                    service = self.get_service(selected)
                    results.append({"model_id": selected, "reloaded": True,
                                    "questions": len(service.question_ids), "concepts": len(service.concept_ids)})
                except (CheckpointNotFoundError, FileNotFoundError, ValueError) as exc:
                    results.append({"model_id": selected, "reloaded": False, "error": str(exc)})
        return {"models": results}

    def active_info(self) -> dict[str, Any]:
        selected = self.default_model_id()
        status = self._entry_status(selected, self._registry[selected]) if selected in self._registry else None
        return {"default_model_id": selected, "model": status}


model_manager = ModelManager()
