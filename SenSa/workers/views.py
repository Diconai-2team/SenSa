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
# CONNECTION_TIMEOUT_SEC 컷오프 계산용

from django.contrib.auth.decorators import login_required
# 페이지 뷰 보호 데코레이터
from django.db import transaction
# NotificationLog INSERT + recipients M2M 저장을 atomic으로 묶기 위함
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
# CSRF 면제 — JWT 미사용 환경에서 fetch POST 받기 위함

from rest_framework import viewsets, status as http_status
# 'status' 변수명 충돌 회피 위해 http_status로 alias (devices/views와 동일 패턴)
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NotificationLog, Worker, WorkerLocation
from .serializers import WorkerSerializer, WorkerLocationSerializer
from realtime.publishers import publish_worker_position
# WebSocket 푸시 헬퍼 — 위치 INSERT 시 대시보드에 즉시 broadcast


# ═══════════════════════════════════════════════════════════
# 기존 DRF ViewSet (변경 없음)
# ═══════════════════════════════════════════════════════════

class WorkerViewSet(viewsets.ModelViewSet):
    """작업자 CRUD"""
    queryset = Worker.objects.filter(is_active=True)
    # 활성 작업자만 노출 — 소프트 삭제된 작업자는 API에서 안 보임
    serializer_class = WorkerSerializer

    def destroy(self, request, *args, **kwargs):
        # 소프트 삭제로 오버라이드 — 위치 이력 보존
        instance = self.get_object()
        instance.is_active = False
        instance.save()
        # ⚠️ save() 전체 필드 — update_fields=['is_active'] 권장
        return Response(status=http_status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    # detail=True — /worker/{id}/latest/ 형태
    def latest(self, request, pk=None):
        # 특정 작업자의 가장 최근 위치 1건 반환
        worker = self.get_object()
        loc = worker.locations.first()
        # WorkerLocation.Meta.ordering=['-timestamp']로 자동 정렬 → first()가 최신
        if not loc:
            return Response(
                {"detail": "위치 기록이 없습니다."},
                status=http_status.HTTP_404_NOT_FOUND,
            )
            # 신규 등록 작업자가 아직 위치 송신 안 한 경우
        return Response(WorkerLocationSerializer(loc).data)


class WorkerLocationViewSet(viewsets.ModelViewSet):
    """작업자 위치 기록"""
    serializer_class = WorkerLocationSerializer

    def get_queryset(self):
        # 동적 쿼리셋 — query string 기반 필터/제한
        qs = WorkerLocation.objects.select_related('worker').all()
        # select_related — N+1 회피 (WorkerLocationSerializer가 worker.name/worker.worker_id 접근)

        worker_id = self.request.query_params.get('worker_id')
        if worker_id:
            qs = qs.filter(worker__worker_id=worker_id)
            # 특정 작업자 이력만 조회 — 차트 데이터 소스

        limit = self.request.query_params.get('limit', '100')
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 100
            # 잘못된 limit 입력은 기본값으로 fallback (devices의 ValueError 위험과 다른 처리)

        return qs[:limit]
        # ⚠️ 페이지네이션 없음 — 100건 이상 조회 불가

    def perform_create(self, serializer):
        # ModelViewSet의 create 훅 — 인스턴스 저장 후 추가 작업 수행
        instance = serializer.save()
        # WorkerLocation INSERT 1건

        # ─── Phase 4A: heartbeat 갱신 ───
        # 위치 업데이트가 올 때마다 Worker.last_seen_at 을 함께 갱신해서
        # '연결 상태' 판정의 단일 출처로 삼는다.
        Worker.objects.filter(pk=instance.worker_id).update(
            last_seen_at=instance.timestamp,
        )
        # ⚠️ filter().update() — save() 안 거치고 SQL UPDATE 직접 (효율적)
        # ⚠️ 별도 트랜잭션 — INSERT(serializer.save)와 UPDATE(여기) 사이에 실패 시 정합성 깨짐
        #    개선안: @transaction.atomic 데코레이터 또는 with 블록

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
        # 모든 대시보드 클라이언트에 즉시 broadcast — 지도 마커 실시간 이동


# ═══════════════════════════════════════════════════════════
# Phase 4A — 작업자 현황 페이지
# ═══════════════════════════════════════════════════════════

# 연결 상태 판정 기준 — last_seen_at 이 이 시간 이내면 "연결 정상"
CONNECTION_TIMEOUT_SEC = 30
# 30초 — 1초 송신 주기 기준으로 30회 미수신이면 끊김 판정
# ⚠️ 모듈 레벨 상수 — settings로 외부화하면 환경별 튜닝 가능


@login_required(login_url='/accounts/login/')
def worker_list_page(request):
    """
    작업자 현황 목록 페이지.

    초기 렌더는 쉘만 깔아두고, 실제 데이터는
    JS 가 /workers/api/list/ 를 호출해서 받는다. (Phase 4B 에서 폴링/WS 전환 용이)
    """
    # ⭐ 패턴: HTML 쉘 + 별도 JSON API → SPA-like 동작
    #    초기 페이지 응답에 데이터를 안 박아서 render 빠름
    #    Phase 4B에서 폴링 또는 WebSocket 전환 시 이 파일은 그대로 유지 가능
    return render(request, 'workers/list.html')
    # 컨텍스트 없음 — 모든 데이터는 WorkerListDataView가 공급


def _get_worker_state_map() -> dict[str, str]:
    """
    state_store 에서 각 작업자의 현재 상태(safe/caution/danger/critical) 를 읽어온다.

    alerts.state_store 가 Redis 기반이므로, 의존성 방향 유지를 위해
    실패해도 빈 dict 반환 (페이지는 계속 렌더).
    """
    # 의존성 방어 — alerts 앱이 망가져도 workers 페이지는 살아남도록
    try:
        from alerts.state_store import get_worker_snapshot
        # 함수 내부 import — alerts↔workers 순환 참조 가능성 회피
    except Exception:
        return {}
        # alerts 앱 미설치/Redis 미가동 등 광범위 실패 모두 흡수

    result: dict[str, str] = {}
    for w in Worker.objects.filter(is_active=True).only('worker_id'):
        # only('worker_id') — 다른 컬럼 안 가져오기 (deferred field 최적화)
        try:
            snap = get_worker_snapshot(w.worker_id)
            # Redis HGETALL — 작업자당 1번 RTT
            # ⚠️ N+1과 비슷한 패턴 (작업자 100명이면 Redis 100번 호출)
            #    개선안: pipeline 사용 또는 일괄 조회 함수 만들기
            if snap:
                result[w.worker_id] = snap.get('state', 'safe')
            else:
                result[w.worker_id] = 'safe'
        except Exception:
            result[w.worker_id] = 'safe'
            # 개별 작업자 조회 실패 시 안전 측 기본값
    return result


def _get_worker_zone_map() -> dict[str, str]:
    """
    각 작업자가 현재 있는 지오펜스 이름(= '작업지명') 매핑.

    WorkerLocation 마지막 좌표로 GeoFence polygon 포함 여부를 계산.
    없으면 빈 문자열.
    """
    # 작업자 현황 페이지의 '작업지' 컬럼 데이터 공급
    try:
        from geofence.models import GeoFence
    except Exception:
        return {}

    # 전체 활성 geofence (polygon = [[x,y], ...])
    fences = list(
        GeoFence.objects.filter(is_active=True).values('name', 'polygon')
        # values() — 딕셔너리 리스트로 변환 (모델 인스턴스 생성 비용 절감)
    )

    result: dict[str, str] = {}
    latest_by_worker = {}
    for loc in WorkerLocation.objects.select_related('worker')[:500]:
        # ⚠️ 하드코딩 [:500] — 작업자 수가 많거나 송신 주기가 빠르면 일부 작업자 누락
        #    개선안: SQL DISTINCT ON (PostgreSQL) 또는 서브쿼리로 작업자별 최신 1건 가져오기
        # 이미 최신 1건 잡힘 (ordering -timestamp)
        if loc.worker.worker_id in latest_by_worker:
            continue
            # 같은 작업자 두 번째 등장은 스킵 — 시간 내림차순이라 첫 번째가 최신
        latest_by_worker[loc.worker.worker_id] = (loc.x, loc.y)

    for wid, (x, y) in latest_by_worker.items():
        zone_name = ''
        for fence in fences:
            poly = fence.get('polygon') or []
            if len(poly) >= 3 and _point_in_polygon(x, y, poly):
                zone_name = fence['name']
                break
                # 첫 매칭만 — 다중 소속 지오펜스가 있어도 1개만 표시
                # ⚠️ alerts._classify_state는 모든 매칭을 보고 우선순위 결정 — 정책 차이
        result[wid] = zone_name
    return result


def _point_in_polygon(x: float, y: float, poly: list) -> bool:
    """Ray casting — poly 는 [[x1,y1],[x2,y2],...]"""
    # ⚠️ geofence.services.point_in_polygon과 중복 정의 — DRY 위반
    #    이 파일에서도 같은 알고리즘을 다시 구현
    #    개선안: from geofence.services import point_in_polygon로 통합
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi):
            # ⭐ ((yj - yi) or 1e-9) — geofence.services와 다름
            #    여기는 ZeroDivisionError 방어책 추가됨
            #    geofence.services는 조건 1로 사전 필터에 의지
            inside = not inside
        j = i
    return inside


