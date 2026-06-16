언제 경고 상태로 들어갔고, 언제 정상으로 돌아왔는지를 기록한 이벤트 로그 + 매 시점 실시간 판단 결과 테이블을 만들어냅니다.

STEP 1과 결과는 이상인지 아닌지 True/False 판정했다면
STEP 2는 지금 상태가 NORMAL인지 ALERT인지 유지상태가 바뀌는 순간 기록 즉, 단순 이상 탐지가 아니라 상태 관리 시스템이 됩니다. 

이 코드는 이런 것을 만들어냅니다
1️⃣ 알람 시작 시점
2️⃣ 알람 종료 시점
3️⃣ 현재 시스템 상태
4️⃣ 실시간 위험 구간 길이 계산 가능

관제 시스템에서 중요한 건:
- 값이 이상했는가? ❌
- 시스템이 위험 상태에 들어갔는가? ✅
- 위험이 몇 초 지속됐는가? ✅
- 언제 복구됐는가? ✅ 입니다.

이 코드는 그걸 계산합니다.

---
### Sliding Window란? 
	전체 데이터를 다 보지 않고, 최근에 들어온 일부 데이터만 가지고 계속 판단하는 방식입니다.

예를 들어 설명해보겠습니다.
- 센서 데이터가 1초마다 계속 들어옵니다.
- 데이터는 끝없이 쌓입니다.
- 그런데 매번 전체 데이터를 다시 계산하면 너무 느립니다.
    
그래서 이렇게 합니다:
✔ 최근 30개만 보고  
✔ 그 안에서 평균과 변동을 계산하고  
✔ 지금 값이 정상인지 위험인지 판단합니다.
이것이 Sliding Window입니다.

### 코드는 어떤 상황에서 사용하나?
	데이터가 계속 들어오는 상황에서 사용합니다.

예를 들면:
- 센서 데이터 모니터링
- 서버 CPU/메모리 감시
- 공장 설비 상태 감시
- 금융 거래 이상 탐지
- 관제 시스템
즉, 지금 이 순간이 정상인가?를 계속 판단해야 하는 시스템에서 사용합니다.

### STEP 1과 STEP 2의 차이
| STEP 1        | STEP 2          |
| ------------- | --------------- |
| 이미 쌓인 데이터를 분석 | 데이터가 들어올 때마다 판단 |
| 한 번에 계산       | 실시간 계산          |
| 과거 분석         | 현재 상태 판단        |
쉽게 말하면:
STEP 1은 시험이 끝난 뒤 채점하는 방식
STEP 2는 시험 보는 순간마다 점수 계산하는 방식


### 이 코드를 통해 무엇을 얻는가?
이 코드는 단순히 평균을 계산하는 코드가 아닙니다.

이 코드는 이런 시스템을 만드는 구조입니다:
✔ 지금 정상인가?  
✔ 지금 위험인가?  
✔ 언제 위험이 시작되었는가?  
✔ 언제 정상으로 돌아왔는가?
즉, 상태를 판단하고, 상태 변화를 기록하는 구조를 만드는 연습입니다.

---
### Sliding Window 뼈대패턴코드
```python
# ============================================
# [STEP 2 Skeleton] Sliding Window 처리 구조 (실시간 사고 전환)
# - 최근 N개만 사용
# - 들어오는 데이터마다 즉시 판단(온라인 판단)
# - 상태 변화 감지(정상 ↔ 위험)
# ============================================

import numpy as np
import pandas as pd

# -------------------------------------------------
# 0) 데이터 준비
#    - stream처럼 "한 줄씩 들어온다"는 가정
# -------------------------------------------------
# df: columns = ["timestamp", "value"]
df = df.sort_values("timestamp").reset_index(drop=True)

# -------------------------------------------------
# 1) Sliding Window 설정
# -------------------------------------------------
WINDOW = 30                 # 최근 30개만 유지
Z_THRESHOLD = 3.0           # 이상 판단 기준
EPS = 1e-9                  # 0 나누기 방지

# -------------------------------------------------
# 2) 상태 머신(상태 변화 감지) 준비
# -------------------------------------------------
# 상태 예시: "NORMAL" / "ALERT"
state = "NORMAL"
events = []  # 상태 변화 이벤트 로그 저장

# -------------------------------------------------
# 3) 스트리밍 처리 (한 건씩 읽으면서 최근 N개로만 판단)
# -------------------------------------------------
window_values = []

for t, x in zip(df["timestamp"], df["value"]):
    # 3-1) 최근 N개 유지
    window_values.append(x)
    if len(window_values) > WINDOW:
        window_values.pop(0)

    # 3-2) WINDOW개가 쌓이기 전에는 판단하지 않음
    if len(window_values) < WINDOW:
        continue

    # 3-3) 최근 N개로 통계 계산
    mean = np.mean(window_values)
    std  = np.std(window_values, ddof=0)

    z = (x - mean) / (std + EPS)
    is_anomaly = abs(z) >= Z_THRESHOLD

    # 3-4) 상태 변화 감지(정상→위험, 위험→정상)
    if state == "NORMAL" and is_anomaly:
        state = "ALERT"
        events.append({"timestamp": t, "event": "ENTER_ALERT", "value": x, "z": z})

    elif state == "ALERT" and (not is_anomaly):
        state = "NORMAL"
        events.append({"timestamp": t, "event": "EXIT_ALERT", "value": x, "z": z})

# -------------------------------------------------
# 4) 결과 확인
# -------------------------------------------------
events_df = pd.DataFrame(events)
print(events_df.head(20))
```
---
`0) 데이터 준비`
```python
df = df.sort_values("timestamp").reset_index(drop=True)
```
데이터가 이미 있다고 가장하고 
시간 순서대로 데이터를 다시 정렬하고 인덱스를 처음부터 깔끔하게 재번호 매기는 작업


`1) Sliding Window 설정`
```python
WINDOW = 30                 # 최근 30개만 유지
Z_THRESHOLD = 3.0           # 이상 판단 기준
EPS = 1e-9                  # 0 나누기 방지
```
실시간 계산에 사용할 기준값들을 미리 정하는 단계로 이상탐지 민감도 + 계산 안정성 설정
✔ WINDOW = 30  
→ 계산할 때 최근 30개 데이터만 사용

✔ Z_THRESHOLD = 3.0  
→ 평균에서 얼마나 벗어나면 이상으로 볼지 기준

