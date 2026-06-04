#!/bin/bash
# kind 노드로 로컬 docker 이미지 import
# Docker Desktop의 kind cluster는 host docker daemon과 이미지 격리됨.
# K8s가 'sensa-app:latest' 'sensa-generator:latest'를 pull하려면 kind 노드 안에 미리 import 필요.

set -e

echo "[1] kind 노드 이름 검색..."
KIND_NODE=$(docker ps --format "{{.Names}}" | grep -iE "control-plane|kind" | head -1)
if [ -z "$KIND_NODE" ]; then
    echo "[실패] kind 노드를 찾을 수 없습니다."
    docker ps
    exit 1
fi
echo "    → $KIND_NODE"

echo "[2] sensa-app:latest + sensa-generator:latest 두 이미지 tar로 저장..."
docker save sensa-app:latest sensa-generator:latest -o /tmp/sensa-images.tar
ls -la /tmp/sensa-images.tar

echo "[3] kind 노드로 복사..."
docker cp /tmp/sensa-images.tar $KIND_NODE:/tmp/sensa-images.tar

echo "[4] kind 노드 안에서 containerd로 import..."
docker exec $KIND_NODE ctr -n=k8s.io images import /tmp/sensa-images.tar

echo "[5] kind 노드 정리..."
docker exec $KIND_NODE rm -f /tmp/sensa-images.tar
rm -f /tmp/sensa-images.tar

echo "[6] 확인 — kind 노드 안 sensa 이미지 목록:"
docker exec $KIND_NODE crictl images | grep -iE "sensa" || \
    docker exec $KIND_NODE ctr -n=k8s.io images ls | grep -iE "sensa"

echo
echo "[성공] 이미지 import 완료. 이제 kubectl apply -f manifests/ 실행 가능."
