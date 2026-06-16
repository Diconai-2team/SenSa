작업 목적

실시간 센서 데이터, 작업자 위치 데이터, 알람 이벤트, AI 분석 요청/결과 등  
여러 종류의 데이터를 안정적으로 중간에서 전달하고,  
웹 서버와 AI 처리 서버, 실시간 송신 서버 간 결합도를 낮추기 위해  
**Redis 기반 Pub/Sub 및 버퍼링 구조를 도입하는 것**이 목적이다.

1단계에서는 FastAPI와 브라우저를 직접 WebSocket으로 연결하여  
실시간 흐름을 빠르게 확인하는 데 집중했다면,  
2단계에서는 서비스가 확장되면서  
**데이터 생산자와 소비자를 분리하고, 순간적인 데이터 폭주나 처리 지연에도 시스템이 무너지지 않도록**  
중간 메시지 계층이 필요해진다.

즉, Redis는 단순 캐시가 아니라  
이 프로젝트에서는 **실시간 데이터 허브이자 비동기 메시지 전달 계층** 역할을 한다.

---
작업 내용

1. Redis 도입 목적 명확화
- Redis는 단순히 데이터를 저장하는 용도가 아니라,
    - 실시간 메시지 전달
    - 서비스 간 중간 버퍼
    - Celery Broker
    - 최신 상태 캐시  
        역할로 활용한다.
- 2단계에서는 특히 다음 두 가지가 핵심이다.
    1. **Pub/Sub 구조를 통한 실시간 이벤트 전달**
    2. **데이터 버퍼링을 통한 처리 안정화**

2. Pub/Sub 구조 설계
- 센서 데이터 생성부 또는 수집부가 Redis 채널에 메시지를 발행(Publish)하면,
- Django, FastAPI, 알람 처리기, WebSocket 송신부 등이 이를 구독(Subscribe)하여 필요한 작업을 수행한다.
- 이렇게 하면 데이터 생산자와 소비자가 직접 강하게 연결되지 않는다.

예시 구조:
```
센서 데이터 생성기  
   ↓ publish  
Redis Channel  
   ↓ subscribe  
Django / AI 처리 / WebSocket 송신 / 알람 처리
```

- 예를 들어 센서 데이터 한 건이 들어왔을 때,
    - Django는 DB 저장
    - AI 서버는 이상 탐지 대상 큐 등록
    - WebSocket 송신부는 실시간 UI 반영  
        을 각각 독립적으로 처리할 수 있다.

3. 채널 분리 전략
- Redis Pub/Sub은 하나의 채널만 사용하는 것보다  
    데이터 성격별로 채널을 분리하는 것이 유지보수에 유리하다.
- 예시:
    - `sensor.raw`
    - `worker.location`
    - `event.alert`
    - `ai.request`
    - `ai.result`
- 이렇게 분리하면 특정 서비스는 필요한 채널만 구독하면 되고,  
    디버깅과 운영 관리도 쉬워진다.

4. 실시간 데이터 버퍼링
- 센서 데이터는 순간적으로 몰릴 수 있고,  
    AI 분석은 바로 처리하지 못할 수 있다.
- 이때 Redis를 중간 버퍼로 사용하면  
    생산 속도와 소비 속도가 달라도 시스템이 바로 무너지지 않는다.
- 2단계에서는 다음 구조를 고려할 수 있다.
    - 최신 데이터는 캐시 키에 저장
    - 이벤트성 데이터는 Pub/Sub으로 발행
    - 처리 대기 데이터는 큐 또는 리스트 구조로 관리
- 즉, 모든 데이터를 DB에 바로 보내는 것이 아니라  
    Redis를 거쳐 적절한 목적지로 분산시키는 구조를 만든다.

5. 최신 상태 캐시
- 관제 화면에서는 모든 과거 데이터보다 **현재 최신 상태**가 더 중요할 때가 많다.
- 예:
    - 현재 센서 상태
    - 현재 작업자 위치
    - 최근 알람 상태
- 이런 정보는 Redis에 최신값으로 캐싱해두면  
    프론트 또는 백엔드가 빠르게 조회할 수 있다.
- 예:
    - `sensor:latest:sensor_01`
    - `worker:latest:worker_01`
    - `alert:latest`
- 이렇게 하면 DB에서 매번 최신값을 다시 계산하지 않아도 된다.

