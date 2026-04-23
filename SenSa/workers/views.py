"""
workers/views.py — 작업자 API

자동 생성되는 엔드포인트:
  GET/POST        /dashboard/api/worker/                 작업자 목록/생성
  GET/PUT/DELETE   /dashboard/api/worker/{id}/            작업자 상세/수정/삭제
  GET              /dashboard/api/worker/{id}/latest/     최근 위치 1건
  GET/POST         /dashboard/api/worker-location/        위치 기록 목록/생성
  GET              /dashboard/api/worker-location/?worker_id=worker_01
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Worker, WorkerLocation
from .serializers import WorkerSerializer, WorkerLocationSerializer
from realtime.publishers import publish_worker_position


class WorkerViewSet(viewsets.ModelViewSet):
    """
    작업자 CRUD

    ModelViewSet 하나로 6개 API가 자동 생성됨:
      list()           GET    /worker/       → 목록
      create()         POST   /worker/       → 생성
      retrieve()       GET    /worker/1/     → 상세
      update()         PUT    /worker/1/     → 전체 수정
      partial_update() PATCH  /worker/1/     → 부분 수정
      destroy()        DELETE /worker/1/     → 삭제
    """

    # ── 기본 조회 범위 ──
    # is_active=True만 → 소프트 삭제된 작업자는 안 보임
    queryset = Worker.objects.filter(is_active=True)

    # ── 어떤 시리얼라이저로 JSON 변환할지 ──
    serializer_class = WorkerSerializer

    def destroy(self, request, *args, **kwargs):
        """
        소프트 삭제 — is_active=False로 변경

        기본 destroy()는 instance.delete()로 DB에서 완전 삭제함
        → 이걸 오버라이드해서 is_active=False로만 변경

        self.get_object()
          → URL의 pk(예: /worker/3/)에 해당하는 Worker를 가져옴
          → 없으면 자동으로 404 에러 반환
        """
        instance = self.get_object()
        instance.is_active = False
        instance.save()

        # 204 No Content: "삭제 성공, 응답 본문 없음"
        # REST API 삭제의 표준 응답 코드
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def latest(self, request, pk=None):
        """
        해당 작업자의 최근 위치 1건

        @action 데코레이터:
          detail=True  → 개별 객체에 대한 액션 (/worker/1/latest/)
          detail=False → 전체 목록에 대한 액션 (/worker/latest/)
          methods=['get'] → GET 요청만 허용

        URL: /dashboard/api/worker/{pk}/latest/
        """
        worker = self.get_object()

        # ordering=['-timestamp']이므로 first() = 가장 최근 기록
        loc = worker.locations.first()

        if not loc:
            return Response(
                {"detail": "위치 기록이 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 시리얼라이저로 JSON 변환 후 응답
        return Response(WorkerLocationSerializer(loc).data)


class WorkerLocationViewSet(viewsets.ModelViewSet):
    """
    작업자 위치 기록

    쿼리 파라미터:
      ?worker_id=worker_01   → 특정 작업자만 필터
      ?limit=50              → 최근 N건만 (기본 100)

    사용 예:
      GET /dashboard/api/worker-location/
      GET /dashboard/api/worker-location/?worker_id=worker_01&limit=20
      POST /dashboard/api/worker-location/
        body: {"worker": 1, "x": 150, "y": 170}
    """
    serializer_class = WorkerLocationSerializer

    def get_queryset(self):
        """
        queryset을 클래스 변수 대신 메서드로 정의하는 이유:
        → 요청(request)마다 다른 결과를 반환해야 하기 때문
        → ?worker_id=... 파라미터에 따라 필터가 달라짐

        만약 queryset = WorkerLocation.objects.all()로 클래스 변수에 두면
        모든 요청에 대해 동일한 결과가 반환됨 (파라미터 무시)
        """

        # ── select_related('worker') ──
        # WorkerLocation을 가져올 때 Worker도 JOIN해서 같이 가져옴
        #
        # 없으면: 쿼리 N+1 문제 발생
        #   1번째 쿼리: SELECT * FROM workerlocation LIMIT 100
        #   2~101번째:  SELECT * FROM worker WHERE id = ?  (100번!)
        #
        # 있으면: 1번의 쿼리로 끝
        #   SELECT * FROM workerlocation
        #     JOIN worker ON worker.id = workerlocation.worker_id
        #     LIMIT 100
        qs = WorkerLocation.objects.select_related('worker').all()

        # ── 특정 작업자 필터 ──
        # ?worker_id=worker_01 → worker_01의 위치 기록만
        #
        # worker__worker_id 에서 __(밑줄 두 개)의 의미:
        #   FK 관계를 타고 들어가는 것
        #   workerlocation.worker.worker_id 를 필터
        #
        # Django ORM에서 __의 다른 용도:
        #   filter(x__gte=100)           → x >= 100
        #   filter(name__contains="A")   → name에 "A" 포함
        #   filter(timestamp__date=...)  → 날짜 필터
        worker_id = self.request.query_params.get('worker_id')
        if worker_id:
            qs = qs.filter(worker__worker_id=worker_id)

        # ── 건수 제한 ──
        # ?limit=50 → 최근 50건만
        # 위치 기록은 매초 쌓이므로 전부 반환하면 안 됨
        # qs[:100]은 SQL의 LIMIT 100과 동일
        limit = self.request.query_params.get('limit', '100')
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 100

        return qs[:limit]
    def perform_create(self, serializer):
        """
        POST /dashboard/api/worker-location/ 요청이 왔을 때
        기본 동작: DB 저장
        추가 동작: 저장 직후 WS로 현재 위치 push
        
        ModelViewSet.create()는 내부적으로 perform_create()를 호출함.
        여기를 오버라이드하면 "저장 + push"를 자연스럽게 묶을 수 있음.
        """
        # 1) DB 저장 (기본 동작)
        instance = serializer.save()
        
        # 2) WS push용 딕셔너리 구성
        #    Worker FK로 연결돼 있으므로 instance.worker.worker_id로 접근
        payload = {
            "worker_id": instance.worker.worker_id,
            "worker_name": instance.worker.name,
            "x": instance.x,
            "y": instance.y,
            "movement_status": instance.movement_status,
            "timestamp": instance.timestamp.isoformat(),
        }
        
        # 3) 방송
        publish_worker_position(payload)