from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("plan", views.plan, name="plan"),
    path("heatmap/<str:plan_id>", views.heatmap, name="heatmap"),
]
