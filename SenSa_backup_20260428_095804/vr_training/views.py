"""
vr_training/views.py — VR 교육 페이지 + 진행/완료 API

[엔드포인트]
  GET  /vr-training/                  VR 교육 플레이어 페이지
  POST /vr-training/api/progress/     재생 위치 저장 (이탈 시점)
  POST /vr-training/api/complete/     완료 처리 (100% 도달)

[접근 제어]
  체크리스트 미완료 상태로 진입하면 체크리스트 페이지로 리다이렉트.
  사이드바에서 잠금이 걸리지만, URL 직타입 방어용 서버 가드.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from safety.models import SafetyChecklist

from .constants import VR_VIDEO_DURATION_SEC, VR_VIDEO_TITLE, VR_VIDEO_DESCRIPTION
from .models import VRTrainingLog


# ═══════════════════════════════════════════════════════════
# 페이지 뷰
# ═══════════════════════════════════════════════════════════


@login_required(login_url="/accounts/login/")
def player_page(request):
    """
    VR 교육 플레이어 페이지.

    선행 조건:
      오늘 안전 확인 체크리스트를 완료해야 함. 미완료 시 체크리스트로 돌려보냄.

    context:
      checklist_done         : 체크리스트 완료 여부 (사이드바 상태)
      vr_completed           : 오늘 이미 VR 완료했는가
      last_position_sec      : 재진입 시 재생 시작 지점
      total_duration_sec     : 영상 총 길이
      video_title/description
    """
    today = timezone.localdate()

    # ─── 선행 조건 — 체크리스트 완료 확인 ───
    checklist_done = SafetyChecklist.objects.filter(
        user=request.user,
        check_date=today,
    ).exists()

    if not checklist_done:
        messages.warning(
            request,
            "먼저 안전 확인 체크리스트를 완료해 주세요.",
        )
        return redirect("safety:checklist")

    # ─── 현재 VR 이력 조회 (이어보기용) ───
    log = VRTrainingLog.objects.filter(
        user=request.user,
        check_date=today,
    ).first()

    context = {
        "checklist_done": checklist_done,
        "vr_completed": bool(log and log.is_completed),
        "last_position_sec": log.last_position_sec if log else 0,
        "total_duration_sec": VR_VIDEO_DURATION_SEC,
        "video_title": VR_VIDEO_TITLE,
        "video_description": VR_VIDEO_DESCRIPTION,
    }
    return render(request, "vr_training/player.html", context)


# ═══════════════════════════════════════════════════════════
# API — 진행 저장 / 완료 처리
# ═══════════════════════════════════════════════════════════


def _clamp_position(seconds) -> int:
    """입력 seconds 를 [0, VR_VIDEO_DURATION_SEC] 범위로 자름."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        s = 0
    if s < 0:
        s = 0
    if s > VR_VIDEO_DURATION_SEC:
        s = VR_VIDEO_DURATION_SEC
    return s


@method_decorator(csrf_exempt, name="dispatch")
class VRProgressView(APIView):
    """
    재생 위치 저장 API.

    요청 (JSON):
        {"position_sec": 42}

    응답 (200):
        {
            "status": "ok",
            "last_position_sec": 42,
            "total_duration_sec": 60,
            "progress_percent": 70,
            "is_completed": false
        }

    [불변식]
      last_position_sec 은 감소하지 않음 (스킵/되감기 방지 정책).
      새 값이 기존보다 작으면 기존 값 유지 — 이탈 시점 저장은 순방향 진행만 기록.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        new_pos = _clamp_position(request.data.get("position_sec"))
        today = timezone.localdate()

        log, _ = VRTrainingLog.objects.get_or_create(
            user=request.user,
            check_date=today,
            defaults={
                "total_duration_sec": VR_VIDEO_DURATION_SEC,
                "last_position_sec": 0,
            },
        )

        # monotonic 증가 보장
        if new_pos > log.last_position_sec:
            log.last_position_sec = new_pos

        # 만약 total_duration 이 비어있으면 동기화
        if not log.total_duration_sec:
            log.total_duration_sec = VR_VIDEO_DURATION_SEC

        log.save(
            update_fields=["last_position_sec", "total_duration_sec", "updated_at"]
        )

        return Response(
            {
                "status": "ok",
                "last_position_sec": log.last_position_sec,
                "total_duration_sec": log.total_duration_sec,
                "progress_percent": log.progress_percent,
                "is_completed": log.is_completed,
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class VRCompleteView(APIView):
    """
    VR 교육 완료 처리.

    요청 (JSON): {} (body 불필요. 서버가 완료 조건 재검증)

    응답 (200 성공):
        {
            "status": "ok",
            "completed_at": "2026-04-24T11:30:01+09:00",
            "is_completed": true
        }

    응답 (400 실패 — 실제로 끝까지 시청 안 한 경우):
        {
            "status": "incomplete",
            "message": "영상 끝까지 시청 후 완료 처리 가능합니다.",
            "last_position_sec": 42,
            "total_duration_sec": 60
        }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localdate()
        log = VRTrainingLog.objects.filter(
            user=request.user,
            check_date=today,
        ).first()

        if not log:
            return Response(
                {
                    "status": "incomplete",
                    "message": "영상을 시청한 기록이 없습니다.",
                    "last_position_sec": 0,
                    "total_duration_sec": VR_VIDEO_DURATION_SEC,
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # 서버 측 재검증 — 클라가 last_position_sec 을 끝까지 보낸 상태여야 함
        if log.last_position_sec < log.total_duration_sec:
            return Response(
                {
                    "status": "incomplete",
                    "message": "영상 끝까지 시청 후 완료 처리 가능합니다.",
                    "last_position_sec": log.last_position_sec,
                    "total_duration_sec": log.total_duration_sec,
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # 이미 완료된 경우 멱등 응답
        if not log.is_completed:
            log.is_completed = True
            log.completed_at = timezone.now()
            log.save(update_fields=["is_completed", "completed_at", "updated_at"])

        return Response(
            {
                "status": "ok",
                "is_completed": True,
                "completed_at": log.completed_at.isoformat(),
            }
        )
