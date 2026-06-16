STEP 4의 목적
데이터의 흐름이 예전과 달라지기 시작한 시점을 찾는 단계입니다.

즉,
✔ 순간적인 이상을 찾는 것이 아니라  
✔ 상태 변화가 시작된 지점을 찾는 것입니다.

---
🔹 이전 단계와 가장 큰 차이

STEP 1 / STEP 2 / STEP 3의 공통점:
이전 단계들은 모두 이런 질문을 합니다:

> 지금 이 숫자가 정상인가? 이상인가?

즉, 개별 데이터 하나하나를 판단합니다.

---
STEP 4는 다릅니다
STEP 4는 이런 질문을 합니다:

> 지금 데이터 흐름이 예전과 달라졌는가?

즉,  
하나의 숫자가 아니라  
전체 패턴 변화를 보는 단계입니다.

---
🔹 쉽게 예를 들어보겠습니다

이전 방식이 잘 잡는 것
✔ 갑자기 100 → 130으로 튀는 값  
✔ 갑자기 -20으로 급하락하는 값  
✔ 단발성 이상 신호

이런 것은 STEP 2나 STEP 3이 잘 잡습니다.

---
하지만 이런 경우는 놓칠 수 있습니다
✔ 평균이 100 → 101 → 102 → 103… 서서히 상승  
✔ 노이즈가 점점 커짐  
✔ 예전의 안정적인 패턴이 무너짐

이 경우는 숫자가 크게 튀지 않기 때문에  
Z-score나 Isolation Forest가 바로 감지하지 못할 수도 있습니다.

---
🔹 STEP 4의 핵심 아이디어
STEP 4는 과거 구간과 최근 구간을 비교합니다.

질문 형태로 보면:
✔ 예전 평균과 지금 평균이 같은가?  
✔ 예전 흔들림과 지금 흔들림이 같은가?  
✔ 패턴이 바뀌었는가?

즉,
> 상태가 변했는지를 보는 것입니다.

---
🔹 이 코드는 실제로 무엇을 하나요?

아주 직관적으로 설명하면:
1️⃣ 데이터를 두 구간으로 나눕니다.
- 과거 구간
- 최근 구간
    
2️⃣ 두 구간의 평균을 비교합니다.
3️⃣ 두 구간의 변동성(표준편차)을 비교합니다.
4️⃣ 차이가 크면  
→ 상태가 바뀌었다고 판단합니다.

---
🔹 예시로 이해해보겠습니다

예전 구간
평균: 100  
표준편차: 1

---
최근 구간
평균: 105  
표준편차: 4

이 경우,
✔ 값은 크게 튀지 않았을 수도 있지만  
✔ 시스템 상태가 분명히 변했습니다.

이것이 STEP 4가 잡으려는 문제입니다.

---
🔹 왜 이런 비교가 중요한가요?

현실에서는 이런 상황이 더 위험합니다.
✔ 문제가 갑자기 폭발하는 경우보다  
✔ 서서히 망가지는 경우가 더 많기 때문입니다.

예를 들어:
- 기계가 점점 마모됨
- 서버 부하가 점점 증가함
- 네트워크 지연이 점점 커짐
    
이때 중요한 것은:

> 문제가 언제부터 시작되었는지를 아는 것입니다.

STEP 4는 바로 그 지점을 찾는 역할을 합니다.

---
🔹 한 문장으로 정리하면

STEP 4는

> 순간적인 이상값을 찾는 단계가 아니라,  
> 데이터 흐름이 예전과 달라진 시점을 감지하는 단계입니다.

