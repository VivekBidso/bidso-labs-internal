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

    @field_validator("*", mode="before")
    @classmethod
    def strip_whitespace(cls, value):
        # Dashboard-pasted env vars (Render, etc.) routinely carry a stray
        # trailing newline from the copy source — strip it here once rather
        # than trust every paste to be clean.
        return value.strip() if isinstance(value, str) else value


settings = Settings()
