import pytest
from pydantic import ValidationError

from app.core.config import Settings


def production(**updates):
    values = dict(
        ENVIRONMENT="production",
        SECRET_KEY="a" * 64,
        DATABASE_URL="postgresql+asyncpg://pilot:independent-long-password@db/pilot",
        FRONTEND_URL="https://camp.pilot.test",
        CORS_ORIGINS=["https://camp.pilot.test"],
        MAIL_BACKEND="smtp",
        SMTP_HOST="smtp.pilot.test",
        SMTP_FROM="noreply@pilot.test",
        SMTP_STARTTLS=True,
        RATE_LIMIT_ENABLED=True,
        STORAGE_BACKEND="local",
    )
    values.update(updates)
    return Settings(_env_file=None, **values)


def test_valid_production_configuration():
    assert production().ENVIRONMENT == "production"


@pytest.mark.parametrize(
    "updates",
    [
        {"SECRET_KEY": "change-me-in-production"},
        {"DATABASE_URL": "postgresql+asyncpg://karavantr:karavantr@db/pilot"},
        {"FRONTEND_URL": "http://camp.pilot.test"},
        {"FRONTEND_URL": "https://camp.pilot.test/reset"},
        {"CORS_ORIGINS": ["*"]},
        {"CORS_ORIGINS": ["https://wrong.pilot.test"]},
        {"MAIL_BACKEND": "file"},
        {"SMTP_HOST": None},
        {"SMTP_STARTTLS": False},
        {"SMTP_FROM": "noreply@karavantr.local"},
        {"SMTP_USERNAME": "user", "SMTP_PASSWORD": None},
        {"RATE_LIMIT_ENABLED": False},
        {"STORAGE_BACKEND": "s3", "S3_ACCESS_KEY_ID": None},
    ],
)
def test_invalid_production_configuration_is_rejected(updates):
    with pytest.raises(ValidationError):
        production(**updates)


def test_development_keeps_existing_defaults():
    assert Settings(_env_file=None, ENVIRONMENT="development").ENVIRONMENT == "development"


def test_gmail_settings_and_password_spacing():
    value = production(
        SMTP_HOST="smtp.gmail.com",
        SMTP_USERNAME="pilot@gmail.com",
        SMTP_FROM="pilot@gmail.com",
        SMTP_PASSWORD="abcd efgh ijkl mnop",
    )
    assert value.SMTP_PASSWORD == "abcdefghijklmnop"
    with pytest.raises(ValidationError):
        production(
            SMTP_HOST="smtp.gmail.com",
            SMTP_USERNAME="pilot@gmail.com",
            SMTP_FROM="other@gmail.com",
            SMTP_PASSWORD="abcdefghijklmnop",
        )
