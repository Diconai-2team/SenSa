# SenSa Observability v2 — 재설계본

## v1 → v2 변경점 (결함 영구 회피)

| v1 결함 | v2 해결 |
|---|---|
| bind mount inode 추적 결함 (sed -i 가 unlink+create, 컨테이너 측 mount 파괴) | Dockerfile COPY 로 config 를 이미지에 내장 |
| host.docker.internal NAT (192.168.65.254) 가 WSL host 라우팅 실패 | `network_mode: host` — 컨테이너가 WSL host 네트워크 namespace 공유, localhost 직접 사용 |
| Prometheus config reload 명령이 작동 안 함 | `--web.enable-lifecycle` 추가 + `docker compose up -d --build` 워크플로 |
| WSL_IP 가변성 | `localhost` 로 통일 (host 네트워크 공유라 IP 무관) |

## 가동 (한 번에)

```bash
# 0. 사전 조건 — Django + FastAPI 가동 중인지 확인
curl -fsS -o /dev/null -w "Django  HTTP %{http_code}\n" http://127.0.0.1:8000/
curl -fsS -o /dev/null -w "FastAPI HTTP %{http_code}\n" http://127.0.0.1:8001/

# 1. 기존 v1 컨테이너 정리 + 폴더 삭제
cd ~/SenSa/sensa_observability && docker compose down -v 2>/dev/null
cd ~ && rm -rf ~/SenSa/sensa_observability

# 2. v2 풀기 + 빌드 + 가동 (이미지 빌드 30~60초)
unzip -o /mnt/c/Users/kapol/Downloads/sensa_observability_v2.zip -d ~/SenSa/
cd ~/SenSa/sensa_observability
docker compose up -d --build

# 3. 20초 대기 (scrape 2회 주기 + Grafana provisioning)
sleep 20

# 4. 검증
bash verify.sh
```

## 브라우저 접속

| URL | 용도 |
|---|---|
| http://localhost:3000/d/sensa-main | 대시보드 직행 |
| http://localhost:9090/targets | scrape UP/DOWN |

## config 변경 워크플로 (v1 보다 단순)

```bash
# prometheus.yml 또는 sensa.json 편집 후
docker compose up -d --build
# 이미지 재빌드 + 컨테이너 재가동 (1초)
# bind mount 추적 결함 없음
```

## 중지 / 정리

```bash
docker compose stop       # 데이터 유지
docker compose down -v    # 완전 제거 (volume 삭제)
```

## network_mode: host 의 의미

- 컨테이너가 별도 네트워크 namespace 를 만들지 않고 WSL host 의 namespace 공유
- prometheus 컨테이너 안에서 `localhost:8000` = WSL host 의 8000 = Django runserver
- 단점: Linux/WSL2 전용. macOS/Windows native Docker 에서는 별도 처리 필요
- SenSa 발표 환경 = WSL2 라 문제 없음
