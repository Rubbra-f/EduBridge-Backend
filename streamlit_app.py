from __future__ import annotations

import hmac
import os
from typing import Any

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="EduBridge Backend Console",
    page_icon="🎓",
    layout="wide",
)

API_BASE_URL = os.getenv("EDUBRIDGE_API_URL", "http://api:8000").rstrip("/")
API_KEY = os.getenv("EDUBRIDGE_API_KEY", "")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
REQUEST_TIMEOUT = float(os.getenv("DASHBOARD_REQUEST_TIMEOUT", "25"))


class ApiError(RuntimeError):
    pass


def api_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = REQUEST_TIMEOUT,
) -> Any:
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ApiError(f"Tidak dapat menghubungi API: {exc}") from exc

    try:
        body = response.json()
    except ValueError:
        body = response.text

    if not response.ok:
        detail = body.get("detail", body) if isinstance(body, dict) else body
        raise ApiError(f"HTTP {response.status_code}: {detail}")
    return body


def api_image(question_id: int) -> bytes:
    headers = {"X-API-Key": API_KEY}
    try:
        response = requests.get(
            f"{API_BASE_URL}/api/v1/assessment/images/{question_id}",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ApiError(f"Tidak dapat mengambil gambar soal: {exc}") from exc
    if not response.ok:
        raise ApiError(f"HTTP {response.status_code}: {response.text[:300]}")
    return response.content


def require_login() -> None:
    if not DASHBOARD_PASSWORD:
        st.error(
            "Dashboard dikunci karena DASHBOARD_PASSWORD belum diatur. "
            "Isi variabel tersebut di file .env lalu restart container dashboard."
        )
        st.stop()
    if len(DASHBOARD_PASSWORD) < 16:
        st.error("DASHBOARD_PASSWORD harus memiliki minimal 16 karakter.")
        st.stop()

    if st.session_state.get("authenticated"):
        return

    st.title("EduBridge Backend Console")
    st.caption("Dashboard internal untuk pengujian API EduBridge.")
    with st.form("login_form"):
        password = st.text_input("Dashboard password", type="password")
        submitted = st.form_submit_button("Masuk", type="primary")
    if submitted:
        if hmac.compare_digest(password, DASHBOARD_PASSWORD):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Password tidak sesuai.")
    st.stop()


def show_api_error(exc: Exception) -> None:
    st.error(str(exc))


def get_question_items() -> list[dict[str, Any]]:
    result = api_request("GET", "/api/v1/assessment/fixed")
    items = result.get("items", [])
    if not items:
        result = api_request("GET", "/api/v1/assessment/bank")
        items = result.get("items", [])
    return items


def question_ids(items: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for item in items:
        try:
            ids.append(int(item["QuestionId"]))
        except (KeyError, TypeError, ValueError):
            continue
    return ids


def show_question_content(item: dict[str, Any]) -> None:
    prompt = item.get("prompt")
    if prompt:
        st.markdown(str(prompt))
    options = item.get("options")
    if isinstance(options, list):
        for option in sorted(options, key=lambda x: x.get("value", 0)):
            st.write(f"{option.get('value')}. {option.get('text', '')}")


def add_response_row(
    *,
    key: str,
    rows_key: str,
    ids: list[int],
    response_type: str,
) -> None:
    if not ids:
        st.warning("Belum ada QuestionId yang tersedia dari API.")
        return

    with st.form(f"{key}_add_form"):
        student_id = st.text_input("Student ID", key=f"{key}_student")
        qid = st.selectbox("Question ID", ids, key=f"{key}_question")
        selected: str | None
        if response_type == "choice":
            selected = st.selectbox(
                "Jawaban",
                ["A", "B", "C", "D", "Lewati"],
                key=f"{key}_answer",
            )
        else:
            selected = st.selectbox(
                "Hasil jawaban",
                ["Benar", "Salah", "Tidak dijawab"],
                key=f"{key}_correctness",
            )
        add = st.form_submit_button("Tambah jawaban")
    if add:
        clean_student = student_id.strip()
        if not clean_student:
            st.error("Student ID wajib diisi.")
        else:
            rows = st.session_state.setdefault(rows_key, [])
            if any(int(row["question_id"]) == int(qid) for row in rows):
                st.warning("Question ID ini sudah ada. Hapus baris lama sebelum menambahkannya lagi.")
            else:
                if response_type == "choice":
                    value = None if selected == "Lewati" else ["A", "B", "C", "D"].index(selected) + 1
                    rows.append(
                        {"student_id": clean_student, "question_id": int(qid), "answer_value": value}
                    )
                else:
                    value = None if selected == "Tidak dijawab" else int(selected == "Benar")
                    rows.append(
                        {"student_id": clean_student, "question_id": int(qid), "response": value}
                    )
                st.rerun()


def show_response_rows(rows_key: str, response_type: str) -> list[dict[str, Any]]:
    rows = st.session_state.setdefault(rows_key, [])
    if not rows:
        st.info("Belum ada jawaban yang dimasukkan.")
        return rows

    if response_type == "choice":
        view = [
            {
                "Student ID": row["student_id"],
                "Question ID": row["question_id"],
                "Jawaban": (
                    "Lewati"
                    if row["answer_value"] is None
                    else ["A", "B", "C", "D"][int(row["answer_value"]) - 1]
                ),
            }
            for row in rows
        ]
    else:
        view = [
            {
                "Student ID": row["student_id"],
                "Question ID": row["question_id"],
                "Respons": (
                    "Tidak dijawab"
                    if row["response"] is None
                    else ("Benar" if row["response"] == 1 else "Salah")
                ),
            }
            for row in rows
        ]
    st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)
    col1, col2 = st.columns(2)
    if col1.button("Hapus semua jawaban", key=f"{rows_key}_clear"):
        st.session_state[rows_key] = []
        st.rerun()
    if col2.button("Hapus jawaban terakhir", key=f"{rows_key}_pop", disabled=not rows):
        rows.pop()
        st.rerun()
    return rows


require_login()

st.sidebar.title("EduBridge")
st.sidebar.caption("Backend testing console")
st.sidebar.caption(f"API: {API_BASE_URL}")
if st.sidebar.button("Keluar"):
    st.session_state["authenticated"] = False
    st.rerun()

page = st.sidebar.radio(
    "Menu",
    [
        "Dashboard",
        "Question Bank",
        "Assessment Submit",
        "Direct Diagnosis",
        "Narrative",
        "Model Management",
    ],
)

if not API_KEY:
    st.sidebar.error("EDUBRIDGE_API_KEY belum diatur pada container dashboard.")

st.title("EduBridge Backend Console")
st.caption("UI pengujian untuk FastAPI dan model P-DINA. Request API berjalan dari server Streamlit, bukan browser.")

if page == "Dashboard":
    st.header("Status backend")
    if st.button("Refresh status", type="primary"):
        st.rerun()
    try:
        health = api_request("GET", "/health")
        cols = st.columns(4)
        cols[0].metric("API status", str(health.get("status", "unknown")).upper())
        cols[1].metric("Versi API", health.get("version", "-"))
        cols[2].metric("Model ready", "Ya" if health.get("model_ready") else "Tidak")
        cols[3].metric("Checkpoint hilang", len(health.get("missing_checkpoint_files", [])))
        if health.get("missing_checkpoint_files"):
            st.warning("Checkpoint belum lengkap: " + ", ".join(health["missing_checkpoint_files"]))
    except ApiError as exc:
        show_api_error(exc)

    st.divider()
    st.subheader("Informasi model")
    try:
        info = api_request("GET", "/api/v1/model")
        cols = st.columns(4)
        cols[0].metric("Engine", info.get("engine", "-"))
        cols[1].metric("Model", info.get("model", "-"))
        cols[2].metric("Soal model", info.get("questions", 0))
        cols[3].metric("Konsep target", info.get("target_concepts", 0))
        st.json(info)
    except ApiError as exc:
        show_api_error(exc)

elif page == "Question Bank":
    st.header("Question bank")
    st.caption("Menampilkan metadata soal yang diizinkan oleh model P-DINA.")
    try:
        bank = api_request("GET", "/api/v1/assessment/bank")
        fixed = api_request("GET", "/api/v1/assessment/fixed")
        items = bank.get("items", [])
        st.metric("Jumlah soal di bank", bank.get("count", len(items)))
        st.metric("Jumlah soal fixed form", fixed.get("count", len(fixed.get("items", []))))
        if not fixed.get("question_content_available", False):
            st.info(
                "Konten teks dan opsi soal belum tersedia. API tetap dapat menampilkan metadata "
                "dan menerima pengujian berdasarkan QuestionId. Pasang content pack yang memiliki izin."
            )
        if items:
            st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)
            ids = question_ids(items)
            selected_id = st.selectbox("Lihat gambar soal (bila tersedia)", ids)
            if st.button("Ambil gambar soal"):
                try:
                    st.image(api_image(selected_id), caption=f"QuestionId {selected_id}")
                except ApiError as exc:
                    st.warning(str(exc))
        else:
            st.warning("API mengembalikan bank soal kosong.")
    except ApiError as exc:
        show_api_error(exc)

