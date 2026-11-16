from pathlib import Path

import pytest

import model_manager as manager_module
from model_manager import ModelManager
from cdacdm.service import CheckpointNotFoundError


class FakeService:
    question_ids = [1, 2]
    concept_ids = [10]

    def __init__(self, artifact_dir):
        self.artifact_dir = Path(artifact_dir)


def _manager(tmp_path, monkeypatch):
    monkeypatch.setenv("EDUBRIDGE_DB_PATH", str(tmp_path / "settings.sqlite3"))
    monkeypatch.setenv("EDUBRIDGE_DEFAULT_MODEL", "eedi_pdina")
    instance = ModelManager()
    instance._registry = {
        "eedi_pdina": {"name": "EEDI", "artifact_dir": str(tmp_path / "eedi"), "demo_only": False},
        "calculus_pdina": {"name": "Calculus", "artifact_dir": str(tmp_path / "calculus"), "demo_only": True},
    }
    return instance


def test_default_model_is_persisted_and_service_is_cached(tmp_path, monkeypatch):
    instance = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(manager_module, "checkpoint_status",
                        lambda path: {"ready": True, "missing": []})
    monkeypatch.setattr(manager_module.CDMService, "load",
                        lambda path: FakeService(path))

    assert instance.default_model_id() == "eedi_pdina"
    result = instance.set_default("calculus_pdina")

    assert result["default_model_id"] == "calculus_pdina"
    assert instance.default_model_id() == "calculus_pdina"
    assert instance.get_service().artifact_dir == tmp_path / "calculus"
    assert instance.get_service().model_id == "calculus_pdina"


def test_unavailable_model_cannot_become_default(tmp_path, monkeypatch):
    instance = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(manager_module, "checkpoint_status",
                        lambda path: {"ready": False, "missing": ["pdina_params.npz"]})

    with pytest.raises(CheckpointNotFoundError):
        instance.set_default("calculus_pdina")

    assert instance.default_model_id() == "eedi_pdina"


def test_unknown_model_is_rejected(tmp_path, monkeypatch):
    instance = _manager(tmp_path, monkeypatch)

    with pytest.raises(KeyError):
        instance.get_service("not_registered")
