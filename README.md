# patch_v3_fixes — 알람 중복/미실시간/확산 부족 동시 해결

사용자가 시연 후 발견한 4개 문제를 단일 패치로 해결.

## 해결 문제

| # | 증상 | 코드 원인 | 해결 |
|---|---|---|---|
| 1 | 위험 알람 7~10초 주기 중복 발화 | sensor_evaluator.py:85 — transition은 RE_ALARM_INTERVAL_SEC throttle 적용 안 됨 + V자 진동 격하·격상 반복 | observed==official 시 격하 카운터 리셋 → V자 진동 자체를 차단해 transition 반복 발화 막음 |
| 2 | 새로고침해야 위험 알람 보임 | sensor_evaluator.py에 publish_alarm 호출 0건 — DB 저장만 | Alarm 생성 직후 publish_alarm() 호출 추가 |
| 3 | 좌측 토스트에 위험 알람 없음 | (문제 2의 직접 결과) | 문제 2 해결로 자동 해결 |
| 4 | sensor_05/06 spike 변동성 없음 | operational_multi.py LEAK_ELAPSED_SEC=15 → 시작 반경 30px이라 인접 sensor 검출 안 됨 | LEAK_ELAPSED_SEC 15→45 (반경 30→91px) |

## V자 진동 차단 알고리즘 (문제 1 핵심)

**문제**: Celery sustain_spike(0.5초/danger) + fastapi_generator(1초/normal)가 같은 sensor에 동시 송신. 윈도우 누적 카운터가 격상→격하→격상 반복 confirm.

**v3 해결**:
```python
# observed가 official과 같음 → 격하 카운터 리셋 (격상 카운터는 보호)
if observed_status == official_state:
    official_rank = _STATE_RANK.get(official_state, 0)
    for st in ('normal', 'caution', 'danger'):
        if _STATE_RANK[st] < official_rank:
            set_sensor_window_counter(device_id, st, 0, 0)
```

V자 진동 시뮬레이션 (official=danger, Celery danger + generator normal 교차):
```
T+0.5  Celery danger    → observed==official → normal/caution 카운터 리셋
T+1.0  generator normal → de-escalation → normal_count = 1
T+1.5  Celery danger    → 리셋 → normal_count = 0
T+2.0  generator normal → normal_count = 1
T+2.5  Celery danger    → 리셋 → normal_count = 0
...
```
→ normal_count는 0~1 진동, 7에 절대 도달 못함 → 격하 안 됨 → ongoing 알람만 60초마다 1번.

정상 ramp_down (자연 곡선 후반, 둘 다 normal 보냄):
```
T+0  generator normal → normal_count = 1
T+0.5 Celery normal   → normal_count = 2
...
T+3  → normal_count = 7 → confirm normal (recovery 알람)
```
→ 정상 작동.

## publish_alarm 호출 추가 (문제 2, 3 핵심)

기존 흐름:
```
sustain_spike_task → evaluate_sensor() → Alarm.objects.create()  ← DB 저장만
                                          ↓
                                          (publish_alarm 미호출 → frontend 무지)
```

v3 흐름:
```
sustain_spike_task → evaluate_sensor() → Alarm.objects.create()
                                          ↓
                                          publish_alarm()  ← 신규
                                          ↓
                                          WebSocket → frontend
                                          ↓
                                          - 우측 패널 알람 즉시 표시 (UX 패치 sticky 작동)
                                          - 좌측 토스트 즉시 표시 (section_09_map.js)
```

## 시작 반경 확대 (문제 4 핵심)

`diffusion_radius('co', elapsed_sec) = 2.0 × √(28.97/28.01) × elapsed_sec ≈ 2.03 × elapsed_sec`

| LEAK_ELAPSED_SEC | 시작 반경 | 인접 sensor 검출 |
|---|---|---|
| 15 (이전) | 30 px | sensor_04만 |
| 45 (v3) | 91 px | sensor_04 + 인근 2~3개 (05/06 등) |

평면도 좌표계 단위와 sensor 배치에 따라 실제 검출 개수는 다를 수 있음. 검증은 시연 후 DB 측정으로.

## 적용 명령 (한 블록)

```bash
cd ~/SenSa && \
unzip -o /mnt/c/Users/kapol/Downloads/patch_v3_fixes.zip && \
cp SenSa/alerts/services/sensor_evaluator.py /tmp/before_evaluator.py && \
cp SenSa/geofence/scenarios/operational_multi.py /tmp/before_multi.py && \
python3 patch_v3_fixes.py && \
echo "===== evaluator 변경 (요약) =====" && diff /tmp/before_evaluator.py SenSa/alerts/services/sensor_evaluator.py | head -50 && \
echo "===== multi 변경 =====" && diff /tmp/before_multi.py SenSa/geofence/scenarios/operational_multi.py && \
docker compose up -d --build django celery
```

## 시연 검증 (다중 누출 클릭 후 3분 관찰)

### 4가지 기대 변화

1. **위험 알람 중복 사라짐** — celery 시연 동안 sensor_04 위험 알람이 transition 1회 + ongoing 60초마다 1회 (총 시연 2분 30초 안에 위험 알람 2~3건만)
2. **새로고침 없이 즉시 표시** — 위험 알람이 발생하는 순간 우측 패널 + 좌측 토스트 모두 즉시 갱신
3. **좌측 토스트에 위험 등장** — 빨간 위험 토스트가 좌측 알림 영역에 표시 (AI 예측 토스트와 동일 영역)
4. **sensor_05/06 변동성 등장** — sensor_04뿐 아니라 인접 sensor도 spike 시계열

### DB 검증 SQL

```bash
# 알람 중복 차단 확인 — 위험 알람이 60초당 1건 이하인지
docker compose exec -T postgres psql -U sensa -d sensa -c "
SELECT to_char(created_at, 'HH24:MI:SS') AS t,
       alarm_type, alarm_level, message
FROM alerts_alarm
WHERE device_id='sensor_04' AND is_ai=false
  AND created_at > NOW() - INTERVAL '5 minutes'
ORDER BY created_at;"
# 기대: transition 1~2건 + ongoing 60초 간격 2~3건 = 총 3~5건 (이전 10건↑에서 감소)

# 확산 sensor 검출 확인
docker compose exec -T postgres psql -U sensa -d sensa -c "
SELECT device_id, status, COUNT(*),
       ROUND(MIN(co)::numeric, 1) AS co_min,
       ROUND(MAX(co)::numeric, 1) AS co_max
FROM devices_sensordata
WHERE device_id IN (SELECT id FROM devices_device WHERE device_id IN ('sensor_04','sensor_05','sensor_06'))
  AND scenario_id LIKE 'op_multi%'
  AND timestamp > NOW() - INTERVAL '5 minutes'
GROUP BY 1,2 ORDER BY 1,2;"
# 기대: sensor_04 외에 sensor_05/06에도 op_multi 라벨 데이터 등장
```

## 롤백

```bash
cd ~/SenSa/SenSa
cp alerts/services/sensor_evaluator.py.bak.YYYYMMDD_HHMMSS alerts/services/sensor_evaluator.py
cp geofence/scenarios/operational_multi.py.bak.YYYYMMDD_HHMMSS geofence/scenarios/operational_multi.py
cd ~/SenSa && docker compose up -d --build django celery
```
