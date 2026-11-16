from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from cdacdm.service import CDMService, CheckpointNotFoundError, checkpoint_status
from assessment_content import AssessmentContentError, load_assessment_content

APP_VERSION = "0.1.0"
app = FastAPI(title="EduBridge Learning Diagnostics API", version=APP_VERSION)

origins = [x.strip() for x in os.getenv("EDUBRIDGE_CORS_ORIGINS", "").split(",") if x.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )

_service: CDMService | None = None


def get_service() -> CDMService:
    global _service
    if _service is None:
        artifact_dir = os.getenv("CDACDM_ARTIFACT_DIR", "/app/artifacts")
        try:
            _service = CDMService.load(artifact_dir)
        except (CheckpointNotFoundError, FileNotFoundError) as exc:
            raise HTTPException(status_code=503, detail=f"Model checkpoint is not ready: {exc}") from exc
    return _service


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("EDUBRIDGE_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="API authentication is not configured")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")


class ResponseRow(BaseModel):
    question_id: int = Field(alias="QuestionId")
    response: int | None = Field(ge=0, le=1)

    model_config = {"populate_by_name": True}


class DiagnoseRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    responses: list[ResponseRow] = Field(min_length=1, max_length=500)

    model_config = {"extra": "forbid"}


class NarrativeRequest(DiagnoseRequest):
    audience: Literal["student", "teacher"] = "student"

class AnswerChoiceRow(BaseModel):
    question_id: int = Field(alias="QuestionId")
    answer_value: int | None = Field(default=None, alias="AnswerValue", ge=1, le=4)

    model_config = {"populate_by_name": True}


class AssessmentSubmitRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    responses: list[AnswerChoiceRow] = Field(min_length=1, max_length=500)

    model_config = {"extra": "forbid"}


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")


@app.get("/health")
def health():
    status = checkpoint_status(os.getenv("CDACDM_ARTIFACT_DIR", "/app/artifacts"))
    return {"status": "ok" if status["ready"] else "degraded", "version": APP_VERSION,
            "model_ready": status["ready"], "missing_checkpoint_files": status["missing"]}


@app.get("/api/v1/model", dependencies=[Depends(require_api_key)])
def model_info(service: CDMService = Depends(get_service)):
    card = service.model_card
    return {
        "engine": "P-DINA",
        "model": card.get("model_selection", {}).get("main_model"),
        "artifact_source": card.get("data", {}).get("artifact_source"),
        "questions": int(len(service.question_ids)),
        "concepts": int(len(service.concept_ids)),
        "target_concepts": int(len(service.policy.target_concept_ids)),
        "policy": service.policy.to_dict(),
        "disclaimer": "Mastery probabilities are model-based estimates, not verified mastery.",
    }


def supported_fixed_form(service: CDMService) -> pd.DataFrame:
    """Return only the packaged, model-supported EEDI fixed-form items."""
    form = service.forms.get("fixed")
    if form is None or form.empty:
        raise HTTPException(status_code=503, detail="The model-supported EEDI fixed assessment is not packaged")
    if "QuestionId" not in form.columns:
        raise HTTPException(status_code=503, detail="The fixed assessment is missing QuestionId")
    form = form.copy()
    form["QuestionId"] = pd.to_numeric(form["QuestionId"], errors="raise").astype(int)
    model_ids = set(int(q) for q in service.question_ids)
    unknown = sorted(set(form["QuestionId"]) - model_ids)
    if unknown:
        raise HTTPException(status_code=503, detail=f"Fixed assessment contains IDs absent from the P-DINA checkpoint: {unknown}")
    for flag in ("eligible_target_item", "reliable_params", "diagnostic"):
        if flag in form.columns:
            form = form[form[flag].astype(str).str.lower().isin(["true", "1"])]
    return form.drop_duplicates("QuestionId").sort_values("position" if "position" in form else "QuestionId")


