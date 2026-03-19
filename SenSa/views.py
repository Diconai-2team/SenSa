from rest_framework import generics
from .models import SensorData
from .serializers import SensorDataSerializer


# POST /api/sensors/
# GET /api/sensors/
class SensorDataListCreateView(generics.ListCreateAPIView):
    queryset = SensorData.objects.all()
    serializer_class = SensorDataSerializer
