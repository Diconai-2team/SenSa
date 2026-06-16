STEP 3는 이런 상황에서 사용합니다. 
정상 기준을 사람이 수학적으로 정하기 어려울 때

STEP 1, STEP 2에서는 이런 전제가 있었습니다.
✔ 평균이 존재한다  
✔ 데이터 분포가 비교적 안정적이다  
✔ 정상 범위를 계산할 수 있다

예를 들어:
- 센서가 항상 100 근처에서 움직이고
- 흔들림도 일정하다면  
    → 평균과 표준편차로 충분히 이상을 판단할 수 있습니다.

❗ 하지만 현실은 다릅니다

현실 데이터는 이런 문제가 많습니다.
❌ 정상 범위가 명확하지 않음  
❌ 패턴이 복잡함  
❌ 센서가 여러 개라서 한 값만으로 판단하기 어려움  
❌ 시간이 지나면 정상 범위 자체가 바뀜

예를 들어:
- 온도, 습도, CO2, 진동, 전류가 동시에 변한다면?
- 단순히 평균 하나로 설명이 안 됩니다.
    
이때 등장하는 것이 머신러닝 모델입니다.

---
🔹 STEP 3의 핵심 개념

✔ STEP 1, 2
사람이 기준을 정합니다. 평균 ± 3표준편차 넘으면 이상

✔ STEP 3
모델이 기준을 학습합니다. 사람이 직접 기준을 정하지 않습니다.

STEP 3의 목적은 정상이 어떤 모양인지를 모델이 스스로 학습하는 모델 학습 입니다.
모델이 학습하는 내용은
✔ 정상 데이터가 어떤 형태인지  
✔ 정상 데이터들이 어떻게 모여 있는지  
✔ 혼자 떨어진 데이터는 무엇인지

왜 이런 방식이 필요한가요?

현실 데이터를 생각해보겠습니다.
예를 들어 제조 설비에서:
- 온도 정상 범위: 상황마다 달라짐
- 진동 정상 범위: 부하에 따라 달라짐
- 습도 영향 있음
- 여러 센서가 동시에 작용

이런 경우:
❌ Z-score로는 한계가 있습니다.  
❌ 단순 임계값으로는 실패합니다.

그래서 데이터 전체 구조를 학습하는 모델이 필요합니다.

###### STEP 2와 STEP 3의 차이
| STEP 2   | STEP 3        |
| -------- | ------------- |
| 통계 계산 기반 | ML 모델 기반      |
| 평균 중심 사고 | 데이터 분포 구조 사고  |
| 기준선 필요   | 기준선 직접 설정 불필요 |
| 규칙 기반 판정 | 학습 기반 판정      |
이 코드가 증명하는 중요한 사실
Isolation Forest는 이런 점이 핵심입니다.
✔ 정상/이상 정답 라벨이 없어도 학습 가능  
✔ 사람이 정상 기준을 정의하지 않아도 됨

즉, 정답이 없는 상태에서도 이상 탐지가 가능하다 이게 가장 큰 가치입니다.

---
Isolation Forest가 실제로 하는 일:

정상 데이터는?
비슷한 값끼리 모여 있습니다.

예:
- 대부분 온도 30~32도
- 대부분 CO2 350~360
- 대부분 진동 일정 범위

→ 서로 비슷해서 무리를 이룹니다.

이상 데이터는?
혼자 튀어 있습니다.

예:
- 갑자기 온도 50도
- 갑자기 진동 급상승
- 다른 센서와 패턴이 맞지 않음
    
→ 다른 값들과 멀리 떨어져 있습니다.

Isolation Forest는 이렇게 생각합니다:
혼자 따로 떨어진 데이터는 이상일 가능성이 높다.

1️⃣ STEP 1  
→ 배치 통계 계산

2️⃣ STEP 2  
→ 실시간 통계 기반 이상 탐지

3️⃣ STEP 3  
→ 기준 정의가 어려울 때 ML 기반 이상 탐지