def supported_question_bank(service: CDMService) -> pd.DataFrame:
    """Load the 139 eligible EEDI questions supported by the P-DINA checkpoint."""
    artifact_dir = Path(os.getenv("CDACDM_ARTIFACT_DIR", "/app/artifacts"))
    path = artifact_dir / "assessment" / "question_bank.csv"

    if not path.is_file():
        raise HTTPException(status_code=503, detail="Question bank is not packaged")

    try:
        bank = pd.read_csv(path)
        bank["QuestionId"] = pd.to_numeric(bank["QuestionId"], errors="raise").astype(int)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot read question bank: {exc}") from exc

    if bank["QuestionId"].duplicated().any():
        raise HTTPException(status_code=503, detail="Question bank contains duplicate QuestionIds")

    model_ids = set(int(q) for q in service.question_ids)
    bank_ids = set(bank["QuestionId"].astype(int))
    unknown = sorted(bank_ids - model_ids)

    if unknown:
        raise HTTPException(
            status_code=503,
            detail=f"Question bank contains IDs absent from P-DINA checkpoint: {unknown}",
        )

    return bank.sort_values(["concept_names", "QuestionId"]).reset_index(drop=True)


def validate_assessment_responses(payload: DiagnoseRequest, service: CDMService) -> None:
    bank = supported_question_bank(service)
    allowed = set(bank["QuestionId"].astype(int))
    submitted = [int(r.question_id) for r in payload.responses]
    duplicates = sorted({q for q in submitted if submitted.count(q) > 1})
    if duplicates:
        raise HTTPException(status_code=422, detail=f"Duplicate EEDI QuestionIds are not allowed: {duplicates}")
    unsupported = sorted(set(submitted) - allowed)
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail={"message": "Only EEDI questions in the packaged P-DINA-supported fixed assessment are accepted.",
                    "unsupported_question_ids": unsupported,
                    "supported_question_count": len(allowed)},
        )

@app.get(
    "/api/v1/assessment/images/{question_id}",
    dependencies=[Depends(require_api_key)],
)
def assessment_image(
    question_id: int,
    service: CDMService = Depends(get_service),
):
    bank = supported_question_bank(service)
    allowed = set(bank["QuestionId"].astype(int))

    if question_id not in allowed:
        raise HTTPException(
            status_code=404,
            detail="Question image not found",
        )

    image_path = (
        Path(os.getenv("EEDI_IMAGE_DIR", "/app/content/images"))
        / f"{question_id}.jpg"
    )

    if not image_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Question image file is missing",
        )

    return FileResponse(
        path=image_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )

@app.get("/api/v1/assessment/bank", dependencies=[Depends(require_api_key)])
def assessment_bank(service: CDMService = Depends(get_service)):
    bank = supported_question_bank(service)
    safe_columns = [
        "QuestionId", "concept_ids", "concept_names",
        "n_concepts", "model_difficulty",
    ]
    items = records(bank[safe_columns])

    for item in items:
        qid = int(item["QuestionId"])
        item["image_url"] = f"/api/v1/assessment/images/{qid}"

    return {
        "assessment_id": "eedi_pdina_question_bank_v1",
        "source": "EEDI NeurIPS 2020",
        "model": "P-DINA",
        "items": items,
        "count": len(items),
        "note": "Question metadata only. Answer keys are never returned.",
    }


@app.get("/api/v1/assessment/fixed", dependencies=[Depends(require_api_key)])
def fixed_assessment(service: CDMService = Depends(get_service)):
    form = supported_fixed_form(service)
    safe_columns = [c for c in ["form_id", "position", "QuestionId", "concept_ids", "concept_names",
                                "n_concepts", "model_difficulty"] if c in form.columns]
    allowed = set(form["QuestionId"].astype(int))
    try:
        content = load_assessment_content(allowed)
    except AssessmentContentError as exc:
        raise HTTPException(status_code=503, detail=f"EEDI content pack invalid: {exc}") from exc
    items = records(form[safe_columns])
    for item in items:
        qid = int(item["QuestionId"])
        if content:
            item.update(content[qid])
    ready = bool(content) and len(content) == len(items)
    return {
        "assessment_id": "eedi_pdina_fixed_v1",
        "source": "EEDI NeurIPS 2020",
        "model": "P-DINA",
        "items": items,
        "count": int(len(items)),
        "question_content_available": ready,
        "delivery_status": "ready_for_authorized_server_delivery" if ready else "metadata_only",
        "note": "Only original EEDI questions in the P-DINA-supported fixed form are included. Content is served only from an explicitly authorized content pack; answer keys are never returned.",
    }

