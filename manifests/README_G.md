# K8s G단계 — Prometheus + Grafana + Ingress + HPA

13차에서 완료한 E·F단계(6 Pod Running) 위에 모니터링 + 외부 노출 + 자동 확장을 추가합니다.

## 산출물 (manifests/ 에 병합)

| 파일 | 리소스 | 핵심 |
|---|---|---|
| `08_prometheus.yaml` | SA + RBAC + ConfigMap + Service + Deployment | K8s endpoints 서비스 디스커버리 (django 2 replica 자동 발견) |
| `09_grafana.yaml` | ConfigMap×3 + Service + Deployment | 실제 sensa.json(18패널) 임베드, datasource=http://prometheus:9090 |
| `10_ingress.yaml` | Ingress×2 | sensa.localhost→django, grafana.localhost→grafana |
| `11_hpa.yaml` | HPA | django CPU 70%, replicas 2~5 |

Compose→K8s 변환점:
- Prometheus: `network_mode:host`+`host.docker.internal` scrape → **`kubernetes_sd_configs(endpoints)`**. django 2 replica 모두 scrape, HPA 확장 Pod 자동 편입.
- Grafana: Dockerfile COPY 내장 → **ConfigMap 3개 mount**. datasource url만 `prometheus:9090`으로 변경.

---

## 적용 (옵션 공통)

```bash
cd ~/SenSa && \
unzip -o /mnt/c/Users/kapol/Downloads/k8s_stage_g.zip && \
kubectl apply -f manifests/08_prometheus.yaml && \
kubectl apply -f manifests/09_grafana.yaml
```

검증 (1~2분 대기):
```bash
kubectl -n sensa get pods -l 'app in (prometheus,grafana)'
# prometheus-xxx 1/1, grafana-xxx 1/1 기대

# Prometheus가 우리 서비스 타겟을 잡았는지 (django 2개 instance 포함)
kubectl -n sensa port-forward svc/prometheus 9090:9090 &
curl -s http://localhost:9090/api/v1/targets | python3 -c "import sys,json;[print(t['labels'].get('service'),t['labels'].get('pod'),t['health']) for t in json.load(sys.stdin)['data']['activeTargets']]"
kill %1

# Grafana 접근
kubectl -n sensa port-forward svc/grafana 3000:3000 &
# 브라우저 http://localhost:3000 → SenSa 폴더 → 18패널 대시보드
```

---

## 옵션 (가): Ingress·HPA 실제 작동 시연

### 사전 설치 (한 번만)
```bash
# 1) nginx-ingress
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.2/deploy/static/provider/cloud/deploy.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod \
  -l app.kubernetes.io/component=controller --timeout=120s

# 2) metrics-server (+ Docker Desktop용 TLS 패치)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
kubectl -n kube-system wait --for=condition=ready pod -l k8s-app=metrics-server --timeout=120s
kubectl top nodes   # 값 나오면 성공
```

### Ingress + HPA 적용
```bash
kubectl apply -f manifests/10_ingress.yaml
kubectl apply -f manifests/11_hpa.yaml
```

### /etc/hosts 추가
Windows: `C:\Windows\System32\drivers\etc\hosts` (관리자 권한)
```
127.0.0.1  sensa.localhost grafana.localhost
```

### 시연
```bash
# 외부 host 라우팅
curl -s http://sensa.localhost/metrics | head -3
# 브라우저: http://sensa.localhost (대시보드) / http://grafana.localhost (모니터링)

# HPA 자동 확장
kubectl -n sensa get hpa django -w     # 별도 터미널
ab -n 20000 -c 100 http://sensa.localhost/metrics   # 부하
# REPLICAS 2 → 3 → 4 ... 관찰, 부하 종료 후 2로 축소
```

---

## 옵션 (나): manifest만 (구조 설명 평가)

08/09는 적용(Prometheus·Grafana는 controller 불필요). 10/11도 apply 가능하나 controller 없으면:
- Ingress: `ADDRESS` 비어 있음(Pending) — 정의는 유효, 라우팅만 보류
- HPA: `TARGETS <unknown>` — metrics-server 없어 metric 미수집

발표 시 "manifest는 정의 완료, controller 설치만 추가하면 작동" 설명. 평가 기준(line 321 "Ingress/HPA 역할 설명") 충족.

---

## 트러블슈팅

| 증상 | 조치 |
|---|---|
| grafana 패널 'No data' | Prometheus 타겟 health 확인 (위 targets 명령). django/celery/generator UP인지 |
| prometheus 타겟 0개 | RBAC 적용됐는지 `kubectl get clusterrolebinding sensa-prometheus` |
| Ingress 404 | /etc/hosts 추가 + nginx-ingress controller Running 확인 |
| HPA `<unknown>` | metrics-server 미설치 또는 `--kubelet-insecure-tls` 패치 누락 |
| grafana ConfigMap 변경 반영 안 됨 | `kubectl -n sensa rollout restart deploy/grafana` |

## 롤백
```bash
kubectl delete -f manifests/11_hpa.yaml -f manifests/10_ingress.yaml \
  -f manifests/09_grafana.yaml -f manifests/08_prometheus.yaml
```

## 발표 어필 포인트 (G단계)

- **서비스 디스커버리**: Prometheus가 K8s API(endpoints role)로 django 2 replica를 자동 발견 — static target과 달리 HPA 확장 시 새 Pod도 자동 scrape
- **ConfigMap 분리 주입**: Grafana datasource/provider/dashboard를 코드 변경 없이 ConfigMap으로 주입
- **Ingress**: host 기반 L7 라우팅 (sensa.localhost / grafana.localhost), ingressClassName nginx
- **HPA**: CPU 70% target, autoscaling/v2 behavior로 확장 즉시(0s)·축소 보수적(120s)
