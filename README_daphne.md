# P-DAPHNE — daphne ASGI 단독 구동 전환 (기술문서 원문에 코드를 맞추는 패치)

## 변경 (2파일)
- SenSa/Dockerfile: collectstatic 빌드 단계 추가 + CMD daphne
- manifests/05_django.yaml: command daphne (PVC 동기화본 v2 기반)

과거 daphne 화면 깨짐 원인 = STATIC_ROOT 비어 있음(collectstatic 부재). 이번에 근본 해소.
media(평면도)는 DEBUG=True에서 urls.py 헬퍼가 서빙 — 기존과 동일, 영향 없음.

## 적용 (이번엔 이미지 재빌드 필요 → redeploy.sh)
```bash
cd ~/SenSa
cp SenSa/Dockerfile SenSa/Dockerfile.bak
unzip -o "/mnt/c/Users/kapol/Downloads/daphne_patch.zip" -d ~/SenSa

kubectl apply -f manifests/05_django.yaml   # command 교체 (이미지가 :latest로 잠깐 돌아가도
./redeploy.sh                               # 곧바로 redeploy가 새 태그로 덮음 — 연속 실행할 것)
```
※ 두 명령은 붙여서 실행. apply 후 redeploy 전 공백이 길면 옛 :latest 이미지로 뜰 수 있음.

## 검증 4가지 (각 스크린샷이 기술문서 3장의 증빙)
1. 기동 명령 확인:
   kubectl get deploy django -n sensa -o jsonpath='{.spec.template.spec.containers[0].command}'
   → ["daphne","-b","0.0.0.0","-p","8000","mysite.asgi:application"]
2. 브라우저 Ctrl+Shift+R → sensa.localhost/ CSS·지도·평면도 이미지 전부 정상
3. 실시간 동작(WS) 정상 — 센서 값 갱신 확인
4. 로그 첫 줄에 daphne 기동 메시지:
   kubectl logs -n sensa deploy/django -c django --tail=5

## 롤백 (문제 시 한 줄, 재빌드 불필요)
```bash
kubectl -n sensa patch deploy django --type json -p \
'[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["python","manage.py","runserver","0.0.0.0:8000","--noreload"]}]'
```
