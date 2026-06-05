#!/usr/bin/env bash
# SenSa K8s 재배포 — 프론트/백 수정 후 한 줄 반영
# 고유 태그 + provenance off 로 :latest 캐시/attestation 함정 회피
#
# [변경] django 뿐 아니라 celery 도 같은 TAG 로 함께 롤아웃.
#   - celery 가 beat 스케줄(cleanup-old-data 등)·태스크 코드를 들고 있어
#     django 만 갱신하면 celery 가 옛 코드로 뒤처짐(스케줄 누락).
#   - django/celery 는 동일 이미지(sensa-app)라 같은 TAG 사용.
#   - generator 는 별도 이미지(sensa-generator)라 건드리지 않음.
set -e
cd "$(dirname "$0")"
TAG="v$(date +%H%M%S)"

echo "▶ build $TAG"
docker build --provenance=false --sbom=false -t sensa-app:$TAG ./SenSa
docker tag  sensa-app:$TAG localhost:5000/sensa-app:$TAG
docker push localhost:5000/sensa-app:$TAG

echo "▶ rollout (django + celery)"
kubectl -n sensa set image deployment/django  django=localhost:5000/sensa-app:$TAG
kubectl -n sensa set image deployment/celery   celery=localhost:5000/sensa-app:$TAG
kubectl -n sensa rollout status deploy/django  --timeout=180s
kubectl -n sensa rollout status deploy/celery  --timeout=180s

echo "✅ 반영 완료: $TAG  (http://sensa.localhost — Ctrl+Shift+R)"
