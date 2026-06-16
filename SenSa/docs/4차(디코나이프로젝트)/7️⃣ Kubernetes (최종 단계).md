작업 목적

Docker Compose 기반으로 개별 컨테이너를 실행하는 수준을 넘어,  
Django, FastAPI, Redis, PostgreSQL, Celery, 모니터링 시스템 등을  
**운영 가능한 형태로 배포·확장·복구할 수 있는 오케스트레이션 환경**을 구축하는 것이 목적이다.

2단계 후반부에서는 시스템이 단순 실행을 넘어서

- 트래픽 증가 시 자동 확장
- 장애 발생 시 자동 복구
- 외부 접근 경로 통합
- 서비스 간 안정적 통신
- 운영 환경 분리  
    가 가능해야 한다.

즉, Kubernetes 단계의 핵심은  
컨테이너를 실행하는 것이 아니라 서비스를 운영 가능한 시스템으로 관리하는 것이다.

본 프로젝트 기준으로 Kubernetes는  
실시간 데이터 수집, AI 분석, 비동기 처리, 알람, 모니터링, 외부 접근 구조를  
하나의 클러스터 안에서 안정적으로 운영하기 위한 최종 인프라 단계에 해당한다.

---
작업 내용

1. Kubernetes 적용 대상 서비스 정의
- Kubernetes에 올릴 주요 서비스는 다음과 같다.
    - Django 관제 서버
    - FastAPI 센서/AI 서버
    - Celery Worker
    - Redis
    - PostgreSQL
    - Prometheus
    - Grafana
- 초기 적용은 핵심 서비스부터 시작하고,  
    이후 모니터링 및 운영 보조 서비스까지 확장하는 방식으로 진행한다.
- 서비스별 역할과 중요도를 기준으로 배포 우선순위를 정해야 한다.

2. Namespace 구성
- 프로젝트 자원을 하나의 작업 공간 안에서 관리할 수 있도록 전용 namespace를 생성한다.
- 예:
    - `monitoring-platform`
    - `review-k8s` 와 같은 별도 namespace
- namespace를 분리하면
    - 서비스 관리가 명확해지고
    - 다른 실습/프로젝트와 충돌을 줄일 수 있으며
    - 리소스 조회, 삭제, 로그 확인이 쉬워진다.

3. Deployment 구성
- 각 애플리케이션 서비스는 Deployment로 배포한다.
- 대상:
    - Django
    - FastAPI
    - Celery
    - (필요 시) Redis
- Deployment는 다음 역할을 한다.
    - 원하는 수의 Pod 유지
    - Pod 장애 시 자동 재생성
    - 이미지 변경 시 롤링 업데이트
- 이를 통해 특정 Pod가 죽어도 서비스가 계속 유지될 수 있다.

4. Stateful 서비스 구성
- PostgreSQL처럼 데이터 영속성이 중요한 서비스는 StatefulSet 또는 별도 영속 스토리지 구조를 고려해야 한다.
- DB는 단순 Deployment보다
    - 데이터 보존
    - 고정된 식별성
    - Persistent Volume 연결  
        이 중요하므로 상태 저장 구조가 필요하다.
- 2단계에서는 최소한 Persistent Volume Claim(PVC)을 연결하여  
    Pod 재생성 시에도 데이터가 유지되도록 구성해야 한다.

5. Service 구성
- Kubernetes 내부에서 각 Pod에 직접 접근하지 않고,  
    안정적인 네트워크 엔드포인트를 제공하기 위해 Service를 생성한다.
- 예:
    - Django Service
    - FastAPI Service
    - Redis Service
    - PostgreSQL Service
- Service를 사용하면 Pod가 재생성되어 IP가 바뀌더라도  
    다른 서비스는 동일한 이름으로 계속 접근할 수 있다.
- 즉, Kubernetes 내부 통신의 기준점 역할을 한다.

6. ConfigMap / Secret 분리
- 환경변수와 민감정보를 코드나 이미지 안에 넣지 않고 Kubernetes 자원으로 분리한다.
- ConfigMap:
    - 일반 환경설정
    - 호스트명
    - URL
    - DEBUG 여부
- Secret:
    - DB 비밀번호
    - Django Secret Key
    - 외부 Webhook 키
- 이를 통해 운영 설정을 배포와 분리하고, 환경 전환을 쉽게 할 수 있다.

7. Ingress 구성
- 외부 사용자가 하나의 도메인 또는 하나의 진입점으로 여러 서비스를 접근할 수 있도록 Ingress를 구성한다.
- 예:
    - `/` → Django
    - `/api` → Django API
    - `/docs` → FastAPI
    - `/grafana` → Grafana
