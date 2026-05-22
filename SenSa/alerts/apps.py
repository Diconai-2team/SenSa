from django.apps import AppConfig


class AlertsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'alerts'
    verbose_name = '알람'

    def ready(self):
        # [P4-C 8차 hotfix] metrics 모듈 eager load — Counter 정의
        try:
            from alerts import metrics  # noqa: F401
        except Exception as e:
            import logging
            logging.getLogger('alerts').warning(f'metrics 모듈 로드 실패 (skip): {e}')
