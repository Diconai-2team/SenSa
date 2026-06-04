# 컨트롤 패널 통합 패치 (레이어 + 가스 탭 전환)

기존 분리돼 있던 두 패널을 우상단 단일 패널로 통합:
- 레이어 토글(지오펜스/센서/작업자) + 가스 9종 → 탭으로 전환
- 기능 추가 시 탭만 늘고 패널 폭/개수 고정 → 지도 화면 안 좁아짐
- 헤더 ▾ 로 접기 가능

## 안전성
- 레이어 토글은 id(layer-geofence/sensor/worker) 그대로 보존 → 기존 JS(section_09_map.js) 그대로 작동
- 백엔드 무변경 (프론트 2파일만)
- 멱등(marker 'control-overlay') + 백업(.bak)

## 변경 파일
- templates/dashboard/sections/section_09_map.html
- static/css/dashboard/scenario_panel.css

## 적용 (K8s)
```bash
cd ~/SenSa && \
unzip -o /mnt/c/Users/kapol/Downloads/control_panel_patch.zip && \
python3 patch_control_panel.py
./redeploy.sh        # 아래 스크립트 (없으면 zip에서 풀림)
```

## redeploy.sh (이미지 재빌드 → push → 롤아웃, 한 줄)
```bash
chmod +x redeploy.sh && ./redeploy.sh
```

## 롤백
```bash
cp templates/dashboard/sections/section_09_map.html.bak.* templates/dashboard/sections/section_09_map.html
cp static/css/dashboard/scenario_panel.css.bak.* static/css/dashboard/scenario_panel.css
./redeploy.sh
```