---
### Isolation Forest 패턴 뼈대코드
```python
# ============================================
# [STEP 3 Skeleton] Isolation Forest 이상 탐지 패턴
# - 라벨 없는 비지도 학습
# - fit → predict 구조
# ============================================

from sklearn.ensemble import IsolationForest

# 0) 데이터 준비
# X = 이상 탐지에 사용할 수치형 데이터 (2차원 구조)
# 예: 센서값 / 파생변수 / 여러 센서 조합 등

# 1) 모델 생성
model = IsolationForest(
    contamination=0.01,   # 이상 비율 가정 (중요 파라미터)
    random_state=42
)

# 2) 학습 (정상/이상 라벨 없이 학습 가능)
model.fit(X)

# 3) 예측
labels = model.predict(X)

# 규칙:
#  1  → 정상
# -1  → 이상치

# 4) 결과 활용
# 이상치 필터링 / 알람 / 시각화 / 로그 기록 등
```
---

```python
from sklearn.ensemble import IsolationForest
```
scikit-learn 라이브러리 안에 있는 `ensemble` 모듈에서  
`IsolationForest`라는 모델 클래스를 가져옵니다.

---
`0) 데이터 준비`
```python
X = 이상 탐지에 사용할 수치형 데이터 (2차원 구조)
```
이상 탐지 모델에 입력으로 사용할 숫자 데이터 묶음을 준비합니다.

---
`1) 모델 생성`
```python
model = IsolationForest(
    contamination=0.01,   # 이상 비율 가정 (중요 파라미터)
    random_state=42
)
```
이상치를 탐지하기 위한 Isolation Forest 모델을 하나 만듦니다. 즉 이상 탐지를 수행할 분석 도구를 설정하고 준비하는 단계입니다.

아직 학습도 아니고 예측도 아니며,
✔ 모델을 실제로 작동시키기 전  
✔ 어떤 기준으로 탐지할지 옵션을 정하고  
✔ 모델 객체를 만드는 단계입니다.

---
`2) 학습 (정상/이상 라벨 없이 학습 가능)`
```python
model.fit(X)
```
준비된 데이터를 이용해 모델이 데이터의 패턴을 스스로 학습하는 단계입니다. 
즉, 모델이 데이터의 특징과 분포를 파악하는 과정입니다.

---
`3) 예측`
```python
labels = model.predict(X)
```
학습이 완료된 모델이 데이터를 검사하여 정상인지 이상인지 판단하는 단계입니다.
좀더 쉽게 설명하면 모델이 각 데이터 값을 확인하고 판정 결과를 만들어내는 과정입니다.


---
`4) 결과 활용`
```python
이상치 필터링 / 알람 / 시각화 / 로그 기록 등
```

이상치 필터링은 모델이 이상치라고 판단한 데이터만 분리하는 작업입니다.
```python
# 기본형태
# 정상 / 이상 구분 컬럼 생성  
df_model["is_anomaly"] = df_model["label"] == -1  
  
# 이상치만 추출  
anomalies = df_model[df_model["is_anomaly"]]  
  
print("이상치 개수:", len(anomalies))  
print(anomalies.head())
```

알람 처리 (경고 시스템)은 이상치가 발견되었을 때 특정 행동을 수행합니다.
```python
# 가장 단순한 형태
if len(anomalies) > 0:  
	print("🚨 이상치 감지! 확인 필요")

# 실무에 가까운 형태
THRESHOLD = 5 # 허용 이상치 개수  
  
if len(anomalies) >= THRESHOLD:  
	print("🚨 위험 상태 — 즉시 점검 필요")  
else:  
	print("정상 범위")
```

시각화는 모델이 제대로 탐지했는지 눈으로 검증하는 단계입니다.
```python
import plotly.express as px

# 전체 데이터
px.line(df_model, x="timestamp", y="value", title="전체 데이터").show()

# 이상치만 강조
px.scatter(
    anomalies,
    x="timestamp",
    y="value",
    title="탐지된 이상치"
).show()
```
- 모델 결과는 반드시 시각 검증 필요
- 잘못 탐지하는 경우 즉시 발견 가능
- 실무에서 거의 필수 단계