---
### Change Point 패턴 뼈대코드 (급변/상태전이)
```python
# ============================================
# [STEP 4 Skeleton] Change Point(급변/상태전이) 탐지 패턴
# - 목표: "언제부터 상태가 바뀌었는지" (고장 시작 시점, 패턴 붕괴 시작점)
# - 접근: 최근 구간(window)의 평균/분산이 "이전 구간"과 크게 달라졌는지 감지
# ============================================

import numpy as np
import pandas as pd

# -------------------------------------------------
# 0) 데이터 준비
#    - df: columns = ["timestamp", "value"]
# -------------------------------------------------
df = df.sort_values("timestamp").reset_index(drop=True)

# -------------------------------------------------
# 1) Change Point 탐지 설정
# -------------------------------------------------
W = 30                 # 비교 구간 길이(최근 30개 vs 이전 30개)
MEAN_K = 3.0           # 평균 변화 감지 민감도(표준편차 대비 몇 배?)
STD_K  = 3.0           # 분산(표준편차) 변화 감지 민감도
EPS = 1e-9

# -------------------------------------------------
# 2) 상태 머신(전이 감지) 준비
# -------------------------------------------------
state = "STABLE"       # "STABLE"(정상) / "SHIFT"(변화 감지)
events = []            # 변화 시점 로그

# -------------------------------------------------
# 3) 슬라이딩으로 "이전 구간" vs "최근 구간" 비교
# -------------------------------------------------
# i 시점에서:
#   prev = [i-2W : i-W)
#   curr = [i-W  : i)
for i in range(2 * W, len(df) + 1):
    prev = df["value"].iloc[i - 2*W : i - W]
    curr = df["value"].iloc[i - W   : i]

    prev_mean, prev_std = float(prev.mean()), float(prev.std(ddof=0))
    curr_mean, curr_std = float(curr.mean()), float(curr.std(ddof=0))

    # 평균 변화량(표준편차로 정규화)
    mean_shift_score = abs(curr_mean - prev_mean) / (prev_std + EPS)

    # 분산 변화량(표준편차의 비율로 비교)
    std_ratio = (curr_std + EPS) / (prev_std + EPS)

    is_change = (mean_shift_score >= MEAN_K) or (std_ratio >= STD_K) or (std_ratio <= 1/STD_K)

    # -------------------------------------------------
    # 4) 상태 변화 감지 (STABLE ↔ SHIFT)
    # -------------------------------------------------
    t = df["timestamp"].iloc[i - 1]
    if state == "STABLE" and is_change:
        state = "SHIFT"
        events.append({"timestamp": t, "event": "CHANGE_POINT", "mean_shift_score": mean_shift_score, "std_ratio": std_ratio})

    elif state == "SHIFT" and (not is_change):
        state = "STABLE"
        events.append({"timestamp": t, "event": "BACK_TO_STABLE", "mean_shift_score": mean_shift_score, "std_ratio": std_ratio})

# -------------------------------------------------
# 5) 결과 확인
# -------------------------------------------------
events_df = pd.DataFrame(events)
print(events_df.head(20))
```
---
`라이브러리 불러오기`
```python
import numpy as np
import pandas as pd
```
데이터 계산과 데이터 처리를 위해 필요한 외부 도구들을 불러오는 단계입니다.

`0) 데이터 준비`
```python
df = df.sort_values("timestamp").reset_index(drop=True)
```
데이터를 시간 순서대로 정렬하고, 인덱스를 다시 깔끔하게 정리하는 단계로 뒤죽박죽일 수 있는 데이터를 올바른 순서로 재배치하는 과정입니다.

---
`1) Change Point 탐지 설정`
```python
W = 30                 # 비교 구간 길이(최근 30개 vs 이전 30개)
MEAN_K = 3.0           # 평균 변화 감지 민감도(표준편차 대비 몇 배?)
STD_K  = 3.0           # 분산(표준편차) 변화 감지 민감도
EPS = 1e-9
```
변화 탐지를 어떤 기준과 민감도로 수행할 것인지 규칙을 정하는 단계로 언제 상태가 바뀌었다고 판단할지 기준선을 설정하는 과정입니다.
즉, 모델 계산 전에
✔ 비교 방식  
✔ 감지 기준  
✔ 민감도 수준을 미리 정의하는 단계입니다.

---
`2) 상태 머신(전이 감지) 준비`
```python
state = "STABLE"       # "STABLE"(정상) / "SHIFT"(변화 감지)
events = []            # 변화 시점 로그
```
데이터 상태를 추적하고 변화 발생 시점을 기록하기 위한 준비 단계로  현재 시스템이 정상 상태인지 변화 상태인지 구분하기 위한 기준을 세우는 과정입니다.
즉, 단순 계산이 아니라
✔ 상태 개념 도입  
✔ 변화 흐름 추적  
✔ 이벤트 기록 구조 생성이 목적의 단계입니다.

