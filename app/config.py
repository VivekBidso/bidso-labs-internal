from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_endpoint_url: str = ""

    resend_api_key: str = ""
    resend_from_address: str = ""
    sales_contact_email: str = ""

    # Pre-MVP-only: seeds/resets one known admin login on deploy and shows
    # it, visibly, on the login form itself — a deliberate stopgap while
    # this is the only account and forgot-password is being built (see
    # evaluation-engine-phased-plan.md). Never committed to git; set only in
    # Render's dashboard. Unset both to turn the stopgap off once
    # forgot-password ships.
    admin_bootstrap_email: str = ""
    admin_bootstrap_password: str = ""

    # Public origin of the internal app itself — used to build the
    # password-reset link sent by email. Falls back to the known Render
    # default if unset.
    app_public_url: str = "https://bidso-labs-internal.onrender.com"

    @field_validator("*", mode="before")
    @classmethod
    def strip_whitespace(cls, value):
        # Dashboard-pasted env vars (Render, etc.) routinely carry a stray
        # trailing newline from the copy source — strip it here once rather
        # than trust every paste to be clean.
        return value.strip() if isinstance(value, str) else value


settings = Settings()
