from rest_framework import serializers
# DRF의 시리얼라이저 클래스 — 모델 ↔ JSON 변환 담당
from .models import GeoFence
# 같은 앱의 GeoFence 모델 import


class GeoFenceSerializer(serializers.ModelSerializer):
    # GeoFence 모델 → JSON 직렬화 자동화 — GeoFenceViewSet의 list/retrieve/create/update 모두 사용
    class Meta:
        model = GeoFence
        # 직렬화 대상 모델 지정
        fields = '__all__'
        # 모델의 모든 필드를 응답에 포함 — id, name, zone_type, description,
        # risk_level, polygon, is_active, created_at
        # ⚠️ '__all__' 사용 — devices/serializers와 동일한 패턴
        #    미래 필드 추가 시 자동 노출, 화이트리스트 권장
        read_only_fields = ['id', 'created_at']
        # 클라이언트가 수정 못 하게 잠그는 필드 — 자동 생성 필드들
        # ⚠️ is_active는 read_only가 아님 → POST/PATCH로 임의 변경 가능
        #    소프트 삭제(destroy)와 충돌 가능성: 클라이언트가 직접 is_active=True로 부활시킬 수 있음
