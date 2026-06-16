작업 목적

개발 환경마다 설치 상태와 실행 방식이 달라 발생할 수 있는 차이를 줄이고,  
Django, FastAPI, Redis, PostgreSQL 등 여러 서비스를 **동일한 실행 환경에서 일관되게 구동**할 수 있도록  
프로젝트를 컨테이너 기반 구조로 전환하는 것이 목적이다.

2단계에서는 AI 서버, 비동기 처리, Redis, DB, 모니터링까지 포함되면서  
서비스 수가 많아지고 실행 순서도 복잡해진다.  
이때 Docker를 도입하면 각 서비스를 독립된 컨테이너로 분리하여  
**개발 / 테스트 / 시연 / 배포 준비 단계까지 동일한 방식으로 실행**할 수 있다.

즉, Docker 구성의 핵심은  
단순히 “컨테이너에서 돌아간다”가 아니라,  
**여러 서비스를 묶어서 운영 가능한 하나의 시스템처럼 관리할 수 있게 만드는 것**이다.

---
작업 내용

1. 컨테이너화 대상 서비스 정의
- 2단계 기준 핵심 실행 대상은 다음과 같다.
    - Django 관제 서버
    - FastAPI 엣지/AI 서버
    - Redis
    - PostgreSQL
- 이후 확장 대상:
    - Celery Worker
    - Prometheus
    - Grafana
    - Nginx
- 처음부터 모든 서비스를 한 번에 올리기보다,  
    핵심 애플리케이션 컨테이너부터 안정화한 뒤 점차 확장하는 것이 좋다.

2. 서비스별 역할 분리
- 각 컨테이너는 하나의 명확한 역할을 갖도록 분리한다.
- 예:
    - Django: 메인 관제 API, 관리자 기능, 지오펜스/이벤트 처리
    - FastAPI: 센서 데이터 생성/수집, AI 분석 API
    - Redis: Pub/Sub, 캐시, Celery Broker
    - PostgreSQL: 운영 데이터 영속 저장
- 이렇게 분리해야 이후 디버깅, 확장, Kubernetes 이전이 쉬워진다.

3. Django Dockerfile 구성
- Django 애플리케이션 실행에 필요한 Python 환경, 패키지 설치, 프로젝트 소스 복사, 실행 명령을 정의한다.
- 주요 포함 항목:
    - Python 베이스 이미지
    - requirements 설치
    - 프로젝트 코드 복사
    - 환경변수 사용
    - runserver 또는 gunicorn 실행 명령
- 개발 단계에서는 runserver로 시작할 수 있지만,  
    운영형 테스트를 고려하면 gunicorn 실행 구조까지 미리 준비하는 것이 좋다.

4. FastAPI Dockerfile 구성
- FastAPI는 Django와 별도의 독립 컨테이너로 구성한다.
- 주요 포함 항목:
    - Python 베이스 이미지
    - requirements 설치
    - FastAPI 소스 복사
    - uvicorn 실행 명령
- 센서 데이터 생성 및 AI 분석 역할을 나중에 분리할 가능성이 있으므로,  
    현재는 하나의 FastAPI 컨테이너로 시작하더라도 폴더 구조는 역할 분리를 염두에 두고 구성하는 것이 좋다.

5. Redis / PostgreSQL 컨테이너 연결
- Redis와 PostgreSQL은 공식 이미지를 활용해 빠르게 구성할 수 있다.
- Redis:
    - 포트 노출
    - 브로커/캐시 역할
- PostgreSQL:
    - DB명, 사용자, 비밀번호, 포트 설정
    - 데이터 영속성을 위한 volume 연결
- DB는 컨테이너 재시작 시 데이터가 유지되어야 하므로 volume 구성이 필수다.

6. Docker Compose 기반 통합 실행
- 여러 서비스를 한 번에 실행하기 위해 `docker-compose.yml` 또는 `compose.yaml` 파일을 작성한다.
- Compose에서는 다음을 한 번에 정의할 수 있다.
    - 서비스 목록
    - 빌드 경로
    - 포트 매핑
    - 환경변수
    - 의존 관계
    - 볼륨
    - 네트워크
- Compose를 사용하면 `docker compose up`만으로 전체 시스템을 띄울 수 있어  
    개발/시연/테스트 효율이 크게 올라간다.

