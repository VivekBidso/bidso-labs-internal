from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=200)


class PresignUploadRequest(BaseModel):
    track: str
    reference_number: str
    stage: str
    filename: str


class PublicPresignRequest(BaseModel):
    submission_id: str
    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = None


class ConfirmAttachmentsRequest(BaseModel):
    submission_id: str
    keys: list[str] = Field(min_length=1, max_length=20)


class ConfirmedAttachment(BaseModel):
    file_key: str
    original_filename: str | None
    size_bytes: int | None
    content_type: str | None


class ConfirmAttachmentsResponse(BaseModel):
    confirmed: list[ConfirmedAttachment]
    skipped_keys: list[str]


# --- Public intake ---------------------------------------------------------
# Field names mirror bidso-labs-public's own request payloads exactly (see
# src/pages/DesignerStage1.jsx, Manufacturer.jsx, Brand.jsx handleSubmit) —
# do not rename without updating the frontend to match.


class DesignerStage1Request(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = None
    city: str | None = None
    working_title: str | None = None
    finish_stage: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=5000)
    file_count: int = 0
    employer_relates: str = Field(min_length=1)
    made_on_employer_time: str = Field(min_length=1)
    can_get_release_letter: str = Field(min_length=1)
    has_co_contributors: bool
    co_contributor_names: str | None = None
    has_existing_ip: bool
    ip_number: str | None = None
    terms_version: str = Field(min_length=1)


class DesignerStage1Response(BaseModel):
    submission_id: str
    reference_number: str
    submitted_date: str
    screen_decision_by: str
    email: str


class ManufacturerRequest(BaseModel):
    legal_entity_name: str = Field(min_length=1, max_length=200)
    gst_number: str | None = None
    contact_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = None
    factory_location: str | None = None
    registered_in_india: bool = True
    product_name: str | None = None
    description: str | None = None
    photo_count: int = 0
    certifications: list[str] = []
    intent: str = Field(min_length=1)
    ex_works_price: str | None = None
    moq: str | None = None
    lead_time_days: str | None = None
    monthly_capacity: str | None = None
    terms_version: str = Field(min_length=1)


class ManufacturerResponse(BaseModel):
    submission_id: str
    reference_number: str | None
    submitted_date: str
    email: str


class BrandRequest(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = None
    looking_for: str | None = None


class BrandResponse(BaseModel):
    submitted_date: str
    email: str


class SubmissionStatusResponse(BaseModel):
    submitted_date: str
    current_stage: str
    decision_due_by: str | None = None
    rejection_message: str | None = None
    stage_dates: dict[str, str]


# --- Evaluation engine, Tier 0 (evaluation-engine-phased-plan.md) -----------


class ReadInput(BaseModel):
    tier: str = Field(pattern="^(TOP|MID|BOTTOM)$")
    evidence: str = Field(min_length=1, max_length=2000)


class KnockoutsInput(BaseModel):
    eligibility: str = Field(pattern="^(CLEAR|KO)$")
    warranty: str = Field(pattern="^(CLEAR|KO)$")
    employer_letter: str = Field(pattern="^(NOT_TRIGGERED|YES|NOT_SURE|NO)$")
    prior_art: str = Field(pattern="^(CLEAR|KO)$")
    registry: str = Field(pattern="^(NONE|VERIFIED|MISMATCH|FALSE)$")


class GatesInput(BaseModel):
    category_fit: str = Field(pattern="^(CORE|ADJACENT|OUTSIDE)$")
    process_fit: str = Field(pattern="^(CORE|MIXED|NON_CORE)$")


class FirstScreenRequest(BaseModel):
    knockouts: KnockoutsInput
    gates: GatesInput
    reads: dict[str, ReadInput]  # keys: differentiation, market_size, manufacturer_concentration, brand_fit


class FirstScreenResponse(BaseModel):
    submission_id: str
    rule_result: str
    status: str


class DetailedScreenRequest(BaseModel):
    bom_cost: float = Field(gt=0)
    target_price: float = Field(gt=0)
    scores: dict[str, int]  # 7 keys, 1-5 each — see evaluation_engine.SCORE_WEIGHTS
    rationale: str = Field(min_length=1, max_length=4000)


class DetailedScreenResponse(BaseModel):
    submission_id: str
    markup_pct: float
    markup_band: str
    composite: float
    zone: str
    status: str


class DecisionRequest(BaseModel):
    outcome: str = Field(pattern="^(ADVANCE|DECLINE)$")
    rationale: str = Field(min_length=1, max_length=4000)


class DecisionResponse(BaseModel):
    submission_id: str
    outcome: str
    status: str
