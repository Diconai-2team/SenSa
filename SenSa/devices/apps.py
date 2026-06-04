from django.apps import AppConfig


class DevicesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'devices'
    verbose_name = '센서 장비'

    def ready(self):
        # metrics 모듈 eager load — Counter 정의 + SensorValueCollector 등록
        try:
            from devices import metrics  # noqa: F401
        except Exception as e:
            import logging
            logging.getLogger('devices').warning(f'metrics 모듈 로드 실패 (skip): {e}')
