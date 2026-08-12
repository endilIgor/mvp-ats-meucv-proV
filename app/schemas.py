from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class Personal(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""


class ExperienceItem(BaseModel):
    role: str = ""
    company: str = ""
    period: str = ""
    bullets: list[str] = Field(default_factory=list)


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    period: str = ""


class ResumeCreate(BaseModel):
    name: str
    target_role: str
    language: str = "pt"
    personal: Personal = Field(default_factory=Personal)
    summary: str = ""
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: Education = Field(default_factory=Education)
    skills: list[str] = Field(default_factory=list)


class ResumePatch(BaseModel):
    name: str | None = None
    target_role: str | None = None
    language: str | None = None
    personal: Personal | None = None
    summary: str | None = None
    experience: list[ExperienceItem] | None = None
    education: Education | None = None
    skills: list[str] | None = None


class ResumeOut(ResumeCreate):
    id: int
    ats_score: int
    fixed_issue_ids: list[str] = Field(default_factory=list)


class AtsAnalyzeRequest(BaseModel):
    job_description: str = ""


class AtsIssue(BaseModel):
    id: str
    pts: int
    severity: str
    title: str
    hint: str
    fixed: bool


class AtsAnalysis(BaseModel):
    score: int
    verdict: str
    issues: list[AtsIssue]


class AtsFixRequest(BaseModel):
    issue_ids: list[str]


class TailorRequest(BaseModel):
    job_description: str = Field(min_length=1)


class TailorResponse(BaseModel):
    fit: int
    keywords_found: list[str]
    keywords_missing: list[str]
    suggestions: list[dict[str, str]]