✔ EPS = 1e-9  
→ 표준편차가 0일 때 계산 오류 방지용 작은 값

---
`2) 상태 머신(상태 변화 감지) 준비`
```python
state = "NORMAL"
events = []  # 상태 변화 이벤트 로그 저장
```
현재 시스템 상태를 기록하고, 상태가 바뀌는 순간을 저장하기 위한 준비 단계로 지금 상태 기억 + 변화 이력 저장 준비
✔ state = "NORMAL"  
→ 처음에는 정상 상태라고 가정

✔ `events = []  `
→ 상태 변화가 발생하면 기록할 저장 공간

---
`3) 스트리밍 처리 (한 건씩 읽으면서 최근 N개로만 판단)`
```python
window_values = []

for t, x in zip(df["timestamp"], df["value"]):
```
최근 데이터들을 담아둘 공간을 만들고, 데이터를 한 줄씩 순서대로 처리하는 반복 구조
✔ `window_values = []`
→ 최근 값들을 저장하는 임시 창문(Window)

✔ `for t, x in zip(...)`
→ 시간과 값을 한 쌍으로 하나씩 꺼내 처리
데이터가 실시간으로 들어온다고 가정하고 한 건씩 읽는 구조입니다.

---
`3-1) 최근 N개 유지`
```python
    window_values.append(x)
    if len(window_values) > WINDOW:
        window_values.pop(0)
```
	최근 WINDOW개 데이터만 남기는 작업
	
새로운 데이터가 들어올 때마다 값을 저장하고,  
저장된 데이터 개수가 WINDOW 크기를 초과하면  
가장 오래된 데이터를 제거하여 항상 최근 데이터만 유지하는 단계입니다.

---
`3-2) WINDOW개가 쌓이기 전에는 판단하지 않음`
```python
    if len(window_values) < WINDOW:
        continue
```
	데이터가 충분히 쌓일 때까지 판단 보류
	
통계 계산의 기준이 되는 데이터가 충분히 모이기 전까지는  
평균이나 표준편차가 불안정해질 수 있으므로  
WINDOW 개수가 채워질 때까지 이상 여부 판단을 잠시 미루는 단계입니다.

---
`3-3) 최근 N개로 통계 계산`
```python
    mean = np.mean(window_values)
    std  = np.std(window_values, ddof=0)
    
    z = (x - mean) / (std + EPS)
    is_anomaly = abs(z) >= Z_THRESHOLD
```
	최근 구간 기준으로 현재 값이 튀었는지 계산
	
최근 WINDOW 구간에 포함된 데이터들만 사용하여  
현재 시점의 평균과 변동성을 계산하고,  
새로 들어온 값이 평균에서 얼마나 벗어났는지를 Z-score로 수치화하여  
이상치 여부를 판단하는 단계입니다.

---
`3-4) 상태 변화 감지(정상→위험, 위험→정상)`
```python
    if state == "NORMAL" and is_anomaly:
        state = "ALERT"
        events.append({"timestamp": t, "event": "ENTER_ALERT", "value": x, "z": z})
        
    elif state == "ALERT" and (not is_anomaly):
        state = "NORMAL"
        events.append({"timestamp": t, "event": "EXIT_ALERT", "value": x, "z": z})    
```
	정상 ↔ 위험 상태 전환 관리
	
현재 시스템 상태를 확인하여  
정상 상태에서 이상이 발생하면 ALERT 상태로 전환하고,  
이미 ALERT 상태인 경우 값이 다시 정상 범위로 돌아오면  
NORMAL 상태로 복귀시키는 상태 관리 단계입니다.

---
`4) 결과 확인`
```python
events_df = pd.DataFrame(events)
print(events_df.head(20))
```
처리 과정에서 발생한 상태 변화 이벤트들을  
테이블 형태로 변환하여 확인하고,  
언제 어떤 변화가 발생했는지를 출력하는 단계입니다.