6. WebSocket 송신부와 Redis 연결
- 2단계에서는 FastAPI가 직접 브라우저에만 보내는 구조에서 나아가,  
    Redis 채널을 구독하는 WebSocket 송신부가 브라우저에 데이터를 전달하는 구조로 확장할 수 있다.
- 즉,
    - 생산자 → Redis publish
    - WebSocket 송신부 → Redis subscribe
    - 브라우저 → 실시간 수신
- 이 구조를 쓰면 생산자 수가 늘어나도 프론트 연결 구조를 단순하게 유지할 수 있다.

7. Django / AI / 알람 처리 분리
- Redis를 도입하면 Django가 모든 로직을 중앙에서 직접 처리하지 않아도 된다.
- 예:
    - 센서 데이터 publish
    - Django는 저장용 consumer
    - AI 서버는 분석용 consumer
    - 알람 처리기는 경고 생성용 consumer
- 즉, 하나의 데이터 흐름에서 여러 서비스가 병렬로 반응할 수 있는 구조가 된다.
- 이는 이후 Kubernetes 및 MSA 확장에도 유리하다.

8. Celery와 Redis 역할 구분
- Redis는 이미 Celery Broker로도 사용되므로,  
    Pub/Sub 용도와 Celery Broker 용도를 함께 쓰게 될 수 있다.
- 이 경우 역할을 명확히 구분해야 한다.
- 예:
    - Pub/Sub: 실시간 이벤트 전달
    - Celery Broker: 비동기 작업 큐 전달
- 같은 Redis를 쓰더라도 키/채널 네이밍 규칙을 분리해야 혼란이 줄어든다.

9. 장애 및 지연 완화
- Redis가 없으면 생산자(FastAPI)가 느려지거나 Django가 잠시 막히면  
    실시간 흐름 전체가 불안정해질 수 있다.
- Redis를 중간에 두면,  
    각 서비스는 자기 속도에 맞게 메시지를 읽거나 처리할 수 있어 전체 안정성이 높아진다.
- 특히 AI 분석처럼 무거운 작업이 붙기 시작하면  
    직접 연결 구조보다 Redis 기반 중간 계층 구조가 훨씬 유리하다.

10. 운영 확장성 확보
- Redis는 단순히 현재 기능을 위한 도구가 아니라  
    이후 다음 구조로 확장하기 위한 핵심 기반이 된다.
    - Celery Worker 분리
    - WebSocket 서버 분리
    - AI 분석 서버 다중화
    - Kubernetes 환경에서 서비스 분산
- 즉, Redis 도입은 “속도 개선”만이 아니라  
    시스템 구조를 운영 가능한 수준으로 끌어올리는 단계라고 볼 수 있다.

---
세부 작업 순서

STEP 1. Redis 도입 범위 정의
- Redis를 어디에 사용할지 먼저 구분한다.
- 예:
    - Celery Broker
    - Pub/Sub 실시간 이벤트
    - 최신 상태 캐시

STEP 2. Redis 서버 구성
- Docker 또는 Docker Compose로 Redis를 실행한다.
- Django, FastAPI, Celery가 Redis에 접근할 수 있도록 환경변수를 정리한다.

STEP 3. Pub/Sub 채널 설계
- 센서, 작업자 위치, 이벤트, AI 분석 요청/결과 등 채널명을 정의한다.
- 네이밍 규칙을 문서화한다.

STEP 4. Publish 로직 구현
- 센서 데이터 생성부 또는 수집부에서 Redis 채널에 데이터를 발행하도록 만든다.
- JSON 포맷을 통일한다.

STEP 5. Subscribe 로직 구현
- Django 또는 별도 소비자 프로세스가 Redis 채널을 구독하여 데이터를 받도록 구현한다.
- 수신 후 DB 저장, 알람 처리, UI 송신 중 어떤 작업을 할지 분리한다.

STEP 6. 최신 상태 캐시 구조 추가
- 센서별 최신값, 작업자 최신 위치, 최근 알람 상태를 Redis key-value로 저장한다.

STEP 7. WebSocket 송신부와 연결
- Redis를 구독하는 WebSocket 송신부가 브라우저에 실시간으로 전달하도록 연결한다.

STEP 8. AI/Celery 연계
- 특정 메시지는 Redis Pub/Sub으로 받고,  
    무거운 작업은 Celery task로 넘기도록 연결한다.

STEP 9. 장애/지연 시나리오 테스트
- 생산자는 빠르고 소비자는 느린 상황
- Redis 재시작 상황
- 소비자 중 하나가 중단된 상황  
    등을 테스트하여 실시간 흐름이 어떻게 유지되는지 확인한다.

