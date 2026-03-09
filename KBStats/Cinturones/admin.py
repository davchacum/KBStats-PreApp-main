from django.contrib import admin
from .models import Equipo, Jugador, Partida, StatsJugador


@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
	list_display = ('nombre',)


@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
	list_display = ('nombre', 'equipo')
	search_fields = ('nombre',)


@admin.register(Partida)
class PartidaAdmin(admin.ModelAdmin):
	list_display = ('match_id', 'jornada', 'equipo_azul', 'equipo_rojo', 'ganador_equipo', 'duracion_segundos')
	search_fields = ('match_id',)


@admin.register(StatsJugador)
class StatsJugadorAdmin(admin.ModelAdmin):
	list_display = ('partida', 'jugador', 'campeon', 'kills', 'muertes', 'asistencias')
	search_fields = ('jugador__nombre', 'partida__match_id')
