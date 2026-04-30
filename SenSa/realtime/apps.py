from django.apps import AppConfig

# Django의 앱 설정 기반 클래스를 가져옴. 모든 앱은 이 클래스를 상속해서 자신을 등록함.


class RealtimeConfig(AppConfig):
    # 'realtime' 앱의 설정 클래스. settings.py의 INSTALLED_APPS에 등록되어 Django가 이 앱을 인식하게 함.

    default_auto_field = "django.db.models.BigAutoField"
    # 모델에 기본 키를 따로 지정하지 않았을 때 자동으로 사용할 필드 타입.
    # BigAutoField = 64비트 정수 자동 증가 ID (일반 AutoField의 상위 호환으로, 데이터가 많아져도 오버플로 없음).

    name = "realtime"
    # Django가 이 설정 클래스와 실제 앱 디렉터리를 연결할 때 쓰는 앱 이름.
    # settings.py의 INSTALLED_APPS에 "realtime" 또는 "realtime.apps.RealtimeConfig"로 등록해야 함.