---
`3) 슬라이딩으로 "이전 구간" vs "최근 구간" 비교`
```python
for i in range(2 * W, len(df) + 1):
```
데이터의 앞부분(초기 구간)은 건너뛰고, ‘이전 구간’과 ‘최근 구간’을 둘 다 만들 수 있는 시점부터 끝까지 한 칸씩 이동하면서 반복 검사하겠다는 뜻으로 이전 30개 + 최근 30개(총 60개)가 쌓인 시점부터, 한 단계씩 밀어가며 계속 비교하는 과정입니다.


```python
    prev = df["value"].iloc[i - 2*W : i - W]
```
현재 시점 i를 기준으로, 최근 구간 바로 이전에 있었던 과거 데이터 묶음을 가져옵니다. 좀더 쉽게 설명하면 비교 기준이 되는 ‘이전 상태 구간’을 선택하는 단계입니다.
핵심 맥락:
- 최근 데이터를 보기 전에
- 먼저 과거 기준 구간을 만드는 과정
    
즉, 예전 상태를 대표하는 데이터 구간을 추출합니다.


```python
    curr = df["value"].iloc[i - W   : i]
```
현재 시점 i 바로 직전까지의 최신 데이터 묶음을 가져옵니다. 쉽게 말해 지금 상태를 대표하는 ‘최근 구간’을 선택하는 단계입니다. 
핵심 맥락:
- 방금 만든 과거 구간(prev)과
- 이제 최신 구간(curr)을 비교하기 위한 준비
즉, 현재 상태를 대표하는 데이터 구간을 추출합니다.


```python
    prev_mean, prev_std = float(prev.mean()), float(prev.std(ddof=0))
```
이전 구간(prev)의 평균과 데이터 흔들림 크기(표준편차)를 계산합니다. 조금 더 쉽게 말하면
과거 상태의 대표적인 값 수준과 변동성을 요약하는 단계입니다.
✔ 이전 상태가 어떤 특징을 갖는지 수치로 정리  
✔ 비교 기준을 만드는 과정
즉, 예전 데이터의 상태 기준값을 계산합니다.


```python
    curr_mean, curr_std = float(curr.mean()), float(curr.std(ddof=0))
```
최근 구간(curr)의 평균과 데이터 흔들림 크기(표준편차)를 계산합니다. 쉽게 설명하면 현재 상태의 값 수준과 변동성을 요약하는 단계입니다.
✔ 지금 데이터가 어떤 상태인지 수치로 표현  
✔ 이전 구간과 비교하기 위한 준비
즉, 현재 데이터의 상태 기준값을 계산합니다.


평균 변화량(표준편차로 정규화)
```python
    mean_shift_score = abs(curr_mean - prev_mean) / (prev_std + EPS)
```
최근 구간의 평균이 이전 구간의 평균과 얼마나 달라졌는지를 계산합니다. 쉽게 설명하면 지금 상태의 값 수준이 예전 상태에 비해 얼마나 이동했는지를 수치로 측정하는 단계입니다

왜 표준편차로 나눌까?
✔ 단순한 평균 차이를 보는 것이 아니라  
✔ 이전 구간의 변동성 기준으로 변화 크기를 평가
즉,
- 평균 차이가 커 보여도
- 원래 데이터 흔들림이 큰 구간이면 큰 변화가 아닐 수 있음
    
그래서 데이터 특성을 고려한 상대적 변화 크기 계산입니다.


분산 변화량(표준편차의 비율로 비교)
```python
    std_ratio = (curr_std + EPS) / (prev_std + EPS)
```
최근 구간의 데이터 흔들림 크기가 이전 구간에 비해 얼마나 달라졌는지를 계산합니다.
즉, 현재 데이터의 변동성이 과거 상태와 비교해 얼마나 커졌거나 작아졌는지를 측정하는 단계입니다
✔ 평균이 아닌 ‘흔들림 수준’ 비교하고 
✔ 데이터 안정성 변화 감지 목적
즉, 상태 불안정 여부를 판단하기 위한 지표 계산입니다.

직관적으로 보면:
- 값이 크다 → 흔들림 증가 (노이즈 증가 / 불안정 가능)
- 값이 작다 → 흔들림 감소 (패턴 변화 / 센서 고정 가능)


