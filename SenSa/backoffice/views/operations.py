"""
backoffice/views/operations.py — 운영 데이터 관리.

2개 도메인 (모두 운영 데이터 라이프사이클 관리):
  - 보관 정책 (DataRetentionPolicy) — 피그마 '운영 데이터 관리'
  - 백업 + 초기화 (v7, 4차 작업) — backoffice/utils/backup.py 활용

라우팅:
  보관 정책:
    GET  /backoffice/operations/                          → retention_list
    GET  /backoffice/api/retention/<pk>/                  → retention_detail_api
    POST /backoffice/api/retention/<pk>/update/           → retention_update_api
    POST /backoffice/api/retention/<pk>/run-now/          → retention_run_now_api

  v7 백업 + 초기화:
    POST /backoffice/api/retention/<pk>/backup/           → retention_backup_api
    POST /backoffice/api/retention/<pk>/init-with-backup/ → retention_init_with_backup_api
    GET  /backoffice/operations/backups/                  → backup_list
    GET  /backoffice/api/backups/<target>/<filename>/preview/  → backup_preview_api
    GET  /backoffice/api/backups/<target>/<filename>/download/ → backup_download_api
    POST /backoffice/api/backups/<target>/<filename>/delete/   → backup_delete_api
"""
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from ..forms import DataRetentionForm
from ..models import DataRetentionPolicy
from ..permissions import super_admin_required, super_admin_required_api
from ..utils import backup as backup_util
from ._common import _parse_json, _form_errors_payload


# ═══════════════════════════════════════════════════════════
# 보관 정책 (Data Retention)
# ═══════════════════════════════════════════════════════════

@super_admin_required(menu_code='operations')
def retention_list(request):
    rows = list(DataRetentionPolicy.objects.all().order_by('target'))

    # 각 target 별 현재 누적 건수 (대략) 표시
    from devices.models import SensorData
    from workers.models import WorkerLocation
    from alerts.models import Alarm
    from ..models import NotificationLog
    counts = {
        'sensor_data':       SensorData.objects.count(),
        'worker_location':   WorkerLocation.objects.count(),
        'alarms':            Alarm.objects.count(),
        'notification_logs': NotificationLog.objects.count(),
        'audit_logs':        0,  # 미구현
    }
    return render(request, 'backoffice/operations/retention_list.html', {
        'rows': rows,
        'counts': counts,
        'active_menu': 'retention',
    })


def _retention_to_dict(p: DataRetentionPolicy) -> dict:
    return {
        'id': p.id, 'target': p.target,
        'target_display': p.get_target_display(),
        'retention_days': p.retention_days,
        'is_active': p.is_active,
        'last_run_at': p.last_run_at.strftime('%Y-%m-%d %H:%M') if p.last_run_at else None,
        'last_run_deleted': p.last_run_deleted,
        'description': p.description,
        'updated_at': p.updated_at.strftime('%Y-%m-%d %H:%M') if p.updated_at else '-',
    }


@super_admin_required_api(menu_code='operations', action='read')
@require_GET
def retention_detail_api(request, pk):
    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    return JsonResponse({'retention': _retention_to_dict(p)})


@super_admin_required_api(menu_code='operations', action='write')
@require_POST
def retention_update_api(request, pk):
    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    form = DataRetentionForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    p = form.save(by=request.user)
    return JsonResponse({'ok': True, 'retention': _retention_to_dict(p)})


@super_admin_required_api(menu_code='operations', action='write')
@require_POST
def retention_run_now_api(request, pk):
    """단건 정책 즉시 실행 — 백그라운드 큐 없이 동기로 처리.
    레코드 수가 많으면 timeout 가능성 있어 v6 에서 큐로 분리 권장.
    """
    from datetime import timedelta as _td
    from ..management.commands.cleanup_data import _resolve_qs

    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    if not p.is_active:
        return JsonResponse({'ok': False, 'error': '비활성 정책은 실행할 수 없습니다.'}, status=400)

    cutoff = timezone.now() - _td(days=p.retention_days)
    qs = _resolve_qs(p.target, cutoff)
    if qs is None:
        return JsonResponse({'ok': False, 'error': '대상 모델 매핑이 없습니다.'}, status=400)

    deleted, _ = qs.delete()
    p.last_run_at = timezone.now()
    p.last_run_deleted = deleted
    p.save(update_fields=['last_run_at', 'last_run_deleted'])
    return JsonResponse({'ok': True, 'deleted': deleted, 'retention': _retention_to_dict(p)})


# ═══════════════════════════════════════════════════════════
# v7 — 운영 데이터 백업 + 초기화 + 조회 (4차 작업)
# ═══════════════════════════════════════════════════════════

def _audit_log_backup_action(request, action, target, filename=None, count=None):
    """백업/초기화 동작을 감사 로그에 기록.

    audit.py 의 일반 모델 변경 추적과 별도로, 운영 데이터 관리 액션을
    명시적으로 기록 (법정 요구).
    """
    try:
        from ..models import AuditLog
        AuditLog.objects.create(
            actor=request.user if request.user.is_authenticated else None,
            actor_username_snapshot=getattr(request.user, 'username', '') or '',
            action=action,  # 예: 'data_backup', 'data_init'
            target_app='backoffice',
            target_model='DataRetentionPolicy',
            target_pk=None,
            target_repr=f'{target} ({filename or "-"})',
            changes={'target': target, 'filename': filename, 'count': count},
            ip_address=request.META.get('REMOTE_ADDR', ''),
            request_path=request.path,
            extra_message=f'운영 데이터 {action}: {target}',
        )
    except Exception:
        # 감사 로그 실패가 본 작업을 막지 않도록 swallow
        pass