---
### 실무를 위한 연습 전체코드
```python
# ============================================
# [STEP 2 전체코드] Sliding Window 처리 구조 (실시간 판단 + 상태 변화 감지)
# - STEP 1의 rolling()은 "배치 계산" 느낌이 강함
# - STEP 2는 "데이터가 한 건씩 들어올 때마다" 최근 N개로 즉시 판단하는 구조
# - 관제 플랫폼에서 가장 흔한 실시간 처리 패턴
# ============================================

import numpy as np
import pandas as pd
import plotly.express as px

# -------------------------------------------------
# 0) 데이터 준비 (실습용 센서 데이터 생성)
#    - df: columns = ["timestamp", "value"]
#    - 실제 환경에선 이 부분이 Kafka/MQTT/Websocket으로 들어오는 데이터라고 보면 됨
# -------------------------------------------------
np.random.seed(42)

n = 600
timestamps = pd.date_range("2026-02-11 10:00:00", periods=n, freq="s")

values = 100 + np.random.normal(0, 1.2, size=n)
spike_idx = [120, 121, 260, 400, 520]
values[spike_idx] += [12, -14, 18, -20, 15]

df = pd.DataFrame({"timestamp": timestamps, "value": values})
df = df.sort_values("timestamp").reset_index(drop=True)

# (선택) 원본 데이터 시각화
px.line(df, x="timestamp", y="value", title="Original Sensor Stream").show()


# -------------------------------------------------
# 1) Sliding Window 설정
#    - WINDOW: 최근 N개만 가지고 판단 (실시간 관제의 핵심)
# -------------------------------------------------
WINDOW = 30
Z_THRESHOLD = 3.0
EPS = 1e-9


# -------------------------------------------------
# 2) 상태 머신(상태 변화 감지) 준비
#    - 관제는 "지금 상태가 정상인지/위험인지"를 계속 유지해야 함
#    - 그래서 단순히 is_anomaly True/False가 아니라
#      NORMAL → ALERT, ALERT → NORMAL 같은 전이를 기록하는 게 중요함
# -------------------------------------------------
state = "NORMAL"  # 초기 상태
events = []       # 상태 변화 이벤트 로그
stream_rows = []  # 매 시점 계산 결과 저장(나중에 그래프/분석용)


# -------------------------------------------------
# 3) 스트리밍 처리 (한 건씩 읽으면서 최근 N개로만 판단)
#    - for loop 1회전 = "센서 데이터 1개가 도착한 순간"이라고 생각
# -------------------------------------------------
window_values = []

# 1️⃣ 데이터 1개 들어옴
# timestamp, value 한 줄을 가져온다
for t, x in zip(df["timestamp"], df["value"]):

    # 2️⃣ 최근 N개 데이터 유지
    # Sliding Window에 현재 값 추가
    window_values.append(float(x))

    # WINDOW보다 많으면 가장 오래된 값 제거
    if len(window_values) > WINDOW:
        window_values.pop(0)

    # WINDOW개가 쌓이기 전에는 통계 계산을 하지 않음
    if len(window_values) < WINDOW:
        stream_rows.append({
            "timestamp": t,
            "value": x,
            "mean": np.nan,
            "std": np.nan,
            "z": np.nan,
            "is_anomaly": False,
            "state": state
        })
        continue

    # 3️⃣ 평균 계산
    # 최근 N개 데이터의 평균(mean) 계산
    mean = float(np.mean(window_values))

    # 4️⃣ 표준편차 계산
    # 최근 N개 데이터의 변동성(std) 계산
    std = float(np.std(window_values, ddof=0))

    # 5️⃣ z-score 계산
    # 현재 값이 평균에서 얼마나 떨어져 있는지 계산
    # z = (현재값 - 평균) / 표준편차
    z = float((x - mean) / (std + EPS))

    # 6️⃣ 이상 여부 판단
    # |z| ≥ 임계값(Z_THRESHOLD)이면 이상
    is_anomaly = abs(z) >= Z_THRESHOLD

    # 7️⃣ 상태 변경
    # NORMAL → ALERT (이상 발생)
    if state == "NORMAL" and is_anomaly:
        state = "ALERT"
        events.append({
            "timestamp": t,
            "event": "ENTER_ALERT",
            "value": x,
            "z": z
        })

    # ALERT → NORMAL (이상 해제)
    elif state == "ALERT" and (not is_anomaly):
        state = "NORMAL"
        events.append({
            "timestamp": t,
            "event": "EXIT_ALERT",
            "value": x,
            "z": z
        })

    # 8️⃣ 결과 저장
    # timestamp, value, mean, std, z, 상태 등을 기록
    stream_rows.append({
        "timestamp": t,
        "value": x,
        "mean": mean,
        "std": std,
        "z": z,
        "is_anomaly": bool(is_anomaly),
        "state": state
    })


# -------------------------------------------------
# 4) 결과 확인
#    - events: "언제 위험 상태로 들어갔고/언제 나왔는지"
#    - stream_df: 매 시점 계산 결과(실시간 판단 로그)
# -------------------------------------------------
events_df = pd.DataFrame(events)
stream_df = pd.DataFrame(stream_rows)

print("상태 변화 이벤트(앞부분):")
print(events_df.head(20))

print("\n알림 상태로 들어간 횟수:", int((events_df["event"] == "ENTER_ALERT").sum()))
print("알림 상태에서 나온 횟수:", int((events_df["event"] == "EXIT_ALERT").sum()))


# -------------------------------------------------
# (선택) 시각화 1) 값(value) + 실시간 기준선(mean)
# -------------------------------------------------
px.line(stream_df, x="timestamp", y=["value", "mean"], title="Streaming: value vs window-mean").show()

# -------------------------------------------------
# (선택) 시각화 2) z-score (실시간 계산 결과)
# -------------------------------------------------
px.line(stream_df, x="timestamp", y="z", title="Streaming: z-score").show()

# -------------------------------------------------
# (선택) 시각화 3) 상태 변화(ENTER_ALERT) 지점만 점으로 표시
# -------------------------------------------------
enter_alert = events_df[events_df["event"] == "ENTER_ALERT"].copy()
if len(enter_alert) > 0:
    px.scatter(enter_alert, x="timestamp", y="value", title="ENTER_ALERT points").show()
```
---
필요한 모듈 불러오기
```python
import numpy as np
import pandas as pd
import plotly.express as px
```
- NumPy는 파이썬에서 숫자 계산(수학/통계/배열 연산)을 빠르게 하기 위한 라이브러리
- Pandas는 표 형태 데이터(DataFrame)를 다루는 라이브러리로, 엑셀처럼 “행/열” 구조로 데이터를 관리합니다
- Plotly Express는 빠르게 그래프를 그리는 시각화 도구입니다.

---
`0) 데이터 준비 (실습용 센서 데이터 생성)`
```python
np.random.seed(42)
```
NumPy 난수 생성기의 시작 상태를 42로 설정합니다. 조금더 쉽게 말하면 앞으로 생성될 랜덤 숫자들의 패턴을 항상 동일하게만든다는 뜻입니다.


```python
n = 600
```
데이터를 총 몇 개 만들지(몇 개의 시점이 있을지) 개수를 정합니다.

- 여기서는 `n`에 600을 넣었으니  
    → 600개 데이터 포인트(600개의 시간, 600개의 센서값)를 만들겠다는 뜻입니다.
    
- 실무로 치면:  
    → “센서가 1초마다 값을 보낸다면, 600개면 600초(10분)치 데이터” 같은 느낌이에요.
    
`n`은 개발자가 만든 변수명입니다. 
관례적으로 “number of samples” 의미로 `n`을 많이 씁니다.

```python
timestamps = pd.date_range("2026-02-11 10:00:00", periods=n, freq="s")
```
시작 시간부터 일정 간격으로 n개 만큼의 시간 목록을 만들어서 timestamps에 저장합니다. 
즉, “시간이 하나씩 늘어나는 리스트(배열)”를 만드는 줄입니다. 
`pd.date_range(...)`가 하는 일
- Pandas가 제공하는 함수(정해진 기능)입니다.
- 역할:  
    → 연속된 날짜/시간 시퀀스(타임스탬프 배열)를 자동 생성

매개변수(인자) 의미
✅ `"2026-02-11 10:00:00"`
- 시작 시간(start) 입니다.
- 이 시간부터 시간 시퀀스를 만들기 시작합니다.
    
✅ `periods=n`
- “몇 개 만들래?”를 의미합니다.
- `n=600`이므로  
    → 총 600개의 시간 값 생성
    
✅ `freq="s"`
- “시간 간격을 얼마나 띄울래?”를 의미합니다.
- `"s"`는 second(초) 단위입니다.
    - `freq="s"` → 1초 간격
    - `freq="min"` → 1분 간격
    - `freq="H"` → 1시간 간격  
        이런 식으로 바꿀 수 있어요.