- Ingress를 사용하면 외부 트래픽을 URL 경로 또는 호스트 기준으로 적절한 서비스에 라우팅할 수 있다.
- 2단계에서는 Nginx Ingress Controller를 기반으로 구성하는 것이 가장 일반적이다.

8. HPA(Horizontal Pod Autoscaler) 구성
- 실시간 데이터량이 증가하거나 AI 요청이 늘어날 경우,  
    Pod 수를 자동으로 늘리거나 줄일 수 있도록 HPA를 설정한다.
- 일반적으로 CPU 또는 메모리 사용량 기준으로 스케일링한다.
- 적용 대상 예시:
    - Django
    - FastAPI
    - Celery Worker
- HPA를 적용하면 트래픽 급증 상황에서도 시스템이 자동으로 대응할 수 있다.

9. 헬스체크(Readiness/Liveness Probe) 적용
- Pod가 단순히 실행 중인 것만으로는 충분하지 않다.
- 실제 요청을 받을 준비가 되었는지, 프로세스가 정상인지 확인하기 위해 probe를 설정한다.
- Readiness Probe:
    - 서비스 트래픽을 받아도 되는 상태인지 확인
- Liveness Probe:
    - 프로세스가 비정상 상태일 때 재시작 유도
- 이 설정은 장애 복구 자동화의 핵심이다.

10. 롤링 업데이트 및 롤백 고려
- 이미지 버전을 변경하거나 설정을 수정해도  
    서비스를 중단하지 않고 순차적으로 Pod를 교체하는 구조가 필요하다.
- Deployment는 롤링 업데이트를 지원하므로,  
    새 버전 배포 시 무중단 배포에 가까운 흐름을 구현할 수 있다.
- 문제가 발생하면 이전 버전으로 롤백할 수 있어야 한다.

11. 모니터링 연계
- Kubernetes 환경에서는 애플리케이션뿐 아니라 Pod, Node, 리소스 사용량까지 함께 관찰해야 한다.
- Prometheus와 Grafana를 Kubernetes에 연결하면 다음을 볼 수 있다.
    - Pod 수 변화
    - CPU/Memory 사용량
    - HPA 동작 여부
    - 서비스별 상태
- 즉, Kubernetes 단계는 모니터링과 분리될 수 없다.

12. 장애 복구 시나리오 검증
- Kubernetes 도입의 핵심 가치는 자동 복구다.
- 따라서 실제로 다음을 테스트해야 한다.
    - Django Pod 강제 삭제
    - FastAPI Pod 재시작
    - Celery Worker 중단
- 이때 Deployment가 새 Pod를 자동 생성하고,  
    Service/Ingress가 계속 정상 연결되는지 확인해야 한다.

13. 배포 순서와 의존성 관리
- 모든 서비스를 한 번에 올리기보다 순차적으로 적용해야 한다.
- 권장 순서:
    1. Namespace
    2. ConfigMap / Secret
    3. PostgreSQL / Redis
    4. Django / FastAPI
    5. Celery
    6. Prometheus / Grafana
    7. Service
    8. Ingress
    9. HPA
- 이렇게 해야 디버깅이 쉬워지고, 어느 단계에서 문제가 생겼는지 추적이 가능하다.

14. 운영 기준 문서화
- Kubernetes는 단순히 YAML 파일을 만드는 것으로 끝나지 않는다.
- 운영 관점에서 다음 기준을 문서로 정리해야 한다.
    - 배포 순서
    - 이미지 업데이트 절차
    - 로그 확인 명령어
    - 장애 시 점검 순서
    - 확장 기준
- 이 문서가 있어야 팀 단위 운영이나 발표/시연 때도 설명이 가능하다.

---
세부 작업 순서

STEP 1. 배포 대상 서비스 정리
- Django, FastAPI, Redis, PostgreSQL, Celery, Prometheus, Grafana 중  
    어떤 서비스부터 Kubernetes에 올릴지 우선순위를 정한다.

STEP 2. Namespace 생성
- 전용 namespace를 만들고 모든 자원을 해당 namespace 기준으로 관리한다.

STEP 3. ConfigMap / Secret 작성
- 환경변수, 비밀키, DB 접속정보, 외부 Webhook 정보를 분리 정의한다.

STEP 4. PostgreSQL / Redis 배포
- DB와 메시지 브로커를 먼저 올리고 내부 통신이 가능한 상태를 만든다.
- DB는 PVC를 연결해 데이터 영속성을 보장한다.

STEP 5. Django / FastAPI Deployment + Service 생성
- 메인 애플리케이션을 배포하고 내부 Service로 연결한다.
- readiness/liveness probe를 함께 설정한다.

