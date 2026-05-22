#!/usr/bin/env bash
# ============================================================
# verify.sh v2 — Observability stack 검증
# ============================================================
set -u
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${CYAN}ℹ${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
section() { echo ""; echo -e "${CYAN}━━━ $1 ━━━${NC}"; }

# ─────────────────────────────────────────────────────────
section "0. 사전 조건 — SenSa host 서비스 가동 확인"
DJANGO=$(curl -fsS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ 2>/dev/null)
FAPI=$(curl -fsS -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/ 2>/dev/null)
[ "${DJANGO:0:1}" = "2" ] || [ "${DJANGO:0:1}" = "3" ] \
    && pass "Django (:8000) HTTP $DJANGO" || fail "Django (:8000) HTTP $DJANGO — 가동 필요"
[ "${FAPI:0:1}" = "2" ] || [ "${FAPI:0:1}" = "3" ] \
    && pass "FastAPI (:8001) HTTP $FAPI" || fail "FastAPI (:8001) HTTP $FAPI — 가동 필요"

# 메트릭 노출 자체 확인
DM_HTTP=$(curl -fsS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/metrics 2>/dev/null)
FM_HTTP=$(curl -fsS -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/metrics 2>/dev/null)
[ "$DM_HTTP" = "200" ] && pass "Django /metrics HTTP 200"  || fail "Django /metrics HTTP $DM_HTTP"
[ "$FM_HTTP" = "200" ] && pass "FastAPI /metrics HTTP 200" || fail "FastAPI /metrics HTTP $FM_HTTP"

# ─────────────────────────────────────────────────────────
section "1. 컨테이너 상태"
docker compose ps --format "table {{.Service}}\t{{.State}}" 2>&1 | head -5
echo ""

PROM_STATE=$(docker inspect -f '{{.State.Status}}' sensa_prometheus 2>/dev/null || echo "missing")
GRAF_STATE=$(docker inspect -f '{{.State.Status}}' sensa_grafana 2>/dev/null || echo "missing")
[ "$PROM_STATE" = "running" ] && pass "sensa_prometheus running" || fail "sensa_prometheus: $PROM_STATE"
[ "$GRAF_STATE" = "running" ] && pass "sensa_grafana running"    || fail "sensa_grafana: $GRAF_STATE"

# ─────────────────────────────────────────────────────────
section "2. Prometheus scrape target 상태"
PROM_READY=$(curl -fsS -o /dev/null -w "%{http_code}" http://localhost:9090/-/ready 2>/dev/null)
[ "$PROM_READY" = "200" ] && pass "Prometheus /-/ready HTTP 200" || fail "Prometheus HTTP $PROM_READY"

TARGETS_JSON=$(curl -fsS http://localhost:9090/api/v1/targets 2>/dev/null)
if [ -n "$TARGETS_JSON" ]; then
    echo "$TARGETS_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
all_up = True
for t in data['data']['activeTargets']:
    job = t['labels'].get('job', '?')
    inst = t['labels'].get('instance', '?')
    health = t['health']
    last = (t.get('lastError', '') or 'ok')[:50]
    marker = '✓' if health == 'up' else '✗'
    if health != 'up': all_up = False
    print(f'    {marker} {job:20s} {inst:25s} {health:5s} {last}')
sys.exit(0 if all_up else 1)
"
fi

# ─────────────────────────────────────────────────────────
section "3. PromQL — SenSa 메트릭 7종"
query_check() {
    local name="$1"
    local q="$2"
    local result=$(curl -fsS --data-urlencode "query=$q" http://localhost:9090/api/v1/query 2>/dev/null)
    local count=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['data']['result']))" 2>/dev/null || echo 0)
    if [ "$count" -gt 0 ]; then
        pass "$name → $count 시계열"
    else
        warn "$name → 0 시계열"
    fi
}
query_check "sensa_ai_forecast_total"        "sensa_ai_forecast_total"
query_check "sensa_alarm_created_total"      "sensa_alarm_created_total"
query_check "sensa_alarm_throttled_total"    "sensa_alarm_throttled_total"
query_check "sensa_zone_active_static"       "sensa_zone_active_static"
query_check "sensa_zone_event_total"         "sensa_zone_event_total"
query_check "sensa_generator_publish_total"  "sensa_generator_publish_total"
query_check "publish_duration_seconds (Histogram)"  "sensa_generator_publish_duration_seconds_bucket"

# ─────────────────────────────────────────────────────────
section "4. Grafana"
GRAF_READY=$(curl -fsS -o /dev/null -w "%{http_code}" http://localhost:3000/api/health 2>/dev/null)
[ "$GRAF_READY" = "200" ] && pass "Grafana /api/health HTTP 200" || fail "Grafana HTTP $GRAF_READY"

DS_RESP=$(curl -fsS http://localhost:3000/api/datasources/name/Prometheus 2>/dev/null)
echo "$DS_RESP" | grep -q '"name":"Prometheus"' \
    && pass "Prometheus datasource 자동 등록" || warn "datasource 미등록"

DASH_RESP=$(curl -fsS http://localhost:3000/api/dashboards/uid/sensa-main 2>/dev/null)
if echo "$DASH_RESP" | grep -q '"title":"SenSa'; then
    PANEL_COUNT=$(echo "$DASH_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['dashboard']['panels']))" 2>/dev/null || echo 0)
    pass "SenSa 대시보드 등록 (패널 $PANEL_COUNT)"
else
    warn "대시보드 미등록"
fi

# ─────────────────────────────────────────────────────────
section "✅ 브라우저 접속"
echo ""
echo -e "  ${CYAN}http://localhost:3000/d/sensa-main${NC}     ← 대시보드 직행"
echo -e "  ${CYAN}http://localhost:9090/targets${NC}            ← scrape UP/DOWN"
echo ""
