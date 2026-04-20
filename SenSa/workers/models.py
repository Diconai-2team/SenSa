"""
workers/models.py — 현장 작업자 + 위치 시계열

┌─────────────────────────────────────────────────────┐
│  accounts.User  = "시스템을 조작하는 사람" (로그인 O)   │
│  workers.Worker = "시스템이 감시하는 사람" (로그인 X)   │
│                                                     │
│  Worker(정보 - 거의 불변)                              │
│    └→ WorkerLocation(위치 - 1초마다 쌓임)              │
│                                                     │
│  이 구조는 Device → SensorData 패턴과 동일            │
└─────────────────────────────────────────────────────┘
"""
from django.db import models


# ────────────────────────────────────────────────────
# WorkerLocation.movement_status 선택지
# DB에 저장되는 값: 'moving' 또는 'stationary'
# Django Admin에 표시되는 값: '이동' 또는 '정지'
# ────────────────────────────────────────────────────
MOVEMENT_STATUS_CHOICES = [
    ('moving', '이동'),
    ('stationary', '정지'),
]


class Worker(models.Model):
    """
    현장 작업자 — 관제 추적 대상

    ※ 이 모델은 로그인 계정이 아닙니다.
      로그인은 accounts.User가 담당합니다.

    DB 테이블명: workers_worker (앱이름_클래스명소문자)
    """

    # ── worker_id: 작업자 고유 식별자 ──
    # unique=True → 같은 ID 중복 불가 (DB UNIQUE 제약조건)
    # max_length=50 → varchar(50)
    worker_id = models.CharField(
        max_length=50,
        unique=True,
        help_text="작업자 식별자 (worker_01 등)"
    )

    # ── name: 작업자 이름 ──
    # blank=True가 없음 → 필수 입력 필드
    name = models.CharField(
        max_length=100,
        help_text="작업자명"
    )

    # ── department: 소속 부서 ──
    # blank=True  → 폼/시리얼라이저에서 빈 값 허용 (유효성 검사 레벨)
    # default=''  → DB에 값 안 들어오면 빈 문자열 저장 (DB 레벨)
    # 이 두 옵션은 거의 항상 같이 씀
    department = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="소속 부서"
    )

    # ── is_active: 활성 여부 (소프트 삭제용) ──
    # 삭제 시 DB에서 실제로 지우지 않고 False로 변경
    # → 과거 알람 기록에서 "삭제된 작업자" 참조 깨지지 않음
    is_active = models.BooleanField(
        default=True,
        help_text="활성 여부"
    )

    # ── created_at: 등록 일시 ──
    # auto_now_add=True → 객체 '처음 생성' 시 자동으로 현재 시간
    # 이후 수정해도 이 값은 안 바뀜
    # (참고: auto_now=True는 '저장할 때마다' 현재 시간으로 갱신 — 용도 다름)
    created_at = models.DateTimeField(auto_now_add=True)

    # ── id 필드는 안 적어도 됨 ──
    # Django가 자동으로 id = AutoField(primary_key=True) 추가

    class Meta:
        # QuerySet 기본 정렬: Worker.objects.all() → worker_id 오름차순
        ordering = ['worker_id']

        # Django Admin에서 표시되는 이름
        verbose_name = '작업자'
        verbose_name_plural = '작업자 목록'

    def __str__(self):
        """
        Admin, 디버깅, print()에서 표시되는 문자열
        예: "작업자 A (worker_01)"
        """
        return f"{self.name} ({self.worker_id})"


class WorkerLocation(models.Model):
    """
    작업자 위치 시계열

    3차: 모델만 존재, 데이터 없음 (JS 시뮬레이션으로 대체)
    4차: FastAPI가 실시간으로 이 테이블에 기록

    DB 테이블명: workers_workerlocation
    """

    # ── worker: FK → Worker ──
    # ForeignKey = 이 위치 기록이 어떤 작업자의 것인지
    #
    # on_delete=CASCADE  → Worker 삭제 시 위치 기록도 전부 삭제
    # related_name='locations' → 역참조 이름
    #   정방향: location.worker         (이 기록의 작업자)
    #   역방향: worker.locations.all()  (이 작업자의 모든 위치)
    #          worker.locations.first() (가장 최근 위치)
    #          worker.locations.count() (위치 기록 수)
    worker = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name='locations',
        help_text="소속 작업자"
    )

    # ── x, y: 평면도 좌표 ──
    # null=True 안 넣음 → 필수 입력 (좌표 없는 위치 기록은 의미 없음)
    x = models.FloatField(help_text="평면도 X 좌표")
    y = models.FloatField(help_text="평면도 Y 좌표")

    # ── movement_status: 이동 상태 ──
    # choices 옵션 → Admin에서 드롭다운, DRF에서 유효성 검사
    movement_status = models.CharField(
        max_length=20,
        choices=MOVEMENT_STATUS_CHOICES,
        default='moving',
        help_text="이동 상태"
    )

    # ── timestamp: 기록 시각 ──
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 최신 기록이 먼저 나옴 (마이너스 = 내림차순)
        ordering = ['-timestamp']

        verbose_name = '작업자 위치'
        verbose_name_plural = '작업자 위치 이력'

        # ── 복합 인덱스 ──
        # "worker_01의 최근 위치 10건" 같은 쿼리를 빠르게 처리
        # 인덱스 없이는 전체 테이블 스캔 → 인덱스 있으면 바로 찾음
        indexes = [
            models.Index(fields=['worker', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.worker.name} @ ({self.x}, {self.y})"