STEP 6. Celery Worker 배포
- Django 이미지 또는 별도 이미지로 Celery Worker를 실행하고 Redis Broker 연결을 검증한다.

STEP 7. Prometheus / Grafana 배포
- 애플리케이션 메트릭과 클러스터 상태를 수집/시각화할 수 있도록 배포한다.

STEP 8. Ingress 구성
- 외부 접근 경로를 통합하고 URL 라우팅 규칙을 설정한다.

STEP 9. HPA 적용
- Django, FastAPI 또는 Celery에 대해 자동 확장 정책을 적용한다.

STEP 10. 장애 복구 및 확장 테스트
- Pod 삭제, 부하 테스트, HPA 반응, Ingress 연결 상태를 검증한다.

---
권장 배포 구조
```
[Ingress]  
   ↓  
[Django Service]   [FastAPI Service]   [Grafana Service]  
   ↓                    ↓  
[Django Pods]       [FastAPI Pods]  
  
[Celery Worker Pods]  
   ↓  
[Redis Service]  
  
[PostgreSQL Stateful Service]  
   ↓  
[Persistent Volume]
```

---
권장 처리 흐름

① Docker 이미지 빌드  
② Kubernetes 클러스터에 이미지 반영  
③ Namespace 생성  
④ ConfigMap / Secret 적용  
⑤ Redis / PostgreSQL 배포  
⑥ Django / FastAPI / Celery 배포  
⑦ Service 연결  
⑧ Ingress 연결  
⑨ HPA 적용  
⑩ 모니터링 및 장애 복구 테스트

---
Kubernetes 리소스별 역할 정리

Deployment
- 애플리케이션 Pod 수 유지
- 장애 시 자동 재생성
- 롤링 업데이트 지원

Service
- Pod 앞단 고정 엔드포인트 제공
- 내부 통신 안정화

Ingress
- 외부 요청 라우팅
- 단일 진입점 구성

HPA
- CPU/메모리 기준 자동 확장
- 트래픽 증가 대응

ConfigMap / Secret
- 설정값 / 민감정보 분리

PVC
- DB 데이터 영속성 보장

---
완료 기준

- Django, FastAPI, Redis, PostgreSQL, Celery가 Kubernetes 환경에서 정상 배포된다.
- 각 서비스가 Service를 통해 안정적으로 내부 통신할 수 있다.
- 외부 사용자는 Ingress를 통해 필요한 서비스에 접근할 수 있다.
- Pod 장애 발생 시 Deployment가 자동으로 새 Pod를 생성한다.
- PostgreSQL 데이터가 Pod 재생성 후에도 유지된다.
- HPA 적용 대상 서비스가 부하 증가 시 자동으로 확장된다.
- readiness/liveness probe를 통해 비정상 Pod가 자동으로 교체된다.
- Prometheus/Grafana를 통해 Kubernetes 및 애플리케이션 상태를 함께 관찰할 수 있다.
- 운영자가 장애 복구 및 확장 흐름을 재현 가능한 수준으로 확인할 수 있다.

---
주요 산출물

- Namespace YAML
- ConfigMap / Secret YAML
- PostgreSQL / Redis 배포 YAML
- Django / FastAPI / Celery Deployment YAML
- Service YAML
- Ingress YAML
- HPA YAML
- Persistent Volume / PVC 설정 문서
- Kubernetes 배포 순서 문서
- 장애 복구 및 확장 테스트 결과
- 운영 점검 가이드

---
작업 시 주의사항

- Kubernetes는 Docker Compose를 단순 치환하는 도구가 아니라 운영 자동화 플랫폼이므로, 서비스 역할 분리를 먼저 명확히 해야 한다.
- DB는 반드시 영속성 구조를 함께 고려해야 하며, 단순 Deployment로만 올리면 운영 환경에서 문제가 발생할 수 있다.
- HPA는 metrics-server 등 전제 조건이 필요하므로, 자동 확장은 YAML만 만든다고 바로 동작하지 않는다.
- Ingress를 적용하기 전에 Service 연결과 애플리케이션 응답이 정상인지 먼저 확인해야 한다.
- readiness/liveness probe가 잘못 설정되면 정상 서비스도 계속 재시작될 수 있으므로 점진적으로 적용해야 한다.
- 장애 복구 테스트는 반드시 실제로 Pod를 삭제해보며 검증하는 것이 좋다.
- 요구사항 문서 및 4차 프로젝트 구조상 최종 단계는 실서비스 수준의 운영 가능 구조, 자동 확장, 장애 대응, 모니터링을 포함하는 방향으로 정의되어 있으므로, Kubernetes 단계는 단순 배포가 아니라 운영 체계 완성 단계로 보는 것이 맞다.