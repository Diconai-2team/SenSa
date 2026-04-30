from django.contrib import admin
# Django 관리자 페이지 기능을 사용하기 위해 admin 모듈을 불러와
from .models import Alarm
# 같은 앱(alerts)의 models.py에서 Alarm 모델을 불러와


@admin.register(Alarm)
# Alarm 모델을 Django 관리자 페이지에 등록하는 데코레이터 — 아래 AlarmAdmin 설정대로 표시돼
class AlarmAdmin(admin.ModelAdmin):
    # Alarm 모델의 admin 화면을 커스터마이즈하는 클래스야
    list_display = ['alarm_type', 'alarm_level', 'worker_name', 'device_id',
                    'geofence', 'is_read', 'created_at']
    # 알람 목록 화면에 표시할 컬럼 — 유형/레벨/작업자/장비/지오펜스/읽음여부/생성시각
    list_filter = ['alarm_type', 'alarm_level', 'is_read']
    # 우측 사이드바 필터 — 유형별/레벨별/읽음여부별로 빠르게 걸러볼 수 있어
    search_fields = ['message', 'worker_name', 'device_id']
    # 상단 검색창 대상 — 메시지 본문/작업자명/디바이스ID로 알람을 검색 가능해
    date_hierarchy = 'created_at'
    # 상단에 연/월/일 드릴다운 네비 추가 — 특정 날짜의 알람을 빠르게 찾을 때 유용해
