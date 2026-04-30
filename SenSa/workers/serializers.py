"""
workers/serializers.py — 모델 ↔ JSON 변환기

시리얼라이저의 역할:
  1. API 요청(JSON) → Python 객체 (역직렬화)
  2. Python 객체 → API 응답(JSON) (직렬화)
  3. 유효성 검사 (타입, 길이, 필수 여부 등)
"""
from rest_framework import serializers
from .models import Worker, WorkerLocation
# NotificationLog 시리얼라이저 부재 — views.WorkerNotifyView가 dict 수동 조립


class WorkerSerializer(serializers.ModelSerializer):
    """
    작업자 CRUD용 시리얼라이저
    """
    # WorkerViewSet의 list/create/retrieve/update에서 사용

    # ── SerializerMethodField ──
    # 모델에 없는 "가상 필드"를 추가
    # 아래 get_location_count() 메서드의 반환값이 이 필드의 값
    # read_only=True → API 요청(POST/PUT)에서는 무시됨
    location_count = serializers.SerializerMethodField(read_only=True)
    # 위치 기록 누적 건수 — UI에 "이 작업자 데이터가 얼마나 쌓였는지" 표시용

    class Meta:
        model = Worker
        # '__all__' → Worker 모델의 모든 필드 + 위에서 추가한 location_count
        fields = '__all__'
        # 모든 필드 자동 포함 — id, worker_id, name, department, position,
        # email, phone, last_seen_at, is_active, created_at + location_count
        # ⚠️ '__all__' 사용 — 미래 필드 추가 시 자동 노출 위험 (다른 앱과 동일 패턴)

        # API 요청으로 변경 불가한 필드
        # POST로 {"id": 999} 보내도 무시됨
        read_only_fields = ['id', 'created_at']
        # ⚠️ last_seen_at 미포함 — 클라이언트가 임의로 갱신할 수 있는 위험
        #    실제 갱신은 WorkerLocationViewSet.perform_create가 자동 처리하므로
        #    명시적으로 read_only 잠그는 게 안전

    def get_location_count(self, obj):
        """
        해당 작업자의 위치 기록 수
        """
        # SerializerMethodField와 짝을 이루는 메서드
        # 메서드명 규칙: get_ + 필드명 → location_count 필드 → get_location_count

        return obj.locations.count()
        # ⚠️ N+1 쿼리 — 작업자 50명 list 응답 시 50번의 COUNT SQL 발생
        #    개선안: get_queryset에서 .annotate(_loc_count=Count('locations'))
        #            후 source='_loc_count'로 노출


class WorkerLocationSerializer(serializers.ModelSerializer):
    """
    위치 기록 조회/생성용 시리얼라이저
    """
    # WorkerLocationViewSet의 list/create에서 사용
    # WorkerViewSet.latest 액션의 응답에도 사용

    # ── source: FK 관계를 따라가서 값 가져오기 ──
    # source='worker.name'      → location.worker.name
    # source='worker.worker_id' → location.worker.worker_id
    # read_only=True → 조회(GET)에서만 표시, 생성(POST)에서는 무시
    worker_name = serializers.CharField(
        source='worker.name',
        # FK를 따라가 Worker.name을 직렬화 시점에 추출
        # ⚠️ select_related('worker') 없이 호출되면 N+1 쿼리 발생
        #    WorkerLocationViewSet.get_queryset은 select_related 사용 중 (좋음)
        read_only=True
    )
    worker_id_str = serializers.CharField(
        source='worker.worker_id',
        # 'worker_id'는 모델 PK와 충돌 가능 → 'worker_id_str' 별칭 사용
        # 응답 JSON에서 worker(FK PK 숫자)와 worker_id_str(사람이 읽는 ID)를 구분
        read_only=True
    )

    class Meta:
        model = WorkerLocation
        # '__all__' 대신 명시적 나열
        # 이유: worker_name, worker_id_str은 모델에 없는 가상 필드라
        #       '__all__'로는 포함되지 않음
        fields = [
            'id',               # PK (자동)
            'worker',           # FK → Worker (숫자 ID, write 가능)
            'worker_name',      # 가상 필드 (작업자명, read-only)
            'worker_id_str',    # 가상 필드 (작업자 식별자, read-only)
            'x',                # X 좌표
            'y',                # Y 좌표
            'movement_status',  # 이동 상태
            'timestamp',        # 기록 시각
        ]
        read_only_fields = ['id', 'timestamp']
        # 시각 필드는 auto_now_add — 클라이언트 변조 차단