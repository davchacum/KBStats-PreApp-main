from django.urls import path, include
from .Cinturones.views import (
    index, buscar_partidos_form, buscar_partidos_por_jornada, detalle_partida,
    promedios_jugadores, clasificacion_grupos, exportar_csv_jugadores, tier_list, heatmap_data,
)
from .Cinturones.views_scouting import (
    scouting_home, scouting_add, scouting_edit, scouting_detail,
    scouting_fetch, scouting_jungle_detail, scouting_jungle_heatmap_data,
    scouting_delete, scouting_export,
)

urlpatterns = [
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
    # ── Scouting ──────────────────────────────────────────────────────────────
    path('scouting/',                                                    scouting_home,                name='scouting_home'),
    path('scouting/add/',                                                scouting_add,                 name='scouting_add'),
    path('scouting/<int:player_id>/',                                    scouting_detail,              name='scouting_detail'),
    path('scouting/<int:player_id>/edit/',                               scouting_edit,                name='scouting_edit'),
    path('scouting/<int:player_id>/fetch/',                              scouting_fetch,               name='scouting_fetch'),
    path('scouting/<int:player_id>/delete/',                             scouting_delete,              name='scouting_delete'),
    path('scouting/<int:player_id>/jungle/<str:match_id>/',              scouting_jungle_detail,       name='scouting_jungle_detail'),
    path('scouting/<int:player_id>/jungle/<str:match_id>/heatmap/',      scouting_jungle_heatmap_data, name='scouting_jungle_heatmap_data'),
    path('scouting/<int:player_id>/export/',                             scouting_export,              name='scouting_export'),
]