로그 기록 (운영 시스템 핵심)은 이상치 발생 이력을 남기는 작업입니다.
```python
# 가장 기본 형태:
anomalies.to_csv("anomalies_log.csv", index=False)
print("로그 파일 저장 완료")

# 좀더 현실적인 형태:
from datetime import datetime

log_time = datetime.now()

anomalies["detected_at"] = log_time
anomalies.to_csv("anomaly_history.csv", mode="a", header=False, index=False)
```
- 나중에 문제 원인 분석 가능
- 재현 / 감사 / 모니터링 가능
- 장애 대응에 매우 중요
- 
---
```bash
uv pip install scikit-learn
```

### 실무를 위한 연습 전체코드
```python
# ============================================
# [STEP 3 전체코드] Isolation Forest 이상 탐지 실무 예시
# - 라벨 없는 이상 탐지
# - 센서 데이터 기반
# - 실무 구조 그대로
# ============================================

import numpy as np
import pandas as pd
import plotly.express as px
from sklearn.ensemble import IsolationForest

# -------------------------------------------------
# 0) 데이터 준비 (실습용 센서 데이터 생성)
# -------------------------------------------------
np.random.seed(42)

n = 600
timestamps = pd.date_range("2026-02-11 10:00:00", periods=n, freq="s")

values = 100 + np.random.normal(0, 1.2, size=n)

# 비정상 패턴 삽입 (센서 급변 상황 가정)
spike_idx = [120, 121, 260, 400, 520]
values[spike_idx] += [12, -14, 18, -20, 15]

df = pd.DataFrame({
    "timestamp": timestamps,
    "value": values
})

df = df.sort_values("timestamp").reset_index(drop=True)

# -------------------------------------------------
# 1) Feature 구성 (매우 중요)
#    Isolation Forest는 2차원 입력 필요
# -------------------------------------------------
# 실무에서는 원본 값 그대로 넣는 경우 거의 없음
# → 최근 평균 / 변화량 / 분산 등 파생변수 추가

WINDOW = 30

df["roll_mean"] = df["value"].rolling(WINDOW).mean()
df["roll_std"]  = df["value"].rolling(WINDOW).std(ddof=0)
df["diff"]      = df["value"].diff()

# 초기 NaN 제거 (ML 모델 필수 작업)
df_model = df.dropna().copy()

# 모델 입력 변수 선택
FEATURES = ["value", "roll_mean", "roll_std", "diff"]
X = df_model[FEATURES]

# -------------------------------------------------
# 2) Isolation Forest 모델 생성
# -------------------------------------------------
model = IsolationForest(
    contamination=0.01,   # 이상 비율 가정 (실무 핵심 파라미터)
    random_state=42
)

# -------------------------------------------------
# 3) 학습 (비지도 학습 → 라벨 불필요)
# -------------------------------------------------
model.fit(X)

# -------------------------------------------------
# 4) 예측 (정상=1 / 이상=-1)
# -------------------------------------------------
df_model["label"] = model.predict(X)

# 이상치만 필터링
df_model["is_anomaly"] = df_model["label"] == -1

anomalies = df_model[df_model["is_anomaly"]]

print("탐지된 이상치 개수:", len(anomalies))
print(anomalies[["timestamp", "value"]].head(10))

# -------------------------------------------------
# 5) 시각화 — 이상치 확인 (실무에서 매우 중요)
# -------------------------------------------------

# (1) 전체 시계열
px.line(df, x="timestamp", y="value", title="Sensor Data").show()

# (2) 이상치 포인트만 표시
px.scatter(
    anomalies,
    x="timestamp",
    y="value",
    title="Isolation Forest Detected Anomalies"
).show()
```
---
`필요한 모듈 불러오기`
```python
import numpy as np
import pandas as pd
import plotly.express as px
from sklearn.ensemble import IsolationForest
```

- `IsolationForest (sklearn)` : 비지도 학습 기반 이상 탐지 모델로, 정상 데이터 패턴을 학습한 뒤 각 데이터의 이상 점수를 계산하여 이상 여부를 판단하는 모델

`0) 데이터 준비 (실습용 센서 데이터 생성)`
```python
np.random.seed(42)
```
랜덤 숫자를 뽑는 기준을 고정하는 설정입니다.