생성된 데이터 확인하기
![[Pasted image 20260215160350.png]]
1초마다 하나씩 증가하는 10분짜리 타임라인을 만든 겁니다.

왜 이게 필요할까?
이 코드는 “실시간 관제”를 흉내 내려는 코드입니다.
그래서:
- 센서값(value)만 있으면 “언제 발생한 값인지”가 없고
- 시간(timestamp)이 있어야
    - 그래프(시계열)
    - 슬라이딩 윈도우
    - 상태 변화 시점 기록 이런 게 가능합니다.
        
즉, 실시간 데이터처럼 보이도록 ‘시간 축’을 만들어주는 단계입니다.

---
```python
values = 100 + np.random.normal(0, 1.2, size=n)
```
정상 센서값(기본 패턴) 생성하는 부분으로 
평균이 100 근처에서 흔들리는(노이즈가 있는) 정상 센서값을 n개 만든다는 뜻입니다.

좀 더 구체적으로:
- `np.random.normal(...)`은 정규분포(가우시안 분포) 형태로 랜덤 숫자를 만들어줍니다. (NumPy 제공 기능)
- `0` : 랜덤 값의 평균(중심)을 0으로 만들고
- `1.2` : 흔들림(표준편차)을 1.2 정도로 주고
- `size=n` : 개수를 n개(여기선 600개) 만들라는 의미입니다.
    
그리고 앞에 `100 +`을 붙였기 때문에:
> 0 중심으로 흔들리던 값들을 100 중심으로 이동시켜서, 센서 정상값이 100 근처에서 움직이도록 만든 것입니다.


```python
spike_idx = [120, 121, 260, 400, 520]
```
이상치를 일부러 넣을 위치(인덱스) 지정으로 이상치(스파이크)가 발생할 데이터 위치를 미리 목록으로 지정하는 것입니다.
포인트:
- `spike_idx`는 개발자가 만든 변수명입니다(파이썬 키워드 아님).
- 리스트 안 숫자들은 “몇 번째 데이터인지”를 의미합니다.
- 예: 120이면 121번째 값(0부터 시작하는 인덱스 기준) 위치입니다.


```python
values[spike_idx] += [12, -14, 18, -20, 15]
```
정상 데이터 중 일부 지점에 인위적으로 이상 패턴(급격한 튐)을 삽입하는 코드로
지정한 위치(spike_idx)의 센서값에 큰 변화량을 더해서, 스파이크(이상치)를 의도적으로 만들어 넣는 코드입니다.

- `values[spike_idx]`는  
    → values 배열에서 spike_idx 위치들만 “콕 집어서” 선택한 것입니다.
    
- `+= [12, -14, 18, -20, 15]`는  
    → 그 위치의 값들을 각각 크게 올리거나/내려서 “비정상 급변”을 만듭니다.
    
직관적으로 보면:
- 어떤 지점은 +12로 갑자기 상승
- 어떤 지점은 -20으로 갑자기 하락
    
즉, 실시간 관제에서 흔히 보는 ‘갑자기 튀는 이상 상황’을 연습용으로 넣은 것입니다.
포인트:
- `pd.DataFrame(...)`은 Pandas의 정해진 기능입니다.
    
- `{"timestamp": timestamps, "value": values}`는  
    → “컬럼 이름 : 데이터” 형태로 넣어주는 방식입니다.
    
- 결과는 엑셀처럼:
    - timestamp 열
    - value 열을 가진 표가 만들어집니다.

`values[spike_idx]` print 결과
![[Pasted image 20260215161547.png]]
보이는 숫자들 대부분이:
✔ 100 근처 값들입니다.
평균 100 + 작은 노이즈구조를 만들어 낸 결과입니다.


```python
spike_idx = [120, 121, 260, 400, 520]
```
이 숫자들은 센서값이 아닙니다.
✔ 실제 데이터 값 아님  
✔ 측정 수치 아님  
✔ 모델 입력값 아님

정확한 의미:
> 배열(또는 데이터) 안에서의 "위치 번호(인덱스)"입니다.

이런 데이터를 만든 이유는 이상 상황을 인위적으로 만들어서 모델과 로직을 검증하기 위해서 입니다.

현실 데이터의 문제

실무에서 가장 큰 어려움:
✔ 언제 이상이 발생할지 모름  
✔ 이상 데이터가 충분하지 않음  
✔ 테스트하기 어려움

그래서 개발 단계에서는 가짜 이상치(스파이크)를 일부러 넣어봅니다.

이 코드의 역할
이 코드는 실제 이상 탐지가 아니라:
✔ 실험용 데이터 생성  
✔ 알고리즘 동작 확인  
✔ 탐지 성능 테스트목적입니다.

즉, 정답을 알고 있는 이상 데이터 만들기입니다.

`spike_idx print 결과`
```
spike_idx : [120, 121, 260, 400, 520]
```

왜 위치(인덱스)로 지정할까?

이렇게 해야:
✔ 어디에 이상 넣었는지 알고 있음  
✔ 모델이 잘 찾는지 확인 가능  
✔ 탐지 실패 여부 판단 가능

예:
- 120번째에 +12 넣음 → 우리가 정답 알고 있음
- 모델이 못 찾음 → 로직 문제
즉 디버깅 및 테스트 + 모델 검증 목적입니다.

실무적인 관점에서 이런 이상위치 데이터를 만드는 이유는
- 테스트 데이터 생성
- 알고리즘 검증
- 알고리즘 검증
- 시각 검증등 의도적으로 이상 상황을 만들어서 코드와 모델을 확인하는 실험용 장치입니다.


```python
values[spike_idx] += [12, -14, 18, -20, 15]
```

이 코드가 하는 일은 지정된 위치(spike_idx)에 있는 값들만 선택해서 각각 다른 변화량을 더합니다. 아주 쉽게 말하면 특정 시점의 센서값을 일부러 크게 흔들어 이상 상황을 만듦니다.

`values[spike_idx]`: values 배열에서 spike_idx에 적힌 위치만 골라서 접근
- values 전체를 바꾸는 게 아니라
- 120, 121, 260, 400, 520 위치만 선택

`+= [12, -14, 18, -20, 15]` : 선택된 각 위치 값에 서로 다른 변화량 적용하며
각각 이런 일이 벌어집니다:
- 어떤 값은 +12 → 급상승
- 어떤 값은 -20 → 급하락
즉, 정상값을 인위적으로 비정상 값으로 변경하는 단계입니다.

