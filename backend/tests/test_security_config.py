"""R1: regression tests for secrets configuration and tracking."""
import subprocess
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.core.config import Settings
from scripts.seed import get_seed_admin_password

def test_missing_jwt_key_rejected(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None)

def test_placeholder_jwt_key_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None)

def test_valid_jwt_key(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "unit-test-signing-key-abcdefghijklmnopqrstuvwxyz")
    assert Settings(_env_file=None).JWT_SECRET_KEY.startswith("unit-test-")

def test_seed_password_required(monkeypatch):
    monkeypatch.delenv("ADMIN_SEED_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="ADMIN_SEED_PASSWORD"):
        get_seed_admin_password()

@pytest.mark.parametrize("unsafe", ["short", "admin123456", "password123456"])
def test_seed_rejects_unsafe_password(monkeypatch, unsafe):
    monkeypatch.setenv("ADMIN_SEED_PASSWORD", unsafe)
    with pytest.raises(RuntimeError, match="ADMIN_SEED_PASSWORD"):
        get_seed_admin_password()

def test_seed_password_valid(monkeypatch):
    monkeypatch.setenv("ADMIN_SEED_PASSWORD", "unique-admin-seed-password-123")
    assert get_seed_admin_password() == "unique-admin-seed-password-123"

def test_sensitive_artifacts_untracked():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["git", "-C", str(root), "ls-files", "--",
                             "backend/.env", "backend/env", "backend/celery_output.log"],
                            capture_output=True, text=True, check=True)
    assert not result.stdout.strip()

def test_docker_context_excludes_secrets():
    ignored = (Path(__file__).resolve().parents[1] / ".dockerignore").read_text()
    for pattern in (".env", "env/", "__pycache__"):
        assert pattern in ignored
