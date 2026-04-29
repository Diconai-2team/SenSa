# Django 앱 설정을 정의하기 위한 AppConfig 기반 클래스를 불러옴
from django.apps import AppConfig


# vr_training 앱의 설정 클래스 — Django가 이 앱을 로드할 때 참조하는 메타 정보를 담음
class VRTrainingConfig(AppConfig):
    # 모델에 기본 키(PK)를 자동 생성할 때 BigAutoField(64비트 정수) 타입을 사용함
    # Django 3.2+ 권장 기본값으로, 대용량 데이터에서도 PK 고갈 없이 사용 가능
    default_auto_field = "django.db.models.BigAutoField"
    # 이 앱의 내부 식별 이름 — INSTALLED_APPS에 등록할 때 사용하는 문자열과 일치해야 함
    name = "vr_training"
    # Django 관리자 페이지 등에서 사람이 읽기 쉬운 앱 이름으로 표시되는 한글 명칭
    verbose_name = "VR 안전 교육"
