from rest_framework import serializers
# DRF의 시리얼라이저 클래스 — 모델 ↔ JSON 변환 담당
from .models import Alarm
# 같은 앱의 Alarm 모델을 가져와


class AlarmSerializer(serializers.ModelSerializer):
    # Alarm 모델 → JSON 직렬화 + JSON → Alarm 역직렬화를 자동화하는 시리얼라이저야
    geofence_name = serializers.CharField(
    # 지오펜스명을 별도 필드로 노출 — 프론트가 FK ID로 다시 조회하지 않아도 되도록 편의 제공
        source='geofence.name', read_only=True, default=None
        # source: alarm.geofence.name 경로로 값 추출 — geofence가 None이면 default(None) 사용
        # read_only: 응답 전용 — POST/PATCH로 들어와도 무시됨
    )

    class Meta:
        model = Alarm
        # 직렬화 대상 모델 지정
        fields = [
        # 응답에 포함될 필드 화이트리스트 — 명시적으로 나열해 의도하지 않은 필드 노출 차단
            'id', 'alarm_type', 'alarm_level',
            'worker_id', 'worker_name', 'worker_x', 'worker_y',
            'geofence', 'geofence_name',
            # geofence는 PK(int), geofence_name은 사람이 읽는 이름 — 둘 다 노출
            'device_id', 'sensor_type',
            'message', 'is_read', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
        # 클라이언트가 수정 못 하게 잠그는 필드 — id는 자동, created_at은 발생 시각이라 변조 차단
