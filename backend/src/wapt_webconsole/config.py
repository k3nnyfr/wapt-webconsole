"""Settings, read from the environment (prefix ``WWC_``).

Secrets are never passed as plain variables: each one is read from a file (Docker secret), whose path is given by
a ``*_file`` setting.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROLES = ("viewer", "operator", "admin")


def read_secret(path: Path | None) -> str:
    if path is None:
        return ""
    return path.read_text(encoding="utf-8").strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WWC_", env_nested_delimiter="__")

    # Public URL of the console, behind the reverse proxies (OIDC redirect URI, cookies)
    public_url: str = "http://localhost:8080"

    # WAPT server, reached by its public URL
    wapt_url: str = "https://wapt.example.org"
    wapt_user: str = "admin"
    wapt_password_file: Path | None = None
    wapt_verify_tls: bool = True
    wapt_timeout: float = 60.0
    # Package repository (icons); default: <wapt_url>/wapt
    wapt_repo_url: str = ""
    # Seconds between two inventory reads while browsers follow the live status
    live_interval: float = 10.0

    # Signature of the agent actions: certificate and encrypted private key of the WAPT administrator
    signer_certificate_file: Path | None = None
    signer_key_file: Path | None = None
    signer_unlock_minutes: int = 30
    waptpython: str = "/opt/wapt/waptpython.sh"
    signer_script: str = "/app/signer/signer.py"

    # Persistent data (audit journal)
    data_dir: Path = Path("/data")
    journal_retention_days: int = 365
    # Largest package accepted by the upload (MB); staged in <data_dir>/tmp, not in memory
    max_upload_mb: int = 2048

    # OpenID Connect (Authelia or any provider)
    oidc_issuer: str = ""
    oidc_client_id: str = "wapt-webconsole"
    oidc_client_secret_file: Path | None = None
    oidc_scopes: str = "openid profile email groups"
    # Provider groups granting each role (a user gets the highest one)
    role_groups: dict[str, list[str]] = Field(default_factory=lambda: {
        "viewer": ["wapt-viewers"], "operator": ["wapt-operators"], "admin": ["wapt-admins"]})

    # Session cookie, signed with this secret
    session_secret_file: Path | None = None
    session_max_age: int = 8 * 3600

    @cached_property
    def wapt_password(self) -> str:
        return read_secret(self.wapt_password_file)

    @cached_property
    def oidc_client_secret(self) -> str:
        return read_secret(self.oidc_client_secret_file)

    @cached_property
    def session_secret(self) -> str:
        secret = read_secret(self.session_secret_file)
        if len(secret) < 32:
            raise ValueError("the session secret must be at least 32 characters (WWC_SESSION_SECRET_FILE)")
        return secret

    @property
    def repo_url(self) -> str:
        return (self.wapt_repo_url or self.wapt_url.rstrip("/") + "/wapt").rstrip("/")

    @property
    def https(self) -> bool:
        return self.public_url.startswith("https://")


def role_for_groups(groups: list[str], role_groups: dict[str, list[str]]) -> str | None:
    """Highest role granted by the provider groups, or None: no access."""
    granted = None
    for role in ROLES:
        if set(groups) & set(role_groups.get(role, [])):
            granted = role
    return granted


def role_at_least(role: str | None, required: str) -> bool:
    return role is not None and ROLES.index(role) >= ROLES.index(required)
