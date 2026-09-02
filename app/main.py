from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, verify_password
from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, LoginResponse, PresignUploadRequest
from app.uploads import presign_upload

app = FastAPI(title="Bidso Labs — Internal Review Platform")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.id, user.role)
    return LoginResponse(access_token=token)


@app.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "email": user.email, "role": user.role}


@app.post("/uploads/presign")
def presign(payload: PresignUploadRequest, _user: User = Depends(get_current_user)):
    return presign_upload(
        track=payload.track,
        reference_number=payload.reference_number,
        stage=payload.stage,
        filename=payload.filename,
    )
