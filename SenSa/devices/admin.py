from django.contrib import admin
# Django 관리자 페이지 기능을 사용하기 위해 admin 모듈을 불러와
from .models import Device, SensorData
# 같은 앱(devices)의 models.py에서 Device(센서 장비)와 SensorData(측정값 히스토리) 모델을 불러와


@admin.register(Device)
# Device 모델을 Django 관리자 페이지에 등록하는 데코레이터 — 아래 DeviceAdmin 설정대로 표시돼
class DeviceAdmin(admin.ModelAdmin):
    # Device 모델의 admin 화면을 커스터마이즈하는 클래스야
    list_display = ['device_id', 'device_name', 'sensor_type', 'x', 'y', 'status', 'is_active']
    # 장비 목록 화면에 표시할 컬럼 — 식별자/이름/종류/좌표(x,y)/상태/활성여부
    list_filter = ['sensor_type', 'status', 'is_active']
    # 우측 사이드바 필터 — 센서 종류별/상태별/활성여부별로 빠르게 걸러볼 수 있어
    search_fields = ['device_id', 'device_name']
    # 상단 검색창 대상 — device_id와 device_name으로 검색 가능
    # ⚠️ geofence FK 검색 미지원 — 'geofence__name' 추가 시 지오펜스명으로도 검색 가능


@admin.register(SensorData)
# SensorData 모델 관리자 등록 — 측정값 히스토리 조회/디버깅용
class SensorDataAdmin(admin.ModelAdmin):
    list_display = ['device', 'co', 'h2s', 'co2', 'status', 'timestamp']
    # 목록 화면에 표시할 컬럼 — ⚠️ 9종 가스 중 3종(co/h2s/co2)만 표시
    #   o2, no2, so2, o3, nh3, voc 누락 + 전력 3종(current/voltage/watt) 누락
    #   → 전력 센서 데이터를 admin에서 점검할 때 빈 컬럼만 보여 디버깅 어려움
    list_filter = ['status']
    # 상태별 필터만 — sensor_type(가스/전력) 필터 미지원
    # ⚠️ 'device__sensor_type' 추가 시 가스/전력 측정값을 분리해서 볼 수 있음
    date_hierarchy = 'timestamp'
    # 상단에 연/월/일 드릴다운 네비 추가 — 특정 시점의 측정값을 빠르게 찾을 때 유용