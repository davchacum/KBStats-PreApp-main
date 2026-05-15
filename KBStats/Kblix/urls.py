from django.urls import path
from . import views

app_name = 'kblix'

urlpatterns = [
    path('', views.index, name='index'),
    path('crear/', views.crear_sala, name='crear_sala'),
    path('sala/<str:room_id>/', views.sala, name='sala'),
]
