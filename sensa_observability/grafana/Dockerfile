# ============================================================
# Grafana image — provisioning + dashboards 를 빌드 시점에 내장
# bind mount 회피
#
# [9차] dashboard 경로를 /var/lib/grafana → /etc/grafana 로 이동.
#   이유: grafana_data named volume 이 /var/lib/grafana 를 덮어
#   COPY 한 dashboard 가 볼륨 안 옛 파일에 가려지는 결함 해결.
#   /etc/grafana 는 볼륨이 안 덮으므로 COPY 가 항상 반영됨.
# ============================================================
FROM grafana/grafana:11.2.2

COPY provisioning/ /etc/grafana/provisioning/
COPY dashboards/   /etc/grafana/dashboards/
