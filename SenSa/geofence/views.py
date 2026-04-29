"""
geofence 앱 뷰

- GeoFenceViewSet: 지오펜스 CRUD (소프트 삭제)
"""

from rest_framework import viewsets, status
from rest_framework.response import Response

from .models import GeoFence
from .serializers import GeoFenceSerializer


class GeoFenceViewSet(viewsets.ModelViewSet):
    """지오펜스 CRUD API"""

    queryset = GeoFence.objects.filter(is_active=True).order_by("-created_at")
    serializer_class = GeoFenceSerializer

    def destroy(self, request, *args, **kwargs):
        """소프트 삭제 — is_active=False"""
        instance = self.get_object()
        instance.is_active = False
        instance.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
