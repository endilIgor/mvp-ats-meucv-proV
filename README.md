# MeuCV.pro ATS

Backend Python para o MVP MeuCV.pro ATS, baseado no design em `project/MeuCV ATS.dc.html`.

## Stack

- FastAPI
- SQLAlchemy
- PostgreSQL via Docker Compose
- Cache em memória com TTL para análise de aderência à vaga
- Testes com pytest seguindo TDD

## Rodar localmente

```bash
uv run --extra test pytest -q
```

## Rodar com Docker + Postgres

```bash
docker compose up --build
```

Serviços:

- Frontend responsivo: http://localhost:8001/
- API docs: http://localhost:8001/docs
- Healthcheck: http://localhost:8001/api/health

## Variáveis

A API usa prefixo `MEUCV_`:

- `MEUCV_DATABASE_URL` — padrão Docker: `postgresql+psycopg://meucv:meucv@postgres:5432/meucv`
- `MEUCV_CACHE_TTL_SECONDS` — padrão: `300`
- `MEUCV_AUTH_TOKEN_TTL_SECONDS` — padrão: 7 dias

## Endpoints principais

- `POST /api/auth/signup`
- `POST /api/auth/login`
- `GET /api/resumes`
- `POST /api/resumes`
- `PATCH /api/resumes/{resume_id}`
- `POST /api/resumes/{resume_id}/ats/analyze`
- `POST /api/resumes/{resume_id}/ats/fix`
- `POST /api/resumes/{resume_id}/tailor`
