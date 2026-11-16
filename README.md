# EduBridge Backend

Standalone FastAPI service extracted from [Rubbra-f/EduBridge](https://github.com/Rubbra-f/EduBridge), with an optional Streamlit console for internal API testing.

The React/Vite frontend remains a separate application. Streamlit is an operations/testing UI, not a replacement for the student/teacher product UI.

## Components

- FastAPI application: \`api_server.py\`
- P-DINA implementation: \`cdacdm/\`
- Model configuration and metadata: \`artifacts/model/\`
- Assessment form metadata: \`artifacts/assessment/\`
- Internal Streamlit testing UI: \`streamlit_app.py\`
- Optional narrative generation through Gemini: configured by \`GEMINI_API_KEY\`

## Run with Docker Compose

\`\`\`bash
git clone https://github.com/Rubbra-f/EduBridge-Backend.git
cd EduBridge-Backend
cp .env.example .env
\`\`\`

Edit \`.env\` before starting:

- Set a unique, high-entropy \`EDUBRIDGE_API_KEY\`.
- Set a separate strong \`DASHBOARD_PASSWORD\`. Do not reuse the API key.
- Add \`GEMINI_API_KEY\` only when narrative generation is needed.

Start both services:

\`\`\`bash
docker compose up -d --build
docker compose logs -f api dashboard
\`\`\`

The API is bound to \`127.0.0.1:8000\`; the Streamlit dashboard is bound to \`127.0.0.1:8501\`.

- API health: \`http://127.0.0.1:8000/health\`
- Streamlit dashboard: \`http://127.0.0.1:8501\`

Open the dashboard and sign in with \`DASHBOARD_PASSWORD\`. The dashboard calls FastAPI over Docker's private service network at \`http://api:8000\`. The API key remains on the Streamlit server and is not sent to browser JavaScript.

## Streamlit dashboard features

- **Dashboard:** API health, model readiness, model version, question/concept counts.
- **Question Bank:** supported item metadata, fixed-form count, and optional image retrieval.
- **Assessment Submit:** enter A/B/C/D choices and submit them for server-side scoring and P-DINA diagnosis.
- **Direct Diagnosis:** send correct/incorrect/omitted responses to the diagnosis endpoint.
- **Narrative:** request a student- or teacher-oriented explanation from the narrative endpoint.
- **Model Management:** manually reload the model checkpoint.

The dashboard only exposes capabilities that currently exist in the FastAPI API. Adaptive next-question selection, class-wide learning-gap analysis, intervention-plan management, and pre-test/post-test comparison are not yet implemented as backend endpoints.

The fixed assessment currently operates in metadata-only mode unless a separately authorized content pack is mounted. The dashboard can still test the API flow by QuestionId, but cannot display the original prompt/options without that content pack.

## VPS deployment

1. Install Docker Engine and the Docker Compose plugin on the VPS.
2. Clone this repository and create \`.env\` from \`.env.example\`.
3. Set strong, separate values for \`EDUBRIDGE_API_KEY\` and \`DASHBOARD_PASSWORD\`.
4. Run \`docker compose up -d --build\`.
5. Keep both ports bound to localhost. Put Caddy/Nginx in front of the API and expose HTTPS publicly.
6. Prefer exposing the Streamlit dashboard only through a VPN or an IP-restricted reverse-proxy route with HTTPS. The dashboard password is an additional access gate, not a substitute for network restrictions.
7. Configure the React frontend's server-side proxy to forward requests to the API and attach \`X-API-Key\`. Do not expose the API key in a browser bundle.
8. Restrict \`EDUBRIDGE_CORS_ORIGINS\` to exact trusted origins when browser access is intentionally enabled.

## API

- \`GET /health\` — public health/model-artifact readiness check
- \`GET /api/v1/model\` — model information
- \`GET /api/v1/assessment/bank\` — supported assessment metadata
- \`GET /api/v1/assessment/fixed\` — fixed-form metadata and optional authorized question content
- \`GET /api/v1/assessment/images/{question_id}\` — optional image asset
- \`POST /api/v1/assessment/submit\` — scores A-D choices server-side and runs diagnosis
- \`POST /api/v1/diagnose\` — runs diagnosis from binary response values
- \`POST /api/v1/narrative\` — generates an explanation
- \`POST /api/v1/admin/reload\` — reloads model artifacts

All \`/api/v1/*\` routes require the \`X-API-Key\` header.

## Assessment content and image assets

Question text/options are not bundled as a deployable content pack. The loader requires a separately authorized pack at \`EEDI_CONTENT_PATH\`, with \`license_confirmed: true\` and a non-empty \`authorization_reference\`. Without it, the fixed assessment endpoint returns metadata-only mode.

The original repository's OCR draft and question images are intentionally not included in this extraction. Add them to \`content/\` only after confirming that the intended use and public redistribution are authorized. Image requests return 404 until the corresponding \`content/images/{question_id}.jpg\` assets are installed.

## Security and data-integrity note

This public repository includes \`artifacts/model/item_bank.csv\`, which the server uses for answer-key-based scoring. Anyone can download files from a public repository. Do not rely on this packaging for confidential/high-stakes examinations. For production use where answer keys must remain secret, move answer-key-bearing artifacts to private storage or a private repository and mount them into the container at deployment time; alternatively make this repository private.

The dashboard is intended for trusted internal testing. Do not expose it to the public internet without HTTPS, network restrictions (VPN/IP allowlist), and a strong unique dashboard password.

## Configuration

See \`.env.example\`. The model artifact directory defaults to \`/app/artifacts\`.

## Source

Backend code and artifacts were extracted from the \`backend/\` directory of the EduBridge project. Frontend code and frontend-specific build configuration are not included.

No license file is included. Confirm the rights for the model/data/content assets before redistribution or commercial use.