`values[spike_idx] 결과`
```
values[spike_idx] :  [112.06797991  86.63563131 117.83385282  79.78052427 115.61572696]
```
이상치 조작이 적용된 후의 실제 센서값들로
원래 값은 대부분 100 근처였을 것이고, 변화량이 적용되면서 크게 이동했습니다.

예를 들어 감각적으로 보면:
- 112 → 정상 범위보다 높음
- 86 → 정상 범위보다 낮음
- 79 → 매우 낮음 (강한 이상)

즉, 스파이크(급변 이상)가 성공적으로 삽입된 상태입니다.

```python
values = 100 + np.random.normal(0, 1.2, size=n)
spike_idx = [120, 121, 260, 400, 520]
values[spike_idx] += [12, -14, 18, -20, 15]
```
즉, 이부분은 실제 센서 스트림처럼 보이도록 정상 데이터 + 이상 데이터(스파이크)를 인위적으로 생성한 시뮬레이션 코드입니다.


```python
df = pd.DataFrame({"timestamp": timestamps, "value": values})
```
시간 + 값 데이터를 표 형태로 묶어서 분석 가능한 구조로 만들기과정으로 쉽게 설명하면
timestamps(시간)와 values(센서값)를 묶어서 ‘timestamp, value’ 두 컬럼을 가진 표(DataFrame)로 만듦니다.

timestamps(시간 목록)과 values(센서값 목록)을 한 표로 묶어서, 이후 분석/그래프/슬라이딩윈도우 처리에 쓰기 쉽게 `df`라는 DataFrame에 담는 단계입니다.

```python
df = df.sort_values("timestamp").reset_index(drop=True)
```
df를 timestamp 시간 순서대로 정렬해서, 시간이 흐르는 순서가 확실하도록 만든 뒤, 행 번호도 0부터 다시 깔끔하게 맞춥니다.
`drop=True` : 이전 인덱스 번호는 컬럼으로 남기지 말고 깔끔하게 버려라 라는 뜻입니다.


```python
# (선택) 원본 데이터 시각화
px.line(df, x="timestamp", y="value", title="Original Sensor Stream").show()
```
시간을 x축으로, 센서값을 y축으로 해서 원본 센서 스트림 그래프를 그려서 눈으로 확인합니다. 그래프 시각화는 데이터가 잘 만들어졌는지, 스파이크가 눈에 보이는지 확인하는 용도로 활용합니다.
`x="timestamp"`, `y="value"`:
- `"timestamp"`, `"value"`는 df의 컬럼 이름을 가리키는 문자열입니다.
- 즉, “df에서 어떤 열을 x축/ y축으로 쓸지” 지정하는 것.
    
`.show()`: 그래프를 실제로 화면에 띄웁니다.

그래프 결과
![[Pasted image 20260215164158.png]]
시간과 센서값을 표로 묶고, 시간순으로 정리한 뒤, 원본 데이터가 제대로 생성됐는지 그래프로 확인하는 단계입니다.

---

`1) Sliding Window 설정`
```python
WINDOW = 30
Z_THRESHOLD = 3.0
EPS = 1e-9
```
최근 데이터 몇 개를 기준으로 판단할지, 이상으로 간주할 기준선은 무엇인지, 계산 안정성을 위한 보정값은 무엇인지 설정하는 단계입니다.

`WINDOW = 30` : 최근 30개 데이터만 가지고 현재 상태를 판단하겠다는 뜻
`Z_THRESHOLD = 3.0` : 현재 값이 평균에서 3 표준편차 이상 벗어나면 이상으로 판단하겠다는 뜻
`EPS = 1e-9` : 수학 계산 오류(0으로 나누기)를 방지하기 위한 안전 보정값

최근 30개 데이터를 기준으로 평균과 변동성을 계산하고, 평균에서 크게 벗어나면 이상으로 간주하며, 계산 오류는 방지한다는 뜻입니다.

---
`2) 상태 머신(상태 변화 감지) 준비`
```python
state = "NORMAL"  # 초기 상태
events = []       # 상태 변화 이벤트 로그
stream_rows = []  # 매 시점 계산 결과 저장(나중에 그래프/분석용)
```

`state = "NORMAL"` : 지금 시스템은 일단 정상 상태라고 가정하고 시작합니다. 실시간 관제에서 값이 한번 이상하다고 바로 끝이 아니라 계속 흐르는 데이터 속에서 현재 상태가 무엇인지 기억해야 합니다. 
그래서 `state`는:
- 지금이 정상(NORMAL)인지
- 지금이 경고(ALERT) 상태인지를 저장하는 상태 메모장 역할을 합니다.

왜 초기 상태가 NORMAL일까?
실제 시스템도 보통:
- 시작할 땐 “정상”으로 시작하고
- 이후 데이터가 기준을 넘으면 “경고”로 바뀌는 구조이기 때문에, 초기값을 `"NORMAL"`로 둡니다.

`events = []` : 상태가 바뀐 순간만 따로 기록하기 위한 빈 리스트를 준비합니다.

관제에서 중요한 건 매 순간의 값도 중요하지만, 더 중요한 건:
✅ 언제 ‘정상 → 경고’로 바뀌었는지  
✅ 언제 ‘경고 → 정상’으로 돌아왔는지
즉, “전이 순간(enter/exit)”입니다.

그래서 `events`에는 이런 것들이 쌓입니다:
- ENTER_ALERT (경고 시작 시점)
- EXIT_ALERT (경고 종료 시점) 
 
events에 실제로 담기는 예시(이런 구조가 들어갑니다)
(아직 코드가 뒤에 나오지만, 담기는 형태는 이런 느낌)
- `timestamp`: 언제 발생했는지
- `event`: 어떤 변화인지(ENTER/EXIT)
- `value`: 그때 값이 얼마였는지
- `z`: 그때 z-score가 얼마였는지
    
즉 `events`는 상태 변화 이력(로그)”을 모아두는 빈 그릇입니다.

`stream_rows = []` : 센서 데이터가 들어올 때마다 계산한 결과를 전부 저장해둘 빈 리스트를 준비합니다.
`events`가 “변화 순간만” 기록하는 요약 로그라면, `stream_rows`는 “매 순간” 기록하는 상세 로그입니다.

즉:
- 매 초마다
- 평균(mean), 표준편차(std), z-score(z), 이상 여부(is_anomaly), 상태(state) 같은 계산 결과를 하나씩 저장해둡니다.

