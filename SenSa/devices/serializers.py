from rest_framework import serializers
# DRF의 시리얼라이저 클래스 — 모델 ↔ JSON 변환 담당
from .models import Device
# Device 모델만 import — SensorData는 별도 시리얼라이저 없음 (views에서 dict 수동 조립)


class DeviceSerializer(serializers.ModelSerializer):
    # Device 모델 → JSON 직렬화 자동화 — DeviceViewSet의 list/retrieve/create 모두 사용
    class Meta:
        model = Device
        # 직렬화 대상 모델 지정
        fields = '__all__'
        # 모델의 모든 필드를 응답에 포함 — id, device_id, device_name, sensor_type,
        # x, y, status, last_value, last_value_unit, is_active, geofence
        # ⚠️ '__all__' 사용 — 미래에 모델에 민감 필드 추가 시 자동 노출되는 위험
        #    화이트리스트 방식(fields=[...]) 권장
        # ⚠️ geofence는 PK(int)만 노출 — geofence_name 같은 사람이 읽는 필드 없음
        #    프론트가 지오펜스명 표시하려면 별도 API 호출 필요 (N+1 가능성)
