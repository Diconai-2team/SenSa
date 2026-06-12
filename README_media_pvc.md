# P-PVC 패치 — Django 업로드 공유 볼륨

## 구성
- 신규: manifests/05b_media_pvc.yaml (PVC 1Gi, RWO)
- 수정: manifests/05_django.yaml (django 컨테이너에 /app/media 마운트, 끝부분 12줄 추가)

## 적용
```bash
cd ~/SenSa
unzip -o /mnt/c/Users/kapol/Downloads/media_pvc_patch.zip   # manifests/ 두 파일 제자리
kubectl apply -f manifests/05b_media_pvc.yaml
kubectl apply -f manifests/05_django.yaml
kubectl rollout status -n sensa deploy/django
```

## 검증 (자소서 증빙용 — 스크린샷 2장)
1) 적용 전 문제 재현은 생략 가능(볼륨 부재가 코드로 증명됨).
2) 백오피스/관제에서 평면도 이미지 1장 업로드.
3) 모든 Pod에서 같은 파일이 보이는지:
```bash
for p in $(kubectl get pods -n sensa -l app=django -o name); do
  echo "== $p =="; kubectl exec -n sensa ${p#pod/} -c django -- ls -la /app/media/maps/
done
```
→ 전 Pod 동일 목록 = 공유 볼륨 증빙.
4) Pod 삭제 후 재기동해도 파일 유지(영속성):
```bash
kubectl delete pod -n sensa -l app=django --wait=false && sleep 40
kubectl exec -n sensa deploy/django -c django -- ls /app/media/maps/
```

## 면접 한 줄 답변
"RWO는 노드 단위 제약이라 단일 노드(kind)에선 다중 Pod 공유가 가능합니다.
다중 노드 확장 시 RWX(NFS)나 S3로 전환해야 한다는 한계까지 인지하고 있습니다."
