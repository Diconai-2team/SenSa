# SenSa (디코나이) — 산업현장 통합 위험 모니터링 플랫폼

가스·전력 센서와 작업자 위치를 **1초 주기로 수집**하고, 위험 상태를 판정해 **실시간 관제 화면과 외부 채널로 경보**하며, 가스 누출 시 **물리 모델 기반 동적 위험구역**이 자동 생성·확산·승격·만료되는 산업안전 백엔드 시스템입니다.

| 항목 | 내용                                                                                                                 |
| ---- | -------------------------------------------------------------------------------------------------------------------- |
| 기간 | 2026.03 ~ 2026.06 (부트캠프 팀 프로젝트, 4인)                                                                        |
| 규모 | Django 앱 16개 · Python 약 21,400 LOC                                                                                |
| 스택 | Django(ASGI/Daphne) · Channels · DRF · FastAPI · Celery · Redis · PostgreSQL · Kubernetes(kind) · Prometheus/Grafana |
| 문서 | [기술문서](docs/SenSa_기술문서_최종_v3.docx) · [검증보고서](docs/SenSa_검증보고서_검증3_시나리오동작.docx)           |

---

## 핵심 기능

**실시간 수집·판정·방송 파이프라인** — FastAPI 생성기가 1초 주기로 전송하는 센서 데이터를 Django가 단일 요청 흐름(값 검증 → 임계 분류 → 저장 → 상태 갱신 → WebSocket 방송 → 경보 평가 → AI 보조 판정)으로 처리합니다. 상태 판정·방송·경보는 매 건, 무거운 저장·AI 추론은 5초 게이트로 솎아 즉시성과 부하를 분리했습니다.

**동적 위험구역 (그레이엄 확산 법칙)** — 센서가 위험으로 전이되는 순간 위험구역이 자동 발동되고, 가스 분자량에 따라 다른 속도(v ∝ 1/√M)로 확산하며, 이웃 센서의 교차 확인으로 잠정→확인→긴급 tier가 승격됩니다(긴급 승격 시 Discord 발송). 시간 만료와 회복 만료의 이중 경로로 좀비 구역을 방지합니다.

**경보 떨림·폭주 제어** — 상태별 독립 윈도우 카운터(격상 5회/회복 7회)로 히스테리시스를 구현해 V자 진동을 차단하고, 동일 경보는 60초 간격으로만 재발행합니다. 억제된 경보 건수까지 메트릭으로 노출해 "조용히 묻은 게 아니라 의도적으로 줄였음"을 수치로 증명합니다.

**복원력 (graceful degradation)** — Redis·채널·외부알림·메트릭 등 보조 기능의 장애가 핵심 경로(저장·판정·생애주기)를 절대 멈추지 않도록 전 구간이 격리돼 있습니다. 상태 저장소는 연결 오류만 흡수하고 코드 버그는 그대로 전파해, 장애 흡수와 버그 은폐를 구분합니다.

## 실측 검증 결과 (실제 운영 구성 Kubernetes, 다중 replica)

| 항목               | 결과                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------- |
| 저장 게이트 효율   | 유입 3,464건 → 저장 773건, **약 −78%** (상태 전이는 즉시 저장 유지)                   |
| 경보 차단율        | **97~98%** (신규 전이는 차단 0, 반복 신호만 억제 — 메트릭으로 검증)                   |
| 시나리오 분류 정합 | 생성 의도(expected_status) 대비 실제 분류 일치율 **95.2%** (n=1,040, 순수 오분류 0건) |
| 다중 Pod 정합성    | 3 replica 동시 운전 중 위험구역 자동 발동 **정확히 1회** (Redis 원자 게이트)          |

상세 절차·스크린샷은 검증보고서(기술문서 14장 통합) 참조.

## 아키텍처

```
FastAPI 생성기 ──1초 POST(X-Internal-API-Key)──▶ Django (Daphne/ASGI, HPA 2~5)
                                                  │ 검증→분류→저장(5초 게이트)→방송→경보→AI
            브라우저 ◀──WebSocket(Channels)────────┤
            Discord ◀──Celery(외부알림)────────────┤
                                                  ├─ PostgreSQL (시계열·도메인, PVC)
                                                  ├─ Redis (db0 채널/브로커 · db2 캐시/상태머신/게이트)
                                                  └─ Celery beat ──30초 tick──▶ 위험구역 확산·승격·만료
            Prometheus ──pull──▶ Django:8000 · 생성기:8001 · Celery:9809 ──▶ Grafana(패널 18+)
```

전체는 kind 단일 노드 Kubernetes(네임스페이스 `sensa`) 위에서 동작하며, 진입은 ingress-nginx를 통합니다. 업로드 파일(평면도)은 PVC 공유 볼륨(`/app/media`)으로 전 Pod에 공동 마운트됩니다.

## 빠른 시작

요구사항: Docker, kind(또는 Docker Desktop K8s) + 로컬 레지스트리 `localhost:5000`, ingress-nginx, kubectl.

