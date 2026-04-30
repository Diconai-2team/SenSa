"""
monitor 앱 뷰

- map_view: 관제 지도 페이지 (Template)
- MapImageViewSet: 공장 평면도 이미지 CRUD
- CheckGeofenceView: 상태 전이 기반 알람 오케스트레이터

[변경 이력]
  Phase E7 : 브라우저 시뮬 제거 후 안정화
  v2       : map_view 에 safety_checklist_done_today / vr_training_done_today context
  v3 (팀원 병합):
    - B1 : 근접 센서 계산 시 normal 센서는 거리 계산 스킵 (O(N·M) → O(N·k))
           수학적으론 동어반복이지만 의미 명확화 + 미미한 성능 개선
    - B3 : 영향 센서 목록 수집 (어떤 센서가 알람 원인인지 로깅용)
           evaluate_worker 로 전달되어 알람 메시지에 반영됨
"""
# ⭐ docstring 첫 줄이 'monitor 앱'으로 되어있음 — 'dashboard 앱'의 옛 이름인 듯
# ⭐ 이 파일의 핵심: CheckGeofenceView가 시스템 전체의 알람 오케스트레이터

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
# 페이지 뷰의 today 계산용 (timezone-aware)

from rest_framework import viewsets, status
# 'status' 모듈을 그대로 사용 — devices/workers의 'http_status' alias와 다른 패턴
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
# 평면도 이미지 업로드용 — multipart/form-data 처리
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from alerts.services import evaluate_worker, evaluate_sensor
# 알람 오케스트레이션의 두 진입점 — 작업자 축 / 센서 축 평가
from .models import MapImage
from .serializers import MapImageSerializer
from realtime.publishers import publish_alarm
# 알람 발생 시 WebSocket으로 모든 대시보드에 broadcast
import math
# sqrt 사용 — 작업자-센서 거리 계산


# ============================================================
# 페이지 뷰
# ============================================================


@login_required(login_url="/accounts/login/")
def map_view(request):
    """
    관제 지도 페이지.

    context:
        safety_checklist_done_today (bool)
        vr_training_done_today (bool)
    """
    # 시스템 메인 화면 — SVG 평면도 + 작업자/센서/지오펜스 오버레이
    # context에 두 가지 부울만 추가 — 안전 체크리스트와 VR 교육 완료 여부 (UI 뱃지/모달 트리거용)
    today = timezone.localdate()
    # 로컬 날짜 기준 — UTC가 아니라 한국 시간 기준 자정으로 '오늘' 판정

    try:
        from safety.models import SafetyChecklist
        # 함수 내부 import — safety 앱이 미설치돼도 dashboard는 살아남도록
        checklist_done = SafetyChecklist.objects.filter(
            user=request.user,
            check_date=today,
        ).exists()
        # exists() — count 대신 사용해 1건만 확인되면 즉시 True (효율적)
    except Exception:
        checklist_done = False
        # 광범위 catch — safety 앱 자체가 없거나 모델 임포트 실패 모두 흡수
        # ⚠️ 정상 운영 환경에서 발생하면 안 되는 예외도 묻혀버릴 위험

    try:
        from vr_training.models import VRTrainingLog

        vr_done = VRTrainingLog.objects.filter(
            user=request.user,
            check_date=today,
            is_completed=True,
        ).exists()
        # is_completed=True — 시작만 하고 안 끝낸 교육은 '미완료'로 처리
    except Exception:
        vr_done = False

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "safety_checklist_done_today": checklist_done,
            "vr_training_done_today": vr_done,
        },
    )


# ============================================================
# API 뷰
# ============================================================


