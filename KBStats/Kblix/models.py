from django.db import models

ROL_CHOICES = [
    ('TOP',     'Top'),
    ('JUNGLE',  'Jungla'),
    ('MID',     'Mid'),
    ('ADC',     'ADC'),
    ('SUPPORT', 'Support'),
]

_TIER_SCORE = {
    '': -400, 'UNRANKED': -100,
    'IRON': 0, 'BRONZE': 400, 'SILVER': 800, 'GOLD': 1200,
    'PLATINUM': 1600, 'EMERALD': 2000, 'DIAMOND': 2400,
    'MASTER': 2800, 'GRANDMASTER': 3200, 'CHALLENGER': 3600,
}
_RANK_SCORE = {'': 0, 'IV': 0, 'III': 100, 'II': 200, 'I': 300}


class Jugador(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

    class Meta:
        app_label = 'Kblix'
        verbose_name_plural = 'Jugadores'
        ordering = ['nombre']


class Temporada(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

    class Meta:
        app_label = 'Kblix'
        verbose_name_plural = 'Temporadas'
        ordering = ['nombre']


class Equipo(models.Model):
    nombre = models.CharField(max_length=100)
    temporada = models.ForeignKey(Temporada, on_delete=models.CASCADE, related_name='equipos')
    jugadores = models.ManyToManyField(Jugador, related_name='equipos')

    def __str__(self):
        return f'{self.nombre} - {self.temporada}'

    class Meta:
        app_label = 'Kblix'
        verbose_name_plural = 'Equipos'
        unique_together = ('nombre', 'temporada')
        ordering = ['nombre', 'temporada__nombre']


class LadderPlayer(models.Model):
    """Jugador del ladder: standalone, referenciado por nombre en StatsJugador."""
    nombre      = models.CharField(max_length=100, unique=True)
    riot_id     = models.CharField(max_length=100, blank=True)
    puuid       = models.CharField(max_length=200, blank=True)
    summoner_id = models.CharField(max_length=200, blank=True)
    # rol y equipo son manuales (override; si vacíos se computan de StatsJugador)
    rol         = models.CharField(max_length=10, blank=True, choices=ROL_CHOICES)
    equipo      = models.CharField(max_length=100, blank=True)

    tier        = models.CharField(max_length=20, blank=True)
    rank        = models.CharField(max_length=5,  blank=True)
    lp          = models.IntegerField(default=0)
    wins        = models.IntegerField(default=0)
    losses      = models.IntegerField(default=0)
    last_updated = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'Kblix'
        ordering  = ['nombre']

    @property
    def rank_score(self):
        return _TIER_SCORE.get(self.tier, -400) + _RANK_SCORE.get(self.rank, 0) + self.lp

    @property
    def winrate(self):
        total = self.wins + self.losses
        return round(self.wins / total * 100) if total else None

    @property
    def rank_display(self):
        if not self.tier or self.tier == 'UNRANKED':
            return 'Sin clasificar'
        if self.tier in ('MASTER', 'GRANDMASTER', 'CHALLENGER'):
            return f'{self.tier.capitalize()} {self.lp} LP'
        return f'{self.tier.capitalize()} {self.rank} · {self.lp} LP'

    def __str__(self):
        return f'{self.nombre} ({self.riot_id or "sin riot_id"})'


class LadderUpdateState(models.Model):
    """Singleton que rastrea el estado de la actualización periódica del ladder."""
    last_request    = models.DateTimeField(null=True, blank=True)
    last_update     = models.DateTimeField(null=True, blank=True)
    is_updating     = models.BooleanField(default=False)
    update_progress = models.IntegerField(default=0)
    total_players   = models.IntegerField(default=0)

    class Meta:
        app_label = 'Kblix'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
