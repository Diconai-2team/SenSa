from django.apps import AppConfig
# Django 앱 설정의 부모 클래스인 AppConfig를 불러와


class DashboardConfig(AppConfig):
    # dashboard 앱의 메타 정보를 담는 설정 클래스야
    default_auto_field = 'django.db.models.BigAutoField'
    # 이 앱 모델들의 PK 기본 타입을 BigAutoField(64bit)로 지정 — 다른 앱과 일관성 유지
    name = 'dashboard'
    # 앱의 실제 Python 패키지 경로 — INSTALLED_APPS에 등록될 이름이야
    verbose_name = '관제 대시보드'
    # 관리자 페이지 등 사람이 읽는 화면에 표시될 한국어 이름이야