class MapImageViewSet(viewsets.ModelViewSet):
    """공장 평면도 이미지 CRUD"""

    permission_classes = [IsAuthenticated]
    # 로그인 필수 — 평면도는 시스템 좌표계의 기준이라 외부 노출 차단
    parser_classes = [MultiPartParser, FormParser]
    # multipart 파서 — 이미지 파일 + 메타데이터 동시 수신용
    queryset = MapImage.objects.all()
    # 활성/비활성 모두 — 운영자가 과거 평면도도 조회 가능 (재활성화 가능성)
    serializer_class = MapImageSerializer

    def perform_create(self, serializer):
        # POST 시 자동 호출되는 훅 — 신규 평면도 업로드 직전 처리
        MapImage.objects.filter(is_active=True).update(is_active=False)
        # 기존 활성 평면도 모두 비활성화 — 동시에 1장만 활성 정책
        # ⚠️ 트랜잭션 부재 — 위 UPDATE 후 아래 save()가 실패하면 활성 평면도 0개 상태가 됨
        #    개선안: @transaction.atomic 적용
        serializer.save(is_active=True)
        # 새 평면도를 활성 상태로 저장
        # ⚠️ width/height 자동 추출 안 함 — 클라이언트가 잘못된 값 보내면 좌표계 어긋남

    @action(detail=False, methods=['get'])
    # detail=False — /map/current/ 컬렉션 액션
    def current(self, request):
        # 현재 활성 평면도 1장만 반환 — 대시보드 초기 로드용
        current_map = MapImage.objects.filter(is_active=True).first()
        # 활성 1장만 — 정책상 0~1장 (perform_create가 보장)
        if current_map:
            serializer = self.get_serializer(current_map)
            return Response(serializer.data)
        return Response(
            {"detail": "업로드된 지도가 없습니다."}, status=status.HTTP_404_NOT_FOUND
        )
        # 평면도 없으면 404 — 운영자가 첫 사용 시 평면도 업로드 유도


PROXIMITY_RADIUS = 200   # 픽셀. 작업자가 센서에서 이 반경 안에 있으면 영향받음
# ⭐ 시스템 핵심 상수 — '근접' 정의의 단일 출처
# 200px = 평면도 크기에 따라 의미 다름 (1920x1080이면 약 10% 거리)
# ⚠️ 모듈 레벨 하드코딩 — settings로 외부화하면 환경별 튜닝 가능


def _compute_nearby_sensor_status(
    worker_x: float, worker_y: float, sensors: list, radius: float = PROXIMITY_RADIUS
) -> tuple[str, list]:
    """
    작업자 좌표 기준 반경 내 센서들의 최악 상태 반환.

    [팀원 병합 v3]
      B1: normal 센서는 거리 계산 자체를 스킵 (early continue)
          → 대부분의 시간 동안 센서 대부분이 normal 상태라
            실제 sqrt 호출 횟수가 크게 줄어듦.
            수학적 의미는 동일하지만 코드 의도가 명확해짐.

      B3: 반환값에 영향 센서 목록도 함께 돌려줌.
          형식: [(device_id, status), ...]
          알람 메시지에 "어떤 센서 때문인지" 로깅하는 용도.

    Returns:
        (worst_status, influencing_sensors)
          - worst_status: 'normal' | 'caution' | 'danger'
          - influencing_sensors: [(device_id, status), ...] 반경 내 비정상 센서만
    """
    # 작업자 1명 기준 모든 센서 순회 — O(M) 시간복잡도 (M = 센서 수)
    # 작업자 N명이면 총 O(N·M) — 작업자 100명 × 센서 50개 = 5,000회/사이클
    
    worst = 'normal'
    influencing: list = []
    # 영향 센서 목록 — alerts._build_message가 알람 본문에 노출

    for s in sensors:
        sensor_status = s.get("status", "normal")

        # ── B1: normal 센서는 거리 계산 생략 ──
        if sensor_status == "normal":
            continue
            # ⭐ 핵심 최적화 — 정상 센서는 거리 무관하게 작업자에 영향 없음
            # 대부분 시간 동안 센서 95%+ 가 normal이므로 sqrt 호출이 1/20로 줄어듦
            # 수학적으로는 worst='normal' 유지가 동일하지만, 의도가 명확해짐

        sx = float(s.get("x", 0))
        sy = float(s.get("y", 0))
        distance = math.sqrt((sx - worker_x) ** 2 + (sy - worker_y) ** 2)
        # 유클리드 거리 — sqrt 비용 있음
        # ⚠️ 최적화 가능: distance² ≤ radius²로 비교하면 sqrt 생략 가능
        if distance > radius:
            continue
            # 반경 밖 센서는 영향 없음

        # ── B3: 영향 센서 기록 ──
        device_id = s.get("device_id", "")
        influencing.append((device_id, sensor_status))
        # ISO 45001 추적성 — 어느 센서가 작업자 알람에 기여했는지 영구 기록

        if sensor_status == 'danger':
            worst = 'danger'
            # danger는 caution을 덮어씀 (한 번 danger 보이면 더 안 봐도 됨)
        elif worst != 'danger':  # caution, 아직 danger 아닐 때만 승격
            worst = 'caution'
            # 이미 danger로 격상됐으면 caution으로 다운그레이드 안 함
            # ⚠️ 미세 최적화 가능: danger 발견 시 break — 이후 센서 안 봐도 됨
            #    (단 B3의 영향 센서 목록은 다 모아야 함 — break 못 함)

    return worst, influencing


