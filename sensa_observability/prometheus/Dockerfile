# ============================================================
# Prometheus image — config 를 빌드 시점에 내장
# bind mount 회피 (WSL2 + Docker Desktop inode 추적 결함 영구 회피)
# ============================================================
FROM prom/prometheus:v2.54.1

COPY prometheus.yml /etc/prometheus/prometheus.yml
