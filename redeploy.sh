#!/usr/bin/env bash
# SenSa K8s 재배포 — 프론트/백 수정 후 한 줄 반영
# 고유 태그 + provenance off 로 :latest 캐시/attestation 함정 회피
set -e
cd "$(dirname "$0")"
TAG="v$(date +%H%M%S)"
echo "▶ build $TAG"
docker build --provenance=false --sbom=false -t sensa-app:$TAG ./SenSa
docker tag sensa-app:$TAG localhost:5000/sensa-app:$TAG
docker push localhost:5000/sensa-app:$TAG
echo "▶ rollout"
kubectl -n sensa set image deployment/django django=localhost:5000/sensa-app:$TAG
kubectl -n sensa rollout status deploy/django --timeout=180s
echo "✅ 반영 완료: $TAG  (http://sensa.localhost — Ctrl+Shift+R)"
