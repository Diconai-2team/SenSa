"""
safety/models.py — 작업 전 안전 확인 체크리스트 기록

[설계]
  "사용자가 오늘(YYYY-MM-DD) 체크리스트를 완료했는가?" 를 판정하려면
  (user, check_date) 조합이 unique 해야 함. 하루 한 번만 완료 기록.
  
  재제출 가능하게 할지 결정 지점 — 현재는 unique_together 로 차단해서
  save_or_create 시 한 번만 insert 되도록. 두 번째 제출은 update.

[필드]
  user          : 어떤 사용자가 제출했는가 (로그인 필수)
  check_date    : 어느 날짜에 대한 체크인가 (auto_now_add 아님. 명시)
                  → "자정 직전 제출 후 자정 직후 재확인" 같은 케이스에도
                    같은 날짜로 묶기 위해 서버 저장 시점의 date 를 명시적으로 씀
  checked_items : 체크된 항목 key 목록 (JSONField)
                  → 예: ["1_1", "1_2", "2_1", ...]
                  → 전체 항목과 비교해 완료율 계산 가능
  completed_at  : 완료 시각 (최초 저장 시간)
  updated_at    : 가장 최근 수정 시각

[왜 checked_items 를 JSONField 로?]
  - 항목 정의가 Python 상수 파일에 있어서 (checklist_data.py)
    Item 테이블 FK 를 걸기가 어색함
  - 3차 기준 운영 스케일에서 JSON 조회로 충분
  - 항목 정의가 나중에 바뀌어도 과거 기록은 해당 날짜의 key 목록 그대로 남음
"""
from django.conf import settings
from django.db import models


class SafetyChecklist(models.Model):
    """작업 전 안전 확인 체크리스트 — 사용자 × 날짜 단위 1건"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='safety_checklists',
        verbose_name='사용자',
    )
    check_date = models.DateField(
        verbose_name='점검 날짜',
        help_text='YYYY-MM-DD. 해당 날짜의 작업 전 점검 1회 기록',
    )
    checked_items = models.JSONField(
        default=list,
        verbose_name='체크된 항목 목록',
        help_text='["1_1", "1_2", ...] 형태. checklist_data.CHECKLIST_ITEMS 의 item.key',
    )
    completed_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='최초 완료 시각',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='최근 수정 시각',
    )

    class Meta:
        db_table = 'safety_checklist'
        verbose_name = '안전 확인 체크리스트'
        verbose_name_plural = '안전 확인 체크리스트 목록'
        ordering = ['-check_date', '-completed_at']
        constraints = [
            # 사용자 1명이 같은 날짜에 여러 건 만들지 못하도록
            models.UniqueConstraint(
                fields=['user', 'check_date'],
                name='uniq_safety_checklist_per_user_per_day',
            ),
        ]
        indexes = [
            # 대시보드에서 "오늘 완료했나?" 조회 최적화
            models.Index(fields=['user', '-check_date']),
        ]

    def __str__(self):
        return f'{self.user.username} — {self.check_date} ({len(self.checked_items)}개 체크)'