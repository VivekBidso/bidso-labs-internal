from pydantic import BaseModel


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
