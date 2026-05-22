"""
ml_engine/model_store.py — AI 모델 영속성 (서버 재시작 후 즉시 복원)

저장 경로: ml_engine/saved_models/
  if_models.pkl    — IsolationForest 학습 완료 모델 딕셔너리
  arima_cache.pkl  — ARIMA 학습 완료 모델 딕셔너리
  cusum_state.json — CUSUM 기준값 (mu, sigma) 딕셔너리

설계:
  - 모델 학습 완료 직후 비동기로 저장 (lock 밖에서 호출)
  - 저장 실패는 경고 로그만 (메인 흐름 블로킹 금지)
  - 로드는 앱 시작 시 1회 (apps.py ready())

Atomic Write (pkl / json 공통):
  직접 목적 파일에 쓰면 서버 비정상 종료 시 절반만 기록된 파일이 남음.
  → tmp 파일에 먼저 완전히 쓴 뒤 os.replace() 로 원자적 교체.
  os.replace() 는 POSIX rename() 래퍼 — 같은 파일시스템 내에서 원자적 보장.
  실패 시 tmp 파일 정리 후 경고 로그만 기록 (메인 흐름 블로킹 금지).
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


def _tmp_path(name: str, ext: str) -> str:
    return os.path.join(STORE_DIR, f"{name}.{ext}.tmp")


# ── Pickle ────────────────────────────────────────────────

def save_pickle(name: str, obj) -> None:
    """
    Atomic pickle 저장.

    tmp 파일에 완전히 기록한 뒤 os.replace() 로 원자적 교체.
    중간에 프로세스가 죽어도 기존 .pkl 은 손상되지 않음.
    """
    os.makedirs(STORE_DIR, exist_ok=True)
    dest = _path(name, 'pkl')
    tmp  = _tmp_path(name, 'pkl')
    try:
        with _io_lock:
            with open(tmp, 'wb') as f:
                pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
                f.flush()
                os.fsync(f.fileno())   # OS 버퍼 → 디스크 플러시
            os.replace(tmp, dest)      # 원자적 교체 (POSIX rename)
    except Exception as e:
        logger.warning("[model_store] pickle save failed (%s): %s", name, e)
        try:
            os.unlink(tmp)
        except OSError:
            pass


def load_pickle(name: str):
    """
    pickle 로드. 파일이 없거나 손상된 경우 None 반환 후 손상 파일 자동 제거.
    """
    p = _path(name, 'pkl')
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning("[model_store] pickle load failed (%s): %s — 손상 파일 삭제 후 재학습 시작", name, e)
        # 손상된 파일 자동 제거 → 다음 학습 주기에 정상 파일로 재생성
        try:
            os.unlink(p)
        except OSError:
            pass
        return None


# ── JSON ──────────────────────────────────────────────────

def save_json(name: str, data) -> None:
    """
    Atomic JSON 저장.

    tmp 파일에 완전히 기록한 뒤 os.replace() 로 원자적 교체.
    """
    os.makedirs(STORE_DIR, exist_ok=True)
    dest = _path(name, 'json')
    tmp  = _tmp_path(name, 'json')
    try:
        with _io_lock:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
    except Exception as e:
        logger.warning("[model_store] json save failed (%s): %s", name, e)
        try:
            os.unlink(tmp)
        except OSError:
            pass


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