STEP 10. 운영 기준 정리
- 어떤 데이터는 Pub/Sub, 어떤 데이터는 캐시, 어떤 데이터는 Celery task로 가는지  
    최종 흐름을 문서로 정리한다.

---
권장 처리 흐름

① 센서 데이터 생성  
② Redis 채널에 publish  
③ Django가 subscribe하여 DB 저장  
④ WebSocket 송신부가 subscribe하여 브라우저 전달  
⑤ AI 처리기는 subscribe 또는 Celery task 등록  
⑥ 최신 상태는 Redis cache에 갱신

---
예시 구조

센서 데이터 실시간 흐름
```
FastAPI 센서 생성기  
   ↓  
Redis publish (sensor.raw)  
   ↓  
- Django 저장 consumer  
- WebSocket 송신 consumer  
- AI 분석 요청 consumer
```

작업자 위치 흐름
```
위치 시뮬레이터  
   ↓  
Redis publish (worker.location)  
   ↓  
- 최신 위치 캐시 업데이트  
- 지도 UI 반영  
- 지오펜스 판단 로직 호출
```

알람 이벤트 흐름
```
위험 판단 로직  
   ↓  
Redis publish (event.alert)  
   ↓  
- WebSocket 알람 송신  
- 이벤트 로그 저장  
- 외부 알림 task 등록
```

---
데이터 예시

Redis publish 메시지 예시
```json
{  
  "type": "sensor_update",  
  "timestamp": "2026-04-12T10:00:00",  
  "device_id": "sensor_01",  
  "metric": "co",  
  "value": 28,  
  "status": "warning",  
  "location": {  
    "x": 150,  
    "y": 180  
  }  
}
```

최신 상태 캐시 예시
```json
key: sensor:latest:sensor_01  
value:  
{  
  "timestamp": "2026-04-12T10:00:00",  
  "co": 28,  
  "status": "warning"  
}
```
---
완료 기준

- Redis가 Docker 환경에서 정상 구동된다.
- 센서 데이터와 작업자 위치 데이터가 Redis 채널로 publish된다.
- Django, WebSocket 송신부, AI 처리부가 필요한 채널을 subscribe할 수 있다.
- 최신 센서 상태 및 작업자 위치를 Redis에서 빠르게 조회할 수 있다.
- 실시간 데이터 처리 흐름이 이전보다 안정적으로 유지된다.
- 한 서비스가 잠시 느려져도 전체 실시간 구조가 즉시 무너지지 않는다.
- Pub/Sub, 캐시, Celery Broker 역할이 명확히 구분된다.

---
주요 산출물

- Redis 환경 구성 파일
- Redis 접속 설정 문서
- Pub/Sub 채널 설계 문서
- publish / subscribe 모듈
- 최신 상태 캐시 키 설계 문서
- WebSocket 연동 구조도
- Redis 기반 실시간 흐름도
- 장애 시나리오 테스트 결과

---
작업 시 주의사항

- Redis를 무조건 빠른 저장소 정도로만 보면 안 되고,  
    이 프로젝트에서는 실시간 데이터 허브로 보는 것이 맞다.
- Pub/Sub은 실시간 전달에는 유리하지만, 영구 저장소가 아니므로  
    중요한 이력 데이터는 반드시 DB에도 저장해야 한다.
- 최신 상태 캐시와 이벤트 로그 저장을 혼동하지 않도록 역할을 구분해야 한다.
- 채널을 너무 세분화하면 복잡해지고, 너무 뭉치면 유지보수가 어려워지므로  
    데이터 성격 기준으로 적절히 나누는 것이 중요하다.
- Celery Broker와 Pub/Sub을 모두 Redis로 사용할 경우  
    네이밍 규칙과 연결 목적을 문서화해두지 않으면 혼란이 생길 수 있다.
- 이후 Prometheus/Grafana로 Redis 상태도 관측할 수 있어야 하므로  
    단순 연결만이 아니라 운영 가능성을 고려한 구조로 설계하는 것이 바람직하다.
- 요구사항 문서상 본 시스템은 실시간 모니터링, 데이터 수집, 알람 대응, AI 분석, API 연계 관리 등 여러 흐름이 동시에 존재하므로,  
    Redis는 이 다중 흐름을 중간에서 안정적으로 연결하는 핵심 인프라 역할을 한다고 볼 수 있다.