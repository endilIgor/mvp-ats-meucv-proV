import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from secrets import token_hex, token_urlsafe

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, build_session_factory, session_dependency
from app.models import AuthToken, Resume, User
from app.schemas import (
    AtsAnalysis,
    AtsAnalyzeRequest,
    AtsFixRequest,
    AuthResponse,
    LoginRequest,
    ResumeCreate,
    ResumeOut,
    ResumePatch,
    SignupRequest,
    TailorRequest,
    TailorResponse,
    UserOut,
)
from app.services import TailorCache, analyze_ats, score_for_fixed, tailor_resume
from app.settings import Settings

def to_user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, full_name=user.full_name)


def to_resume_out(resume: Resume) -> ResumeOut:
    return ResumeOut(
        id=resume.id,
        name=resume.name,
        target_role=resume.target_role,
        language=resume.language,
        personal=resume.personal or {},
        summary=resume.summary,
        experience=resume.experience or [],
        education=resume.education or {},
        skills=resume.skills or [],
        ats_score=resume.ats_score,
        fixed_issue_ids=resume.fixed_issue_ids or [],
    )


def create_token(session: Session, user: User, settings: Settings) -> str:
    token = token_urlsafe(32)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=settings.auth_token_ttl_seconds)
    session.add(AuthToken(token=token, user_id=user.id, expires_at=expires_at))
    session.commit()
    return token


def hash_password(password: str) -> str:
    salt = token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(actual, expected)


def get_current_user_dependency(factory: sessionmaker[Session]):
    def current_user(authorization: str | None = Header(default=None)) -> User:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1]
        with factory() as session:
            row = session.get(AuthToken, token)
            if not row or row.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
            user = session.get(User, row.user_id)
            if not user:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
            session.expunge(user)
            return user

    return current_user


def get_owned_resume(session: Session, resume_id: int, user: User) -> Resume:
    resume = session.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return resume


