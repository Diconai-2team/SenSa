"""
geofence 앱 뷰

- GeoFenceViewSet: 지오펜스 CRUD (소프트 삭제)
"""

from rest_framework import viewsets, status
# viewsets — ModelViewSet 사용 / status — HTTP 상태 코드 상수 (204 NO_CONTENT 사용)
from rest_framework.response import Response

from .models import GeoFence
from .serializers import GeoFenceSerializer


class GeoFenceViewSet(viewsets.ModelViewSet):
    """지오펜스 CRUD API"""
    # ModelViewSet — list/retrieve/create/update/partial_update/destroy 모두 자동 제공
    # destroy만 오버라이드해서 소프트 삭제로 변경 (아래)
    queryset = GeoFence.objects.filter(is_active=True).order_by('-created_at')
    # 활성 지오펜스만 노출 — 소프트 삭제된(is_active=False) 지오펜스는 API에서 안 보임
    # 정렬: 최신 등록 먼저 — admin과 동일한 정책
    # ⚠️ 소프트 삭제된 지오펜스를 복구할 API 없음 — 운영자가 admin 가서 직접 처리해야 함
    serializer_class = GeoFenceSerializer

    def destroy(self, request, *args, **kwargs):
        """소프트 삭제 — is_active=False"""
        # ModelViewSet의 기본 destroy(물리 삭제)를 오버라이드 — 데이터 보존 우선
        # 이유: 과거 알람의 geofence FK가 SET_NULL이지만, 운영자가 "어느 구역이었는지"
        #       이름까지 추적할 수 있도록 row 자체는 유지
        instance = self.get_object()
        # URL의 pk로 GeoFence 1건 조회 + queryset 권한 체크
        # ⚠️ queryset이 is_active=True 필터링되어 있어 이미 삭제된 지오펜스를 다시 destroy 호출 시 404
        instance.is_active = False
        instance.save()
        # ⚠️ save() 호출 — 모든 필드 UPDATE 발생
        #    개선안: instance.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)
        # 204 NO_CONTENT — REST 표준의 DELETE 성공 응답 (body 없음)
        # 클라이언트는 응답 body를 기대하지 않음