@method_decorator(csrf_exempt, name='dispatch')
# CSRF 면제 — 외부 디바이스/시뮬레이터의 POST 호출 받기 위함
# ⚠️ devices/workers와 동일 — 인증/CSRF 정책 일관 미흡
class CheckGeofenceView(APIView):
    """작업자/센서 상태 전이 기반 알람 오케스트레이터"""
    # ⭐ 시스템 핵심 진입점 — 다른 모든 앱의 도메인 로직이 여기서 만남
    # ⚠️ permission_classes 미지정 — 누구나 호출 가능 (위치/센서 데이터 조작 가능)

    def post(self, request):
        # 클라이언트가 한 사이클(예: 1초)의 작업자+센서 스냅샷을 보냄
        # 서버는 모든 작업자와 모든 센서를 한 번에 평가하고 발생한 알람 반환
        workers = request.data.get('workers', [])
        # [{worker_id, name, x, y}, ...] 형태
        sensors = request.data.get('sensors', [])
        # [{device_id, sensor_type, status, x, y, detail}, ...] 형태

        all_alarms = []
        # 이 사이클에서 발생한 모든 알람 누적

        # 1) 작업자 축 판정 — 각 작업자별로 근접 센서만 평가
        for worker in workers:
            w_id = worker.get("worker_id", "")
            if not w_id:
                continue
                # worker_id 없는 항목은 무시 (스키마 검증 부재)

            w_x = float(worker.get('x', 0))
            w_y = float(worker.get('y', 0))
            # ⚠️ float() 변환 — 'abc' 같은 비숫자 들어오면 ValueError → 500
            #    devices/views와 동일한 위험 (try/except 부재)

            # B1 + B3 : worst_status 와 함께 영향 센서 목록도 받음
            nearby_status, influencing_sensors = _compute_nearby_sensor_status(
                w_x, w_y, sensors
            )
            # 작업자 1명 기준 영향권 내 센서들의 worst-case + 영향 목록

            alarms = evaluate_worker(
                worker_id=w_id,
                worker_name=worker.get('name', w_id),
                # name 없으면 worker_id로 fallback — 알람 메시지 가독성 보장
                x=w_x,
                y=w_y,
                worst_sensor_status=nearby_status,
                influencing_sensors=influencing_sensors,  # B3
            )
            # alerts.evaluate_worker가 Hysteresis 통과시켜 알람 발행 결정
            all_alarms.extend(alarms)

        # 2) 센서 축 판정 — 기존 그대로
        for sensor in sensors:
            d_id = sensor.get("device_id", "")
            if not d_id:
                continue
            alarms = evaluate_sensor(
                device_id=d_id,
                sensor_type=sensor.get('sensor_type', ''),
                observed_status=sensor.get('status', 'normal'),
                detail=sensor.get('detail', ''),
                # detail은 알람 메시지에 추가 정보 노출용 (예: 측정값)
            )
            # alerts.evaluate_sensor가 센서별 Hysteresis 통과시켜 알람 발행 결정
            # ⚠️ 작업자 축과 센서 축이 별개로 알람 발행 → 같은 사건에 알람 2건 발생 가능
            #    (가스 센서 위험 + 그 근처 작업자 위험 → 센서 알람 + 작업자 알람)
            all_alarms.extend(alarms)

        # 3) WS 방송
        for alarm in all_alarms:
            publish_alarm(alarm)
            # 발생한 모든 알람을 대시보드 클라이언트에 즉시 broadcast
            # ⚠️ N건 개별 publish — 알람 폭주 시 WebSocket 부하
            #    개선안: 1번에 묶어서 broadcast (publish_alarm_batch)

        return Response({
            'alarms': all_alarms,
            'alarm_count': len(all_alarms),
            # 알람 0건도 정상 응답 — 클라이언트가 사이클 성공 여부 확인 가능
        })
        # ⚠️ 트랜잭션 부재 — workers/sensors 평가 도중 일부만 알람 생성 후 실패 시 정합성 깨짐
        # ⚠️ 동기 처리 — 작업자 100명 × 센서 50개 처리 시 응답 지연 가능
        #    Celery 등 비동기 큐 검토
