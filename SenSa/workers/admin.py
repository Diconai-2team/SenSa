"""
workers/admin.py — Django Admin에 작업자 모델 등록

/admin/workers/worker/          → 작업자 목록
/admin/workers/workerlocation/  → 위치 이력
"""
from django.contrib import admin
from .models import Worker, WorkerLocation
# .models → 같은 앱(workers) 안의 models.py


@admin.register(Worker)
# ↑ Worker 모델을 아래 WorkerAdmin 설정으로 Admin에 등록
# admin.site.register(Worker, WorkerAdmin) 과 동일한 의미
class WorkerAdmin(admin.ModelAdmin):

    # ── 목록 페이지에서 보여줄 컬럼들 ──
    # /admin/workers/worker/ 에 표(table) 형태로 표시
    list_display = ['worker_id', 'name', 'department', 'is_active', 'created_at']

    # ── 우측 필터 사이드바 ──
    # "활성 여부", "부서"로 필터링 가능
    list_filter = ['is_active', 'department']

    # ── 상단 검색창 ──
    # worker_id나 name에서 검색
    search_fields = ['worker_id', 'name']

    # ── 수정 화면에서 편집 불가 필드 ──
    # created_at은 자동 생성이므로 수정하면 안 됨
    readonly_fields = ['created_at']


@admin.register(WorkerLocation)
class WorkerLocationAdmin(admin.ModelAdmin):

    list_display = ['worker', 'x', 'y', 'movement_status', 'timestamp']

    # worker별, 이동상태별 필터
    list_filter = ['movement_status', 'worker']

    readonly_fields = ['timestamp']

    # ── raw_id_fields ──
    # FK 필드를 드롭다운 대신 "ID 직접입력 + 검색 팝업"으로 변경
    # WorkerLocation이 수만 건이 되면 드롭다운이 느려지기 때문
    # 일반 ForeignKey: 드롭다운에 Worker 전체 목록 로드
    # raw_id_fields:   숫자 입력칸 + 돋보기 아이콘(검색 팝업)
    raw_id_fields = ['worker']