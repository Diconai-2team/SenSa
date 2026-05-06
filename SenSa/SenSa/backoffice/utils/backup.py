"""
backoffice/utils/backup.py — 운영 데이터 백업 + 복원 + 조회 도우미.

핵심 기능:
1. 스트리밍 백업: 122,000+ 건도 메모리 안전하게 .json.gz 로 압축
2. 파일 관리: 정책당 N개 유지 (오래된 것 자동 삭제)
3. 조회: 압축 파일을 풀어서 미리보기 / 전체 조회
4. 복원: Django loaddata 호환 형식

설계 원칙:
- Django Fixtures JSON 형식 (loaddata 로 즉시 복원 가능)
- gzip 으로 70~80% 압축
- iterator(chunk_size=1000) 로 메모리 안전
"""
import gzip
import json
from datetime import datetime
from pathlib import Path

from django.apps import apps
from django.core import serializers


# ═══════════════════════════════════════════════════════════
# Target Registry — 5개 데이터 모델 매핑
# ═══════════════════════════════════════════════════════════

TARGET_REGISTRY = {
    'alarms': {
        'app_model':   'alerts.Alarm',
        'time_field':  'created_at',
        'display':     '알람',
    },
    'audit_logs': {
        'app_model':   'backoffice.AuditLog',
        'time_field':  'created_at',
        'display':     '감사 로그',
    },
    'notification_logs': {
        'app_model':   'backoffice.NotificationLog',
        'time_field':  'created_at',
        'display':     '알림 발송 이력',
    },
    'sensor_data': {
        'app_model':   'devices.SensorData',
        'time_field':  'timestamp',
        'display':     '센서 측정값',
    },
    'worker_location': {
        'app_model':   'workers.WorkerLocation',
        'time_field':  'timestamp',
        'display':     '작업자 위치',
    },
}

# 백업 디렉토리 (프로젝트 루트 기준)
BACKUP_ROOT = Path('_backups')

# 정책당 유지 백업 개수
KEEP_BACKUPS = 10


def get_model_for_target(target):
    """target 문자열 → Django Model 클래스. 매핑 없으면 None."""
    if target not in TARGET_REGISTRY:
        return None
    app_model = TARGET_REGISTRY[target]['app_model']
    app_label, model_name = app_model.split('.')
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def make_backup_filename(target):
    """타겟 + 현재 시각으로 파일명 생성. 예: sensor_data_20260501_153020.json.gz"""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f'{target}_{ts}.json.gz'


def get_backup_dir(target):
    """target 의 백업 디렉토리. 없으면 생성."""
    d = BACKUP_ROOT / target
    d.mkdir(parents=True, exist_ok=True)
    return d


# ═══════════════════════════════════════════════════════════
# 백업 (스트리밍 dump)
# ═══════════════════════════════════════════════════════════

def stream_backup_to_file(target, file_path=None):
    """target 의 모든 데이터를 .json.gz 파일로 스트리밍 저장.

    Returns:
        dict: {'count': int, 'path': str, 'size_bytes': int}
    """
    Model = get_model_for_target(target)
    if Model is None:
        raise ValueError(f'Unknown target: {target!r}')

    if file_path is None:
        file_path = get_backup_dir(target) / make_backup_filename(target)
    else:
        file_path = Path(file_path)

    qs = Model.objects.all().order_by('id').iterator(chunk_size=1000)
    count = 0

    # gzip 으로 직접 쓰기 (메모리 안전)
    with gzip.open(file_path, 'wt', encoding='utf-8', compresslevel=6) as f:
        f.write('[\n')
        first = True
        for obj in qs:
            # 단일 객체 직렬화 → "[{...}]" 형태
            data = serializers.serialize('json', [obj])
            inner = data[1:-1]  # 양쪽 [] 제거
            if not first:
                f.write(',\n')
            f.write(inner)
            first = False
            count += 1
        f.write('\n]\n')

    size_bytes = file_path.stat().st_size
    return {
        'count': count,
        'path': str(file_path),
        'filename': file_path.name,
        'size_bytes': size_bytes,
    }


# ═══════════════════════════════════════════════════════════
# 파일 관리 (오래된 것 자동 정리)
# ═══════════════════════════════════════════════════════════

