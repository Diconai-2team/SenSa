# 가스 농도 추세 패널 (Grafana)

Grafana에 Postgres 데이터소스 + 가스 9종 농도 추세 대시보드 추가.
가스별 시계열 + 주의/위험 임계선 + 초과 시 라인 색 변화(녹→노랑→빨강)로 이상 상승 즉시 탐지.

## 변경점 (09_grafana.yaml 재생성)
- 데이터소스: Prometheus(기존) + **SensaPostgres(신규, uid sensa_pg)** — postgres:5432, 비번은 Secret(sensa-secret)에서 env 주입(평문 복사 없음)
- 대시보드: sensa.json(18, 기존) + **sensa_gas.json(9종 가스, 신규)**
- grafana Deployment: POSTGRES_PASSWORD env(secretKeyRef) 추가

## 적용 (grafana만 갱신 — django 재빌드 불필요)
```bash
cd ~/SenSa && \
unzip -o /mnt/c/Users/kapol/Downloads/gas_panel_patch.zip && \
kubectl apply -f manifests/09_grafana.yaml && \
kubectl -n sensa rollout restart deploy/grafana && \
kubectl -n sensa rollout status deploy/grafana --timeout=120s
```

## 확인
```bash
kubectl -n sensa get pods -l app=grafana   # 1/1 Running
```
브라우저: http://grafana.localhost (또는 port-forward svc/grafana 3000:3000)
→ 대시보드 "🧪 가스 농도 추세 (이상 상승 탐지)" → 9패널, 임계선 표시, 값 상승 시 색 변화

## 임계치 (패널 임계선)
co 25/200 · h2s 10/50 · co2 1000/5000 · nh3 25/50 · no2 3/5 · so2 2/5 · o3 0.05/0.1 · voc 0.5/2.0 · o2 19.5/18(낮을수록 위험)
