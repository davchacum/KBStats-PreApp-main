"""
URL configuration for KBStats project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# from django.contrib import admin  # DESACTIVADO POR SEGURIDAD
from django.urls import path
from .Cinturones.views import index, buscar_partidos_form, buscar_partidos_por_jornada, detalle_partida, promedios_jugadores, clasificacion_grupos  # , add_partida  # DESACTIVADO

urlpatterns = [
    # FUNCIONALIDADES DE ADMIN DESACTIVADAS POR SEGURIDAD
    # path('admin/add_partida/', add_partida, name='add_partida'),
    # path('admin/', admin.site.urls),
    path('', index, name='index'),
    path('clasificacion/', clasificacion_grupos, name='clasificacion_grupos'),
    path('buscar_partidos/', buscar_partidos_form, name='buscar_partidos_form'),
    path('partida/<str:match_id>/', detalle_partida, name='detalle_partida'),
    path('promedios_jugadores/', promedios_jugadores, name='promedios_jugadores'),
    path('promedios_jugadores/<str:jugador_nombre>/', promedios_jugadores, name='promedios_jugadores_detalle'),
    path('promedios_jugadores/<str:jugador_nombre>/<str:campeon>/', promedios_jugadores, name='promedios_jugadores_detalle_campeon'),
]
