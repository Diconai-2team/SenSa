"""
mysite/celery.py — Celery 앱 설정.

[기동]
    # worker + beat 통합 (개발/단순 운영)
    celery -A mysite worker -B --loglevel=info

    # 또는 분리 운영 (프로덕션 권장)
    celery -A mysite worker --loglevel=info
    celery -A mysite beat   --loglevel=info
"""
import os

from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')

app = Celery('mysite')

# settings.py 의 CELERY_ 접두 항목 자동 인식
app.config_from_object('django.conf:settings', namespace='CELERY')

# 각 앱의 tasks.py 자동 발견
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """디버깅용 — `celery -A mysite call mysite.celery.debug_task`."""
    print(f'Request: {self.request!r}')
