"""Load an explicitly authorized EEDI assessment content pack.

Question text is deliberately not bundled in this repository. An operator may mount
an independently licensed content pack at EEDI_CONTENT_PATH after confirming
permission covers this website and its intended audience.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class AssessmentContentError(ValueError):
    pass


def load_assessment_content(allowed_question_ids: set[int]) -> dict[int, dict[str, Any]]:
    path = Path(os.getenv("EEDI_CONTENT_PATH", "/app/content/eedi_questions.json"))
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssessmentContentError(f"Cannot read EEDI content pack: {exc}") from exc
    if payload.get("license_confirmed") is not True or not str(payload.get("authorization_reference", "")).strip():
        raise AssessmentContentError("Content pack requires license_confirmed=true and authorization_reference")
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise AssessmentContentError("Content pack questions must be a list")
    result: dict[int, dict[str, Any]] = {}
    for item in questions:
        if not isinstance(item, dict):
            raise AssessmentContentError("Each content item must be an object")
        try:
            qid = int(item["question_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AssessmentContentError("Each item needs an integer question_id") from exc
        if qid not in allowed_question_ids:
            raise AssessmentContentError(f"QuestionId {qid} is not in the supported P-DINA fixed form")
        if qid in result:
            raise AssessmentContentError(f"Duplicate content for EEDI QuestionId {qid}")
        prompt, options = item.get("prompt"), item.get("options")
        if not isinstance(prompt, str) or not prompt.strip():
            raise AssessmentContentError(f"QuestionId {qid} has no prompt")
        if not isinstance(options, list) or len(options) != 4:
            raise AssessmentContentError(f"QuestionId {qid} must have exactly four ordered options")
        clean, seen = [], set()
        for option in options:
            if not isinstance(option, dict):
                raise AssessmentContentError(f"QuestionId {qid} has an invalid option")
            value, text = option.get("value"), option.get("text")
            if value not in (1, 2, 3, 4) or value in seen or not isinstance(text, str) or not text.strip():
                raise AssessmentContentError(f"QuestionId {qid} options must use unique values 1-4 and non-empty text")
            seen.add(value)
            clean.append({"value": value, "text": text.strip()})
        if seen != {1, 2, 3, 4}:
            raise AssessmentContentError(f"QuestionId {qid} options must contain values 1, 2, 3, and 4")
        result[qid] = {"QuestionId": qid, "prompt": prompt.strip(),
                       "options": sorted(clean, key=lambda x: x["value"])}
    if set(result) != allowed_question_ids:
        raise AssessmentContentError(f"Content pack incomplete; missing QuestionIds: {sorted(allowed_question_ids - set(result))}")
    return result