class WorkerListDataView(APIView):
    """
    작업자 목록 + 요약 데이터 (JSON).
    """
    # 작업자 현황 페이지의 백엔드 — JS가 fetch로 호출
    permission_classes = [IsAuthenticated]
    # 로그인 필수 — 작업자 개인정보(이메일/연락처) 노출이라 보호 필요

    def get(self, request):
        now = timezone.now()
        cutoff = now - timedelta(seconds=CONNECTION_TIMEOUT_SEC)
        # 30초 컷오프 — 이후 last_seen_at >= cutoff 비교

        workers_qs = Worker.objects.filter(is_active=True).order_by('worker_id')
        # 활성 작업자만, ID 순 정렬

        state_map = _get_worker_state_map()
        # Redis에서 작업자별 현재 알람 상태 한 번에
        zone_map  = _get_worker_zone_map()
        # 작업자별 현재 작업지(지오펜스 이름) 한 번에

        workers_data = []
        checked_in_count = 0
        # '출근' 카운트 — 30초 내 송신 있는 작업자 수
        status_counter = {'danger': 0, 'caution': 0, 'safe': 0}
        # UI 3-배지 카운트 (danger / caution / safe)

        for w in workers_qs:
            connection_ok = bool(w.last_seen_at and w.last_seen_at >= cutoff)
            # last_seen_at 존재 + 30초 이내 → 연결 정상
            if connection_ok:
                checked_in_count += 1

            status = state_map.get(w.worker_id, 'safe')
            # critical 은 UI 표시상 danger 로 합침 (3-배지 체계)
            ui_status = 'danger' if status in ('danger', 'critical') else status
            # ⭐ 4단계 상태(safe/caution/danger/critical) → UI 3-state 매핑
            #    critical은 색상 의미상 danger와 같은 빨간 계열로 통합
            if ui_status not in status_counter:
                ui_status = 'safe'
                # 예상치 못한 상태값은 safe로 fallback (방어적 코딩)
            status_counter[ui_status] += 1

            workers_data.append({
                'worker_id':    w.worker_id,
                'name':         w.name,
                'department':   w.department,
                'position':     w.position,
                'email':        w.email,
                'phone':        w.phone,
                # ⚠️ 개인정보(email/phone) 모두 노출 — 권한 차등화 필요할 수도
                'zone_name':    zone_map.get(w.worker_id, ''),
                'last_seen_at': w.last_seen_at.isoformat() if w.last_seen_at else None,
                'connection_ok': connection_ok,
                'status':       ui_status,
            })

        return Response({
            'summary': {
                'total':       workers_qs.count(),
                # ⚠️ COUNT 1번 추가 SQL — workers_data 길이로 대체 가능 (len(workers_data))
                'checked_in':  checked_in_count,
                'by_status':   status_counter,
            },
            'workers': workers_data,
        })


