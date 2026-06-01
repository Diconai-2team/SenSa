"""
dashboard/tasks.py — 시연용 Celery task.

[목적]
이미 구현된 TaskStatusView(/dashboard/api/task-status/<task_id>/)를
AI·외부전송과 무관하게 안정적으로 on-demand 시연하기 위한 데모 task.
PENDING → STARTED → SUCCESS(또는 FAILURE) 상태 전이를 결정론적으로 재현.

[부작용 없음]
- DB 쓰기 없음, 외부 전송 없음, AI 호출 없음. 단순 sleep 후 dict 반환.
- ignore_result 아님 → AsyncResult 로 상태/결과 조회 가능.
"""
import time

from celery import shared_task


@shared_task(bind=True, name='dashboard.tasks.demo_status_task')
def demo_status_task(self, steps: int = 3, step_delay: float = 1.0, fail: bool = False):
    """시연용 task.

    Args:
        steps:      진행 단계 수 (기본 3)
        step_delay: 단계당 sleep 초 (기본 1.0)
        fail:       True 면 마지막 단계에서 의도적 예외 → FAILURE 시연

    Returns:
        {'ok': True, 'steps': n, 'message': ...}  (성공 시)
    """
    total = max(1, int(steps))
    delay = max(0.0, float(step_delay))
    for i in range(1, total + 1):
        time.sleep(delay)
        if fail and i == total:
            raise RuntimeError(f"demo intentional failure at step {i}/{total}")
    return {'ok': True, 'steps': total, 'message': 'demo task completed'}
