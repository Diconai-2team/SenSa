from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('devices', '0004_alter_device_geofence_alter_sensordata_co_and_more'),
    ]

    operations = [
        # No-op: current/voltage/watt fields are added by
        # 0005_sensordata_current_sensordata_voltage_and_more (duplicate work from merged branch)
    ]