from django.db import models

class SensorData(models.Model):
    device_id = models.CharField(max_length=50)
    timestamp = models.DateTimeField()
    CO = models.FloatField()
    H2S = models.FloatField()
    temperature = models.FloatField()
    humidity = models.FloatField()
    lat = models.FloatField()
    lon = models.FloatField()
    risk_score = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.device_id} @ {self.timestamp}"