```bash
# 1) 최초 부트스트랩 — 매니페스트 순서 적용
kubectl apply -f manifests/01_namespace.yaml
kubectl apply -f manifests/02_config_secret.yaml -f manifests/02b_config_patch.yaml
kubectl apply -f manifests/03_postgres.yaml -f manifests/04_redis.yaml
kubectl apply -f manifests/05b_media_pvc.yaml -f manifests/05_django.yaml
kubectl apply -f manifests/06_celery.yaml -f manifests/07_generator.yaml
kubectl apply -f manifests/08_prometheus.yaml -f manifests/09_grafana.yaml
kubectl apply -f manifests/10_ingress.yaml -f manifests/11_hpa.yaml

# 2) 이미지 빌드·반영 (이후 코드 수정 시에도 이 한 줄)
./redeploy.sh    # 시각 기반 고유 태그 빌드 → push → django+celery 동시 롤아웃

# 3) 관리자 계정 (시드가 superuser는 만들지 않음)
kubectl exec -n sensa deploy/django -c django -it -- python manage.py createsuperuser
```

접속: 관제 대시보드 `http://sensa.localhost` · Grafana `http://grafana.localhost`
(생성기·Prometheus 직접 확인: `kubectl port-forward -n sensa svc/generator 8001:8001`, `svc/prometheus 9090:9090`)

마이그레이션은 Django Pod 기동 시 initContainer가 자동 실행하며, 정적 파일은 이미지 빌드 단계의 `collectstatic`으로 수집됩니다.

## 시나리오 시연 (R&D 토글)

명령 한 번으로 사고 시계열(정상→전조→주의→위험→peak→복귀)이 자동 전개됩니다.

```bash
# H2S 누출 시나리오 시작 — 약 60~90초 후 위험 돌파, 위험구역 자동 생성
curl -X POST 'localhost:8001/anomaly/toggle?device_id=sensor_01&state=true'

curl localhost:8001/anomaly/state          # phase 진행 확인
curl -X POST 'localhost:8001/anomaly/toggle?device_id=sensor_01&state=false'   # 복귀
curl -X POST 'localhost:8001/anomaly/clear-all'                                # 전체 초기화
```

매핑: `sensor_01`=G3 H₂S 누출 · `sensor_02`=G4 CO 연소이상 · `sensor_03`=G1 환기 불량 · `power_01`=P1 과부하 · `power_02`=P3 전압 강하. 생성 데이터에는 `expected_status` 라벨이 동봉돼 분류 정합을 사후 정량 검증할 수 있습니다.

## 설계 원칙

1. **단일 출처·단일 발행** — 판정·저장·방송을 Django 한 곳에서, 경보 발행은 평가기 한 곳에서, 구역 이벤트는 `_emit` 한 곳에서.
2. **부하 게이트** — 무거운 작업(저장·AI·백업·외부발송)은 원자적 게이트(Redis SET NX EX)·청크·Celery로 솎거나 오프로드. 다중 Pod에서도 창당 정확히 1회.
3. **graceful degradation** — 보조 기능 실패가 본류를 멈추지 않게 전 구간 격리. 단, 장애만 흡수하고 버그는 전파.
4. **운영 가시성** — 경보 생성·억제, 저장 결과, Celery 재시도까지 비즈니스 메트릭으로 노출해 설계 효과를 Grafana에서 수치로 증명.

## 프로젝트 구조

| 디렉터리                                                              | 책임                                             |
| --------------------------------------------------------------------- | ------------------------------------------------ |
| `SenSa/devices`                                                       | 센서 수신구(SensorDataView)·근접 그래프          |
| `SenSa/alerts`                                                        | 경보 평가기·상태머신(Redis)·AI 서비스·외부 알림  |
| `SenSa/geofence`                                                      | 위험구역 확산·생애주기·자동 발동·이벤트·시나리오 |
| `SenSa/realtime`                                                      | WebSocket consumer·발행 래퍼·최신 상태 캐시      |
| `SenSa/backoffice`                                                    | 마스터데이터·권한·감사·알림 디스패치·백업        |
| `SenSa/dashboard` · `workers` · `accounts` · `safety` · `vr_training` | 관제 UI·작업자·인증·부가기능                     |
| `fastapi_generator/`                                                  | 센서 데이터 생성기 + R&D 시나리오 토글           |
| `manifests/`                                                          | Kubernetes 매니페스트 (01→11 순서 적용)          |
| `sensa_observability/`                                                | Prometheus 설정·Grafana 대시보드(JSON)           |

## 팀 구성과 기여 경계

4인 팀 프로젝트입니다. AI 알고리즘 내부(ARIMA 이상탐지·IsolationForest 추세예측·임계 분류기)는 담당 팀원이 구현했으며, 본 저장소의 수집·판정·방송 파이프라인, 위험구역 도메인, 실시간 인프라, Kubernetes 배포·관측은 백엔드/인프라 담당이 구현했습니다. 알고리즘은 명확한 함수 인터페이스로 캡슐화되어 파이프라인이 내부를 알 필요 없이 결과만 소비합니다. 상세 경계는 기술문서 13장에 명시되어 있습니다.

## 한계와 향후 과제 (인지된 상태)

단일 Redis·PostgreSQL은 SPOF(데모 규모의 의도적 단순화)이며, 임계값이 코드·DB·프런트 세 곳에 존재해 단일화가 1순위 후속 과제입니다. 업로드 볼륨의 RWO는 단일 노드 전제로, 다중 노드 확장 시 RWX/오브젝트 스토리지 전환이 필요합니다. Alertmanager·시스템 알람 규칙·CI 자동 테스트는 미구성이고(이미지 고유 태그는 적용됨), 운영 중 kubectl 직접 변경으로 인한 매니페스트 드리프트를 경험하고 동기화한 사례로부터 GitOps 도입 필요성을 확인했습니다. 전체 목록은 기술문서 15장 참조.