```python
    is_change = (mean_shift_score >= MEAN_K) or (std_ratio >= STD_K) or (std_ratio <= 1/STD_K)
```
평균 변화 또는 변동성 변화가 기준 이상이면 상태 변화로 판단합니다. 아주 쉽게 말하면 
변화 감지 규칙을 적용하여 현재 시점이 변화 구간인지 결정하는 단계입니다.
✔ 평균 변화 검사  
✔ 분산(흔들림) 변화 검사  
✔ 둘 중 하나라도 크면 변화 인정
즉, 상태 전이 여부를 최종 판단하는 조건식입니다.

---
이번 구간은 STEP 4(Change Point)에서 가장 실무적인 핵심 로직입니다.

`4) 상태 변화 감지 (STABLE ↔ SHIFT)`
```python
t = df["timestamp"].iloc[i - 1]
```
현재 검사 중인 시점의 시간 정보를 가져옵니다. 즉, 지금 판단이 발생한 정확한 시간 위치를 기억하는 단계입니다.
✔ 변화가 언제 발생했는지 기록하기 위한 준비  
✔ 로그 / 이벤트 저장의 기준 시점 확보


변화 감지 조건 구간
```python
    if state == "STABLE" and is_change:
        state = "SHIFT"
        events.append({"timestamp": t, "event": "CHANGE_POINT", "mean_shift_score": mean_shift_score, "std_ratio": std_ratio})
```
현재 정상 상태인데 변화 조건이 감지되었는지 확인합니다 다시 말해서 정상 → 변화 상태로 전환해야 하는 순간인지 검사하는 단계입니다.


```python
   state == "SHIFT"
```
현재 상태를 변화 감지 상태로 변경합니다. 쉽게 표현하면 이 시점부터 시스템 상태가 달라졌다고 선언하는 단계입니다.

```python
   events.append({...})
```
변화가 발생한 시점을 기록 목록에 저장합니다.
✔ 변화 시작 시점 로그  
✔ 나중에 분석 / 알람 / 시각화 가능
즉, 상태 전이 이벤트 기록 단계입니다

정상 복귀 조건 구간
```python
elif state == "SHIFT" and (not is_change):
```
현재 변화 상태인데 더 이상 변화 조건이 없는지 확인합니다. 쉽게 말하면 변화 상태 → 정상 상태로 돌아갈 시점인지 검사하는 단계입니다.

```python
state = "STABLE"
```
시스템 상태를 다시 정상 상태로 변경합니다. 즉 불안정 구간이 종료되었음을 선언하는 단계입니다.

```python
   events.append({...})
```
정상 복귀 시점을 기록 목록에 저장합니다. 
✔ 변화 구간 종료 로그  
✔ 상태 변화 이력 완성

전체적으로 해석하면 
재 시점의 시간을 가져오고, 정상 상태에서 변화가 감지되면 상태를 변경하고 기록하며, 변화 상태에서 안정되면 다시 정상 상태로 복귀하고 기록합니다.

이 부분이 하는 가장 중요한 역할은
✔ 변화가 발생했는지 여부만 판단하는 것이 아니라  
✔ 언제 상태가 바뀌었는지 기록
즉, 관제 시스템에서 가장 중요한 이벤트 기록 로직입니다.

---
`5) 결과 확인`
```python
events_df = pd.DataFrame(events)
print(events_df.head(20))
```
기록해 둔 상태 변화 정보들을 표 형태 데이터로 정리하는 단계입니다. 쉽게 설명하면 변화 시점 로그 목록을 사람이 보기 쉬운 구조로 변환하는 과정입니다.
✔ 리스트 형태 기록 → 표 구조 변환  
✔ 분석 / 확인 / 시각화 가능 상태로 정리
즉, 결과 데이터를 해석 가능한 형태로 만드는 단계입니다.

그런후 앞쪽의 20번째줄까지의 데이터를 확인합니다.

