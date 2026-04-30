from rest_framework import serializers
from .models import MapImage


class MapImageSerializer(serializers.ModelSerializer):
    # MapImage 모델 ↔ JSON 변환 — MapImageViewSet의 모든 액션에서 사용
    class Meta:
        model = MapImage
        fields = ['id', 'image', 'name', 'width', 'height', 'is_active', 'uploaded_at']
        # 명시적 필드 나열 — 다른 앱의 '__all__'과 다른 패턴 (좋음)
        # ⚠️ image 필드는 응답에 file URL로 직렬화됨 — settings.MEDIA_URL 설정 필요
        read_only_fields = ['uploaded_at']
        # ⚠️ width/height는 read_only가 아님 → 클라이언트가 거짓 값 보낼 수 있음
        #    이미지 실제 크기와 다른 값이 들어가면 좌표 시스템 전체가 어긋남
        #    개선안: perform_create에서 PIL로 자동 추출 + read_only 처리
        # ⚠️ is_active도 노출 — 클라이언트가 임의로 False로 바꿔 활성 평면도를 0개로 만들 위험
