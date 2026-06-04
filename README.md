# 가스 9종 On/Off 토글 패널 패치

R&D 시나리오 패널 옆(우상단)에 가스 9종 표시 토글 패널 추가.
토글 Off → ⑫ 유해가스 위험 현황 테이블에서 해당 가스 행 숨김 (프론트엔드 전용).

## 변경 파일 (2개, 백엔드 무변경)
- `templates/dashboard/sections/section_09_map.html` — #gas-toggle-overlay + 인라인 JS
- `static/css/dashboard/scenario_panel.css` — 패널 스타일 append

## 적용 (로컬/Compose)
```bash
cd ~/SenSa && \
unzip -o /mnt/c/Users/kapol/Downloads/gas_toggle_patch.zip && \
python3 patch_gas_toggle.py
# runserver는 템플릿 자동 반영 → 브라우저 새로고침
```

## 적용 (K8s — 정적/템플릿이 이미지에 baked-in)
```bash
# 1) 패치 적용 (소스)
cd ~/SenSa && unzip -o /mnt/c/Users/kapol/Downloads/gas_toggle_patch.zip && python3 patch_gas_toggle.py
# 2) 이미지 재빌드 + registry push
docker build -t sensa-app:latest ./SenSa
docker tag sensa-app:latest localhost:5000/sensa-app:latest
docker push localhost:5000/sensa-app:latest
# 3) 롤아웃 (무중단)
kubectl -n sensa rollout restart deploy/django
kubectl -n sensa rollout status deploy/django
```

## 멱등/백업
- 마커 `gas-toggle-overlay` 검사 → 재실행 시 스킵
- 변경 전 `.bak.YYYYMMDD_HHMMSS` 생성

## 롤백
```bash
# 가장 최근 .bak 복원
cp templates/dashboard/sections/section_09_map.html.bak.* templates/dashboard/sections/section_09_map.html
cp static/css/dashboard/scenario_panel.css.bak.* static/css/dashboard/scenario_panel.css
```
