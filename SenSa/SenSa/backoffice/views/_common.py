"""
backoffice/views/_common.py — 모든 뷰 모듈이 공유하는 헬퍼.

분리 이력 (Phase 2):
  원래 backoffice/views.py 상단에 박혀있던 두 헬퍼를 분리.
  다른 뷰 모듈은 `from ._common import _parse_json, _form_errors_payload` 로 사용.
"""
import json


def _parse_json(request) -> dict:
    """request.body 에서 JSON 디코드. 실패 시 빈 dict."""
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _form_errors_payload(form) -> dict:
    """form.errors → 프런트가 필드별로 표시하기 좋은 형태로 변환."""
    return {
        field: [str(err) for err in errs]
        for field, errs in form.errors.items()
    }
