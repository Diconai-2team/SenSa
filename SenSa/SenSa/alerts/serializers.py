from rest_framework import serializers
from .models import Alarm


class AlarmSerializer(serializers.ModelSerializer):
    geofence_name = serializers.CharField(
        source='geofence.name', read_only=True, default=None
    )

    class Meta:
        model = Alarm
        fields = [
            'id', 'alarm_type', 'alarm_level',
            'worker_id', 'worker_name', 'worker_x', 'worker_y',
            'geofence', 'geofence_name',
            'device_id', 'sensor_type',
            'message', 'is_read', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
