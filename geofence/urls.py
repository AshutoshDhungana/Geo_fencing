from django.contrib import admin
from django.urls import path, re_path
from django.views.static import serve

from tracker import views

urlpatterns = [
    path("api/readings", views.ingest),
    path("api/me", views.me),
    path("api/login", views.login_view),
    path("api/logout", views.logout_view),
    path("api/latest", views.latest),
    path("api/track/<str:tag>", views.track),
    path("api/alerts", views.alerts),
    path("api/fences", views.fences), path("api/fences/<int:pk>", views.fence_detail),
    path("api/animals/<str:tag>", views.animal_detail),
    path("api/sim/tick", views.sim_tick),
    path("api/sim/reset", views.sim_reset),
    path("admin/", admin.site.urls),
    # Built React app (frontend/dist). ponytail: Django serves the files itself; put nginx in front if traffic grows.
    re_path(r"^assets/(?P<path>.*)$", serve, {"document_root": views.FRONTEND_DIST / "assets"}),
    path("", views.frontend),
]
