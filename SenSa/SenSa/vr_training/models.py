"""
vr_training/models.py — VR 안전 교육 시청 이력

[설계]
  체크리스트(SafetyChecklist)와 동일한 (user, date) 1건 패턴.
  "오늘 VR 교육을 완료했는가?" 가 핵심 질의.
  
  단, 체크리스트와 달리 "도중 이탈" 개념이 있어서 재생 위치(초 단위)
  저장 필드 추가 — 사용자가 이전 버튼으로 나가도 다시 들어오면 그 위치부터
  재생할 수 있어야 함 (Figma 설명의 "임시 저장" 요구사항).

[필드]
  user               : 로그인 사용자
  check_date         : 교육 이수 날짜 기준 (YYYY-MM-DD)
  last_position_sec  : 마지막으로 기록된 재생 위치 (초 단위)
                        → 완료 전 이탈 시에도 갱신. 완료 시 total_duration 과 같음.
  total_duration_sec : 영상 총 길이. 저장된 영상 메타에서 가져옴.
  is_completed       : 100% 시청 완료 여부
  completed_at       : 완료 전환 시점 (is_completed=True 된 순간)
  started_at         : 최초 진입 시점 (auto_now_add)
  updated_at         : 마지막 갱신 시점

[핵심 불변식]
  - 하루에 같은 user 에 대해 1 row 만 존재 (unique)
  - is_completed=True 가 되면 completed_at 반드시 세팅
  - last_position_sec 은 monotonic 증가 (앞으로만 감; 스킵 방지 의도)
    — 이 규칙은 API 레이어에서 강제. 모델 자체는 제약하지 않음.
"""
from django.conf import settings
from django.db import models


class VRTrainingLog(models.Model):
    """VR 안전 교육 이수/진행 기록 — 사용자 × 날짜 단위 1건"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vr_training_logs',
        verbose_name='사용자',
    )
    check_date = models.DateField(
        verbose_name='교육 날짜',
    )
    last_position_sec = models.PositiveIntegerField(
        default=0,
        verbose_name='마지막 재생 위치 (초)',
        help_text='이탈 시 저장되는 시청 지점. 다음 진입 시 여기서 재생 재개.',
    )
    total_duration_sec = models.PositiveIntegerField(
        default=0,
        verbose_name='영상 총 길이 (초)',
    )
    is_completed = models.BooleanField(
        default=False,
        verbose_name='완료 여부',
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='완료 시각',
    )
    started_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='최초 진입 시각',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='마지막 갱신 시각',
    )

    class Meta:
        db_table = 'vr_training_log'
        verbose_name = 'VR 교육 이력'
        verbose_name_plural = 'VR 교육 이력 목록'
        ordering = ['-check_date', '-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'check_date'],
                name='uniq_vr_training_per_user_per_day',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-check_date']),
        ]

    def __str__(self):
        status = '완료' if self.is_completed else f'{self.last_position_sec}s'
        return f'{self.user.username} — {self.check_date} [{status}]'

    @property
    def progress_percent(self) -> int:
        """진행률 % (0~100). total_duration 이 0이면 0 반환."""
        if not self.total_duration_sec:
            return 0
        return min(100, int(self.last_position_sec * 100 / self.total_duration_sec))