stream_rows에 담길 데이터 예시(이런 구조가 계속 쌓입니다)
- timestamp: 현재 시각
- value: 현재 센서값
- mean: 최근 WINDOW 평균
- std: 최근 WINDOW 표준편차
- z: 현재 값의 z-score
- is_anomaly: 이상치 여부(True/False)
- state: NORMAL/ALERT

즉 `stream_rows`는 실시간 판단 기록 전체(타임라인 로그)를 담는 큰 그릇입니다.

나중에 이걸 DataFrame으로 바꾸면:
- 그래프 그리기
- 이상 구간 분석
- 튜닝(임계치 조정)이 쉬워집니다.

---
이 코드 블록의 개념:
센서 데이터가 1개씩 들어오는 상황을 흉내 내면서, 매 순간 최근 WINDOW개(예: 30개)만으로 평균/표준편차를 계산해 z-score로 이상 여부를 판단하고, 정상↔경고 상태 전이를 기록하는 실시간 관제 처리 루프입니다.

핵심 포인트 4개:
1. 스트리밍 처리 시뮬레이션
	- for loop 한 번 = 센서값 1개 도착
2. 슬라이딩 윈도우 유지
	- 최근 30개만 계속 유지 (오래된 건 버림)
3. 실시간 기준선 계산
	- 최근 30개로 mean/std 계산 (고정 기준이 아니라 “계속 변하는 기준선”)
4. 상태 머신 + 이벤트 로그
	- 이상이면 ALERT 진입(ENTER_ALERT)
	- 정상으로 돌아오면 EXIT_ALERT 기록  
	    → 언제부터 위험이었는지/언제 끝났는지가 남음

`3) 스트리밍 처리 (한 건씩 읽으면서 최근 N개로만 판단)`
```python
window_values = []
```
최근 WINDOW개 센서값만 담아둘 빈 리스트(슬라이딩 윈도우 그릇)를 만듦니다.
- 이 리스트는 계속 길이가 WINDOW를 넘지 않도록 관리됩니다.
- 추후 관제 시스템에서는 최근 N개 값들을 모아두는 그릇으로 사용됩니다.

```
1️⃣ 데이터 1개 들어옴  
→ timestamp, value 한 줄을 가져온다  
  
2️⃣ 최근 N개 데이터 유지  
→ Sliding Window에 현재 값 추가  
→ WINDOW보다 많으면 가장 오래된 값 제거  
  
3️⃣ 평균 계산  
→ 최근 N개 데이터의 평균(mean) 계산  
  
4️⃣ 표준편차 계산  
→ 최근 N개 데이터의 변동성(std) 계산  
  
5️⃣ z-score 계산  
→ 현재 값이 평균에서 얼마나 떨어져 있는지 계산  
→ z = (현재값 - 평균) / 표준편차  
  
6️⃣ 이상 여부 판단  
→ |z| ≥ 임계값(Z_THRESHOLD)이면 이상  
  
7️⃣ 상태 변경  
→ NORMAL → ALERT (이상 발생)  
→ ALERT → NORMAL (이상 해제)  
  
8️⃣ 결과 저장  
→ timestamp, value, mean, std, z, 상태 등을 기록
```

1️⃣ 데이터 1개 들어옴
```python
for t, x in zip(df["timestamp"], df["value"]):
```
timestamp와 value를 한 쌍씩 묶어서, 데이터가 한 건씩 들어오는 것처럼 순서대로 처리합니다.
- `zip(A, B)` : A와 B를 같은 인덱스끼리 묶어서 (t, x) 형태로 하나씩 꺼냄
- 여기서:
    - `t` = 현재 시점의 시간(timestamp)
    - `x` = 그 시점의 센서값(value)
- 이 for문 1회전이 센서 데이터 1개가 도착한 순간을 의미합니다.


2️⃣ 최근 N개 데이터 유지 (Sliding Window)
```python
    window_values.append(float(x))
    
    # WINDOW보다 많으면 가장 오래된 값 제거
    if len(window_values) > WINDOW:
        window_values.pop(0)
```
`window_values.append(float(x))` : 이번에 들어온 센서값 x를 슬라이딩 윈도우 리스트에 추가합니다.
- `append()`는 파이썬 메서드로 리스트에 값을 하나 추가하는 명령입니다.
- `float(x)`는 x 값을 실수(float) 형태로 변환하는 처리입니다.
- 실수로 변환하는 이유는 NumPy 숫자일 수도 있고 Pandas 타입일 수도 있고 정수(int)일 수도 있기 때문에 계산전에 항상 float로 통일하는 안전 습관때문입니다.

`if len(window_values) > WINDOW:` 최근 값이 WINDOW개를 넘어가면(예: 31개가 되면), 가장 오래된 값을 제거할 준비를 합니다. 
조건문을 해석하면 리스트에 쌓인 최근 데이터 개수가 WINDOW(예: 30개)를 초과하면 조건문을 실행한다는 뜻입니다.
- `len()`은 길이를 알려주는 파이썬 내장 함수입니다.
- 위 코드의 목적은 윈도우 크기를 항상 일정하게 유지해주는 조건입니다.

`window_values.pop(0)` : 리스트의 0번째(가장 오래된 값)를 삭제해서, 최근 WINDOW개만 남도록 만듧니다.
- `pop(0)` : 0번째 요소를 꺼내면서 제거 (가장 앞 = 가장 오래된 값)
- 결과적으로 `window_values`는 항상 최근 값들만 유지


`3-2) WINDOW개가 쌓이기 전에는 통계가 안정적이지 않으므로 판단 보류`
```python
    # WINDOW개가 쌓이기 전에는 통계 계산을 하지 않음
    if len(window_values) < WINDOW:
        stream_rows.append({
            "timestamp": t,
            "value": x,
            "mean": np.nan,
            "std": np.nan,
            "z": np.nan,
            "is_anomaly": False,
            "state": state
        })
        continue
```
`if len(window_values) < WINDOW:` : 아직 WINDOW개가 다 안 쌓였으면(초반 구간이면), 판단을 하지 않고 기록만 남깁니다.
- 초반에는 데이터가 부족해서 mean/std가 신뢰하기 어렵기 때문에 보류가 합리적

`stream_rows.append({ ... })` (초반 보류 기록) : 판단을 보류하는 대신, 현재 시점 데이터를 로그로 남깁니다. (단, 통계값은 아직 없으니 NaN으로)

