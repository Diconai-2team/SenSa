# ============================================================
# Grafana image — provisioning + dashboards 를 빌드 시점에 내장
# bind mount 회피
# ============================================================
FROM grafana/grafana:11.2.2

COPY provisioning/ /etc/grafana/provisioning/
COPY dashboards/   /var/lib/grafana/dashboards/
