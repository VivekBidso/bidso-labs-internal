from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PresignUploadRequest(BaseModel):
    track: str
    reference_number: str
    stage: str
    filename: str


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
