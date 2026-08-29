"""Configuration, read from environment variables (or a local .env file).

Nothing here has a secret as its default. An unset secret must fail loudly at
the point of use, never fall back to something that happens to work.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "wa-agent-starter"
    LOG_LEVEL: str = "INFO"

    # --- Meta WhatsApp Cloud API ------------------------------------------- #
    # The token you generate in the Meta app ("System user" token for anything
    # long-lived; the 24-hour test token is fine for the first run).
    WHATSAPP_TOKEN: str = ""
    # "Phone number ID" from WhatsApp > API Setup. NOT the phone number itself.
    WHATSAPP_PHONE_ID: str = ""
    # Any string you invent. You type the SAME value into Meta's callback form;
    # Meta echoes it back once during the GET handshake.
    WHATSAPP_VERIFY_TOKEN: str = ""
    # App Secret from Meta > App settings > Basic. Used to verify the
    # X-Hub-Signature-256 header on every inbound POST. Without it, every POST
    # is rejected - that is deliberate.
    META_APP_SECRET: str = ""
    GRAPH_API_VERSION: str = "v21.0"
    GRAPH_API_BASE: str = "https://graph.facebook.com"

    # --- Behaviour --------------------------------------------------------- #
    # Path to the answer file. Point it at your own copy to change every reply
    # without touching Python.
    FAQ_FILE: str = "faq.json"
    # Reply language when the incoming text carries no script hint at all
    # (an emoji, a bare number, an unsupported message type).
    DEFAULT_LANGUAGE: str = "he"
    # Local development only: skip signature verification. NEVER set this to
    # true on a public URL - it turns the webhook into an open remote control.
    ALLOW_UNSIGNED_WEBHOOK: bool = False

    @property
    def graph_url(self) -> str:
        base = self.GRAPH_API_BASE.rstrip("/")
        return f"{base}/{self.GRAPH_API_VERSION}"

    @property
    def send_configured(self) -> bool:
        """False => replies are computed and logged but not delivered, so the
        whole flow can be exercised before Meta credentials exist."""
        return bool(self.WHATSAPP_TOKEN.strip() and self.WHATSAPP_PHONE_ID.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