---
### 실무를 위한 연습 전체코드
```python
# ============================================
# [STEP 4 전체코드] Change Point(급변/상태전이) 탐지 실무 예시
# - 센서 값이 "어느 시점부터" 평균이 바뀌거나(고장 시작)
#   변동성이 커지는(패턴 붕괴) 상황을 감지
# - 실무에서 흔한 "두 윈도우 비교(two-window)" 방식
# ============================================

import numpy as np
import pandas as pd
import plotly.express as px

# -------------------------------------------------
# 0) 데이터 준비 (실습용 센서 데이터 생성)
#    - 앞의 STEP들과 동일하게, 1초 간격 센서 데이터라고 가정
# -------------------------------------------------
np.random.seed(42)

n = 600
timestamps = pd.date_range("2026-02-11 10:00:00", periods=n, freq="s")

# 정상 구간: 평균 100, 작은 노이즈
values = 100 + np.random.normal(0, 1.2, size=n)

# (A) 스파이크 몇 개 (단발성 이상)
spike_idx = [120, 121, 260, 520]
values[spike_idx] += [12, -14, 18, 15]

# (B) 상태 전이(고장 시작) 시뮬레이션
# 예: 360초부터 평균이 100 -> 106으로 올라가며, 변동성도 커짐(패턴 붕괴)
shift_start = 360
values[shift_start:] = 106 + np.random.normal(0, 2.0, size=n - shift_start)

df = pd.DataFrame({"timestamp": timestamps, "value": values})
df = df.sort_values("timestamp").reset_index(drop=True)

px.line(df, x="timestamp", y="value", title="Sensor Stream (with change point)").show()


# -------------------------------------------------
# 1) Change Point 탐지 설정
#    - W: 이전 구간 vs 최근 구간 비교 길이
#    - MEAN_K: 평균 변화 감지 민감도 (표준편차 대비 몇 배 차이면 변화로 볼지)
#    - STD_K:  변동성(표준편차) 변화 감지 민감도 (비율로 비교)
# -------------------------------------------------
W = 30
MEAN_K = 3.0
STD_K = 2.0   # 분산 변화는 보통 2배만 커져도 의미가 있어 2.0부터 보는 경우가 많음
EPS = 1e-9


# -------------------------------------------------
# 2) 상태 머신(전이 감지) 준비
#    - STABLE: 정상 구간
#    - SHIFT : 변화 구간(상태 전이/패턴 붕괴 의심)
# -------------------------------------------------
state = "STABLE"
events = []
rows = []  # 각 시점의 점수 기록(그래프/분석용)


# -------------------------------------------------
# 3) 슬라이딩으로 "이전 구간" vs "최근 구간" 비교(two-window)
#    i 시점 기준:
#      prev = [i-2W : i-W)
#      curr = [i-W  : i)
# -------------------------------------------------
for i in range(2 * W, len(df) + 1):
    prev = df["value"].iloc[i - 2*W : i - W]
    curr = df["value"].iloc[i - W   : i]

    prev_mean = float(prev.mean())
    prev_std  = float(prev.std(ddof=0))
    curr_mean = float(curr.mean())
    curr_std  = float(curr.std(ddof=0))

    # 평균 변화 점수: "이전 표준편차 기준으로 평균이 얼마나 이동했나?"
    mean_shift_score = abs(curr_mean - prev_mean) / (prev_std + EPS)

    # 표준편차 비율: 변동성이 얼마나 변했나? (2배↑면 위험)
    std_ratio = (curr_std + EPS) / (prev_std + EPS)

    # 변화 감지 규칙:
    # - 평균이 크게 이동했거나
    # - 변동성이 갑자기 커지거나/작아지면(센서 고정/고장 등)
    is_change = (mean_shift_score >= MEAN_K) or (std_ratio >= STD_K) or (std_ratio <= 1/STD_K)

    t = df["timestamp"].iloc[i - 1]
    x = float(df["value"].iloc[i - 1])

    # -------------------------------------------------
    # 4) 상태 변화 감지 (STABLE ↔ SHIFT)
    #    - 관제에서 중요한 건 "변화 자체"뿐 아니라
    #      "언제 시작했는지(CHANGE_POINT)" 기록하는 것
    # -------------------------------------------------
    if state == "STABLE" and is_change:
        state = "SHIFT"
        events.append({
            "timestamp": t,
            "event": "CHANGE_POINT",
            "value": x,
            "mean_shift_score": mean_shift_score,
            "std_ratio": std_ratio
        })

    elif state == "SHIFT" and (not is_change):
        state = "STABLE"
        events.append({
            "timestamp": t,
            "event": "BACK_TO_STABLE",
            "value": x,
            "mean_shift_score": mean_shift_score,
            "std_ratio": std_ratio
        })

    # 각 시점 점수/상태 저장
    rows.append({
        "timestamp": t,
        "value": x,
        "prev_mean": prev_mean,
        "curr_mean": curr_mean,
        "prev_std": prev_std,
        "curr_std": curr_std,
        "mean_shift_score": mean_shift_score,
        "std_ratio": std_ratio,
        "is_change": bool(is_change),
        "state": state
    })


# -------------------------------------------------
# 5) 결과 확인
#    - events_df: 상태 전이 시점 로그(고장 시작 시점 후보)
#    - score_df : 매 시점 점수/상태 (그래프 확인용)
# -------------------------------------------------
events_df = pd.DataFrame(events)
score_df = pd.DataFrame(rows)

print("상태 전이 이벤트(앞부분):")
print(events_df.head(20))

# CHANGE_POINT만 모아서 보기
cp = events_df[events_df["event"] == "CHANGE_POINT"].copy()
print("\nCHANGE_POINT 후보 개수:", len(cp))

# -------------------------------------------------
# (선택) 시각화 1) mean_shift_score / std_ratio 추이
# -------------------------------------------------
px.line(score_df, x="timestamp", y="mean_shift_score", title="Mean shift score").show()
px.line(score_df, x="timestamp", y="std_ratio", title="Std ratio").show()

# -------------------------------------------------
# (선택) 시각화 2) CHANGE_POINT 지점을 센서 값 위에 표시
# -------------------------------------------------
if len(cp) > 0:
    px.scatter(cp, x="timestamp", y="value", title="Detected CHANGE_POINT on sensor value").show()
```
---
### 직접 해석해보기

