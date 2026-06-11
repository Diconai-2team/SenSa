# P-AZ 패치 — 가스 danger 전이 → 동적 위험구역 자동 발동

## 무엇이 바뀌나
- **신규**: `geofence/auto_trigger.py` — danger 전이 판별 + 2중 중복방지 + zone 발동
- **수정**: `devices/views.py` — post() 끝부분(경보 평가 후)에 훅 6줄 삽입

GeoFence 모델에 처음부터 정의돼 있던 `trigger_source='threshold'`의 배선 작업.
classify_gas(팀원 영역) 무수정. 수집 경로 장애격리 유지(예외 전부 흡수).
O2·전력은 확산 모델 비대상이라 제외(모듈 docstring에 사유 명시).

## 적용 (K8s)
```bash
cd ~/SenSa
cp devices/views.py devices/views.py.bak   # 백업
unzip -o /mnt/c/Users/kapol/Downloads/auto_zone_patch.zip
cd ~/SenSa && ./redeploy.sh
```
(zip 내 경로: geofence/auto_trigger.py, devices/views.py — 프로젝트 루트에서 풀면 제자리)

## 검증 절차 (검증 ③-2)
1. 깨끗한 상태에서 시작:
   curl -s -X POST 'localhost:8001/anomaly/clear-all'
   (기존 토글 OFF → phase 5 복귀 30초 대기. 잔여 동적 zone 있으면 만료 대기 또는 admin 비활성)
2. 대시보드(sensa.localhost/) 지도를 띄워둔 채:
   curl -s -X POST 'localhost:8001/anomaly/toggle?device_id=sensor_01&state=true'
3. 예상 타임라인:
   - ~60초(phase 2 진입 전까진 normal/caution)
   - **~75~90초: H2S가 danger 임계(50ppm) 돌파 → 전이 → 지도에 [자동] sensor_01 H2S 임계초과 확산 zone 즉시 생성(tentative)**
   - 이후 30초 tick마다 반경 확장, 인접 센서 confirming 시 tier 승격
4. 로그 확인:
   kubectl logs -n sensa deploy/django | grep auto-zone
   → "[auto-zone] danger 전이 → 동적 zone 발동: device=sensor_01 gas=h2s zone_id=N"
5. Grafana: 현장—활성 위험구역 수 0→1, 안전—분당 알람 상승