7. 환경변수 분리
- 컨테이너 내부 설정값(DB 접속정보, Redis 주소, 비밀키, API URL 등)은  
    코드에 하드코딩하지 말고 `.env` 파일 또는 Compose 환경변수로 분리한다.
- 예:
    - DB_HOST
    - DB_NAME
    - DB_USER
    - DB_PASSWORD
    - REDIS_URL
    - FASTAPI_BASE_URL
- 이렇게 해야 로컬 / 테스트 / 운영 환경 전환이 쉬워진다.

8. 컨테이너 간 네트워크 통신 구조 정리
- Docker Compose 환경에서는 각 서비스가 서비스명으로 서로 통신할 수 있다.
- 예:
    - Django → PostgreSQL: `db`
    - Django → Redis: `redis`
    - Django → FastAPI: `fastapi`
- 즉, 로컬의 `127.0.0.1`이 아니라  
    컨테이너 내부에서는 서비스명 기준 주소를 사용해야 한다.
- 이 구조를 정확히 잡아야 추후 Kubernetes Service 구조로 넘어갈 때도 자연스럽다.

9. 데이터 영속성 및 볼륨 구성
- PostgreSQL 데이터는 컨테이너가 재생성되어도 유지되어야 한다.
- Redis는 경우에 따라 메모리 기반으로 충분할 수 있으나,  
    개발/테스트 환경에서는 최소한 DB는 반드시 볼륨을 분리해야 한다.
- 필요 시 Django의 정적 파일, 업로드 파일도 volume 또는 외부 저장소 구조를 고려한다.

10. 개발/운영 모드 구분
- Docker 구성은 개발용과 운영용을 명확히 구분할 필요가 있다.
- 개발용:
    - 코드 수정 반영 빠름
    - 볼륨 마운트
    - debug 활성화 가능
- 운영용:
    - gunicorn/uvicorn 정식 실행
    - debug 비활성화
    - 정적 파일 처리
- 2단계에서는 우선 개발/시연용 Compose를 만들고,  
    이후 운영형 Compose 또는 Kubernetes 매니페스트로 확장하는 것이 적절하다.

11. Celery / 모니터링 서비스 확장 준비
- 현재 작업 항목은 django / fastapi / redis / postgres가 핵심이지만,  
    2단계 후반에는 다음 서비스를 추가해야 한다.
    - Celery Worker
    - Prometheus
    - Grafana
- 따라서 초기 Compose 작성 시에도 서비스 확장이 가능하도록 구조를 정리해두는 것이 좋다.
- 예를 들어 Django와 동일 이미지를 Celery Worker에서 재사용할 수 있게 하면 관리가 쉬워진다.

12. 실행 및 헬스체크 검증
- 각 컨테이너가 단순히 실행 중인 것만으로는 충분하지 않다.
- 다음을 검증해야 한다.
    - Django가 실제 요청에 응답하는가
    - FastAPI `/docs` 또는 API가 열리는가
    - Redis 연결이 정상인가
    - PostgreSQL 접속이 되는가
- 향후 Kubernetes 이전을 고려하면 헬스체크 개념을 미리 반영하는 것이 좋다.

---
세부 작업 순서

STEP 1. 서비스 목록 확정
- 우선 docker 대상 서비스를 정리한다.
- 기본: Django / FastAPI / Redis / PostgreSQL

STEP 2. Django Dockerfile 작성
- Python 이미지, requirements 설치, 프로젝트 복사, 실행 명령을 정의한다.

STEP 3. FastAPI Dockerfile 작성
- FastAPI 앱 실행용 Dockerfile을 작성한다.

STEP 4. Compose 파일 작성
- 서비스별 build, ports, volumes, env, depends_on을 정의한다.

STEP 5. Redis / PostgreSQL 연결
- 공식 이미지를 붙이고 Django/FastAPI가 접근할 수 있도록 환경변수를 설정한다.

STEP 6. `.env` 파일 분리
- 비밀키, DB 정보, 서비스 URL 등을 환경변수로 분리한다.

STEP 7. 컨테이너 실행 테스트
- `docker compose up --build` 로 전체 서비스를 띄운다.
- 각 컨테이너가 정상 기동되는지 확인한다.

STEP 8. 애플리케이션 연결 테스트
- Django ↔ DB
- Django ↔ Redis
- Django ↔ FastAPI  
    연결이 정상 동작하는지 검증한다.