elif page == "Assessment Submit":
    st.header("Submit assessment A–D")
    st.caption("Jawaban pilihan dikirim ke server. Kunci jawaban tidak dikirim dari dashboard.")
    try:
        fixed = api_request("GET", "/api/v1/assessment/fixed")
        items = fixed.get("items", [])
        ids = question_ids(items)
        if not fixed.get("question_content_available", False):
            st.info("Mode metadata-only: prompt dan opsi asli tidak tersedia. Anda masih dapat menguji alur submit menggunakan QuestionId.")
        if ids:
            selected_id = st.selectbox("Preview QuestionId", ids)
            item = next((x for x in items if int(x.get("QuestionId", -1)) == int(selected_id)), {})
            show_question_content(item)
            add_response_row(
                key="assessment",
                rows_key="assessment_rows",
                ids=ids,
                response_type="choice",
            )
            rows = show_response_rows("assessment_rows", "choice")
            if rows and st.button("Kirim assessment ke API", type="primary"):
                student_ids = {row["student_id"] for row in rows}
                if len(student_ids) != 1:
                    st.error("Satu pengiriman hanya boleh berisi satu Student ID.")
                else:
                    payload = {
                        "student_id": rows[0]["student_id"],
                        "responses": [
                            {"question_id": row["question_id"], "answer_value": row["answer_value"]}
                            for row in rows
                        ],
                    }
                    try:
                        result = api_request("POST", "/api/v1/assessment/submit", payload)
                        st.success("Assessment berhasil diproses.")
                        st.json(result)
                    except ApiError as exc:
                        show_api_error(exc)
        else:
            st.warning("Fixed assessment belum menyediakan daftar QuestionId.")
    except ApiError as exc:
        show_api_error(exc)