이코드를 초반에 설정하는 이유:
- 지금 코드를 다시 실행했을 때  같은 결과가 나와야 비교가 가능합니다.(재현가능성)
- 특히 ML 모델은 랜덤 요소가 많기 때문에  seed를 고정하지 않으면 결과가 조금씩 달라질 수 있습니다.
- 이상 탐지가 잘 되었는지 확인할 때 데이터가 매번 바뀌면 비교가 어렵습니다. (디버깅)

---
```python
n = 600 # 데이터 개수를 600개로 설정
timestamps = pd.date_range("2026-02-11 10:00:00", periods=n, freq="s")
```
시작 시각부터 1초 간격(`freq="s"`)으로 600개의 시간 데이터를 생성
2026-02-11 10:00:00부터 시작해서 1초 간격(`freq="s"`)으로 총 n개(`periods=n`)의 시간 데이터를 생성한 뒤 그것을 `timestamps` 변수에 저장하라

`date_range()` 함수 정의
```python
pd.date_range(start=None, end=None, periods=None, freq=None)
```
`freq`는 함수에 값을 전달하는 입력 옵션(parameter) 입니다. 시간 간격을 초단위로 만드는 설정
설정은 순서대로 진행되며 첫번째 나오는 값이 시작값이며 다음에 등장하는것이 periods면 end는 생략이 된것입니다.

---
```python
values = 100 + np.random.normal(0, 1.2, size=n)
```
평균이 100 근처에서 약간씩 흔들리는 센서 데이터를 n개 생성하라

- `normal` → 정규분포(가우시안 분포)
- `0` → 평균(mean)
- `1.2` → 표준편차(std)
- `size=n` → n개 생성

즉, 평균 0, 표준편차 1.2를 가지는 난수를 n개 생성
```
0.5  
-1.1  
0.8  
-0.3  
1.4
```
이런 난수들을 만들어 냅니다.

그리고 100을 더하면?
```
0.5 → 100.5  
-1.1 → 98.9  
0.8 → 100.8
```
정상 센서가 100 근처에서 약간씩 흔들리는 상황을 인위적으로 만들어내는 연습용 데이터 생성 과정입니다.


실제 데이터 범위
```json
{
  "device_id": "sensor_01",
  "timestamp": "2025-11-10T10:30:00Z",
  "seq": 12345,

  "lat": 37.5665,
  "lon": 126.9780,
  "zone_id": "ZONE_A",

  "CO": 65.3,
  "H2S": 9.8,
  "CO2": 350.0,
  "O2": 19.2,
  "temperature": 35.1,
  "humidity": 72.4,
  "fine_dust": 45.0,
  "noise": 82.0,

  "battery": 88,
  "signal_strength": -73,
  "fw_version": "1.0.3",

  "power_usage": 420,
  "relay_state": true,
  "control_source": "auto",

  "valid": true,
  "calibration_flag": false,

  "risk_score": 42.0,
  "alert_level": "caution",
  "trend": 3.5
}
```
예를 들어 `"CO2": 350.0,` 이산화탄소 데이터 같은 경우 범위가 350.0이므로 난수로 만들기 위해 `values = 350 + np.random.normal(0, 1.2, size=n)` 이렇게 만들어 낼수 있습니다.

---
```python
spike_idx = [120, 121, 260, 400, 520]
values[spike_idx] += [12, -14, 18, -20, 15]
```

- `spike_idx = [120, 121, 260, 400, 520]` : 데이터 배열에서 특정 위치(인덱스)를 지정한 것
예를 들어:
- 120번째 데이터
- 121번째 데이터
- 260번째 데이터
- 400번째 데이터
- 520번째 데이터
    
이 위치에 이상값을 만들겠다는 의미입니다. 

- `values[spike_idx] += [12, -14, 18, -20, 15]` : 해당 위치의 값에 특정 숫자를 더하라

###### 원래 값이 이렇게 있었다고 가정해보겠습니다
| index | 원래 값  |
| ----- | ----- |
| 120   | 100.2 |
| 121   | 99.8  |
| 260   | 100.5 |
| 400   | 100.1 |
| 520   | 99.9  |
```
[12, -14, 18, -20, 15] 를 더하면
```

|index|변경 후 값|
|---|---|
|120|112.2|
|121|85.8|
|260|118.5|
|400|80.1|
|520|114.9|
이렇게 됩니다.