여기 dict의 키들은 전부 **개발자가 정한 컬럼 이름**(키워드 아님)이고,  
나중에 DataFrame으로 바꾸기 쉽게 “표의 한 행(row)” 형태로 저장하는 겁니다.
- `"timestamp": t` → 이 시점의 시간
- `"value": x` → 이 시점의 센서값
- `"mean": np.nan` → 평균은 아직 계산 못함(결측 표시)
- `"std": np.nan` → 표준편차도 아직 없음
- `"z": np.nan` → z-score도 없음
- `"is_anomaly": False` → 일단 이상 아님으로 기록(판단 보류니까)
- `"state": state` → 현재 상태(초기에는 NORMAL)
    
`np.nan`은 NumPy에서 제공하는 결측값 표기입니다.

`continue` : 이번 루프(현재 시점)는 여기서 끝내고, 다음 데이터(다음 시점)로 넘어간다는 뜻
- 파이썬 제어문(키워드)
- WINDOW가 채워질 때까지는 아래 계산을 아예 하지 않게 만드는 역할


`3-3) 최근 N개로만 평균/표준편차 계산 (실시간 기준선)`
```python
    # 3️⃣ 평균 계산
    mean = float(np.mean(window_values))
    
    # 4️⃣ 표준편차 계산
    std  = float(np.std(window_values, ddof=0))
```

`mean = float(np.mean(window_values))` : 최근 WINDOW개 값으로 평균을 계산해서 현재 기준선 평균을 만듦니다.
- `np.mean()` : NumPy 평균 계산 함수
- 전체 평균이 아니라 최근 N개 평균이라는 게 핵심  
    → 실시간 기준선

`std = float(np.std(window_values, ddof=0))` :  최근 WINDOW개 값으로 표준편차를 계산해서 현재 기준선의 흔들림 정도를 만든다는 뜻
- `np.std()` : 표준편차 계산
- `ddof=0` : 모집단 표준편차 방식(실시간 윈도우에서는 흔히 사용)
    - 키워드가 아니라 NumPy 함수의 옵션 파라미터(정해진 인자)
- 표준편차는 “평균 주변에서 얼마나 흔들리는지”를 수치화합니다.


`3-4) 현재 값이 기준선에서 얼마나 튀었는지(z-score)`
```python
    # 5️⃣ z-score 계산
    z = float((x - mean) / (std + EPS))
    
    # 6️⃣ 이상 여부 판단
    is_anomaly = abs(z) >= Z_THRESHOLD
```

`z = float((x - mean) / (std + EPS))` :  현재 값 x가 최근 평균에서 얼마나 벗어났는지(표준편차 단위로) 점수(z-score)를 계산한다는 뜻

핵심 해석:
- `(x - mean)` : 평균에서의 거리(차이)
- `/ (std + EPS)` : 그 차이를 “흔들림 크기(std)” 기준으로 상대화
- `EPS`는 0으로 나누는 상황 방지
    
즉 z는 현재 값이 평균에서 표준편차 몇 배만큼 떨어져 있나?

`is_anomaly = abs(z) >= Z_THRESHOLD` :  z-score의 절대값이 임계치 이상이면 이상치로 판단한다는 뜻
- `abs(z)` : 위로 튀든 아래로 튀든(상승/하락) 모두 감지하기 위해 절대값
- `Z_THRESHOLD = 3.0`이면 의미는:
    - 평균에서 3표준편차 이상 벗어나면 이상


`3-5) 상태 변화 감지 (NORMAL ↔ ALERT)`
```python
    # 7️⃣ 상태 변경 NORMAL → ALERT (이상 발생)
    if state == "NORMAL" and is_anomaly:
        state = "ALERT"
        events.append({"timestamp": t, "event": "ENTER_ALERT", "value": x, "z": z})
```

`if state == "NORMAL" and is_anomaly:` 현재 상태가 정상인데, 이번 값이 이상치로 판정되면 경고 상태로 진입한다는 뜻
- `"NORMAL"`은 개발자가 정한 상태명(문자열)
- 여기서부터 상태 머신이 동작합니다.

`state = "ALERT"` : 상태를 경고(ALERT)로 바꾼다는 뜻
- 이제부터는 경고 상태가 유지됩니다 (다음 데이터에서도 계속)

`events.append({"timestamp": t, "event": "ENTER_ALERT", "value": x, "z": z})` :  경고 상태로 들어간 순간을 이벤트 로그로 기록한다는 뜻
- `events`는 “상태가 바뀐 순간만” 저장하는 로그
- `"event": "ENTER_ALERT"`도 개발자 정의 문자열
- `timestamp/value/z`를 같이 남겨서, 나중에 왜 들어갔는지 근거를 남김


```python
    # ALERT → NORMAL (이상 해제)
    elif state == "ALERT" and (not is_anomaly):
        state = "NORMAL"
        events.append({"timestamp": t, "event": "EXIT_ALERT", "value": x, "z": z})
```

`elif state == "ALERT" and (not is_anomaly):`  현재 경고 상태인데, 이번 값이 더 이상 이상치가 아니면 정상 상태로 복귀한다는 뜻
- `not is_anomaly` : 이상 조건이 풀림


`3-6) 현재 시점 결과 저장 (나중에 시각화/분석)`
```python
    # 8️⃣ 결과 저장
    stream_rows.append({
        "timestamp": t,
        "value": x,
        "mean": mean,
        "std": std,
        "z": z,
        "is_anomaly": bool(is_anomaly),
        "state": state
    })
```

`stream_rows.append({ ... })` (매 시점 결과 저장) :  현재 시점의 계산 결과(mean/std/z/이상여부/상태)를 한 줄 기록으로 저장한다는 뜻
- 이게 쌓여서 나중에 `stream_df`가 되고
- 그래프(`value vs mean`, `z-score`)를 그릴 수 있게 됩니다.
- `"is_anomaly": bool(is_anomaly)`는 True/False를 확실한 파이썬 bool로 고정하는 습관입니다.

센서값이 하나씩 들어올 때마다 최근 30개로 기준선을 만들고, 현재 값이 크게 벗어나면 ALERT 상태로 전환하고, 다시 안정되면 NORMAL 상태로 복귀하며, 모든 계산 결과와 상태 변화를 기록하는 실시간 관제 루프입니다.

---
`4) 결과 확인`
```python
events_df = pd.DataFrame(events)
stream_df = pd.DataFrame(stream_rows)
```

