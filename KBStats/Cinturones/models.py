from django.db import models


class Equipo(models.Model):
	nombre = models.CharField(max_length=200, unique=True)

	class Meta:
		verbose_name = "Equipo"
		verbose_name_plural = "Equipos"

	def __str__(self):
		return self.nombre


class Jugador(models.Model):
	nombre = models.CharField(max_length=200, unique=True)
	equipo = models.ForeignKey(Equipo, null=True, blank=True, on_delete=models.SET_NULL, related_name='jugadores')

	class Meta:
		verbose_name = "Jugador"
		verbose_name_plural = "Jugadores"

	def __str__(self):
		return self.nombre


class Partida(models.Model):
	match_id = models.CharField(max_length=100, unique=True)
	jornada = models.CharField(max_length=100, blank=True, null=True)
	numero_partida = models.CharField(max_length=50, blank=True, null=True)
	equipo_azul = models.ForeignKey(Equipo, related_name='partidas_azul', on_delete=models.PROTECT)
	equipo_rojo = models.ForeignKey(Equipo, related_name='partidas_rojo', on_delete=models.PROTECT)
	ganador_equipo = models.ForeignKey(Equipo, null=True, blank=True, related_name='partidas_ganadas', on_delete=models.SET_NULL)
	duracion_segundos = models.IntegerField(default=0)
	dragones_azul = models.IntegerField(default=0)
	dragones_rojo = models.IntegerField(default=0)
	heraldos_azul = models.IntegerField(default=0)
	heraldos_rojo = models.IntegerField(default=0)
	barones_azul = models.IntegerField(default=0)
	barones_rojo = models.IntegerField(default=0)
	elders_azul = models.IntegerField(default=0)
	elders_rojo = models.IntegerField(default=0)
	atakhan_azul = models.IntegerField(default=0)
	atakhan_rojo = models.IntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = "Partida"
		verbose_name_plural = "Partidas"

	def __str__(self):
		return f"{self.match_id} ({self.jornada or 'N/A'})"


class StatsJugador(models.Model):
	partida = models.ForeignKey(Partida, on_delete=models.CASCADE, related_name='stats_jugadores')
	jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name='stats')
	campeon = models.CharField(max_length=100, blank=True, null=True)
	# Rol del jugador en esta partida (top, jgl, mid, adc, sup)
	rol = models.CharField(max_length=20, blank=True, null=True)
	# Nombre del equipo en esta partida (cadena para evitar depender del FK del jugador)
	equipo_nombre = models.CharField(max_length=200, blank=True, null=True)
	kills = models.IntegerField(default=0)
	muertes = models.IntegerField(default=0)
	asistencias = models.IntegerField(default=0)
	kda = models.FloatField(default=0.0)
	kp_porcentaje = models.FloatField(default=0.0)
	oro_min = models.FloatField(default=0.0)
	dano_infligido = models.BigIntegerField(default=0)
	porcentaje_dano_equipo = models.FloatField(default=0.0)
	dano_min = models.FloatField(default=0.0)
	dano_recibido = models.BigIntegerField(default=0)
	cs = models.IntegerField(default=0)
	cs_min = models.FloatField(default=0.0)
	vision_min = models.FloatField(default=0.0)
	double_kills = models.IntegerField(default=0)
	triple_kills = models.IntegerField(default=0)
	quadra_kills = models.IntegerField(default=0)
	penta_kills = models.IntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = "Estadística de Jugador"
		verbose_name_plural = "Estadísticas de Jugadores"
		unique_together = ('partida', 'jugador')

	def __str__(self):
		return f"{self.jugador} - {self.partida.match_id}"