STEP 9. 데이터 영속성 테스트
- PostgreSQL 컨테이너를 재시작해도 데이터가 유지되는지 확인한다.

STEP 10. 확장 서비스 준비
- 이후 Celery, Prometheus, Grafana를 Compose에 추가할 수 있도록 파일 구조를 정리한다.

---
권장 구성 구조
```
[django]  
  - 관제 서버  
  - DRF API  
  - 지오펜스 / 이벤트 처리  
  
[fastapi]  
  - 센서 데이터 생성/수집  
  - AI 분석 API  
  
[redis]  
  - Pub/Sub  
  - Celery Broker  
  - 캐시  
  
[postgres]  
  - 운영 데이터 저장
```

---
예시 실행 흐름
```
docker compose up --build  
   ↓  
django / fastapi / redis / postgres 컨테이너 기동  
   ↓  
Django가 DB 연결  
   ↓  
Django가 Redis 연결  
   ↓  
Django가 FastAPI 호출 가능  
   ↓  
전체 시스템 통합 실행 가능
```

---
환경변수 예시
```python
DJANGO_SECRET_KEY=your-secret-key  
DJANGO_DEBUG=True  
  
DB_NAME=monitoring_db  
DB_USER=postgres  
DB_PASSWORD=postgres  
DB_HOST=db  
DB_PORT=5432  
  
REDIS_URL=redis://redis:6379/0  
FASTAPI_BASE_URL=http://fastapi:8001
```

---
Compose 예시 구조 개념
```yaml
services:  
  django:  
    build: ./backend  
    ports:  
      - "8000:8000"  
    env_file:  
      - .env  
    depends_on:  
      - db  
      - redis  
      - fastapi  
  
  fastapi:  
    build: ./ai-server  
    ports:  
      - "8001:8001"  
  
  redis:  
    image: redis:7  
  
  db:  
    image: postgres:15
```
※ 실제 문서에는 개념 구조만 넣고, 상세 코드는 별도 실행 문서로 분리하는 것이 좋다.

---
완료 기준

- Django, FastAPI, Redis, PostgreSQL이 각각 컨테이너로 분리되어 실행된다.
- `docker compose up` 명령으로 전체 시스템을 한 번에 기동할 수 있다.
- Django가 PostgreSQL과 Redis에 정상 연결된다.
- Django가 FastAPI API를 호출할 수 있다.
- 컨테이너 재시작 후에도 PostgreSQL 데이터가 유지된다.
- `.env` 기반 설정 분리가 적용되어 환경 변경이 가능하다.
- 이후 Celery, Prometheus, Grafana를 쉽게 추가할 수 있는 구조가 마련된다.

---
주요 산출물

- Django Dockerfile
- FastAPI Dockerfile
- Docker Compose 파일
- `.env` 환경변수 파일
- 컨테이너 실행 가이드
- 서비스 연결 구조 문서
- 볼륨 및 데이터 영속성 설정 문서
- 통합 실행 테스트 결과

---
작업 시 주의사항

- 컨테이너 내부에서는 `localhost` 대신 서비스명으로 통신해야 한다.
- Django/FastAPI 모두 requirements 누락이 없도록 관리해야 하며,  
    패키지 하나만 빠져도 컨테이너가 기동 실패할 수 있다.
- DB와 Redis는 애플리케이션보다 먼저 준비되어야 하므로 `depends_on`만 믿지 말고  
    실제 연결 재시도 로직도 고려하는 것이 좋다.
- 개발용 Docker와 운영용 Docker의 목적이 다르므로, 2단계에서는 우선 개발/시연용 안정화에 집중한다.
- PostgreSQL volume 설정이 없으면 컨테이너 재생성 시 데이터가 사라질 수 있으므로 반드시 영속성 구성을 해야 한다.
- 본 프로젝트는 이후 Kubernetes로 확장될 예정이므로, Docker Compose 단계에서 이미 서비스 분리와 환경변수 관리 원칙을 명확히 잡아두는 것이 중요하다.
- 요구사항 문서상 외부 접근 가능한 MVP, 클라우드 배포, API 연계 관리, 로그 관리, 운영 환경 적용 가능한 구조가 포함되어 있으므로,  
    Docker 구성은 단순 실행 편의가 아니라 운영 인프라로 넘어가기 위한 필수 중간 단계라고 볼 수 있다.