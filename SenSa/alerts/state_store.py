"""
alerts/state_store.py — 작업자별 알람 상태 + 안정화 카운터 (Redis)

저장 구조 (Hash):
  sensa:worker:{worker_id}:alarm
    state           : "safe" | "caution" | "danger"   (현재 공식 상태)
    last_alarm_at   : "1745380923.456"                  (마지막 알람 발행 시각)
    pending_state   : "safe" | "caution" | "danger"    (회복 후보 상태, 아직 미확정)
    pending_count   : "2"                                (후보 상태 연속 관측 횟수)

TTL: 5분.
"""
import time
# Unix timestamp 기록용 — last_alarm_at 필드에 사용해 60초 재알림 주기 계산의 기준이 돼
import redis
# Redis 클라이언트 라이브러리 — DB 대신 사용해 알람 판정 핫패스 지연 최소화
from django.conf import settings
# CHANNEL_LAYERS 설정에서 Redis 호스트 정보를 꺼내오기 위해 불러와


_pool = None
# 모듈 레벨 ConnectionPool 캐시 — 매 요청마다 새 connection 만들지 않게 (성능)
# 첫 _client() 호출 시 1회 생성되고 이후 모든 호출이 재사용해


def _client() -> redis.Redis:
    """Channels 설정의 Redis 호스트를 재사용."""
    # Redis 클라이언트 인스턴스를 반환하는 헬퍼 — Lazy 초기화 + Pool 재사용
    global _pool
    if _pool is None:
        # 첫 호출 시점에만 Pool 생성 — 모듈 import 시점이 아니라 실제 사용 시점에 초기화
        host_tuple = settings.CHANNEL_LAYERS['default']['CONFIG']['hosts'][0]
        # Django Channels(WebSocket)용 Redis와 동일 인스턴스 재사용 — 인프라 단순화
        # settings에 별도 ALARM_REDIS 설정 추가하지 않음 (운영 단순성 우선)
        if isinstance(host_tuple, (tuple, list)):
            # ('redis', 6379) 형태 — Channels 표준 설정 포맷
            host, port = host_tuple
            _pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
            # decode_responses=True — bytes 대신 str 자동 변환 (Python에서 .decode() 호출 불필요)
        else:
            # 'redis://...' URL 형식 — Channels 호스트를 URL로 설정한 경우 대응
            _pool = redis.ConnectionPool.from_url(host_tuple, decode_responses=True)
    return redis.Redis(connection_pool=_pool)
    # ConnectionPool에서 connection을 빌려 쓰는 클라이언트 반환 — 호출 끝나면 자동 반납


KEY_FORMAT = "sensa:worker:{worker_id}:alarm"
# 작업자 알람 상태 키 패턴 — 'sensa:' 네임스페이스로 다른 앱 키와 충돌 방지
# 예: 'sensa:worker:worker_01:alarm'
TTL_SEC = 300
# 5분 TTL — 작업자가 5분 이상 데이터 안 보내면 상태 키 자동 삭제 (실종/오프라인 처리)
# 다음 데이터 수신 시 신규 작업자처럼 'safe'에서 다시 시작


def get_worker_snapshot(worker_id: str) -> dict:
    """
    작업자의 현재 전체 스냅샷 반환.
    기본값:
      state='safe', last_alarm_at=0.0, pending_state=None, pending_count=0
    """
    # 한 번의 HGETALL로 작업자의 모든 상태 필드를 dict로 가져옴 — race condition 회피
    # (필드별 GET을 4번 부르면 그 사이에 다른 프로세스가 commit_state할 수 있음)
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    # 'sensa:worker:{worker_id}:alarm' 형태의 Redis 키 조립
    data = r.hgetall(key)
    # Hash 구조 전체 조회 — 1번의 RTT(Round Trip Time)로 모든 필드 획득
    # 키가 존재하지 않으면 빈 dict {} 반환 (예외 안 던짐)
    return {
        'state': data.get('state', 'safe'),
        # 키가 없으면 'safe' 기본값 — 신규 작업자는 안전 상태로 시작
        'last_alarm_at': float(data.get('last_alarm_at', 0) or 0),
        # 빈 문자열 처리 — `or 0`로 ValueError 방지 (float('') 호출 시 에러나는 것 차단)
        'pending_state': data.get('pending_state') or None,
        # 빈 문자열도 None으로 정규화 — 호출자가 `if pending_state` 깔끔히 쓸 수 있게
        'pending_count': int(data.get('pending_count', 0) or 0),
        # 회복 후보 연속 관측 횟수 — Hysteresis 카운터의 핵심
    }


