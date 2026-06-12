# 매니페스트 동기화 v2 — 라이브 클러스터와 1:1 (media PVC + 실행방식 + probe)

## 이번 v2에서 맞춘 것
- command: runserver --noreload (= INSTALLED_APPS 'daphne' 최상단 → ASGI/Daphne 모드) + 사유 주석
- probe: tcpSocket, timeoutSeconds liveness 5 / readiness 3 (라이브 값)
- volumes: media-pvc 마운트 (/app/media)
- image ':latest' 는 부트스트랩 전용임을 주석으로 명시 (운영 반영은 redeploy.sh의 고유 태그)

## 절차
```bash
cd ~/SenSa
unzip -o "/mnt/c/Users/kapol/Downloads/media_pvc_sync_v2.zip" -d ~/SenSa
kubectl diff -f manifests/05_django.yaml
```
기대 결과: 남는 차이는 image(:latest ↔ v태그)와 replicas(2 ↔ HPA 현재값) 뿐.
이 둘은 "부트스트랩 값 vs 런타임 관리 값"이라 정상적인 차이다.

## ⚠ apply 하지 말 것 (05_django.yaml)
클러스터는 이미 올바른 상태다. 이 파일을 apply하면 이미지가 :latest로 롤백된다.
파일은 '진실의 기록'으로 보관 — 클러스터 재구축 시에만 apply 후 ./redeploy.sh 실행.

## PVC 파일만 선택 적용 (무해)
```bash
kubectl diff -f manifests/05b_media_pvc.yaml    # 빈 출력 기대
kubectl apply -f manifests/05b_media_pvc.yaml   # 기존 media-pvc 그대로, 변화 없음
```