@super_admin_required_api(menu_code='retention', action='write')
@require_POST
def retention_backup_api(request, pk):
    """단건 정책의 데이터를 .json.gz 로 백업.

    동작:
    1. 서버 _backups/{target}/ 에 파일 저장
    2. 정책당 KEEP_BACKUPS (10개) 초과 시 가장 오래된 것 자동 삭제
    3. 응답 — 파일명/카운트/크기 (다운로드는 별도 API 로)
    """
    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    target = p.target

    if target not in backup_util.TARGET_REGISTRY:
        return JsonResponse({
            'ok': False,
            'errors': {'_form': [f'백업 미지원 target: {target}']},
        }, status=400)

    try:
        from backoffice.tasks import run_backup
        run_backup.delay(
            target,
            actor_id=request.user.id if request.user.is_authenticated else None,
            actor_username=getattr(request.user, 'username', '') or '',
            ip=request.META.get('REMOTE_ADDR', ''),
            path=request.path,
        )
        return JsonResponse({
            'ok': True,
            'async': True,
            'message': '백업을 백그라운드에서 시작했습니다. 잠시 후 백업 파일 조회에서 확인하세요.',
        }, status=202)
    except Exception as e:
        return JsonResponse({
            'ok': False,
            'errors': {'_form': [f'백업 시작 실패: {e}']},
        }, status=500)


@super_admin_required_api(menu_code='retention', action='write')
@require_POST
def retention_init_with_backup_api(request, pk):
    """단건 정책의 모든 데이터를 백업 후 삭제 (초기화).

    안전장치:
    1. 클라이언트가 confirm 필드에 'DELETE' 보내야 진행
    2. 백업 먼저 → 성공해야 삭제
    3. 모든 동작 감사 로그 기록
    """
    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    target = p.target

    # 안전장치 — confirm 텍스트 검증
    data = _parse_json(request)
    confirm = (data.get('confirm') or '').strip().upper()
    if confirm != 'DELETE':
        return JsonResponse({
            'ok': False,
            'errors': {'_form': ['확인 텍스트가 일치하지 않습니다. "DELETE" 를 정확히 입력하세요.']},
        }, status=400)

    if target not in backup_util.TARGET_REGISTRY:
        return JsonResponse({
            'ok': False,
            'errors': {'_form': [f'초기화 미지원 target: {target}']},
        }, status=400)

    # 무거운 백업+삭제는 Celery 워커로 오프로드 — 웹 요청은 즉시 반환.
    # (요청 안에서 동기 실행 시 daphne 워커가 오래 묶여 /metrics probe 실패 → Pod 재시작)
    try:
        from backoffice.tasks import run_init_with_backup
        run_init_with_backup.delay(
            target,
            actor_id=request.user.id if request.user.is_authenticated else None,
            actor_username=getattr(request.user, 'username', '') or '',
            ip=request.META.get('REMOTE_ADDR', ''),
            path=request.path,
        )
    except Exception as e:
        return JsonResponse({
            'ok': False,
            'errors': {'_form': [f'초기화 시작 실패: {e}']},
        }, status=500)

    return JsonResponse({
        'ok': True,
        'async': True,
        'message': '백업 후 삭제를 백그라운드에서 시작했습니다. 잠시 후 새로고침해 누적 건수를 확인하세요.',
    }, status=202)


@super_admin_required(menu_code='retention')
def backup_list(request):
    """백업 파일 조회 페이지."""
    files = backup_util.list_backup_files()
    return render(request, 'backoffice/operations/backup_list.html', {
        'active_menu': 'retention',
        'active_submenu': 'backups',
        'files': files,
        'total_count': len(files),
        'targets': backup_util.TARGET_REGISTRY,
    })


@super_admin_required_api(menu_code='retention', action='read')
@require_GET
def backup_preview_api(request, target, filename):
    """백업 파일 미리보기 (앞 100건)."""
    file_path = backup_util.find_backup_file(target, filename)
    if file_path is None:
        return JsonResponse({'ok': False, 'errors': {'_form': ['파일을 찾을 수 없습니다.']}}, status=404)

    limit = int(request.GET.get('limit', 100))
    limit = min(max(limit, 1), 500)  # 1~500 제한

    preview = backup_util.preview_backup(target, filename, limit=limit)
    if preview is None or 'error' in preview:
        return JsonResponse({
            'ok': False,
            'errors': {'_form': [preview.get('error', '미리보기 실패') if preview else '파일 없음']},
        }, status=500)

    return JsonResponse({
        'ok': True,
        'target': target,
        'filename': filename,
        'preview': preview,
    })


@super_admin_required_api(menu_code='retention', action='read')
@require_GET
def backup_download_api(request, target, filename):
    """백업 파일 다운로드."""
    file_path = backup_util.find_backup_file(target, filename)
    if file_path is None:
        raise Http404('백업 파일을 찾을 수 없습니다.')

    # FileResponse 사용 — 큰 파일도 스트리밍
    from django.http import FileResponse
    response = FileResponse(
        open(file_path, 'rb'),
        as_attachment=True,
        filename=filename,
        content_type='application/gzip',
    )

    _audit_log_backup_action(request, 'backup_download', target, filename=filename)

    return response


@super_admin_required_api(menu_code='retention', action='write')
@require_POST
def backup_delete_api(request, target, filename):
    """백업 파일 삭제."""
    if not backup_util.delete_backup_file(target, filename):
        return JsonResponse({'ok': False, 'errors': {'_form': ['파일을 찾을 수 없습니다.']}}, status=404)

    _audit_log_backup_action(request, 'backup_delete', target, filename=filename)

    return JsonResponse({'ok': True, 'message': f'{filename} 삭제 완료'})
