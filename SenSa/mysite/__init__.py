"""
mysite/__init__.py

Django 기동 시 Celery 앱 등록 — autodiscover_tasks 가 동작하도록.
"""
from .celery import app as celery_app

__all__ = ('celery_app',)
