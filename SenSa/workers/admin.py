"""
workers/admin.py — Django Admin 등록

/admin/workers/worker/            → 작업자 목록
/admin/workers/workerlocation/    → 위치 이력
/admin/workers/notificationlog/   → 알림 전송 이력 (Phase 4A)
"""

from django.contrib import admin
# Django 관리자 페이지 기능을 사용하기 위해 admin 모듈을 불러와
from .models import NotificationLog, Worker, WorkerLocation
# workers 앱의 3종 모델 모두 import — 각각 admin 등록


@admin.register(Worker)
# Worker 모델을 admin에 등록하는 데코레이터
class WorkerAdmin(admin.ModelAdmin):
    # Worker 모델의 admin 화면 커스터마이즈
    list_display = ['worker_id', 'name', 'department', 'position',
                    'phone', 'last_seen_at', 'is_active', 'created_at']
    # 목록 화면 컬럼 — Phase 4A 신규 필드(position, phone, last_seen_at) 모두 노출
    # ⚠️ email 누락 — search_fields엔 있지만 list_display엔 없어 한눈에 안 보임
    list_filter = ['is_active', 'department', 'position']
    # 사이드바 필터 — 부서별/직급별 분류로 운영자가 빠르게 그룹 조회 가능
    search_fields = ['worker_id', 'name', 'email', 'phone']
    # 검색창 대상 — 식별자/이름/이메일/연락처로 작업자 찾기
    readonly_fields = ['created_at', 'last_seen_at']
    # 자동 생성/시스템 필드는 수정 불가 — 운영자 실수로 last_seen_at을 임의 변경하는 것 차단
    # last_seen_at은 WorkerLocationViewSet.perform_create가 자동 갱신하는 값

    fieldsets = (
    # 상세 화면 필드 그룹화 — 정보 종류별로 섹션 분리해 가독성 ↑
        ('기본 정보', {
            'fields': ('worker_id', 'name', 'department', 'position', 'is_active'),
            # 작업자의 정체성/소속 정보
        }),
        ('연락처', {
            'fields': ('email', 'phone'),
            # 알림 발송 시 사용될 수 있는 채널 정보 (Phase 4B+ 푸시 발송용)
        }),
        ('시스템', {
            'fields': ('last_seen_at', 'created_at'),
            'classes': ('collapse',),
            # collapse — 기본 접힘 상태로 표시 (자주 보지 않는 메타 정보)
        }),
    )


@admin.register(WorkerLocation)
# 위치 이력 admin 등록 — 시계열 데이터의 운영 디버깅용
class WorkerLocationAdmin(admin.ModelAdmin):
    list_display = ['worker', 'x', 'y', 'movement_status', 'timestamp']
    # 위치 이력 컬럼 — 누구의 어느 시각 어떤 좌표인지 한눈에
    list_filter = ['movement_status', 'worker']
    # ⚠️ 'worker' 필터 — 작업자 수가 100명+이면 사이드바가 너무 길어짐
    #    autocomplete_fields 또는 list_filter에서 제거 권장
    readonly_fields = ['timestamp']
    # auto_now_add 필드는 수정 불가
    raw_id_fields = ['worker']
    # FK 입력 시 select 박스 대신 ID 입력 + 검색 팝업 — 작업자가 많을 때 성능 최적화


@admin.register(NotificationLog)
# Phase 4A 신규 — 관리자가 보낸 푸시 알림 이력
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'sender', 'send_type', 'recipient_count',
                    'message_preview', 'sent_at']
    # 목록 컬럼 — 누가 어떤 유형으로 몇 명에게 무슨 메시지를 보냈는지 요약
    list_filter = ['send_type', 'sent_at']
    # 전송유형별/날짜별 필터 — 'sent_at'은 date hierarchy 같은 효과
    search_fields = ['message']
    # 메시지 본문으로 검색 — 특정 사건 관련 알림 추적용
    readonly_fields = ['sent_at']
    filter_horizontal = ['recipients']
    # M2M 필드를 좌우 박스 UI로 표시 — 수신자 다중 선택 시 직관적
    # raw_id_fields와 달리 모든 작업자 후보가 보임 (작업자 수 많으면 느려짐)

    @admin.display(description='수신자 수')
    # 컬럼 헤더에 표시될 한국어 라벨
    def recipient_count(self, obj):
        # 가상 컬럼 — DB 필드가 아닌 메서드 결과를 표시
        return obj.recipients.count()
        # ⚠️ N+1 쿼리 — 목록에 50건 표시되면 50번의 COUNT SQL 발생
        #    개선안: get_queryset 오버라이드해서 .annotate(_recip_count=Count('recipients'))

    @admin.display(description="메시지")
    def message_preview(self, obj):
        # 메시지 본문 미리보기 — 40자 초과 시 말줄임표 추가
        return (obj.message[:40] + '…') if len(obj.message) > 40 else obj.message
        # 목록 화면 가독성 확보 — 전체 메시지는 상세 화면에서 확인
