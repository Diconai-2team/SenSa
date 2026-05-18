"""
ml_engine/model_store.py — AI 모델 영속성 (서버 재시작 후 즉시 복원)

저장 경로: ml_engine/saved_models/
  if_models.pkl   — IsolationForest 학습 완료 모델 딕셔너리
  arima_cache.pkl — ARIMA 학습 완료 모델 딕셔너리
  cusum_state.json — CUSUM 기준값 (mu, sigma) 딕셔너리

설계:
  - 모델 학습 완료 직후 비동기로 저장 (lock 밖에서 호출)
  - 저장 실패는 경고 로그만 (메인 흐름 블로킹 금지)
  - 로드는 앱 시작 시 1회 (apps.py ready())
"""
import json
import logging
import os
import pickle
import threading

logger = logging.getLogger(__name__)

STORE_DIR = os.path.join(os.path.dirname(__file__), 'saved_models')
_io_lock = threading.Lock()


def _path(name: str, ext: str) -> str:
    return os.path.join(STORE_DIR, f"{name}.{ext}")


# ── Pickle ────────────────────────────────────────────────

def save_pickle(name: str, obj) -> None:
    os.makedirs(STORE_DIR, exist_ok=True)
    try:
        with _io_lock:
            with open(_path(name, 'pkl'), 'wb') as f:
                pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        logger.warning("[model_store] pickle save failed (%s): %s", name, e)


def load_pickle(name: str):
    p = _path(name, 'pkl')
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning("[model_store] pickle load failed (%s): %s", name, e)
        return None


# ── JSON ──────────────────────────────────────────────────

def save_json(name: str, data) -> None:
    os.makedirs(STORE_DIR, exist_ok=True)
    try:
        with _io_lock:
            with open(_path(name, 'json'), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("[model_store] json save failed (%s): %s", name, e)


def load_json(name: str):
    p = _path(name, 'json')
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[model_store] json load failed (%s): %s", name, e)
        return None
