#!/bin/bash
# fastapi_generator — 5차 세션 C′-3b-2 (b) 단계 적용
# R&D 시나리오 토글 5개 + Phase 자동 ramp + 라벨 동봉

set -e
TS=$(date +%Y%m%d_%H%M%S)
echo "═══════════════════════════════════════════════"
echo "  fastapi_generator 시나리오 토글 적용"
echo "  타임스탬프: $TS"
echo "═══════════════════════════════════════════════"

# 1. 백업
echo ""
echo "[1/3] 기존 파일 백업..."
cp main.py        main.py.bak.$TS
cp scheduler.py   scheduler.py.bak.$TS
cp poster.py      poster.py.bak.$TS
echo "  ✅ main.py.bak.$TS"
echo "  ✅ scheduler.py.bak.$TS"
echo "  ✅ poster.py.bak.$TS"

# 2. AST 검증
echo ""
echo "[2/3] AST 검증..."
python -c "
import ast
for f in ['scenario.py', 'main.py', 'scheduler.py', 'poster.py']:
    ast.parse(open(f).read())
    print(f'  ✅ {f}')
"

# 3. 안내
echo ""
echo "[3/3] 적용 완료. uvicorn 재기동:"
echo "      pkill -f 'uvicorn main:app'"
echo "      uvicorn main:app --host 127.0.0.1 --port 8001"
echo ""
echo "═══════════════════════════════════════════════"
echo "  ✅ 적용 완료!"
echo "═══════════════════════════════════════════════"
echo ""
echo "검증 (uvicorn 가동 후):"
echo "  # 상태 조회 (전 device OFF / phase 0)"
echo "  curl http://localhost:8001/anomaly/state"
echo ""
echo "  # sensor_01 H2S 누출 시나리오 ON"
echo "  curl -X POST 'http://localhost:8001/anomaly/toggle?device_id=sensor_01&state=true'"
echo ""
echo "  # 30초 후 phase 2 자동 진입 — Django 의 SensorData 보면 scenario_id=G3, expected_phase=2 채워짐"
echo "  python ../SenSa/manage.py shell -c \"from devices.models import SensorData; print(SensorData.objects.filter(device__device_id='sensor_01').values('h2s','scenario_id','expected_phase','expected_status').last())\""
echo ""
echo "  # 전부 OFF"
echo "  curl -X POST 'http://localhost:8001/anomaly/clear-all'"