@method_decorator(csrf_exempt, name='dispatch')
# CSRF 면제 — devices.SensorDataView와 동일 패턴
# ⚠️ csrf_exempt + IsAuthenticated 조합 — 세션 기반 인증인데 CSRF 보호 없음
#    이론상 CSRF 공격 가능 (인증된 세션을 외부 사이트가 악용)
#    개선안: API는 JWT, 세션 쿠키 사용 시 CSRF 토큰 유지
class WorkerNotifyView(APIView):
    """
    푸시 알림 전송 (Phase 4A 더미).
    """
    permission_classes = [IsAuthenticated]
    # 로그인된 사용자만 알림 발송 가능

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
            # send_type 화이트리스트 검증
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
            # 모델의 max_length=200과 일치 — 이중 방어선
            # ⚠️ docstring은 "100자 권장"이지만 실제 한계는 200자 — 일관성 부재

        # ─── 수신자 결정 ───
        if send_type == 'all':
            recipients = list(Worker.objects.filter(is_active=True))
            # 활성 작업자 전원 스냅샷 — 이 시점의 명단이 영구 보존됨
        else:
            if not isinstance(recipient_ids, list) or not recipient_ids:
                return Response(
                    {'status': 'error', 'message': '수신 대상을 지정해주세요.'},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
                # single/selected는 recipients 배열 필수
            recipients = list(
                Worker.objects.filter(
                    worker_id__in=recipient_ids, is_active=True,
                )
            )
            # worker_id 기반 조회 + 활성 작업자만
            if not recipients:
                return Response(
                    {'status': 'error', 'message': '유효한 수신 대상이 없습니다.'},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
                # 잘못된 worker_id만 보냈거나 모두 비활성인 경우

        # ─── DB 저장 ───
        with transaction.atomic():
            # NotificationLog INSERT + recipients M2M SET을 원자적으로 묶음
            # 중간 실패 시 롤백 — DB 정합성 보호
            log = NotificationLog.objects.create(
                sender=request.user,
                send_type=send_type,
                message=message,
            )
            log.recipients.set(recipients)
            # M2M 일괄 설정 — 기존 관계 모두 새 list로 교체

        return Response(
            {
                'status':          'ok',
                'notification_id': log.id,
                'sent_at':         log.sent_at.isoformat(),
                'recipient_count': len(recipients),
            },
            status=http_status.HTTP_201_CREATED,
        )
        # ⚠️ 실제 푸시 전송 안 함 — Phase 4A는 DB 로깅까지만
        #    Phase 4B에서 FCM/APNs/WebSocket 발송 추가 예정