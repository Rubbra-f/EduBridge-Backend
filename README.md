# EduBridge Backend

Standalone FastAPI service extracted from [Rubbra-f/EduBridge](https://github.com/Rubbra-f/EduBridge), with an optional Streamlit console for internal API testing.

The React/Vite frontend remains a separate application. Streamlit is an operations/testing UI, not a replacement for the student/teacher product UI.

## Components

- FastAPI application: `api_server.py`
- P-DINA implementation: `cdacdm/`
- Model configuration and metadata: `artifacts/model/`
- Assessment form metadata: `artifacts/assessment/`
- Internal Streamlit testing UI: `streamlit_app.py`
- Optional narrative generation through Gemini: configured by `GEMINI_API_KEY`

## Run with Docker Compose

```bash
git clone https://github.com/Rubbra-f/EduBridge-Backend.git
cd EduBridge-Backend
cp .env.example .env
```

Edit `.env` before starting:

- Set a unique, high-entropy `EDUBRIDGE_API_KEY`.
- Set a separate strong `DASHBOARD_PASSWORD`. Do not reuse the API key.
- Add `GEMINI_API_KEY` only when narrative generation is needed.

Start both services:

```bash
docker compose up -d --build
docker compose logs -f api dashboard
```

The API is bound to `127.0.0.1:8000`; the Streamlit dashboard is bound to `127.0.0.1:8501`.

- API health: `http://127.0.0.1:8000/health`
- Streamlit dashboard: `http://127.0.0.1:8501`

Open the dashboard and sign in with `DASHBOARD_PASSWORD`. The dashboard calls FastAPI over Docker's private service network at `http://api:8000`. The API key remains on the Streamlit server and is not sent to browser JavaScript.

## Streamlit dashboard features

- **Dashboard:** API health, model readiness, model version, question/concept counts.
- **Question Bank:** supported item metadata, fixed-form count, and optional image retrieval.
- **Assessment Submit:** enter A/B/C/D choices and submit them for server-side scoring and P-DINA diagnosis.
- **Direct Diagnosis:** send correct/incorrect/omitted responses to the diagnosis endpoint.
- **Narrative:** request a student- or teacher-oriented explanation from the narrative endpoint.
- **Model Management:** inspect all registered checkpoints, choose a persistent default model, and reload one or all model services.

The dashboard only exposes capabilities that currently exist in the FastAPI API. Adaptive next-question selection, class-wide learning-gap analysis, intervention-plan management, and pre-test/post-test comparison are not yet implemented as backend endpoints.

The fixed assessment currently operates in metadata-only mode unless a separately authorized content pack is mounted. The dashboard can still test the API flow by QuestionId, but cannot display the original prompt/options without that content pack.

## VPS deployment

1. Install Docker Engine and the Docker Compose plugin on the VPS.
2. Clone this repository and create `.env` from `.env.example`.
3. Set strong, separate values for `EDUBRIDGE_API_KEY` and `DASHBOARD_PASSWORD`.
4. Run `docker compose up -d --build`.
5. Keep both ports bound to localhost. Put Caddy/Nginx in front of the API and expose HTTPS publicly.
6. Prefer exposing the Streamlit dashboard only through a VPN or an IP-restricted reverse-proxy route with HTTPS. The dashboard password is an additional access gate, not a substitute for network restrictions.
7. Configure the React frontend's server-side proxy to forward requests to the API and attach `X-API-Key`. Do not expose the API key in a browser bundle.
8. Restrict `EDUBRIDGE_CORS_ORIGINS` to exact trusted origins when browser access is intentionally enabled.

## API

- `GET /health` — public health/model-artifact readiness check
- `GET /api/v1/models` — list registered models and checkpoint readiness
- `GET /api/v1/models/active` — inspect the configured default model
- `PUT /api/v1/admin/models/default` — set the persistent default model (admin/API key)
- `GET /api/v1/model` — model information for the default model (or `?model_id=...`)
- `GET /api/v1/assessment/bank` — supported assessment metadata
- `GET /api/v1/assessment/fixed` — fixed-form metadata and optional authorized question content
- `GET /api/v1/assessment/images/{question_id}` — optional image asset
- `POST /api/v1/assessment/submit` — scores A-D choices server-side and runs diagnosis
- `POST /api/v1/diagnose` — runs diagnosis from binary response values; optional body `model_id` selects a model for that request
- `POST /api/v1/admin/reload?model_id=eedi_pdina` — reload one model; omit the query to reload all registered models
- `POST /api/v1/narrative` — generates an explanation
- `POST /api/v1/admin/reload` — reloads model artifacts

All `/api/v1/*` routes require the `X-API-Key` header.

## Assessment content and image assets

Question text/options are not bundled as a deployable content pack. The loader requires a separately authorized pack at `EEDI_CONTENT_PATH`, with `license_confirmed: true` and a non-empty `authorization_reference`. Without it, the fixed assessment endpoint returns metadata-only mode.

The original repository's OCR draft and question images are intentionally not included in this extraction. Add them to `content/` only after confirming that the intended use and public redistribution are authorized. Image requests return 404 until the corresponding `content/images/{question_id}.jpg` assets are installed.

## Security and data-integrity note

This public repository includes `artifacts/model/item_bank.csv`, which the server uses for answer-key-based scoring. Anyone can download files from a public repository. Do not rely on this packaging for confidential/high-stakes examinations. For production use where answer keys must remain secret, move answer-key-bearing artifacts to private storage or a private repository and mount them into the container at deployment time; alternatively make this repository private.

The dashboard is intended for trusted internal testing. Do not expose it to the public internet without HTTPS, network restrictions (VPN/IP allowlist), and a strong unique dashboard password.

## Configuration

See `.env.example`. The model artifact directory defaults to `/app/artifacts`.

## Source

Backend code and artifacts were extracted from the `backend/` directory of the EduBridge project. Frontend code and frontend-specific build configuration are not included.

No license file is included. Confirm the rights for the model/data/content assets before redistribution or commercial use.


## Local demo analytics and Gemini reports

Set `EDUBRIDGE_DEMO_MODE=true` in `.env` to expose demo endpoints. It defaults to disabled;
keep it disabled in production. The demo analytics module stores synthetic data in SQLite at
`/app/data/edubridge_demo.sqlite3` (host path `./data/edubridge_demo.sqlite3`).
The `./data` directory is git-ignored. No PostgreSQL service is required.

After starting Compose, use the Streamlit dashboard:
- **Demo Data**: seed synthetic classes, students, pre/post sessions and response rows.
- **Analytics**: inspect aggregate accuracy, P-DINA class diagnosis, learning gaps, recommendations and pre/post comparisons.
- **Gemini Reports**: generate an Indonesian teacher report from backend-computed facts.

Set `GEMINI_API_KEY` in `.env` to enable Gemini reports. `GEMINI_MODEL` defaults to
`gemini-2.5-flash`. Gemini receives compact aggregated diagnostic facts, not raw
answer-level records or student names. Reports are marked as demo data.

Demo endpoints:
- `POST /api/v1/admin/demo/seed`
- `DELETE /api/v1/admin/demo/reset`
- `GET /api/v1/analytics/overview`
- `GET /api/v1/analytics/class/{class_id}?period=post`
- `GET /api/v1/analytics/student/{student_id}?period=post`
- `GET /api/v1/analytics/prepost/{class_id}`
- `POST /api/v1/analytics/generate-report`

All endpoints require `X-API-Key`. Synthetic responses use question IDs from the
P-DINA fixed assessment form. This is separate from local EduBridge image assets:
matching numeric image filenames do not prove item equivalence, answer-key validity,
or concept mapping. Demo data is for software testing only, not evidence of
intervention effectiveness.

## Multiple model checkpoints

The API includes a model registry with two initial entries:

- `eedi_pdina`: default model, loaded from `/app/artifacts`.
- `calculus_pdina`: optional demo model, loaded from `/app/artifacts_calculus`; its documented dataset is synthetic and must not be used as validated student evidence.

The calculus checkpoint is **not bundled in this backend repository**. To make it available, place the complete `artifacts_calculus/` folder beside `compose.yaml` on the host, including its `model/` and (where used) `assessment/` subfolders. Compose mounts that folder read-only. The dashboard lists unavailable models but prevents selecting a model until all required checkpoint files are present.

The default model is persisted in the SQLite database configured by `EDUBRIDGE_DB_PATH`, so it survives container restarts. Set `EDUBRIDGE_DEFAULT_MODEL=eedi_pdina` for the initial default. The administrator can change it in Streamlit **Model Management**.

For a one-off model choice, send `model_id` in a diagnosis or assessment request body:

```json
{
  "model_id": "eedi_pdina",
  "student_id": "S001",
  "responses": [
    {"QuestionId": 123, "response": 1}
  ]
}
```

If `model_id` is omitted, the API uses the saved default. The model identifier is returned in diagnosis metadata. Each model has its own item IDs and answer-key artifacts; never send question IDs from one model to another.
