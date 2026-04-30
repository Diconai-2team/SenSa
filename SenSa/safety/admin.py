# Django의 관리자(admin) 기능을 사용하기 위한 모듈을 불러옴
from django.contrib import admin

# 같은 앱(safety)의 models.py에서 SafetyChecklist 모델을 가져옴
from .models import SafetyChecklist


# @admin.register 데코레이터: SafetyChecklist 모델을 Django 관리자 페이지에 등록함
# 이 클래스가 관리자 페이지에서 SafetyChecklist 데이터를 어떻게 보여줄지를 정의함
@admin.register(SafetyChecklist)
class SafetyChecklistAdmin(admin.ModelAdmin):
    # 관리자 목록 페이지에서 보여줄 컬럼: 사용자, 점검 날짜, 체크 항목 수(커스텀), 완료 시각
    list_display = ("user", "check_date", "checked_count", "completed_at")
    # 오른쪽 필터 패널에 'check_date(날짜)' 기준으로 필터링 기능을 추가함
    list_filter = ("check_date",)
    # 검색창에서 사용자 이름(username)으로 레코드를 검색할 수 있도록 설정
    search_fields = ("user__username",)
    # 완료 시각(completed_at)과 수정 시각(updated_at)은 자동 기록 필드이므로 수정 불가 처리
    readonly_fields = ("completed_at", "updated_at")
    # 목록 기본 정렬: 날짜 최신순 → 동일 날짜 내에서는 완료 시각 최신순
    ordering = ("-check_date", "-completed_at")

    # 관리자 목록 컬럼에 표시될 이름을 "체크 항목 수"로 지정
    @admin.display(description="체크 항목 수")
    def checked_count(self, obj):
        # checked_items 필드(JSON 리스트)의 길이를 반환 → 해당 제출에서 체크한 항목 개수를 보여줌
        # checked_items가 None일 경우를 대비해 빈 리스트([])로 대체 후 길이를 셈
        return len(obj.checked_items or [])
