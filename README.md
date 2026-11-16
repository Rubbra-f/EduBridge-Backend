# EduBridge Backend

Standalone FastAPI service extracted from [Rubbra-f/EduBridge](https://github.com/Rubbra-f/EduBridge).

It serves the P-DINA learning-diagnostics engine independently of the React/Vite frontend.

## Components

- FastAPI application: `api_server.py`
- P-DINA implementation: `cdacdm/`
- Model configuration and metadata: `artifacts/model/`
- Assessment form metadata: `artifacts/assessment/`
- Optional narrative generation through Gemini: configured by `GEMINI_API_KEY`

## Run with Docker Compose

```bash
git clone https://github.com/Rubbra-f/EduBridge-Backend.git
cd EduBridge-Backend
cp .env.example .env
```

Edit `.env` and set a strong `EDUBRIDGE_API_KEY`. Add `GEMINI_API_KEY` only when narrative generation is needed.

```bash
docker compose up -d --build
docker compose logs -f api
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Authenticated API example:

```bash
curl -H "X-API-Key: $EDUBRIDGE_API_KEY" \
  http://127.0.0.1:8000/api/v1/model
```

The `.env` file is intentionally ignored by Git. Never place API keys in frontend JavaScript or commit them to this public repository.

## VPS deployment

1. Install Docker Engine and the Docker Compose plugin on the VPS.
2. Clone this repository and create `.env` from `.env.example`.
3. Set a unique, high-entropy `EDUBRIDGE_API_KEY`.
4. Run `docker compose up -d --build`.
5. Put Caddy/Nginx in front of the API and expose HTTPS publicly. The Compose port is bound to `127.0.0.1` by default.
6. Configure the frontend's server-side proxy to forward requests to this API and attach `X-API-Key`. Do not expose the API key in a browser bundle.
7. Restrict `EDUBRIDGE_CORS_ORIGINS` to exact trusted origins when browser access is intentionally enabled.

## API

- `GET /health` — public health/model-artifact readiness check
- `GET /api/v1/model` — model information
- `GET /api/v1/assessment/bank` — supported assessment metadata
- `GET /api/v1/assessment/fixed` — fixed-form metadata and optional authorized question content
- `GET /api/v1/assessment/images/{question_id}` — optional image asset
- `POST /api/v1/assessment/submit` — scores A-D choices server-side and runs diagnosis
- `POST /api/v1/diagnose` — runs diagnosis from binary response values
- `POST /api/v1/narrative` — generates an explanation
- `POST /api/v1/admin/reload` — reloads model artifacts

All `/api/v1/*` routes require the `X-API-Key` header.

## Assessment content and image assets

Question text/options are not bundled as a deployable content pack. The loader requires a separately authorized pack at `EEDI_CONTENT_PATH`, with `license_confirmed: true` and a non-empty `authorization_reference`. Without it, the fixed assessment endpoint returns metadata-only mode.

The original repository's OCR draft and question images are intentionally not included in this extraction. Add them to `content/` only after confirming that the intended use and public redistribution are authorized. Image requests return 404 until the corresponding `content/images/{question_id}.jpg` assets are installed.

## Security and data-integrity note

This public repository includes `artifacts/model/item_bank.csv`, which the server uses for answer-key-based scoring. Anyone can download files from a public repository. Do not rely on this packaging for confidential/high-stakes examinations. For production use where answer keys must remain secret, move answer-key-bearing artifacts to private storage or a private repository and mount them into the container at deployment time; alternatively make this repository private.

## Configuration

See `.env.example`. The model artifact directory defaults to `/app/artifacts`.

## Source

Backend code and artifacts were extracted from the `backend/` directory of the EduBridge project. Frontend code and frontend-specific build configuration are not included.

No license file is included. Confirm the rights for the model/data/content assets before redistribution or commercial use.