왜 이렇게 하냐면 정상 데이터 중간에 급격히 튀는 값(스파이크)을 일부러 삽입하는 것입니다.
갑자기 급상승이나 갑자기 급하락 같은 센서 이상 상황을 시뮬레이션하는 것입니다.
- +12 → 급상승
- -14 → 급하락을 넣은 것입니다.

---
```python
df = pd.DataFrame({
    "timestamp": timestamps,
    "value": values
})
```
`timestamps`와 `values`를 하나의 표(테이블)로 묶어서 Pandas DataFrame 객체로 만드는 코드입니다.

쉽게 말하면 지금까지 우리는:
- `timestamps` → 시간 목록
- `values` → 센서 값 목록을 따로 가지고 있었습니다.

---
```python
df = df.sort_values("timestamp").reset_index(drop=True)
```

`sort_values("timestamp")` : 컬럼을 기준으로 데이터를 정렬합니다. 즉, 시간 순서대로 다시 줄 세우는 작업입니다.

`.reset_index(drop=True)` : 인덱스를 다시 정리하는 작업입니다.

|index|timestamp|value|
|---|---|---|
|1|10:00:01|99|
|2|10:00:03|100|
|0|10:00:05|101|
정렬한뒤 인덱스 번호가 뒤죽박죽 되므로 다시 인덱스를 시간순으로 0부터 정리합니다.

---
`1) Feature 구성 (매우 중요)`
```python
WINDOW = 30
```
최근 몇 개 데이터를 기준으로 계산할 것인지를 정하는 설정입니다.
✔ 최근 30개 데이터만 사용하겠다  
✔ 30개를 하나의 묶음(창, Window)으로 보겠다 라는 의미입니다.

---
```python
df["roll_mean"] = df["value"].rolling(WINDOW).mean()        # roll_mean 계산
df["roll_std"]  = df["value"].rolling(WINDOW).std(ddof=0)   # roll_std 계산
df["diff"]      = df["value"].diff()                        # diff 계산
# 이 순서대로 실행됩니다. 그러나 서로의 계산에 영향을 주지 않습니다.

# 쉽게 말하면 
# value → 평균 구하기  
# value → 표준편차 구하기  
# value → 변화량 구하기
# 같은 재료로 서로 다른 특징(feature)을 만드는 것입니다.
```

왜 이렇게 연달아 쓰는가?
우리는 value 하나만 보는 게 아니라: 
- `roll_mean` : 최근 평균 수준
- `roll_std` : 최근 변동성
- `diff` : 직전 대비 변화량
이렇게 여러 관점으로 데이터를 보려고 하는 것입니다.

계산방법
##### `roll_mean (이동 평균)` : 최근 `WINDOW`개 값의 평균을 계산해서 `roll_mean`이라는 새로운 컬럼에 저장합니다.

예를 들어 WINDOW = 3이면: 
value 값이 
100 
101 
99 
102 
이렇게 있을 경우

→ 3번째 행부터 계산됩니다.
- (100+101+99)/3 = 100
- (101+99+102)/3 = 100.67
즉, 최근 구간의 기준선 평균을 만드는 코드입니다.

---
##### `df["roll_std"]` : 최근 `WINDOW`개 값의 표준편차(흔들림 크기)를 계산합니다.
표준편차는 값이 평균에서 얼마나 흔들리는지 나타내는 숫자입니다.
WINDOW = 30이라면 → 최근 30개 데이터가 얼마나 안정적인지 계산하는 것입니다.

계산방식:
WINDOW = 3 이라고 가정해보겠습니다. 아래 데이터에서

| index | value |
| ----- | ----- |
| 0     | 100   |
| 1     | 101   |
| 2     | 99    |
| 3     | 102   |

① 평균 계산 
```
mean=(100+101+99)/3=100
```
② 각 값이 평균에서 얼마나 떨어졌는지 
```
100 - 100 = 0  
101 - 100 = 1  
99 - 100 = -1
```
③ 제곱
```
0² = 0  
1² = 1  
(-1)² = 1
```
④ 평균 (ddof=0 이므로 3으로 나눔)
```
variance=(0+1+1)/3=0.67
```
⑤ 루트 씌움 (표준편차)
```
std=√0.67≈0.82
```

