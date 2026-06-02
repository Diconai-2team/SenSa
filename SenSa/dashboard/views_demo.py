"""
dashboard/views_demo.py — 시연용 Task 큐잉 엔드포인트.

POST /dashboard/api/demo-task/
    body(JSON, 전부 선택): {"steps": 3, "step_delay": 1.0, "fail": false}
    응답: {"task_id": "...", "poll": "/dashboard/api/task-status/<id>/", ...}

이후 GET /dashboard/api/task-status/<task_id>/ 로 PENDING→STARTED→SUCCESS/FAILURE 추적.
권한은 기존 TaskStatusView 와 동일(IsAuthenticated).
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from dashboard.tasks import demo_status_task


class DemoTaskView(APIView):
    """시연용 Celery task 를 큐잉하고 task_id 를 반환."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        try:
            steps = int(data.get('steps', 3))
            step_delay = float(data.get('step_delay', 1.0))
            fail = bool(data.get('fail', False))
        except (TypeError, ValueError):
            return Response({'error': 'invalid parameters'}, status=400)

        res = demo_status_task.delay(steps=steps, step_delay=step_delay, fail=fail)
        return Response({
            'task_id': res.id,
            'steps': steps,
            'step_delay': step_delay,
            'fail': fail,
            'poll': f'/dashboard/api/task-status/{res.id}/',
        })
