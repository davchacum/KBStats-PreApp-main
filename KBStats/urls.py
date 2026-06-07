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
from django.urls import path, include
from django.contrib.auth import views as auth_views
from .Cinturones.views import index, buscar_partidos_form, buscar_partidos_por_jornada, detalle_partida, promedios_jugadores, clasificacion_grupos, exportar_csv_jugadores, tier_list, heatmap_data  # , add_partida  # DESACTIVADO
from .Kblix import views as kblix_views

urlpatterns = [
    # FUNCIONALIDADES DE ADMIN DESACTIVADAS POR SEGURIDAD
    # path('admin/add_partida/', add_partida, name='add_partida'),
    # path('admin/', admin.site.urls),
    path('', index, name='index'),
    path('clasificacion/', clasificacion_grupos, name='clasificacion_grupos'),
    path('buscar_partidos/', buscar_partidos_form, name='buscar_partidos_form'),
    path('partida/<str:match_id>/', detalle_partida, name='detalle_partida'),
    path('partida/<str:match_id>/heatmap/', heatmap_data, name='heatmap_data'),
    path('promedios_jugadores/', promedios_jugadores, name='promedios_jugadores'),
    path('promedios_jugadores/exportar/csv/', exportar_csv_jugadores, name='exportar_csv_jugadores'),
    path('tierlist/', tier_list, name='tier_list'),
    path('promedios_jugadores/<str:jugador_nombre>/', promedios_jugadores, name='promedios_jugadores_detalle'),
    path('promedios_jugadores/<str:jugador_nombre>/<str:campeon>/', promedios_jugadores, name='promedios_jugadores_detalle_campeon'),
    path('kblix/', include('KBStats.Kblix.urls', namespace='kblix')),
    # Ladder
    path('ladder/',                              kblix_views.ladder,                  name='ladder'),
    path('ladder/status/',                       kblix_views.ladder_status,           name='ladder_status'),
    path('ladder/partial/',                      kblix_views.ladder_partial,          name='ladder_partial'),
    path('ladder/forzar-update/',               kblix_views.ladder_force_update,     name='ladder_force_update'),
    path('ladder/configurar/',                   kblix_views.ladder_config,           name='ladder_config'),
    path('ladder/add/',                          kblix_views.ladder_player_save,      name='ladder_player_add'),
    path('ladder/<int:player_id>/edit/',         kblix_views.ladder_player_save,      name='ladder_player_edit'),
    path('ladder/<int:player_id>/forzar-update/', kblix_views.ladder_player_force_update, name='ladder_player_force_update'),
    path('ladder/<int:player_id>/delete/',       kblix_views.ladder_player_delete,    name='ladder_player_delete'),
    path('ladder/exportar/',                     kblix_views.ladder_export_csv,       name='ladder_export_csv'),
    path('ladder/importar/',                     kblix_views.ladder_import_csv,       name='ladder_import_csv'),
    path('ladder/importar-desde-stats/',         kblix_views.ladder_import_from_stats, name='ladder_import_from_stats'),
    path('ladder/sync-riot-ids/',                kblix_views.ladder_sync_riot_ids,    name='ladder_sync_riot_ids'),
    # Auth
    path('login/',  auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