`events_df = pd.DataFrame(events)` : 상태가 바뀐 순간만 기록된 이벤트 로그 테이블입니다.
즉,
✔ 모든 센서값이 아니라  
✔ NORMAL ↔ ALERT 전환 시점만 저장

`stream_df = pd.DataFrame(stream_rows)` : 실시간 처리 과정에서 매 시점마다 저장한 계산 결과들을 표(DataFrame) 형태로 변환한다는 뜻으로 쉽게 표현하면 실시간 판단 로그를 테이블로 만드는 단계입니다.
```python
stream_rows.append({  
"timestamp": t,  
"value": x,  
"mean": mean,  
"std": std,  
"z": z,  
"is_anomaly": bool(is_anomaly),  
"state": state  
})
```
`stream_rows`는:
✔ 리스트(list) 구조  
✔ 안에 딕셔너리(dict)들이 계속 쌓임  
✔ 딕셔너리 하나 = 한 시점의 계산 결과
DataFrame 바꾸는 이유는 
리스트 상태로는 불편합니다:
❌ 그래프 어려움  
❌ 필터링 불편  
❌ 분석 불편

DataFrame으로 바꾸면:
✔ 열(column) 기반 접근 가능  
✔ 시각화 가능  
✔ 통계 분석 가능  
✔ 조건 검색 가능

`events_df`는 상태 변화 순간만 저장하고
`stream_df`는 모든 시점 계산 결과 저장합니다.
✔ ENTER / EXIT만 아님  
✔ 정상 구간 포함  
✔ 전체 타임라인 로그


```python
print("상태 변화 이벤트(앞부분):")
print(events_df.head(20))

print("\n알림 상태로 들어간 횟수:", int((events_df["event"] == "ENTER_ALERT").sum()))
print("알림 상태에서 나온 횟수:", int((events_df["event"] == "EXIT_ALERT").sum()))
```

`(events_df["event"] == "ENTER_ALERT").sum()` : event 컬럼에서 ENTER_ALERT가 몇 번 등장하는지 개수를 계산합니다.
`.sum()` : Pandas에서 `sum()`은 True 값을 숫자 1로 간주하여 모두 더합니다.
즉:
- True → 1
- False → 0
    
그래서 결과는 조건을 만족한 개수 계산합니다.
 
결과확인
![[Pasted image 20260215191942.png]]


`(선택) 시각화 1) 값(value) + 실시간 기준선(mean)`
```python
px.line(stream_df, x="timestamp", y=["value", "mean"], title="Streaming: value vs window-mean").show()
```

화면결과
![[Pasted image 20260215192010.png]]
이 그래프는 두 개의 선을 비교합니다:
- 파란선 (value) → 실제 센서값
- 빨간선 (mean) → 최근 WINDOW 기반 실시간 평균(기준선)
    
즉, 현재 값 vs 실시간 기준선 비교 그래프입니다.

✔ 파란선이 100 근처에서 작은 흔들림  
✔ 빨간선은 거의 평평하게 유지

의미: 센서가 정상 상태로 안정적으로 동작 중입니다.

스파이크 구간 해석

중간중간 보이는 큰 튐(위/아래로 급격한 변화):
✔ 파란선이 갑자기 크게 상승 / 하락  
✔ 빨간선은 천천히 반응

이 의미는 순간적인 이상치(급변 값)가 발생했다 입니다.

빨간선이 거의 직선에 가까운 이유는 
✔ 이상치가 있어도 평균은 완만하게 움직임  
✔ 노이즈 제거 효과  
✔ 기준선 역할 수행

즉, 시스템이 순간 노이즈에 과민 반응하지 않도록 완충 작용을 하고 있습니다.

이 그래프가 말해주는 상황은 센서값은 대부분 정상 범위에서 움직이며, 일부 시점에서 급격한 이상이 발생했지만 전체 시스템 기준선은 안정적으로 유지된다고 해석하면 됩니다.



`(선택) 시각화 2) z-score (실시간 계산 결과)`
```python
px.line(stream_df, x="timestamp", y="z", title="Streaming: z-score").show()
```

화면결과
![[Pasted image 20260215192212.png]]
평균 대비 얼마나 벗어났는지를 표준화 점수(z-score)로 표현한 그래프입니다.

이 그래프의 y축은 센서값이 평균에서 몇 표준편차 떨어져 있는지를 의미합니다.
그래서 
- 0 근처 → 평균과 거의 동일 → 정상
- 큰 양수 → 평균보다 크게 높음 → 이상 가능
- 큰 음수 → 평균보다 크게 낮음 → 이상 가능

전체 그래프 패턴을 해석하면
✔ 대부분 구간이 0 근처에서 작은 흔들림  
✔ 일부 시점에서 급격한 피크 발생

의미: 대부분 정상 상태이며, 특정 시점에서만 통계적으로 큰 이탈 발생합니다.

스파이크 구간 해석
갑자기 크게 튀는 부분들
✔ +4 ~ +5 수준  
✔ -4 ~ -5 수준

이 의미는 해당 시점의 값이 평균 대비 매우 비정상적인 위치에 있었다를 의미합니다.

왜냐하면:
Z_THRESHOLD = 3.0 이었기 때문입니다.
✔ |z| ≥ 3 → 이상치 판정

센서값이 정상 평균 범위에서 얼마나 벗어났는지를 보여주는 그래프이며, 대부분 안정적이지만 특정 시점에서 강한 이상 신호가 발생했음을 나타낸다는 뜻으로 쉽게 말해서 값이 얼마나 비정상적으로 튀었는지를 보는 그래프입니다.


(선택) 시각화 3) 상태 변화(ENTER_ALERT) 지점만 점으로 표시
```python
enter_alert = events_df[events_df["event"] == "ENTER_ALERT"].copy()
if len(enter_alert) > 0:
    px.scatter(enter_alert, x="timestamp", y="value", title="ENTER_ALERT points").show()
```

화면결과
![[Pasted image 20260215192235.png]]
전체 데이터 중에서 ‘알람 상태로 진입한 순간(ENTER_ALERT)’만 골라서 시점과 값을 점으로 표시한 그래프입니다.

화면에 점으로 찍힌 값들은
✔ 모두 ENTER_ALERT가 발생한 시점  
✔ 정상 → 위험 상태로 전이된 순간

중요한 차이:
🚨 이상치 전체가 아니라  
🚨 알람 트리거 순간만 표시
