# Django 관리자(admin) 기능을 사용하기 위한 모듈을 불러옴
from django.contrib import admin

# 같은 앱(vr_training)의 models.py에서 VRTrainingLog 모델을 가져옴
from .models import VRTrainingLog


# @admin.register 데코레이터: VRTrainingLog 모델을 Django 관리자 페이지에 등록함
# 이 클래스가 관리자 페이지에서 VRTrainingLog 데이터를 어떻게 표시하고 다룰지 정의함
@admin.register(VRTrainingLog)
class VRTrainingLogAdmin(admin.ModelAdmin):
    # 관리자 목록 페이지에서 보여줄 컬럼 목록
    # 사용자 / 점검 날짜 / 진행률(커스텀) / 완료 여부 / 완료 시각 순으로 표시
    list_display = (
        "user",
        "check_date",
        "progress_display",
        "is_completed",
        "completed_at",
    )
    # 오른쪽 필터 패널에 '완료 여부(is_completed)'와 '날짜(check_date)' 기준 필터를 추가함
    list_filter = ("is_completed", "check_date")
    # 검색창에서 사용자 이름(username)으로 로그를 검색할 수 있도록 설정
    search_fields = ("user__username",)
    # 시작 시각, 수정 시각, 완료 시각은 자동 기록 필드이므로 관리자 화면에서 수정 불가 처리
    readonly_fields = ("started_at", "updated_at", "completed_at")
    # 목록 기본 정렬: 날짜 최신순 → 같은 날짜 내에서는 최근 수정 시각 최신순
    ordering = ("-check_date", "-updated_at")

    # 관리자 목록 컬럼에 표시될 이름을 "진행률"로 지정
    @admin.display(description="진행률")
    def progress_display(self, obj):
        # VR 영상 재생 진행률을 퍼센트와 초(sec) 단위로 함께 표시
        # 예: "75% (45/60s)" → 60초짜리 영상을 45초까지 시청해 75% 진행
        return f"{obj.progress_percent}% ({obj.last_position_sec}/{obj.total_duration_sec}s)"
