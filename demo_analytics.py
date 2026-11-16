from __future__ import annotations

import json
import os
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("EDUBRIDGE_DB_PATH", "/app/data/edubridge_demo.sqlite3"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _init_db() -> None:
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS demo_classes (
            class_id TEXT PRIMARY KEY, class_name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS demo_students (
            student_id TEXT PRIMARY KEY, student_name TEXT NOT NULL,
            class_id TEXT NOT NULL REFERENCES demo_classes(class_id),
            ability_band TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS demo_assessments (
            assessment_id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES demo_classes(class_id),
            period TEXT NOT NULL CHECK(period IN ('pre', 'post')),
            created_at TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS demo_responses (
            response_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id TEXT NOT NULL REFERENCES demo_assessments(assessment_id) ON DELETE CASCADE,
            student_id TEXT NOT NULL REFERENCES demo_students(student_id),
            question_id INTEGER NOT NULL, response INTEGER CHECK(response IN (0, 1)),
            UNIQUE(assessment_id, student_id, question_id)
        );
        CREATE INDEX IF NOT EXISTS idx_demo_students_class ON demo_students(class_id);
        CREATE INDEX IF NOT EXISTS idx_demo_assessments_class ON demo_assessments(class_id, period);
        CREATE INDEX IF NOT EXISTS idx_demo_responses_assessment ON demo_responses(assessment_id);
        """)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _question_ids(service) -> list[int]:
    form = service.forms.get("fixed")
    if form is not None and not form.empty and "QuestionId" in form.columns:
        form = form.copy()
        for flag in ("eligible_target_item", "reliable_params", "diagnostic"):
            if flag in form.columns:
                form = form[form[flag].astype(str).str.lower().isin(["true", "1"])]
        ids = pd.to_numeric(form["QuestionId"], errors="coerce").dropna().astype(int).tolist()
    else:
        ids = [int(q) for q in service.question_ids[:50]]
    ids = list(dict.fromkeys(q for q in ids if q in set(int(x) for x in service.question_ids)))
    if len(ids) < 5:
        raise HTTPException(status_code=503, detail="Model checkpoint does not expose enough supported questions for demo seeding")
    return ids[:60]


class SeedRequest(BaseModel):
    students_per_class: int = Field(default=10, ge=3, le=30)
    class_count: int = Field(default=3, ge=1, le=6)
    seed: int = Field(default=42, ge=0, le=2_000_000_000)


def _session_frame(db: sqlite3.Connection, class_id: str, period: str) -> pd.DataFrame:
    rows = db.execute("""
        SELECT r.student_id, r.question_id AS QuestionId, r.response
        FROM demo_responses r
        JOIN demo_assessments a ON a.assessment_id = r.assessment_id
        WHERE a.class_id = ? AND a.period = ?
        ORDER BY r.student_id, r.question_id
    """, (class_id, period)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def require_demo_mode() -> None:
    if os.getenv("EDUBRIDGE_DEMO_MODE", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="Demo analytics is disabled")


def build_router(get_service: Callable, require_api_key: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["demo-analytics"], dependencies=[Depends(require_demo_mode)])

    @router.post("/admin/demo/seed", dependencies=[Depends(require_api_key)])
    def seed_demo(payload: SeedRequest, service=Depends(get_service)):
        _init_db()
        qids = _question_ids(service)
        rng = random.Random(payload.seed)
        now = _now()
        class_names = ["Kelas 7A", "Kelas 7B", "Kelas 7C", "Kelas 8A", "Kelas 8B", "Kelas 8C"]
        bands = [("perlu_dukungan", 0.34), ("berkembang", 0.52), ("baik", 0.70), ("unggul", 0.84)]
        with _connect() as db:
            db.execute("DELETE FROM demo_responses")
            db.execute("DELETE FROM demo_assessments")
            db.execute("DELETE FROM demo_students")
            db.execute("DELETE FROM demo_classes")
            total_students = 0
            for ci in range(payload.class_count):
                class_id = f"DEMO-C{ci + 1:02d}"
                db.execute("INSERT INTO demo_classes VALUES (?, ?, ?)", (class_id, class_names[ci], now))
                for si in range(payload.students_per_class):
                    student_id = f"DEMO-{ci + 1:02d}-{si + 1:03d}"
                    band, base = bands[(si + ci) % len(bands)]
                    ability = min(0.92, max(0.25, base + rng.uniform(-0.08, 0.08)))
                    db.execute("INSERT INTO demo_students VALUES (?, ?, ?, ?, 1)",
                               (student_id, f"Siswa Demo {ci + 1}-{si + 1:02d}", class_id, band))
                    total_students += 1
                    for period in ("pre", "post"):
                        assessment_id = f"{class_id}-{student_id}-{period.upper()}"
                        db.execute("INSERT INTO demo_assessments VALUES (?, ?, ?, ?, 1)",
                                   (assessment_id, class_id, period, now))
                        improvement = rng.uniform(0.10, 0.20) if period == "post" else 0.0
                        for qid in qids:
                            q_effect = ((qid * 17) % 13 - 6) / 100
                            probability = min(0.97, max(0.08, ability + improvement - q_effect))
                            response = int(rng.random() < probability)
                            db.execute("""
                                INSERT INTO demo_responses (assessment_id, student_id, question_id, response)
                                VALUES (?, ?, ?, ?)
                            """, (assessment_id, student_id, qid, response))
            db.commit()
        return {
            "seeded": True, "is_demo": True, "classes": payload.class_count,
            "students": total_students, "questions_per_assessment": len(qids),
            "assessment_sessions": total_students * 2,
            "response_rows": total_students * len(qids) * 2,
            "question_source": "P-DINA checkpoint fixed form (synthetic responses)",
            "warning": "Seluruh data ini sintetis untuk pengujian, bukan data siswa nyata."
        }

    @router.delete("/admin/demo/reset", dependencies=[Depends(require_api_key)])
    def reset_demo():
        _init_db()
        with _connect() as db:
            db.execute("DELETE FROM demo_responses")
            db.execute("DELETE FROM demo_assessments")
            db.execute("DELETE FROM demo_students")
            db.execute("DELETE FROM demo_classes")
            db.commit()
        return {"reset": True, "scope": "demo_only"}

    @router.get("/analytics/overview", dependencies=[Depends(require_api_key)])
    def overview():
        _init_db()
        with _connect() as db:
            classes = db.execute("SELECT COUNT(*) n FROM demo_classes").fetchone()["n"]
            students = db.execute("SELECT COUNT(*) n FROM demo_students").fetchone()["n"]
            sessions = db.execute("SELECT COUNT(*) n FROM demo_assessments").fetchone()["n"]
            responses = db.execute("SELECT COUNT(*) n, AVG(response) score FROM demo_responses").fetchone()
            periods = db.execute("""
                SELECT a.period, AVG(r.response) score, COUNT(*) responses
                FROM demo_responses r JOIN demo_assessments a USING(assessment_id)
                GROUP BY a.period
            """).fetchall()
        return {
            "is_demo": True, "classes": classes, "students": students, "assessment_sessions": sessions,
            "response_rows": responses["n"], "overall_accuracy": responses["score"],
            "periods": [dict(r) for r in periods],
            "disclaimer": "Angka berasal dari data sintetis jika dataset demo telah dibuat."
        }

    @router.get("/analytics/class/{class_id}", dependencies=[Depends(require_api_key)])
    def class_analytics(class_id: str, period: str = "post", service=Depends(get_service)):
        if period not in ("pre", "post"):
            raise HTTPException(status_code=422, detail="period must be pre or post")
        _init_db()
        with _connect() as db:
            cls = db.execute("SELECT * FROM demo_classes WHERE class_id=?", (class_id,)).fetchone()
            if not cls:
                raise HTTPException(status_code=404, detail="Demo class not found")
            frame = _session_frame(db, class_id, period)
        if frame.empty:
            raise HTTPException(status_code=404, detail=f"No {period}-test responses for this class")
        result = service.diagnose(frame)
        return {
            "is_demo": True, "class": dict(cls), "period": period,
            "students": int(frame["student_id"].nunique()),
            "accuracy": float(frame["response"].mean()),
            "diagnosis": service.report_json(result),
            "disclaimer": "Diagnosis adalah estimasi P-DINA pada data sintetis; bukan mastery terverifikasi."
        }

    @router.get("/analytics/student/{student_id}", dependencies=[Depends(require_api_key)])
    def student_analytics(student_id: str, period: str = "post", service=Depends(get_service)):
        if period not in ("pre", "post"):
            raise HTTPException(status_code=422, detail="period must be pre or post")
        _init_db()
        with _connect() as db:
            student = db.execute("SELECT * FROM demo_students WHERE student_id=?", (student_id,)).fetchone()
            if not student:
                raise HTTPException(status_code=404, detail="Demo student not found")
            rows = db.execute("""
                SELECT r.student_id, r.question_id AS QuestionId, r.response
                FROM demo_responses r JOIN demo_assessments a USING(assessment_id)
                WHERE r.student_id=? AND a.period=?
            """, (student_id, period)).fetchall()
        frame = pd.DataFrame([dict(r) for r in rows])
        if frame.empty:
            raise HTTPException(status_code=404, detail="No responses for this student and period")
        result = service.diagnose(frame)
        return {"is_demo": True, "student": dict(student), "period": period,
                "accuracy": float(frame["response"].mean()), "diagnosis": service.report_json(result),
                "disclaimer": "Profil ini merupakan estimasi model dari data sintetis."}

    @router.get("/analytics/prepost/{class_id}", dependencies=[Depends(require_api_key)])
    def prepost_analytics(class_id: str):
        _init_db()
        with _connect() as db:
            cls = db.execute("SELECT * FROM demo_classes WHERE class_id=?", (class_id,)).fetchone()
            if not cls:
                raise HTTPException(status_code=404, detail="Demo class not found")
            rows = db.execute("""
                SELECT a.period, r.student_id, AVG(r.response) accuracy, COUNT(*) answered
                FROM demo_responses r JOIN demo_assessments a USING(assessment_id)
                WHERE a.class_id=? GROUP BY a.period, r.student_id
            """, (class_id,)).fetchall()
        frame = pd.DataFrame([dict(r) for r in rows])
        if frame.empty or not {"pre", "post"}.issubset(set(frame["period"])):
            raise HTTPException(status_code=404, detail="Pre-test and post-test data are not both available")
        wide = frame.pivot(index="student_id", columns="period", values="accuracy").dropna()
        return {
            "is_demo": True, "class": dict(cls), "students_compared": int(len(wide)),
            "pre_accuracy": float(wide["pre"].mean()), "post_accuracy": float(wide["post"].mean()),
            "mean_change": float((wide["post"] - wide["pre"]).mean()),
            "students_improved": int((wide["post"] > wide["pre"]).sum()),
            "students_unchanged": int((wide["post"] == wide["pre"]).sum()),
            "students_declined": int((wide["post"] < wide["pre"]).sum()),
            "student_results": wide.reset_index().to_dict(orient="records"),
            "warning": "Perubahan skor sintetis ini hanya untuk menguji visualisasi dan alur analisis; bukan bukti efektivitas intervensi."
        }

    @router.post("/analytics/generate-report", dependencies=[Depends(require_api_key)])
    def generate_report(payload: dict, service=Depends(get_service)):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(status_code=503, detail="GEMINI_API_KEY belum diatur pada .env")
        class_id = str(payload.get("class_id", "")).strip()
        period = str(payload.get("period", "post")).strip()
        if not class_id or period not in ("pre", "post"):
            raise HTTPException(status_code=422, detail="class_id wajib diisi dan period harus pre atau post")
        _init_db()
        with _connect() as db:
            cls = db.execute("SELECT * FROM demo_classes WHERE class_id=?", (class_id,)).fetchone()
            if not cls:
                raise HTTPException(status_code=404, detail="Demo class not found")
            frame = _session_frame(db, class_id, period)
        if frame.empty:
            raise HTTPException(status_code=404, detail="Belum ada respons untuk kelas dan periode tersebut")
        result = service.diagnose(frame)
        facts = service.narrative_facts(result, audience="teacher").to_dict()
        facts["demo_data"] = True
        prompt = (
            "Buat laporan analisis pembelajaran dalam Bahasa Indonesia untuk guru berdasarkan JSON fakta berikut. "
            "Gunakan heading: Ringkasan kelas, Temuan utama, Konsep prioritas, Rekomendasi tindakan, Keterbatasan dan catatan. "
            "Jangan menambah angka, konsep, atau klaim yang tidak ada di fakta. Sebut mastery sebagai estimasi model, "
            "bukan fakta terverifikasi. Jika rekomendasi placeholder, wajib tulis perlu validasi guru. "
            "Insufficient evidence bukan learning gap. Data ini sintetis untuk demo, jangan menyajikannya sebagai data nyata.\\n\\n"
            + json.dumps(facts, ensure_ascii=False)
        )
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        try:
            response = requests.post(
                url, params={"key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1200}},
                timeout=60,
            )
            response.raise_for_status()
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Gemini report generation failed: {exc}") from exc
        return {
            "class_id": class_id, "period": period, "provider": "Google Gemini",
            "model": model_name, "is_demo": True, "text": text,
            "facts": {"students": int(frame["student_id"].nunique()), "responses": int(len(frame)),
                      "accuracy": float(frame["response"].mean())},
            "disclaimer": "Laporan dibuat dari data sintetis dan estimasi P-DINA. Verifikasi hasil sebelum digunakan untuk keputusan pembelajaran."
        }

    return router
