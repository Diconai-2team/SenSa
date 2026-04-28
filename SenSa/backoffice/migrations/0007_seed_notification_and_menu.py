"""
0007_seed_notification_and_menu — 알림 정책 + 메뉴 권한 시드

- 5개 기본 알림 정책 (가스 위험/주의, 전력 위험, 위치 위험, 작업 안전 위험)
- admin 역할 기본 메뉴 권한 (계정관리/이벤트이력 visible, 나머지 invisible)

idempotent — 운영 추가 데이터는 보존.
"""
from django.db import migrations


# 알림 정책 — risk_category.code 와 alarm_level.code 로 lookup
DEFAULT_POLICIES = [
    # (code, name, risk_cat_code, alarm_level_code, channels, recipients, msg)
    ('POLICY_GAS_DANGER', '가스 위험 즉시 알림', 'RISK_GAS', 'DANGER',
     'app,realtime,sms', 'all_users,role:super_admin',
     '[가스 위험] {worker_name} 위치에서 {device_id} 임계 초과'),
    ('POLICY_GAS_CAUTION', '가스 주의 알림', 'RISK_GAS', 'CAUTION',
     'app,realtime', 'leaders,role:super_admin',
     '[가스 주의] {device_id} 주의 단계 도달'),
    ('POLICY_POWER_DANGER', '전력 위험 알림', 'RISK_POWER', 'DANGER',
     'app,realtime,sms', 'all_users',
     '[전력 위험] 즉시 점검 필요'),
    ('POLICY_LOCATION_DANGER', '위치 이탈 위험 알림', 'RISK_LOCATION', 'WARNING',
     'app,realtime', 'leaders',
     '[위치 위험] {worker_name} 위험구역 진입'),
    ('POLICY_WORK_DANGER', '작업 안전 위험 알림', 'RISK_WORK', 'DANGER',
     'app,realtime,sms', 'role:super_admin,leaders',
     '[작업 안전] {worker_name} 위험 작업 감지'),
]

# admin 역할 기본 메뉴 권한 — 사용자 관리 + 알림/이벤트만 활성
ADMIN_MENU_PERMS = [
    # (menu_code, is_visible, is_writable)
    ('users',         True,  False),
    ('menus',         False, False),
    ('devices',       True,  False),
    ('maps',          False, False),
    ('references',    True,  False),
    ('operations',    True,  False),
    ('notices',       True,  True),
    ('notifications', True,  False),
]


def seed(apps, schema_editor):
    NotificationPolicy = apps.get_model('backoffice', 'NotificationPolicy')
    MenuPermission     = apps.get_model('backoffice', 'MenuPermission')
    RiskCategory       = apps.get_model('backoffice', 'RiskCategory')
    AlarmLevel         = apps.get_model('backoffice', 'AlarmLevel')

    # 알림 정책
    for idx, (code, name, rc_code, al_code, channels, recipients, msg) in enumerate(DEFAULT_POLICIES, start=1):
        rc = RiskCategory.objects.filter(code=rc_code).first()
        al = AlarmLevel.objects.filter(code=al_code).first()
        if not rc or not al:
            continue
        NotificationPolicy.objects.get_or_create(
            code=code,
            defaults={
                'name': name, 'risk_category': rc, 'alarm_level': al,
                'channels_csv': channels, 'recipients_csv': recipients,
                'message_template': msg, 'sort_order': idx * 10,
            },
        )

    # admin 메뉴 권한
    for menu_code, is_visible, is_writable in ADMIN_MENU_PERMS:
        MenuPermission.objects.get_or_create(
            role='admin', menu_code=menu_code,
            defaults={'is_visible': is_visible, 'is_writable': is_writable},
        )


def unseed(apps, schema_editor):
    NotificationPolicy = apps.get_model('backoffice', 'NotificationPolicy')
    MenuPermission     = apps.get_model('backoffice', 'MenuPermission')
    NotificationPolicy.objects.filter(code__in=[p[0] for p in DEFAULT_POLICIES]).delete()
    MenuPermission.objects.filter(role='admin').delete()


class Migration(migrations.Migration):
    dependencies = [('backoffice', '0006_notification_and_menu')]
    operations = [migrations.RunPython(seed, reverse_code=unseed)]
