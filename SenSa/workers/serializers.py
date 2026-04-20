"""
workers/serializers.py — 모델 ↔ JSON 변환기

시리얼라이저의 역할:
  1. API 요청(JSON) → Python 객체 (역직렬화)
  2. Python 객체 → API 응답(JSON) (직렬화)
  3. 유효성 검사 (타입, 길이, 필수 여부 등)
"""
from rest_framework import serializers
from .models import Worker, WorkerLocation


class WorkerSerializer(serializers.ModelSerializer):
    """
    작업자 CRUD용 시리얼라이저

    API 응답 예시:
    {
        "id": 1,
        "worker_id": "worker_01",
        "name": "작업자 A",
        "department": "생산1팀",
        "is_active": true,
        "created_at": "2026-04-20T10:00:00Z",
        "location_count": 0
    }
    """

    # ── SerializerMethodField ──
    # 모델에 없는 "가상 필드"를 추가
    # 아래 get_location_count() 메서드의 반환값이 이 필드의 값
    # read_only=True → API 요청(POST/PUT)에서는 무시됨
    location_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Worker

        # '__all__' → Worker 모델의 모든 필드 + 위에서 추가한 location_count
        fields = '__all__'

        # API 요청으로 변경 불가한 필드
        # POST로 {"id": 999} 보내도 무시됨
        read_only_fields = ['id', 'created_at']

    def get_location_count(self, obj):
        """
        해당 작업자의 위치 기록 수

        메서드명 규칙: get_ + 필드명
        location_count 필드 → get_location_count 메서드

        obj = 현재 직렬화 중인 Worker 인스턴스
        obj.locations = related_name='locations' 덕분에 가능
        """
        return obj.locations.count()


class WorkerLocationSerializer(serializers.ModelSerializer):
    """
    위치 기록 조회/생성용 시리얼라이저

    API 응답 예시:
    {
        "id": 1,
        "worker": 1,                  ← FK (숫자 ID)
        "worker_name": "작업자 A",     ← source로 추가한 가상 필드
        "worker_id_str": "worker_01", ← source로 추가한 가상 필드
        "x": 150.0,
        "y": 170.0,
        "movement_status": "moving",
        "timestamp": "2026-04-20T10:00:01Z"
    }
    """

    # ── source: FK 관계를 따라가서 값 가져오기 ──
    # source='worker.name'      → location.worker.name
    # source='worker.worker_id' → location.worker.worker_id
    # read_only=True → 조회(GET)에서만 표시, 생성(POST)에서는 무시
    worker_name = serializers.CharField(
        source='worker.name',
        read_only=True
    )
    worker_id_str = serializers.CharField(
        source='worker.worker_id',
        read_only=True
    )

    class Meta:
        model = WorkerLocation

        # '__all__' 대신 명시적 나열
        # 이유: worker_name, worker_id_str은 모델에 없는 가상 필드라
        #       '__all__'로는 포함되지 않음
        fields = [
            'id',               # PK (자동)
            'worker',           # FK → Worker (숫자 ID)
            'worker_name',      # 가상 필드 (작업자명)
            'worker_id_str',    # 가상 필드 (작업자 식별자)
            'x',                # X 좌표
            'y',                # Y 좌표
            'movement_status',  # 이동 상태
            'timestamp',        # 기록 시각
        ]
        read_only_fields = ['id', 'timestamp']