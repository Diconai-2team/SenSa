"""
alerts 앱 뷰

- AlarmViewSet: 알람 조회 + 읽음 처리
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Alarm
from .serializers import AlarmSerializer


class AlarmViewSet(viewsets.ReadOnlyModelViewSet):
    """알람 조회 / 읽음 처리 API"""
    queryset = Alarm.objects.all().order_by('-created_at')
    serializer_class = AlarmSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('unread') == 'true':
            qs = qs.filter(is_read=False)
        return qs[:50]

    @action(detail=True, methods=['patch'])
    def read(self, request, pk=None):
        """특정 알람 읽음 처리 — PATCH /api/alarm/{id}/read/"""
        alarm = self.get_object()
        alarm.is_read = True
        alarm.save()
        return Response({'status': 'read', 'id': alarm.id})

    @action(detail=False, methods=['patch'])
    def read_all(self, request):
        """전체 알람 읽음 처리 — PATCH /api/alarm/read_all/"""
        Alarm.objects.filter(is_read=False).update(is_read=True)
        return Response({'status': 'all read'})
