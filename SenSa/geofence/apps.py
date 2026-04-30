from django.apps import AppConfig
# Django 앱 설정의 부모 클래스인 AppConfig를 불러와


class GeofenceConfig(AppConfig):
    # geofence 앱의 메타 정보를 담는 설정 클래스야
    default_auto_field = 'django.db.models.BigAutoField'
    # 이 앱 모델들의 PK 기본 타입을 BigAutoField(64bit)로 지정 — 일관성 차원에서 다른 앱과 통일
    name = 'geofence'
    # 앱의 실제 Python 패키지 경로 — INSTALLED_APPS에 등록될 이름이야
    # devices.Device.geofence와 alerts.Alarm.geofence FK가 'geofence.GeoFence'로 이 이름 참조
    verbose_name = '지오펜스'
    # 관리자 페이지 등 사람이 읽는 화면에 표시될 한국어 이름이야