from django.contrib import admin
# Django 관리자 페이지 기능을 사용하기 위해 admin 모듈을 불러와
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
# Django 기본 UserAdmin 클래스를 가져와 — 우리 커스텀 UserAdmin의 부모로 사용할 거야
from .models import User
# 같은 앱(accounts)의 models.py에서 커스텀 User 모델을 불러와


@admin.register(User)
# User 모델을 Django 관리자 페이지에 등록하는 데코레이터 — 아래 UserAdmin 설정대로 표시돼
class UserAdmin(BaseUserAdmin):
    # Django 기본 UserAdmin을 상속해서 커스텀 필드(role, department 등)를 추가한 관리자 클래스야
    list_display = ['username', 'email', 'role', 'department', 'position',
                    'is_active', 'is_staff', 'date_joined']
    # 관리자 페이지 사용자 목록 화면에 표시할 컬럼 목록 — 아이디/이메일/역할/부서/직급/활성여부/스태프여부/가입일이야
    list_filter = ['role', 'is_active', 'is_staff']
    # 우측 사이드바 필터 옵션 — 역할별/활성여부별/스태프여부별로 사용자를 빠르게 걸러볼 수 있게 해
    search_fields = ['username', 'email', 'department', 'position']
    # 상단 검색창에서 검색 가능한 필드 — 아이디/이메일/부서/직급으로 사용자를 찾을 수 있어
    ordering = ['-date_joined']
    # 기본 정렬 순서 — 가입일 내림차순(최근 가입자가 위에 오도록) 정렬할게

    fieldsets = BaseUserAdmin.fieldsets + (
    # 사용자 상세/수정 화면의 필드 그룹 구성 — 기본 필드셋에 우리 커스텀 그룹을 덧붙여
        ('디코나이 추가 정보', {
        # '디코나이 추가 정보'라는 제목의 섹션을 만들어 (※ 오타로 보임 — '추가 정보'로 수정 권장)
            'fields': ('role', 'department', 'position', 'phone'),
            # 이 섹션 안에 역할/부서/직급/연락처 필드를 묶어서 표시할게
        }),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
    # 신규 사용자 추가 화면의 필드셋 — 기본 가입 필드(username/password)에 추가 필드를 덧붙여
        ('추가 정보', {
            'fields': ('email', 'role', 'department', 'position'),
            # 신규 등록 시 이메일/역할/부서/직급도 함께 입력받을 수 있도록 노출시켜
        }),
    )