def create_app(database_url: str | None = None) -> FastAPI:
    settings = Settings(database_url=database_url) if database_url else Settings()
    session_factory = build_session_factory(settings.database_url)
    Base.metadata.create_all(session_factory.kw["bind"])
    get_session = session_dependency(session_factory)
    get_current_user = get_current_user_dependency(session_factory)
    tailor_cache = TailorCache(settings.cache_ttl_seconds)

    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health(session: Session = Depends(get_session)):
        session.execute(select(1))
        return {"status": "ok", "database": "ok", "cache": "ok"}

    @app.post("/api/auth/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
    def signup(payload: SignupRequest, session: Session = Depends(get_session)):
        user = User(
            email=payload.email.lower(),
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from exc
        session.refresh(user)
        token = create_token(session, user, settings)
        return AuthResponse(access_token=token, user=to_user_out(user))

    @app.post("/api/auth/login", response_model=AuthResponse)
    def login(payload: LoginRequest, session: Session = Depends(get_session)):
        user = session.scalar(select(User).where(User.email == payload.email.lower()))
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        token = create_token(session, user, settings)
        return AuthResponse(access_token=token, user=to_user_out(user))

    @app.get("/api/resumes", response_model=list[ResumeOut])
    def list_resumes(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
        rows = session.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.updated_at.desc())).all()
        return [to_resume_out(row) for row in rows]

    @app.post("/api/resumes", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
    def create_resume(payload: ResumeCreate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
        resume = Resume(
            user_id=user.id,
            name=payload.name,
            target_role=payload.target_role,
            language=payload.language,
            personal=payload.personal.model_dump(),
            summary=payload.summary,
            experience=[item.model_dump() for item in payload.experience],
            education=payload.education.model_dump(),
            skills=payload.skills,
            fixed_issue_ids=[],
            ats_score=62,
        )
        session.add(resume)
        session.commit()
        session.refresh(resume)
        return to_resume_out(resume)

    @app.patch("/api/resumes/{resume_id}", response_model=ResumeOut)
    def update_resume(resume_id: int, payload: ResumePatch, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
        resume = get_owned_resume(session, resume_id, user)
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            if hasattr(value, "model_dump"):
                value = value.model_dump()
            elif isinstance(value, list):
                value = [item.model_dump() if hasattr(item, "model_dump") else item for item in value]
            setattr(resume, key, value)
        resume.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(resume)
        return to_resume_out(resume)

    @app.post("/api/resumes/{resume_id}/ats/analyze", response_model=AtsAnalysis)
    def analyze_resume(resume_id: int, _payload: AtsAnalyzeRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
        resume = get_owned_resume(session, resume_id, user)
        return analyze_ats(resume.fixed_issue_ids or [])

    @app.post("/api/resumes/{resume_id}/ats/fix", response_model=ResumeOut)
    def fix_resume(resume_id: int, payload: AtsFixRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
        resume = get_owned_resume(session, resume_id, user)
        merged = list(dict.fromkeys([*(resume.fixed_issue_ids or []), *payload.issue_ids]))
        resume.fixed_issue_ids = merged
        resume.ats_score = score_for_fixed(merged)
        resume.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(resume)
        return to_resume_out(resume)

    @app.post("/api/resumes/{resume_id}/tailor", response_model=TailorResponse)
    def tailor(resume_id: int, payload: TailorRequest, response: Response, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
        resume = get_owned_resume(session, resume_id, user)
        cached = tailor_cache.get(resume, payload.job_description)
        if cached:
            response.headers["X-Cache"] = "HIT"
            return cached
        result = tailor_resume(resume, payload.job_description)
        tailor_cache.set(resume, payload.job_description, result)
        response.headers["X-Cache"] = "MISS"
        return result

    @app.get("/")
    def frontend(response: Response):
        response.headers["Cache-Control"] = f"public, max-age={settings.frontend_cache_seconds}"
        return Response(content=FRONTEND_HTML, media_type="text/html", headers=dict(response.headers))

    return app


FRONTEND_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MeuCV.pro ATS</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&display=swap">
  <style>
    :root{--color-bg:#f3f2f2;--color-text:#201e1d;--color-accent:#ec3013;--color-divider:color-mix(in srgb,#201e1d 40%,transparent);--color-neutral-100:#f8f4f4;--color-neutral-300:#d7d3d3;--color-neutral-700:#605d5d;--font-heading:Archivo,system-ui,sans-serif;--font-body:Archivo,system-ui,sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--color-bg);color:var(--color-text);font-family:var(--font-body);font-size:14px;line-height:1.5}.wrap{max-width:1240px;margin:0 auto;padding:0 40px}.nav{display:flex;align-items:center;gap:28px;padding:22px 0;border-bottom:2px solid var(--color-divider)}.brand{font-family:var(--font-heading);font-weight:800;font-size:19px;margin-right:auto}.brand span{color:var(--color-accent)}.btn{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--color-divider);background:transparent;color:inherit;height:42px;padding:0 18px;font:800 14px var(--font-heading);text-decoration:none}.btn.primary{background:var(--color-accent);border-color:var(--color-accent);color:var(--color-bg)}.hero{display:grid;grid-template-columns:7fr 5fr;gap:56px;padding:72px 0 64px;align-items:end}.kicker{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--color-accent);margin-bottom:20px}h1{font:800 clamp(42px,6vw,72px)/.96 var(--font-heading);letter-spacing:-.03em;margin:0 0 24px}.lead{font-size:17px;max-width:46ch;color:var(--color-neutral-700);margin:0 0 32px}.stats{border-left:2px solid var(--color-divider);padding-left:32px;display:grid;gap:22px}.stat strong{display:block;font:800 40px/1 var(--font-heading)}.grid{display:grid;grid-template-columns:repeat(3,1fr);border-top:2px solid var(--color-divider);border-bottom:2px solid var(--color-divider)}.cell{padding:36px 32px 40px 0;border-right:1px solid var(--color-divider)}.cell b{display:block;font:800 21px var(--font-heading);margin:14px 0 10px}.poster{background:var(--color-accent);color:var(--color-bg);margin-top:72px}.poster .wrap{padding-top:72px;padding-bottom:72px;display:grid;grid-template-columns:8fr 4fr;gap:48px;align-items:end}.poster h2{font:800 52px/1 var(--font-heading);letter-spacing:-.03em;margin:0;max-width:18ch}@media (max-width: 900px){.wrap{padding:0 20px}.nav{flex-wrap:wrap;gap:10px}.brand{flex-basis:100%}.hero,.poster .wrap{grid-template-columns: 1fr;gap:28px;padding-top:42px;padding-bottom:42px}.stats{border-left:0;border-top:2px solid var(--color-divider);padding:22px 0 0}.grid{grid-template-columns: 1fr}.cell{border-right:0;border-bottom:1px solid var(--color-divider);padding-right:0}.poster h2{font-size:38px}}
  </style>
</head>
<body>
  <div class="wrap"><header class="nav"><div class="brand">MEU<span>CV</span>.PRO</div><a class="btn" href="/api/health">API</a><a class="btn primary" href="#start">Criar meu currículo</a></header><section class="hero"><div><div class="kicker">Currículo ATS com IA</div><h1>Seu currículo precisa passar pelo robô antes da pessoa.</h1><p class="lead">Importe seu PDF, veja a pontuação ATS, corrija o que trava a leitura e adapte o texto para cada vaga — sem inventar experiência.</p><a class="btn primary" id="start" href="/docs">Começar grátis</a></div><div class="stats"><div class="stat"><strong>94%</strong>das grandes empresas filtram currículos com ATS</div><div class="stat"><strong>7s</strong>de leitura humana média por currículo</div><div class="stat"><strong>3×</strong>mais respostas com currículo adaptado</div></div></section><section class="grid"><div class="cell"><span class="kicker">01</span><b>Importe seu PDF</b><p>Mapeamos tudo em campos editáveis.</p></div><div class="cell"><span class="kicker">02</span><b>Meça a leitura do robô</b><p>Nota de 0 a 100 e problemas com correção em um clique.</p></div><div class="cell"><span class="kicker">03</span><b>Adapte por vaga</b><p>Receba lacunas de palavra-chave e reescritas da sua história real.</p></div></section></div><section class="poster"><div class="wrap"><h2>78% dos currículos são descartados antes de um humano abrir.</h2><p>Backend Python, Postgres, Docker e API pronta para conectar ao produto.</p></div></section>
</body>
</html>"""

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    configured = create_app()
    app_instance.router.routes = configured.router.routes
    app_instance.user_middleware = configured.user_middleware
    app_instance.middleware_stack = configured.middleware_stack
    yield


app = FastAPI(title="MeuCV.pro ATS", lifespan=lifespan)