def commit_state(worker_id: str, state: str, mark_alarmed: bool = False) -> None:
    """
    공식 상태 확정 + pending 초기화.
    mark_alarmed=True 면 last_alarm_at 도 now 로 갱신.
    """
    # 알람 발행 직후 호출되어 작업자의 공식 상태를 새로 확정짓는 함수
    if state not in ("safe", "caution", "danger"):
        raise ValueError(f"invalid state: {state}")
        # 화이트리스트 검증 — 오타나 잘못된 호출을 빠르게 잡아냄
        # ⚠️ 'critical' 누락 — services.py는 critical 상태를 만드는데 여기선 거부됨 (버그)
        #    services.py에서 restricted 구역 진입 시 critical로 commit_state 호출하면 ValueError
    
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    mapping = {
        'state': state,
        # 새 공식 상태로 갱신
        'pending_state': '',
        # pending 후보 비우기 — 상태 확정됐으니 회복 카운터 리셋
        'pending_count': '0',
        # Redis Hash는 문자열만 저장 — int 0 대신 '0' 문자열로 저장
    }
    if mark_alarmed:
        mapping['last_alarm_at'] = str(time.time())
        # 알람 발행 시각 기록 — 60초 재알림 주기 계산의 기준
        # 지속 알림(ongoing) 분기에서만 mark_alarmed=True로 호출됨
    r.hset(key, mapping=mapping)
    # 1번의 HSET으로 여러 필드 한 번에 갱신 — atomic (원자적)
    # 중간 상태(state만 바뀌고 pending은 안 바뀐 상태)가 외부에 노출되지 않음
    r.expire(key, TTL_SEC)
    # 매 commit마다 TTL 갱신 — 활동 중인 작업자는 키 유지, 끊긴 작업자는 자동 삭제
    # Redis의 expire는 절대시간이 아니라 sliding window처럼 동작


def set_pending(worker_id: str, pending_state: str, count: int) -> None:
    """
    회복 후보 상태 저장 (아직 확정 안 함).
    상태 자체(state 필드)는 건드리지 않음.
    """
    # Hysteresis 회복 카운터 누적 — 3틱 채워질 때까지 official_state는 그대로 둠
    # 회복 도중 다시 악화되면 pending이 덮어씌워지면서 카운터 리셋
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    r.hset(key, mapping={
        'pending_state': pending_state,
        # 어떤 상태로 회복하려고 하는지 후보 저장 (예: 'caution', 'safe')
        'pending_count': str(count),
        # 같은 후보 상태가 연속 관측된 횟수 — RECOVERY_CONFIRM_TICKS(기본 3) 도달 시 확정
    })
    r.expire(key, TTL_SEC)
    # 회복 진행 중에도 TTL 갱신 — pending 카운팅 도중 키가 만료되어 카운터 리셋되는 것 방지


def clear_pending(worker_id: str) -> None:
    """회복 후보 폐기 (현재 상태를 유지함을 의미)."""
    # 관측 상태가 공식 상태와 일치할 때 호출 — 회복 진행 중이었다면 카운터 리셋
    # (예: pending=safe count=2였는데 다시 caution 관측되면 회복 무효)
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    r.hset(key, mapping={
        'pending_state': '',
        # 빈 문자열로 후보 제거 (HDEL 안 쓰는 이유: Hash 자체는 살려두고 필드만 비움)
        'pending_count': '0',
    })
    r.expire(key, TTL_SEC)


# ═══════════════════════════════════════════════════════════
# 센서용 상태 저장소 (구조는 작업자와 동일)
# ═══════════════════════════════════════════════════════════
# 작업자 함수 4종(get/commit/set_pending/clear_pending)을 센서용으로 1:1 복제한 섹션
# ⚠️ DRY 위반 — 향후 _StateStore 베이스 클래스로 추상화 검토 필요

SENSOR_KEY_FORMAT = "sensa:sensor:{device_id}:alarm"
# 센서 알람 상태 키 — 작업자와 다른 prefix로 분리해 ID 충돌 가능성 차단
# 예: 'sensa:sensor:gas_01:alarm', 'sensa:sensor:power_03:alarm'


def get_sensor_snapshot(device_id: str) -> dict:
    """센서의 현재 스냅샷."""
    # 작업자 get_worker_snapshot과 동일 구조 — 다른 점은 키 prefix와 기본 state
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    data = r.hgetall(key)
    return {
        'state': data.get('state', 'normal'),
        # 센서는 'normal'이 안전 상태 — 작업자의 'safe'에 대응 (의미는 같지만 단어가 다름)
        'last_alarm_at': float(data.get('last_alarm_at', 0) or 0),
        'pending_state': data.get('pending_state') or None,
        'pending_count': int(data.get('pending_count', 0) or 0),
    }


def commit_sensor_state(device_id: str, state: str, mark_alarmed: bool = False) -> None:
    """센서 공식 상태 확정."""
    # 작업자 commit_state와 동일 구조 — valid states만 다름 (normal/caution/danger)
    if state not in ("normal", "caution", "danger"):
        raise ValueError(f"invalid sensor state: {state}")
        # 센서는 'critical' 단계가 없음 — 출입금지 개념은 작업자에만 적용되는 비즈니스 룰
    
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    mapping = {
        'state': state,
        'pending_state': '',
        'pending_count': '0',
    }
    if mark_alarmed:
        mapping['last_alarm_at'] = str(time.time())
    r.hset(key, mapping=mapping)
    r.expire(key, TTL_SEC)


def set_sensor_pending(device_id: str, pending_state: str, count: int) -> None:
    """센서 회복 후보 저장."""
    # 작업자 set_pending의 센서 버전 — 키 prefix만 다름
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    r.hset(key, mapping={
        'pending_state': pending_state,
        'pending_count': str(count),
    })
    r.expire(key, TTL_SEC)


def clear_sensor_pending(device_id: str) -> None:
    """센서 회복 후보 폐기."""
    # 작업자 clear_pending의 센서 버전
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    r.hset(key, mapping={
        'pending_state': '',
        'pending_count': '0',
    })
    r.expire(key, TTL_SEC)