from django.apps import AppConfig


class DevicesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'devices'
    verbose_name = '센서 장비'

    def ready(self):
        from django.db.backends.signals import connection_created

        def _set_sqlite_pragmas(sender, connection, **kwargs):
            if connection.vendor != 'sqlite':
                return
            cursor = connection.cursor()
            # 쓰기 경합 시 즉시 실패(OperationalError: database is locked) 대신
            # 최대 20초 대기. WAL 모드는 db 파일에 이미 적용돼 있음.
            cursor.execute('PRAGMA busy_timeout = 20000;')
            cursor.execute('PRAGMA synchronous = NORMAL;')

        connection_created.connect(_set_sqlite_pragmas)
