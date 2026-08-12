import hashlib
import re
from dataclasses import dataclass

from cachetools import TTLCache


ISSUES = [
    {
        "id": "i1",
        "pts": 8,
        "severity": "high",
        "title": "Cabeçalho dentro de uma tabela",
        "hint": "Converta o cabeçalho para texto corrido para parsers ATS.",
    },
    {
        "id": "i2",
        "pts": 7,
        "severity": "high",
        "title": "Poucas palavras-chave da vaga",
        "hint": "Inclua termos relevantes da descrição sem inventar experiência.",
    },
    {
        "id": "i3",
        "pts": 6,
        "severity": "medium",
        "title": "Bullets sem resultado numérico",
        "hint": "Transforme tarefas em impacto mensurável.",
    },
    {
        "id": "i4",
        "pts": 5,
        "severity": "medium",
        "title": "Datas em formatos diferentes",
        "hint": "Padronize datas em todas as seções.",
    },
    {
        "id": "i5",
        "pts": 4,
        "severity": "low",
        "title": "Ícones no lugar de rótulos",
        "hint": "Use rótulos textuais para telefone, e-mail e localização.",
    },
]

KEYWORDS = ["SQL", "Looker", "SLA", "Power BI", "OKR", "supply chain", "custo por pedido", "stakeholder management"]

SUGGESTIONS = [
    {"was": "Responsável pelo time de suporte.", "text": "Liderei um time de 6 analistas de suporte, reduzindo o tempo médio de resposta de 9h para 2h."},
    {"was": "Ajudei na migração de sistema.", "text": "Coordenei a migração de 40 mil registros para o novo CRM sem downtime."},
    {"was": "Fiz relatórios mensais.", "text": "Automatizei o relatório mensal de operação em SQL e Looker, devolvendo ~12h/mês ao time."},
]


def score_for_fixed(fixed_issue_ids: list[str]) -> int:
    fixed = set(fixed_issue_ids)
    return min(100, 62 + sum(issue["pts"] for issue in ISSUES if issue["id"] in fixed))


def verdict(score: int) -> str:
    if score < 70:
        return "Abaixo do corte da maioria dos ATS. Corrija os itens de risco alto."
    if score < 90:
        return "Passa na maioria dos filtros, mas perde pontos em palavras-chave."
    return "Pronto para enviar. Legível por qualquer parser comum."


def analyze_ats(fixed_issue_ids: list[str]) -> dict:
    fixed = set(fixed_issue_ids)
    score = score_for_fixed(list(fixed))
    return {
        "score": score,
        "verdict": verdict(score),
        "issues": [{**issue, "fixed": issue["id"] in fixed} for issue in ISSUES],
    }


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def resume_text(resume) -> str:
    chunks = [resume.target_role, resume.summary, " ".join(resume.skills or [])]
    for job in resume.experience or []:
        chunks.extend([job.get("role", ""), job.get("company", ""), " ".join(job.get("bullets", []))])
    return "\n".join(chunks)


@dataclass
class TailorCache:
    ttl_seconds: int

    def __post_init__(self):
        self.cache = TTLCache(maxsize=512, ttl=self.ttl_seconds)

    def key(self, resume, job_description: str) -> str:
        source = f"{resume.id}:{resume.updated_at}:{resume_text(resume)}:{job_description}"
        return hashlib.sha256(source.encode()).hexdigest()

    def get(self, resume, job_description: str):
        return self.cache.get(self.key(resume, job_description))

    def set(self, resume, job_description: str, value: dict):
        self.cache[self.key(resume, job_description)] = value


def tailor_resume(resume, job_description: str) -> dict:
    combined = normalize(resume_text(resume))
    job = normalize(job_description)
    relevant = [kw for kw in KEYWORDS if normalize(kw) in job]
    found = [kw for kw in relevant if normalize(kw) in combined]
    missing = [kw for kw in relevant if kw not in found]
    fit = min(100, 54 + len(found) * 7)
    return {
        "fit": fit,
        "keywords_found": found,
        "keywords_missing": missing,
        "suggestions": SUGGESTIONS,
    }
