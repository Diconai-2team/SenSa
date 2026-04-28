from rest_framework import serializers
from .models import MapImage


class MapImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = MapImage
        fields = ['id', 'image', 'name', 'width', 'height', 'is_active', 'uploaded_at']
        read_only_fields = ['uploaded_at']
