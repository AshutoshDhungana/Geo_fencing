from django.contrib import admin

from .models import Alert, Animal, Fence, Reading

admin.site.register(Fence, list_display=["name", "center_lat", "center_lon", "radius_m"])
admin.site.register(Animal, list_display=["tag", "name", "fence"])
admin.site.register(Reading, list_display=["animal", "received_at", "lat", "lon", "distance_m", "inside", "sats", "rssi", "seq"], list_filter=["animal", "inside"])
admin.site.register(Alert, list_display=["animal", "started_at", "ended_at", "lat", "lon"], list_filter=["animal"])
