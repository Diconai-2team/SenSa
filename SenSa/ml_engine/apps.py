from django.apps import AppConfig


class MlEngineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ml_engine'
    verbose_name = 'ML Engine'

    def ready(self):
        # 저장된 ML 모델 복원 (서버 재시작 후 즉시 복원)
        try:
            import logging
            _log = logging.getLogger(__name__)
            from ml_engine import model_store, isolation_forest, cusum_detector, arima_forecaster

            if_data = model_store.load_pickle('if_models')
            if isinstance(if_data, dict) and if_data:
                # 1) 구 버전 모델 폐기: 특징 차원이 다른 모델을 로드하면
                #    predict() 에서 "X has N features, expected M" ValueError 발생.
                current_ver = isolation_forest.MODEL_VERSION
                valid = {
                    k: v for k, v in if_data.items()
                    if v.get("version", 1) == current_ver
                }
                stale = len(if_data) - len(valid)
                if stale:
                    _log.warning(
                        "[ml_engine] IF 구 버전 모델 %d개 폐기 (v%d → 재학습 예정)",
                        stale, current_ver,
                    )

                # 2) 테스트/개발 잔재 모델 정리: _is_test_device 기준으로 필터
                before_count = len(valid)
                valid = {
                    k: v for k, v in valid.items()
                    if not isolation_forest._is_test_device(k.split(':')[0])
                }
                purged = before_count - len(valid)
                if purged:
                    _log.info(
                        "[ml_engine] IF 테스트 잔재 모델 %d개 정리 (pkl 갱신)",
                        purged,
                    )
                    # 정리된 상태를 pkl 에 즉시 반영 → 재시작 시 깨끗한 상태 유지
                    model_store.save_pickle('if_models', valid)

                if valid:
                    isolation_forest._models.update(valid)
                _log.info(
                    "[ml_engine] IF 모델 %d개 복원 (버전폐기 %d개, 테스트정리 %d개)",
                    len(valid), stale, purged,
                )

            cusum_data = model_store.load_json('cusum_state')
            if isinstance(cusum_data, dict) and cusum_data:
                cusum_detector._state.update(cusum_data)
                _log.info("[ml_engine] CUSUM 상태 %d개 복원", len(cusum_data))

            arima_data = model_store.load_pickle('arima_cache')
            if isinstance(arima_data, dict) and arima_data:
                arima_forecaster._cache.update(arima_data)
                _log.info("[ml_engine] ARIMA 캐시 %d개 복원", len(arima_data))

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[ml_engine] 모델 복원 실패: %s", e)

        # AI 성능 평가 캐시 예열 — 실제 서버 실행 시에만 (management command 제외)
        try:
            import sys
            _cmd = ' '.join(sys.argv)
            _server_cmds = ('runserver', 'daphne', 'uvicorn', 'gunicorn', 'asgi')
            if any(c in _cmd for c in _server_cmds):
                from ml_engine.evaluator import warm_cache
                warm_cache(days=7)
        except Exception:
            pass
