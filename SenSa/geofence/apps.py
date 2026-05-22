from django.apps import AppConfig


class GeofenceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'geofence'
    verbose_name = '지오펜스'

    def ready(self):
        # [P4-C 8차 hotfix] metrics 모듈 eager load — Gauge.set_function 등록 + Counter 정의
        try:
            from geofence import metrics  # noqa: F401
        except Exception as e:
            # 메트릭 로드 실패가 앱 기동을 막지 않게 격리
            import logging
            logging.getLogger('geofence').warning(f'metrics 모듈 로드 실패 (skip): {e}')