따라서
```
roll_std ≈ 0.82
```

###### index 2에서의 계산
| index | value |
| ----- | ----- |
| 0     | 100   |
| 1     | 101   |
| 2     | 99    |
| 3     | 102   |
위와 같은 방식으로 반복해서 계산하면

###### 🔹 정리된 결과
| index | value | roll_std |
| ----- | ----- | -------- |
| 0     | 100   | NaN      |
| 1     | 101   | NaN      |
| 2     | 99    | 0.82     |
| 3     | 102   | 1.25     |
왜 0,1은 NaN이고 2부터 값이 나오나?
Rolling(window=3)은 최근 3개가 모였을 때부터 계산 가능이기 때문입니다.

index 0
데이터: `[100]`  
→ 아직 1개밖에 없음  
→ 평균/표준편차 계산 불가  
→ NaN

index 1
데이터: `[100, 101]`  
→ 2개밖에 없음  
→ WINDOW=3 미충족  
→ NaN

index 2
부터는 위에 계산한 값이 값에 대입이 됩니다.

---
##### `df["diff"]` : 현재 값에서 바로 이전 값을 뺀 “변화량”을 계산합니다.

즉
```
diff = 현재값 - 이전값
```

###### value 컬럼이 이렇게 있다고 가정:
|index|value|
|---|---|
|0|100|
|1|101|
|2|99|
|3|102|
###### `diff()` 적용 결과:
|index|value|diff|
|---|---|---|
|0|100|NaN|
|1|101|1|
|2|99|-2|
|3|102|3|

계산과정
index 0
이전 값이 없음  
→ NaN

index 1
```
101 - 100 = 1
```

index 2
```
99 - 101 = -2
```

index 3
```
102 - 99 = 3
```

그래서 diff는 무엇을 보는가?
값의 수준(level)이 아니라 변화의 크기와 방향을 보는 것입니다

직관적으로 말하면
- 값이 갑자기 확 튀면 → diff도 크게 튑니다
- 값이 천천히 움직이면 → diff는 작습니다
- 상승하면 → 양수
- 하락하면 → 음수

🚨 이상 탐지에서 왜 쓰냐면 예를 들어 센서값이:
```
100, 101, 99, 100, 115
```

마지막 값에서:
```
115 - 100 = +15
```
즉, 급격한 상승이 감지됩니다. 
이걸로:
✔ 급격한 변동 감지  
✔ 스파이크 탐지 보조  
✔ 추세 변화 감지  
✔ 상태 전이 감지를 할 수 있습니다.

---
##### `df["diff"] ` : 지금 값이 방금 전보다 얼마나 변했는가? 를 계산하는 것입니다.

`diff()`는 현재 값 - 이전 값 = 순간 변화량 계산 함수입니다.

---
초기 NaN 제거 (ML 모델 필수 작업)
```python
df_model = df.dropna().copy()
```

`dropna()` : NaN(결측값)이 하나라도 있는 행을 전부 삭제합니다.

|index|value|roll_mean|roll_std|diff|
|---|---|---|---|---|
|0|100|NaN|NaN|NaN|
|1|101|NaN|NaN|1|
|2|99|100|0.82|-2|
|3|102|100.6|1.25|3|
###### `dropna()`를 하면:
| index | value | roll_mean | roll_std | diff |
| ----- | ----- | --------- | -------- | ---- |
| 2     | 99    | 100       | 0.82     | -2   |
| 3     | 102   | 100.6     | 1.25     | 3    |
처음 WINDOW-1개는 NaN 발생하여 diff의 첫 행도 NaN이므로 머신러닝 모델은 ❌ NaN을 입력으로 받지 못합니다. 그래서 모델용 데이터 만들 때는 반드시 제거합니다.

---
모델 입력 변수 선택
```python
# 사용할 컬럼 이름 목록을 변수에 저장한 것
FEATURES = ["value", "roll_mean", "roll_std", "diff"]
X = df_model[FEATURES]
```

`X = df_model[FEATURES]` : `df_model`에서 FEATURES에 해당하는 컬럼들만 뽑아서 새로운 데이터셋 X를 만든다 즉 X에 저장한다는 뜻입니다. 

