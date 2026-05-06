"""
workers/views.py — 작업자 API + 페이지 (Phase 4A)

[구성]
  === 기존 (대시보드용) ===
  WorkerViewSet          /dashboard/api/worker/
  WorkerLocationViewSet  /dashboard/api/worker-location/

  === Phase 4A 신규 (작업자 현황 페이지) ===
  worker_list_page       GET  /workers/
  WorkerListDataView     GET  /workers/api/list/
  WorkerNotifyView       POST /workers/api/notify/
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import viewsets, status as http_status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NotificationLog, Worker, WorkerLocation
from .serializers import WorkerSerializer, WorkerLocationSerializer
from realtime.publishers import publish_worker_position


# ═══════════════════════════════════════════════════════════
# 기존 DRF ViewSet (변경 없음)
# ═══════════════════════════════════════════════════════════

class WorkerViewSet(viewsets.ModelViewSet):
    """작업자 CRUD"""
    queryset = Worker.objects.filter(is_active=True)
    serializer_class = WorkerSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save()
        return Response(status=http_status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def latest(self, request, pk=None):
        worker = self.get_object()
        loc = worker.locations.first()
        if not loc:
            return Response(
                {"detail": "위치 기록이 없습니다."},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(WorkerLocationSerializer(loc).data)


class WorkerLocationViewSet(viewsets.ModelViewSet):
    """작업자 위치 기록"""
    serializer_class = WorkerLocationSerializer

    def get_queryset(self):
        qs = WorkerLocation.objects.select_related('worker').all()

        worker_id = self.request.query_params.get('worker_id')
        if worker_id:
            qs = qs.filter(worker__worker_id=worker_id)

        limit = self.request.query_params.get('limit', '100')
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 100

        return qs[:limit]

    def perform_create(self, serializer):
        instance = serializer.save()

        # ─── Phase 4A: heartbeat 갱신 ───
        # 위치 업데이트가 올 때마다 Worker.last_seen_at 을 함께 갱신해서
        # '연결 상태' 판정의 단일 출처로 삼는다.
        Worker.objects.filter(pk=instance.worker_id).update(
            last_seen_at=instance.timestamp,
        )

        # WS 방송 (기존)
        payload = {
            "worker_id": instance.worker.worker_id,
            "worker_name": instance.worker.name,
            "x": instance.x,
            "y": instance.y,
            "movement_status": instance.movement_status,
            "timestamp": instance.timestamp.isoformat(),
        }
        publish_worker_position(payload)


# ═══════════════════════════════════════════════════════════
# Phase 4A — 작업자 현황 페이지
# ═══════════════════════════════════════════════════════════

# 연결 상태 판정 기준 — last_seen_at 이 이 시간 이내면 "연결 정상"
CONNECTION_TIMEOUT_SEC = 30


@login_required(login_url='/accounts/login/')
def worker_list_page(request):
    """
    작업자 현황 목록 페이지.

    초기 렌더는 쉘만 깔아두고, 실제 데이터는
    JS 가 /workers/api/list/ 를 호출해서 받는다. (Phase 4B 에서 폴링/WS 전환 용이)
    """
    return render(request, 'workers/list.html')


def _get_worker_state_map() -> dict[str, str]:
    """
    state_store 에서 각 작업자의 현재 상태(safe/caution/danger/critical) 를 읽어온다.

    alerts.state_store 가 Redis 기반이므로, 의존성 방향 유지를 위해
    실패해도 빈 dict 반환 (페이지는 계속 렌더).
    """
    try:
        from alerts.state_store import get_worker_snapshot
    except Exception:
        return {}

    result: dict[str, str] = {}
    for w in Worker.objects.filter(is_active=True).only('worker_id'):
        try:
            snap = get_worker_snapshot(w.worker_id)
            if snap:
                # get_worker_snapshot 이 반환하는 dict 의 'state' 키 사용
                result[w.worker_id] = snap.get('state', 'safe')
            else:
                result[w.worker_id] = 'safe'
        except Exception:
            result[w.worker_id] = 'safe'
    return result


def _get_worker_zone_map() -> dict[str, str]:
    """
    각 작업자가 현재 있는 지오펜스 이름(= '작업지명') 매핑.

    WorkerLocation 마지막 좌표로 GeoFence polygon 포함 여부를 계산.
    없으면 빈 문자열.
    """
    try:
        from geofence.models import GeoFence
    except Exception:
        return {}

    # 전체 활성 geofence (polygon = [[x,y], ...])
    fences = list(
        GeoFence.objects.filter(is_active=True).values('name', 'polygon')
    )

    result: dict[str, str] = {}
    latest_by_worker = {}
    for loc in WorkerLocation.objects.select_related('worker')[:500]:
        # 이미 최신 1건 잡힘 (ordering -timestamp)
        if loc.worker.worker_id in latest_by_worker:
            continue
        latest_by_worker[loc.worker.worker_id] = (loc.x, loc.y)

    for wid, (x, y) in latest_by_worker.items():
        zone_name = ''
        for fence in fences:
            poly = fence.get('polygon') or []
            if len(poly) >= 3 and _point_in_polygon(x, y, poly):
                zone_name = fence['name']
                break
        result[wid] = zone_name
    return result


def _point_in_polygon(x: float, y: float, poly: list) -> bool:
    """Ray casting — poly 는 [[x1,y1],[x2,y2],...]"""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


class WorkerListDataView(APIView):
    """
    작업자 목록 + 요약 데이터 (JSON).

    응답:
    {
        "summary": {
            "total": 100,
            "checked_in": 50,      // last_seen_at <= 30s 이내
            "by_status": {"danger": 2, "caution": 2, "safe": 46}
        },
        "workers": [
            {
                "worker_id": "worker_01",
                "name": "김재승",
                "department": "공정관리팀",
                "position": "대리",
                "email": "...",
                "phone": "...",
                "zone_name": "고온구역 A",
                "last_seen_at": "2026-04-24T10:00:00+09:00",
                "connection_ok": true,
                "status": "safe"
            }, ...
        ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        cutoff = now - timedelta(seconds=CONNECTION_TIMEOUT_SEC)

        workers_qs = Worker.objects.filter(is_active=True).order_by('worker_id')

        state_map = _get_worker_state_map()
        zone_map  = _get_worker_zone_map()

        workers_data = []
        checked_in_count = 0
        status_counter = {'danger': 0, 'caution': 0, 'safe': 0}

        for w in workers_qs:
            connection_ok = bool(w.last_seen_at and w.last_seen_at >= cutoff)
            if connection_ok:
                checked_in_count += 1

            status = state_map.get(w.worker_id, 'safe')
            # critical 은 UI 표시상 danger 로 합침 (3-배지 체계)
            ui_status = 'danger' if status in ('danger', 'critical') else status
            if ui_status not in status_counter:
                ui_status = 'safe'
            status_counter[ui_status] += 1

            workers_data.append({
                'worker_id':    w.worker_id,
                'name':         w.name,
                'department':   w.department,
                'position':     w.position,
                'email':        w.email,
                'phone':        w.phone,
                'zone_name':    zone_map.get(w.worker_id, ''),
                'last_seen_at': w.last_seen_at.isoformat() if w.last_seen_at else None,
                'connection_ok': connection_ok,
                'status':       ui_status,
            })

        return Response({
            'summary': {
                'total':       workers_qs.count(),
                'checked_in':  checked_in_count,
                'by_status':   status_counter,
            },
            'workers': workers_data,
        })


@method_decorator(csrf_exempt, name='dispatch')
class WorkerNotifyView(APIView):
    """
    푸시 알림 전송 (Phase 4A 더미).

    요청 (JSON):
    {
        "send_type": "single" | "selected" | "all",
        "recipients": ["worker_01", "worker_02"],  // single/selected 일 때
        "message": "가스 농도 상승 중..."
    }

    응답 (201):
    {
        "status": "ok",
        "notification_id": 42,
        "sent_at": "...",
        "recipient_count": 2
    }

    [동작]
      - DB에 NotificationLog 1건 + recipients M2M 저장
      - 실제 푸시 전송은 하지 않음 (Phase 4B 범위)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        send_type = request.data.get('send_type', '').strip()
        message   = request.data.get('message', '').strip()
        recipient_ids = request.data.get('recipients', [])

        # ─── 검증 ───
        if send_type not in ('single', 'selected', 'all'):
            return Response(
                {'status': 'error', 'message': 'send_type 은 single/selected/all 중 하나여야 합니다.'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        if not message:
            return Response(
                {'status': 'error', 'message': '메시지를 입력해주세요.'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        if len(message) > 200:
            return Response(
                {'status': 'error', 'message': '메시지는 200자 이내여야 합니다.'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # ─── 수신자 결정 ───
        if send_type == 'all':
            recipients = list(Worker.objects.filter(is_active=True))
        else:
            if not isinstance(recipient_ids, list) or not recipient_ids:
                return Response(
                    {'status': 'error', 'message': '수신 대상을 지정해주세요.'},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
            recipients = list(
                Worker.objects.filter(
                    worker_id__in=recipient_ids, is_active=True,
                )
            )
            if not recipients:
                return Response(
                    {'status': 'error', 'message': '유효한 수신 대상이 없습니다.'},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )

        # ─── DB 저장 ───
        with transaction.atomic():
            log = NotificationLog.objects.create(
                sender=request.user,
                send_type=send_type,
                message=message,
            )
            log.recipients.set(recipients)

        return Response(
            {
                'status':          'ok',
                'notification_id': log.id,
                'sent_at':         log.sent_at.isoformat(),
                'recipient_count': len(recipients),
            },
            status=http_status.HTTP_201_CREATED,
        )