elif page == "Direct Diagnosis":
    st.header("Direct diagnosis")
    st.caption("Uji endpoint /api/v1/diagnose dengan respons benar/salah.")
    try:
        items = get_question_items()
        ids = question_ids(items)
        add_response_row(
            key="diagnosis",
            rows_key="diagnosis_rows",
            ids=ids,
            response_type="correctness",
        )
        rows = show_response_rows("diagnosis_rows", "correctness")
        if rows and st.button("Jalankan diagnosis", type="primary"):
            student_ids = {row["student_id"] for row in rows}
            if len(student_ids) != 1:
                st.error("Satu diagnosis hanya boleh berisi satu Student ID.")
            else:
                payload = {
                    "student_id": rows[0]["student_id"],
                    "responses": [
                        {"QuestionId": row["question_id"], "response": row["response"]}
                        for row in rows
                    ],
                }
                try:
                    result = api_request("POST", "/api/v1/diagnose", payload)
                    st.success("Diagnosis berhasil.")
                    st.json(result)
                except ApiError as exc:
                    show_api_error(exc)
    except ApiError as exc:
        show_api_error(exc)

elif page == "Narrative":
    st.header("Narrative explanation")
    st.caption("Uji pembuatan penjelasan hasil diagnosis untuk siswa atau guru.")
    try:
        items = get_question_items()
        ids = question_ids(items)
        add_response_row(
            key="narrative",
            rows_key="narrative_rows",
            ids=ids,
            response_type="correctness",
        )
        rows = show_response_rows("narrative_rows", "correctness")
        audience = st.radio("Ditujukan kepada", ["student", "teacher"], horizontal=True)
        if rows and st.button("Buat narrative", type="primary"):
            student_ids = {row["student_id"] for row in rows}
            if len(student_ids) != 1:
                st.error("Satu permintaan narrative hanya boleh berisi satu Student ID.")
            else:
                payload = {
                    "student_id": rows[0]["student_id"],
                    "audience": audience,
                    "responses": [
                        {"QuestionId": row["question_id"], "response": row["response"]}
                        for row in rows
                    ],
                }
                try:
                    result = api_request("POST", "/api/v1/narrative", payload, timeout=90)
                    if result.get("text"):
                        st.markdown(result["text"])
                    st.caption(
                        "Fallback template digunakan."
                        if result.get("fallback")
                        else "Narrative berhasil dibuat oleh provider yang dikonfigurasi."
                    )
                    st.json(result.get("validation", {}))
                except ApiError as exc:
                    show_api_error(exc)
    except ApiError as exc:
        show_api_error(exc)

elif page == "Model Management":
    st.header("Model management")
    st.warning("Reload akan membuang service cache di API dan memuat ulang checkpoint model.")
    confirmed = st.checkbox("Saya paham bahwa reload dapat membuat request diagnosis gagal sementara.")
    if st.button("Reload model", type="primary", disabled=not confirmed):
        try:
            result = api_request("POST", "/api/v1/admin/reload")
            st.success("Model berhasil dimuat ulang.")
            st.json(result)
        except ApiError as exc:
            show_api_error(exc)

st.divider()
st.caption("EduBridge Backend Console · Internal testing tool · Jangan publikasikan dashboard tanpa proteksi akses.")
