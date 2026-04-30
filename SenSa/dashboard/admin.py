from django.contrib import admin
# Django 관리자 페이지 기능을 사용하기 위해 admin 모듈을 불러와
from .models import MapImage
# 같은 앱(dashboard)의 models.py에서 MapImage 모델을 불러와 — 이 앱의 유일한 모델


@admin.register(MapImage)
# MapImage 모델을 Django 관리자 페이지에 등록하는 데코레이터 — 아래 MapImageAdmin 설정대로 표시돼
class MapImageAdmin(admin.ModelAdmin):
    # MapImage 모델의 admin 화면을 커스터마이즈하는 클래스야
    list_display = ['name', 'width', 'height', 'is_active', 'uploaded_at']
    # 평면도 목록 화면 컬럼 — 이름/가로/세로/활성여부/업로드시각
    # ⚠️ 이미지 썸네일 미노출 — 운영자가 어떤 평면도인지 시각 확인 불가
    #    개선안: image_tag 메서드로 <img> 태그 렌더링 + readonly_fields 추가
    list_filter = ['is_active']
    # 사이드바 필터 — 활성/비활성 분류
    # ⚠️ search_fields 미설정 — 평면도 이름으로 검색 불가