모듈 불러오기
```python
import numpy as np
import pandas as pd
import plotly.express as px
```


`0) 데이터 준비 (실습용 센서 데이터 생성)`
```python
np.random.seed(42)
```


```python
n = 600
timestamps = pd.date_range("2026-02-11 10:00:00", periods=n, freq="S")
```


`정상 구간: 평균 100, 작은 노이즈`
```python
values = 100 + np.random.normal(0, 1.2, size=n)
```


`(A) 스파이크 몇 개 (단발성 이상)`
```python
spike_idx = [120, 121, 260, 520]
values[spike_idx] += [12, -14, 18, 15]
```


`(B) 상태 전이(고장 시작) 시뮬레이션`
```python
shift_start = 360
values[shift_start:] = 106 + np.random.normal(0, 2.0, size=n - shift_start)
```


```python
df = pd.DataFrame({"timestamp": timestamps, "value": values})
df = df.sort_values("timestamp").reset_index(drop=True)
```


```python
px.line(df, x="timestamp", y="value", title="Sensor Stream (with change point)").show()
```


`1) Change Point 탐지 설정`
```python
W = 30
MEAN_K = 3.0
STD_K = 2.0   # 분산 변화는 보통 2배만 커져도 의미가 있어 2.0부터 보는 경우가 많음
EPS = 1e-9
```


`2) 상태 머신(전이 감지) 준비`
```python
state = "STABLE"
events = []
rows = []  # 각 시점의 점수 기록(그래프/분석용)

```


`3) 슬라이딩으로 "이전 구간" vs "최근 구간" 비교(two-window)`
```python
for i in range(2 * W, len(df) + 1):
```


```python
    prev = df["value"].iloc[i - 2*W : i - W]
    curr = df["value"].iloc[i - W   : i]

    prev_mean = float(prev.mean())
    prev_std  = float(prev.std(ddof=0))
    curr_mean = float(curr.mean())
    curr_std  = float(curr.std(ddof=0))
```


`평균 변화 점수: "이전 표준편차 기준으로 평균이 얼마나 이동했나?"`
```python
    mean_shift_score = abs(curr_mean - prev_mean) / (prev_std + EPS)
```


`표준편차 비율: 변동성이 얼마나 변했나? (2배↑면 위험)`
```python
    std_ratio = (curr_std + EPS) / (prev_std + EPS)
```


```python
    is_change = (mean_shift_score >= MEAN_K) or (std_ratio >= STD_K) or (std_ratio <= 1/STD_K)
```


```python
    t = df["timestamp"].iloc[i - 1]
    x = float(df["value"].iloc[i - 1])
```


`4) 상태 변화 감지 (STABLE ↔ SHIFT)`
```python
    if state == "STABLE" and is_change:
        state = "SHIFT"
        events.append({
            "timestamp": t,
            "event": "CHANGE_POINT",
            "value": x,
            "mean_shift_score": mean_shift_score,
            "std_ratio": std_ratio
        })
```