---
`2) Isolation Forest 모델 생성`
```python
model = IsolationForest(
    contamination=0.01,   # 이상 비율 가정 (실무 핵심 파라미터)
    random_state=42
)
```

IsolationForest란? 비지도학습 기반 이상 탐지 알고리즘입니다.
즉,
✔ 정상 데이터만 있어도 작동  
✔ y(정답)가 없어도 됨  
✔ 데이터 중에서 “고립되기 쉬운 점”을 이상치로 판단

이름뜻
- Isolation = 고립시키다
- Forest = 여러 개의 트리(Decision Tree)
원리: 정상 데이터는 서로 비슷해서 분리하기 어렵고 이상 데이터는 특이해서 쉽게 분리됩니다.

즉, 이상치는 적은 분기만으로 고립됩니다.

`model = IsolationForest(...)` : 이상 탐지 모델 객체를 생성하는 단계입니다.

`contamination=0.01` : 전체 데이터 중 약 1%를 이상치로 간주하겠다는 뜻입니다

---
`3) 학습 (비지도 학습 → 라벨 불필요)`
```python
model.fit(X)
```
X변수의 모델을 학습합니다.

---
`4) 예측 (정상=1 / 이상=-1)`
```python
df_model["label"] = model.predict(X)
```
추론한 결과를 label에 담습니다.

---
이상치만 필터링
```python
df_model["is_anomaly"] = df_model["label"] == -1
```
label 컬럼이 -1인 행은 True, 아니면 False로 해서  is_anomaly 컬럼에 저장합니다.

|값|의미|
|---|---|
|1|정상|
|-1|이상|
IsolationForest는 이상치를 -1로 표시합니다.

---
```python
anomalies = df_model[df_model["is_anomaly"]]
```
is_anomaly가 True인 행들만 골라서  anomalies라는 새로운 데이터프레임에 저장합니다.

---
```python
print("탐지된 이상치 개수:", len(anomalies))
print(anomalies[["timestamp", "value"]].head(10))
```

결과
![[Pasted image 20260303210601.png]]
전체 데이터 중 **6개가 이상치로 판정**되었습니다.

✔ 알람 후보 6개 발생  
✔ 해당 시점 관리자 통보 가능  
✔ 로그 기록 가능  
✔ 이상 구간 분석 가능

모델이 총 6개의 시점을 이상치로 판단했으며,  
대부분 인위적으로 삽입한 스파이크를 정확히 탐지했습니다.

---
`5) 시각화 — 이상치 확인 (실무에서 매우 중요)`
`(1) 전체 시계열`
```python
px.line(df, x="timestamp", y="value", title="Sensor Data").show()
```

![[Pasted image 20260303210734.png]]

🟢 `10:00 ~ 10:02` : 값이 약 100 근처에서 작은 진동, 값이 약 100 근처에서 작은 진동
👉 정상 상태  
👉 안정적인 구간

🔴`10:02 부근` :  이건 의도적으로 넣은 이상치입니다.
- 위로 크게 튐 (약 113)
- 바로 아래로 크게 떨어짐 (약 85)
👉 강한 스파이크 구간  
👉 급격한 상승 + 급격한 하락  
👉 이상 탐지 모델이 잡은 120, 121 인덱스

🔴 1`0:04 부근` : 또 한 번 위로 크게 튀는 구간 (약 117)
👉 또 다른 스파이크  
👉 모델이 잡은 260번 인덱스

🟡 `10:06 이후` : 이건 단순 스파이크가 아니라 정상 기준 자체가 올라간 구간입니다
- 전체 평균이 약간 상승한 상태로 유지됨
- 105~108 근처에서 계속 움직임

`(2) 이상치 포인트만 표시`
```python
px.scatter(
    anomalies,
    x="timestamp",
    y="value",
    title="Isolation Forest Detected Anomalies"
).show()
```

결과
![[Pasted image 20260303211031.png]]

시간대별로 총 6개의 점이 있습니다.

대략:
- 🔴 10:02 부근 → 2개
- 🔴 10:04 부근 → 2개
- 🔴 10:06:40 → 1개
- 🔴 10:08:40 → 1개
    
이건 이전에 출력된 6개와 정확히 일치합니다.