def cleanup_old_backups(target, keep=KEEP_BACKUPS):
    """target 의 백업 파일 중 가장 최신 keep 개만 남기고 삭제.

    Returns:
        int: 삭제된 파일 개수
    """
    backup_dir = BACKUP_ROOT / target
    if not backup_dir.exists():
        return 0

    files = sorted(
        backup_dir.glob(f'{target}_*.json.gz'),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    deleted = 0
    for old_file in files[keep:]:
        old_file.unlink()
        deleted += 1

    return deleted


def list_backup_files(target=None):
    """백업 파일 목록. target=None 이면 전체."""
    if not BACKUP_ROOT.exists():
        return []

    targets = [target] if target else list(TARGET_REGISTRY.keys())
    files = []

    for t in targets:
        target_dir = BACKUP_ROOT / t
        if not target_dir.exists():
            continue
        for f in target_dir.glob(f'{t}_*.json.gz'):
            stat = f.stat()
            files.append({
                'target': t,
                'target_display': TARGET_REGISTRY.get(t, {}).get('display', t),
                'filename': f.name,
                'path': str(f),
                'size_bytes': stat.st_size,
                'size_human': _human_size(stat.st_size),
                'created_at': datetime.fromtimestamp(stat.st_mtime),
            })

    files.sort(key=lambda x: x['created_at'], reverse=True)
    return files


def find_backup_file(target, filename):
    """파일명으로 백업 파일 경로 찾기. 보안 — 디렉토리 탈출 방지."""
    if target not in TARGET_REGISTRY:
        return None
    if '/' in filename or '\\' in filename or '..' in filename:
        return None  # 디렉토리 탈출 시도 차단
    file_path = BACKUP_ROOT / target / filename
    if not file_path.exists():
        return None
    if not file_path.is_file():
        return None
    return file_path


def delete_backup_file(target, filename):
    """백업 파일 삭제."""
    file_path = find_backup_file(target, filename)
    if file_path is None:
        return False
    file_path.unlink()
    return True


# ═══════════════════════════════════════════════════════════
# 조회 (압축 풀고 미리보기 / 전체)
# ═══════════════════════════════════════════════════════════

def preview_backup(target, filename, limit=100):
    """백업 파일에서 앞 limit 건만 미리보기.

    Returns:
        dict: {'count_preview': N, 'records': [...], 'total_in_file': int}
    """
    file_path = find_backup_file(target, filename)
    if file_path is None:
        return None

    records = []
    total = 0
    with gzip.open(file_path, 'rt', encoding='utf-8') as f:
        # JSON 전체 로드는 큰 파일에서 비효율 → 라인 단위 처리
        # 그러나 fixtures 는 [....] 형태라 단순 readline 안 됨
        # 안전한 방법: 전체 로드 (preview 는 작은 limit 이라 OK)
        # 큰 파일이면 메모리 부담 → 추후 ijson 같은 streaming parser 권장
        try:
            data = json.load(f)
            total = len(data)
            for item in data[:limit]:
                # Django fixture 형식 → 사용자 친화적 평탄화
                flat = {
                    'id': item.get('pk'),
                    'model': item.get('model'),
                    **item.get('fields', {}),
                }
                records.append(flat)
        except json.JSONDecodeError as e:
            return {'error': f'JSON 파싱 실패: {e}', 'records': []}

    return {
        'count_preview': len(records),
        'total_in_file': total,
        'records': records,
    }


# ═══════════════════════════════════════════════════════════
# 삭제 (모든 데이터)
# ═══════════════════════════════════════════════════════════

def delete_all_data(target):
    """target 의 모든 데이터 삭제. 백업 후 호출 권장.

    Returns:
        int: 삭제된 레코드 수
    """
    Model = get_model_for_target(target)
    if Model is None:
        raise ValueError(f'Unknown target: {target!r}')

    deleted, _ = Model.objects.all().delete()
    return deleted


# ═══════════════════════════════════════════════════════════
# 헬퍼
# ═══════════════════════════════════════════════════════════

def _human_size(num_bytes):
    """1234567 → '1.2 MB' 형태."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if num_bytes < 1024:
            return f'{num_bytes:.1f} {unit}'
        num_bytes /= 1024
    return f'{num_bytes:.1f} PB'
