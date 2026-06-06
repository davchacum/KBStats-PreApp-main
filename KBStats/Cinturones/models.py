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
	position_data = models.JSONField(null=True, blank=True)
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
	game_time = models.FloatField(default=0.0)
	dano_oro = models.FloatField(default=0.0)
	# Visión desglosada
	wpm = models.FloatField(default=0.0)    # wards colocados / min
	cwpm = models.FloatField(default=0.0)   # control wards comprados / min
	wcpm = models.FloatField(default=0.0)   # wards destruidos / min
	# Shares de equipo
	gold_pct = models.FloatField(default=0.0)     # % oro del equipo
	death_share = models.FloatField(default=0.0)  # % muertes del equipo
	# Resultado
	victoria = models.BooleanField(default=False)
	# Early game (min 15) — null cuando no hay datos de timeline
	gd15  = models.IntegerField(null=True, blank=True)
	csd15 = models.IntegerField(null=True, blank=True)
	xpd15 = models.IntegerField(null=True, blank=True)
	cs15  = models.IntegerField(null=True, blank=True)
	ka15  = models.IntegerField(null=True, blank=True)
	fb    = models.BooleanField(null=True, blank=True)   # participó en First Blood
	fbv   = models.BooleanField(null=True, blank=True)   # fue víctima del First Blood
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = "Estadística de Jugador"
		verbose_name_plural = "Estadísticas de Jugadores"
		unique_together = ('partida', 'jugador')

	def __str__(self):
		return f"{self.jugador} - {self.partida.match_id}"


# ── Scouting ──────────────────────────────────────────────────────────────────

ROLE_CHOICES = [
	('',        'Todos los roles'),
	('TOP',     'Top'),
	('JUNGLE',  'Jungla'),
	('MIDDLE',  'Mid'),
	('BOTTOM',  'Bot (ADC)'),
	('UTILITY', 'Support'),
]


class ScoutedPlayer(models.Model):
	identifier     = models.CharField(max_length=100, unique=True)
	preferred_role = models.CharField(max_length=20, blank=True, choices=ROLE_CHOICES)
	notes          = models.TextField(blank=True)
	created_at     = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering            = ['identifier']
		verbose_name        = 'Jugador Scouted'
		verbose_name_plural = 'Jugadores Scouted'

	def __str__(self):
		return self.identifier

	@property
	def role_label(self):
		return dict(ROLE_CHOICES).get(self.preferred_role, 'Todos los roles')


class PlayerAccount(models.Model):
	player       = models.ForeignKey(ScoutedPlayer, on_delete=models.CASCADE, related_name='accounts')
	riot_id      = models.CharField(max_length=100)
	puuid        = models.CharField(max_length=200, blank=True)
	is_main      = models.BooleanField(default=False)
	last_fetched = models.DateTimeField(null=True, blank=True)

	class Meta:
		unique_together     = ('player', 'riot_id')
		verbose_name        = 'Cuenta'
		verbose_name_plural = 'Cuentas'

	def __str__(self):
		return f'{self.riot_id}{" (main)" if self.is_main else ""}'


class ScoutedMatch(models.Model):
	account       = models.ForeignKey(PlayerAccount, on_delete=models.CASCADE, related_name='scouted_matches')
	match_id      = models.CharField(max_length=50)
	game_start    = models.BigIntegerField(default=0)
	game_duration = models.IntegerField(default=0)
	queue_id      = models.IntegerField(default=0)
	champion_name = models.CharField(max_length=50)
	role          = models.CharField(max_length=20, blank=True)
	team_id       = models.IntegerField(default=100)
	win           = models.BooleanField(default=False)
	kills         = models.IntegerField(default=0)
	deaths        = models.IntegerField(default=0)
	assists       = models.IntegerField(default=0)
	cs            = models.IntegerField(default=0)
	vision_score  = models.IntegerField(default=0)
	damage_dealt  = models.IntegerField(default=0)
	gold_earned   = models.IntegerField(default=0)
	position_data = models.JSONField(null=True, blank=True)
	jungle_stats  = models.JSONField(null=True, blank=True)
	participants  = models.JSONField(null=True, blank=True)

	class Meta:
		unique_together     = ('account', 'match_id')
		ordering            = ['-game_start']
		verbose_name        = 'Partida Scouted'
		verbose_name_plural = 'Partidas Scouted'

	def __str__(self):
		return f'{self.account.riot_id} · {self.champion_name} ({self.match_id})'

	@property
	def kda(self):
		return round((self.kills + self.assists) / max(1, self.deaths), 2)

	@property
	def game_start_dt(self):
		from datetime import datetime
		return datetime.fromtimestamp(self.game_start / 1000) if self.game_start else None

