# -*- coding: utf-8 -*-
"""
devices.metrics — SensorData 저장 결과 카운터.

평가 지표 #2/#9 "DB 저장 성공률 / 성공·실패 수" 를 위한 메트릭.
sensor_data_save_total{device_type, result}

호출 지점: devices/views.py 의 _save_gas / _save_power
   SensorData.objects.create 직후 success / 예외 시 failure.
"""

from prometheus_client import Counter

sensor_data_save_total = Counter(
    'sensa_sensor_data_save_total',
    'SensorData 저장 시도 횟수 (DB 저장 성공/실패 통계)',
    ['device_type', 'result'],   # device_type: gas|power, result: success|failure
)