@app.post("/api/v1/assessment/submit", dependencies=[Depends(require_api_key)])
def submit_assessment(payload: AssessmentSubmitRequest, service: CDMService = Depends(get_service)):
    """Score A-D choices server-side, then run P-DINA. Trusted server-to-server only."""
    validation_payload = DiagnoseRequest(
        student_id=payload.student_id,
        responses=[ResponseRow(question_id=r.question_id, response=None) for r in payload.responses],
    )
    validate_assessment_responses(validation_payload, service)
    bank = service.item_bank
    required = {"QuestionId", "correct_answer"}
    if bank is None or not required.issubset(bank.columns):
        raise HTTPException(status_code=503, detail="Server-side EEDI answer key is unavailable")
    key_frame = bank.copy()
    key_frame["QuestionId"] = pd.to_numeric(key_frame["QuestionId"], errors="raise").astype(int)
    if "correct_answer_consistent" in key_frame.columns:
        consistent = key_frame["correct_answer_consistent"].astype(str).str.lower().isin(["true", "1"])
        key_frame = key_frame[consistent]
    if "correct_answer_nunique" in key_frame.columns:
        key_frame = key_frame[pd.to_numeric(key_frame["correct_answer_nunique"], errors="coerce") == 1]
    answer_key = key_frame.drop_duplicates("QuestionId").set_index("QuestionId")["correct_answer"]
    rows = []
    for item in payload.responses:
        if item.answer_value is None:
            scored = None
        else:
            if item.question_id not in answer_key.index:
                raise HTTPException(status_code=422, detail=f"No verified EEDI answer key for QuestionId {item.question_id}")
            correct = int(answer_key.loc[item.question_id])
            if correct not in (1, 2, 3, 4):
                raise HTTPException(status_code=503, detail=f"Invalid server-side answer key for QuestionId {item.question_id}")
            scored = int(item.answer_value == correct)
        rows.append({"student_id": payload.student_id, "QuestionId": item.question_id, "response": scored})
    try:
        result = service.diagnose(pd.DataFrame(rows))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "assessment_id": "eedi_pdina_fixed_v1",
        "scoring": "server_side_answer_key",
        "answered": sum(r["response"] is not None for r in rows),
        "submitted": len(rows),
        "diagnosis": service.report_json(result),
    }


@app.post("/api/v1/diagnose", dependencies=[Depends(require_api_key)])
def diagnose(payload: DiagnoseRequest, service: CDMService = Depends(get_service)):
    validate_assessment_responses(payload, service)
    rows = [{"student_id": payload.student_id, "QuestionId": r.question_id, "response": r.response}
            for r in payload.responses]
    try:
        result = service.diagnose(pd.DataFrame(rows))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    report = service.report_json(result)
    return report


@app.post("/api/v1/narrative", dependencies=[Depends(require_api_key)])
def narrative(payload: NarrativeRequest, service: CDMService = Depends(get_service)):
    """Run P-DINA, then explain only compact pseudonymized facts with Gemini."""
    validate_assessment_responses(payload, service)
    rows = [{"student_id": payload.student_id, "QuestionId": r.question_id, "response": r.response}
            for r in payload.responses]
    try:
        result = service.diagnose(pd.DataFrame(rows))
        generated = service.generate_narrative(result, audience=payload.audience, student_id=payload.student_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"text": generated.get("text", ""), "fallback": bool(generated.get("fallback", False)),
            "validation": generated.get("validation"), "meta": generated.get("meta"),
            "diagnostic_engine": "P-DINA", "narrative_provider": "Google Gemini API"}


@app.post("/api/v1/admin/reload", dependencies=[Depends(require_api_key)])
def reload_model():
    global _service
    _service = None
    service = get_service()
    return {"reloaded": True, "questions": int(len(service.question_ids)), "concepts": int(len(service.concept_ids))}
