"""Интеграция ML-сервиса с телефонией (/dialogue/turn) и Backend (/api/v1/...)."""

from .routes import build_router

__all__ = ["build_router"]
