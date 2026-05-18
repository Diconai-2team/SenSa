"""
관리 명령: 근접도 캐시 사전 로드 (선택사항).

캐시는 lazy load 되므로 명시적 빌드 없어도 동작.
다만 첫 zone 발동 시 지연을 피하려면 서버 기동 후 한 번 실행 권장.

사용:
    python manage.py build_neighbor_cache
"""
from django.core.management.base import BaseCommand
from devices.neighbor_graph import (
    invalidate_neighbor_cache,
    _ensure_loaded,
    cache_stats,
)


class Command(BaseCommand):
    help = '센서 근접도 메모리 캐시를 사전 로드 (lazy load 회피용)'

    def handle(self, *args, **options):
        self.stdout.write('근접도 캐시 사전 로드 중...')

        invalidate_neighbor_cache()
        _ensure_loaded()
        stats = cache_stats()

        self.stdout.write(self.style.SUCCESS(
            f"완료: {stats['source_count']} 센서, "
            f"{stats['total_edges']} edge 캐시됨"
        ))
