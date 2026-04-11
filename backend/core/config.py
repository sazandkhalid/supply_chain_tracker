import logging
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional

logger = logging.getLogger(__name__)

# AWS regions accepted for GCC / Saudi Arabia data residency compliance.
# me-south-1 = Bahrain (primary GCC region)
# me-central-1 = UAE / Abu Dhabi
_GCC_COMPLIANT_REGIONS = {"me-south-1", "me-central-1"}


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/tradeflow"

    # AWS / DynamoDB
    # Default: me-south-1 (Bahrain) — the nearest AWS region to Saudi Arabia.
    # Data must NOT leave the GCC.  If you change this, update the allowed set
    # in _GCC_COMPLIANT_REGIONS above and confirm your legal/compliance team
    # has approved the destination region.
    AWS_REGION: str = "me-south-1"
    DYNAMODB_TABLE_NAME: str = "Shipments"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # Auth
    SECRET_KEY: str = "change-me-before-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # App
    APP_NAME: str = "TradeFlow AI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Exception engine thresholds
    WEIGHT_DISCREPANCY_THRESHOLD_PCT: float = 2.0   # flag if >2% difference
    VALUE_DISCREPANCY_THRESHOLD_PCT: float = 5.0    # flag if >5% difference
    CERT_EXPIRY_WARNING_DAYS: int = 7               # warn if expiring within N days

    # WhatsApp notifications via Twilio
    # Sign up at https://www.twilio.com/ and enable the WhatsApp sandbox (or a
    # production WhatsApp sender) in your account.
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    # Twilio WhatsApp-enabled sender number in E.164 format, e.g. +14155238886
    TWILIO_WHATSAPP_FROM: Optional[str] = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        """
        Railway's Postgres plugin exposes DATABASE_URL as ``postgresql://...``.
        SQLAlchemy's async engine needs an explicit asyncpg driver — rewrite
        the scheme so operators don't have to know the difference.
        """
        if not v:
            return v
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    def validate_region_compliance(self) -> None:
        """Warn loudly at startup if the configured AWS region is outside GCC."""
        if self.AWS_REGION not in _GCC_COMPLIANT_REGIONS:
            logger.warning(
                "DATA RESIDENCY WARNING: AWS_REGION='%s' is outside the GCC-compliant "
                "region set %s.  Data stored in DynamoDB may leave Saudi Arabia / GCC "
                "jurisdiction.  Update AWS_REGION to 'me-south-1' (Bahrain) or "
                "'me-central-1' (UAE) before going to production.",
                self.AWS_REGION,
                sorted(_GCC_COMPLIANT_REGIONS),
            )


settings = Settings()
settings.validate_region_compliance()
