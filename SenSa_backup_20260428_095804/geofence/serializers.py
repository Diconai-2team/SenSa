from rest_framework import serializers
from .models import GeoFence


class GeoFenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFence
        fields = "__all__"
        read_only_fields = ["id", "created_at"]
