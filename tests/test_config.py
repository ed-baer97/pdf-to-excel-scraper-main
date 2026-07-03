"""Тесты конфигурации окружений."""

import os

import pytest

from webapp.config import DevelopmentConfig, ProductionConfig, TestingConfig


def test_development_allows_default_secret_key():
    assert DevelopmentConfig.SECRET_KEY


def test_production_validate_requires_secrets(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("PASSWORD_ENC_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        ProductionConfig.validate()


def test_production_validate_passes_with_secrets(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "prod-secret")
    monkeypatch.setenv("PASSWORD_ENC_KEY", "enc-key")
    ProductionConfig.validate()


def test_testing_config_in_memory_db():
    assert TestingConfig.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"
