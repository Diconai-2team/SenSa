from django.contrib import admin
# Django 관리자 페이지 기능을 사용하기 위해 admin 모듈을 불러와
from .models import GeoFence
# 같은 앱(geofence)의 models.py에서 GeoFence 모델을 불러와


@admin.register(GeoFence)
# GeoFence 모델을 Django 관리자 페이지에 등록하는 데코레이터 — 아래 GeoFenceAdmin 설정대로 표시돼
class GeoFenceAdmin(admin.ModelAdmin):
    # GeoFence 모델의 admin 화면을 커스터마이즈하는 클래스야
    list_display = ['name',
                    'zone_type',
                    'risk_level',
                    'is_active',
                    'created_at']
    # 지오펜스 목록 화면에 표시할 컬럼 — 이름/구역타입/위험도/활성여부/생성일
    # ⚠️ polygon 정점 개수 같은 디버깅 정보 미노출 — 잘못 그려진 지오펜스 식별 어려움
    list_filter = ['zone_type',
                    'risk_level',
                    'is_active']
    # 우측 사이드바 필터 — 구역타입별/위험도별/활성여부별로 빠르게 걸러볼 수 있어
    search_fields = ['name']
    # 상단 검색창 대상 — 지오펜스 이름으로만 검색 가능
    # ⚠️ description 누락 — 설명 텍스트로도 검색 가능하게 하면 운영 편의성 ↑