```python
    elif state == "SHIFT" and (not is_change):
        state = "STABLE"
        events.append({
            "timestamp": t,
            "event": "BACK_TO_STABLE",
            "value": x,
            "mean_shift_score": mean_shift_score,
            "std_ratio": std_ratio
        })
```


`각 시점 점수/상태 저장`
```python
    rows.append({
        "timestamp": t,
        "value": x,
        "prev_mean": prev_mean,
        "curr_mean": curr_mean,
        "prev_std": prev_std,
        "curr_std": curr_std,
        "mean_shift_score": mean_shift_score,
        "std_ratio": std_ratio,
        "is_change": bool(is_change),
        "state": state
    })
```


`5) 결과 확인`
```python
events_df = pd.DataFrame(events)
score_df = pd.DataFrame(rows)
```


```python
print("상태 전이 이벤트(앞부분):")
print(events_df.head(20))
```


`CHANGE_POINT만 모아서 보기`
```python
cp = events_df[events_df["event"] == "CHANGE_POINT"].copy()
print("\nCHANGE_POINT 후보 개수:", len(cp))
```


`(선택) 시각화 1) mean_shift_score / std_ratio 추이`
```python
px.line(score_df, x="timestamp", y="mean_shift_score", title="Mean shift score").show()
px.line(score_df, x="timestamp", y="std_ratio", title="Std ratio").show()
```


`(선택) 시각화 2) CHANGE_POINT 지점을 센서 값 위에 표시`
```python
if len(cp) > 0:
    px.scatter(cp, x="timestamp", y="value", title="Detected CHANGE_POINT on sensor value").show()
```


---
실무에서는 보통 이렇게 진행합니다.

1️⃣ 가장 단순한 구조부터 시작
처음에는 보통 STEP 2 수준으로 시작합니다.

예:
데이터 수집  
→ Rolling Mean  
→ Z-score  
→ 알람

이유:
- 빠름
- 가벼움
- 설명 쉬움
- 유지보수 쉬움

2️⃣ 한계가 생기면 확장
문제가 생기면 추가합니다.

예:
- 다변량 구조가 복잡하다
- 단순 임계치로 못 잡는다
- 오탐/미탐이 많다
    
이때 STEP 3(ML)을 붙입니다.

3️⃣ 실제 관제 플랫폼 구조는 이런 느낌입니다

```
[데이터 수집]  
      ↓  
[전처리]  
      ↓  
[1차 필터 (통계 기반)]  
      ↓  
[2차 필터 (ML 기반)]  
      ↓  
[알람 엔진]  
      ↓  
[로그 저장 / 시각화]
```

즉, 여러 탐지 모듈을 조합하는 구조입니다.

---

🔹 그럼 처음부터 ML로 만들지 않나요?

대부분 아닙니다.

이유는:
✔ 통계 기반이 빠르고 안정적임  
✔ ML은 계산 비용 있음  
✔ ML은 튜닝 필요  
✔ ML은 해석 어려움

그래서 실무에서는 보통 간단한 방법 → 안 되면 복잡한 방법 순서로 갑니다.

---
🔹 중요한 개념: 레이어 구조

관제 시스템은 보통 레이어 구조입니다.

예시
- 1차: Threshold (즉시 위험 감지)
- 2차: Z-score (통계 기반)
- 3차: Isolation Forest (패턴 기반)
- 4차: 예측 기반 (ARIMA, LSTM 등)

이걸 전부 순서대로 쓰는 게 아니라, 필요한 만큼만 붙입니다.

---
🔹 정리하면

학습에서는 STEP1 → STEP2 → STEP3 이렇게 배우지만
실무에서는 문제에 맞게 필요한 모듈을 조합하는 방식으로 설계합니다.

---
🔹 아주 쉽게 비유하면

이건 건물을 짓는 것과 같습니다.
- STEP1 = 벽돌
- STEP2 = 철근
- STEP3 = 철골 구조
- STEP4 = 스마트 센서
    
항상 다 쓰는 게 아니라 건물 용도에 맞게 필요한 것만 사용합니다.

---
🔹 가장 중요한 실무 감각

관제 플랫폼은
- 단계 순서대로 만드는 프로젝트가 아니라  
- 탐지 모듈을 점점 확장하는 시스템입니다.