"""
safety/views.py — 안전 확인 체크리스트 페이지 + 제출 API

[변경 이력]
  v1 : 기본 체크리스트 페이지
  v2 : 사이드바에 VR 교육 완료 상태 표시용 context 추가
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .checklist_data import CHECKLIST_ITEMS, get_all_item_keys, get_total_count
from .models import SafetyChecklist


# ═══════════════════════════════════════════════════════════
# 페이지 뷰
# ═══════════════════════════════════════════════════════════

@login_required(login_url='/accounts/login/')
def checklist_page(request):
    """체크리스트 페이지 + 사이드바 컨텍스트."""
    today = timezone.localdate()

    existing = SafetyChecklist.objects.filter(
        user=request.user, check_date=today,
    ).first()
    checklist_done = existing is not None

    # VR 완료 여부 — 사이드바 뱃지에 사용
    # 지연 import: safety → vr_training 의존성만 한쪽 방향으로 유지
    vr_completed = False
    try:
        from vr_training.models import VRTrainingLog
        vr_log = VRTrainingLog.objects.filter(
            user=request.user, check_date=today, is_completed=True,
        ).first()
        vr_completed = vr_log is not None
    except Exception:
        # vr_training 앱 미로드 시에도 체크리스트는 동작해야 함
        vr_completed = False

    context = {
        'checklist_categories': CHECKLIST_ITEMS,
        'total_count': get_total_count(),
        'today': today,
        'already_completed': checklist_done,
        'previously_checked': existing.checked_items if existing else [],
        # 사이드바용
        'checklist_done': checklist_done,
        'vr_completed': vr_completed,
    }
    return render(request, 'safety/checklist.html', context)


# ═══════════════════════════════════════════════════════════
# 제출 API
# ═══════════════════════════════════════════════════════════

@method_decorator(csrf_exempt, name='dispatch')
class ChecklistSubmitView(APIView):
    """체크리스트 제출 API."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        checked_items = request.data.get('checked_items', [])
        if not isinstance(checked_items, list):
            return Response(
                {'status': 'error', 'message': 'checked_items 는 배열이어야 합니다.'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        checked_items = sorted({str(k) for k in checked_items})

        all_keys = set(get_all_item_keys())
        checked_set = set(checked_items)
        missing = sorted(all_keys - checked_set)
        invalid = sorted(checked_set - all_keys)

        if invalid:
            return Response(
                {
                    'status': 'error',
                    'message': f'정의되지 않은 항목 key 가 포함됨: {invalid}',
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        if missing:
            return Response(
                {
                    'status': 'incomplete',
                    'message': '모든 항목을 체크해주세요.',
                    'missing_keys': missing,
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        today = timezone.localdate()
        obj, created = SafetyChecklist.objects.update_or_create(
            user=request.user,
            check_date=today,
            defaults={'checked_items': checked_items},
        )

        return Response(
            {
                'status': 'ok',
                'created': created,
                'check_date': obj.check_date.isoformat(),
                'completed_at': obj.completed_at.isoformat(),
                'total_count': get_total_count(),
                'checked_count': len(checked_items),
            },
            status=http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK,
        )