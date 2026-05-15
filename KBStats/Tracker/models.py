from django.db import models


class TrackerSummoner(models.Model):
    STATUS_PENDING  = "pending"
    STATUS_FETCHING = "fetching"
    STATUS_DONE     = "done"
    STATUS_ERROR    = "error"
    STATUS_CHOICES  = [
        (STATUS_PENDING,  "Pendiente"),
        (STATUS_FETCHING, "Descargando"),
        (STATUS_DONE,     "Completado"),
        (STATUS_ERROR,    "Error"),
    ]

    puuid       = models.CharField(max_length=200, unique=True)
    game_name   = models.CharField(max_length=100)
    tag_line    = models.CharField(max_length=50)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_msg   = models.TextField(blank=True, default="")
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Summoner Trackeado"

    def __str__(self):
        return f"{self.game_name}#{self.tag_line}"

    @property
    def riot_id(self):
        return f"{self.game_name}#{self.tag_line}"


class TrackerMatch(models.Model):
    match_id      = models.CharField(max_length=100, unique=True)
    patch         = models.CharField(max_length=20)   # "15.8"
    game_duration = models.IntegerField()              # segundos
    game_date     = models.DateTimeField()

    class Meta:
        verbose_name = "Partida Tracker"
        ordering = ["-game_date"]

    def __str__(self):
        return f"{self.match_id} ({self.patch})"


ROLES = [("TOP", "Top"), ("JGL", "Jungla"), ("MID", "Mid"), ("ADC", "ADC"), ("SUP", "Support"), ("UNK", "Desconocido")]

ROLE_MAP = {
    "TOP":     "TOP",
    "JUNGLE":  "JGL",
    "MIDDLE":  "MID",
    "BOTTOM":  "ADC",
    "UTILITY": "SUP",
}


class TrackerParticipant(models.Model):
    summoner = models.ForeignKey(TrackerSummoner, on_delete=models.CASCADE, related_name="participations")
    match    = models.ForeignKey(TrackerMatch, on_delete=models.CASCADE, related_name="participants")

    champion = models.CharField(max_length=100)
    role     = models.CharField(max_length=10, choices=ROLES, default="UNK")
    win      = models.BooleanField()

    kills      = models.IntegerField()
    deaths     = models.IntegerField()
    assists    = models.IntegerField()
    kp         = models.FloatField(default=0.0)   # kill participation %

    # Early game (min 15) — null si no hay timeline
    gd15  = models.IntegerField(null=True, blank=True)
    csd15 = models.IntegerField(null=True, blank=True)
    xpd15 = models.IntegerField(null=True, blank=True)
    ka15  = models.IntegerField(null=True, blank=True)
    fb    = models.BooleanField(null=True, blank=True)   # participó en First Blood
    fbv   = models.BooleanField(null=True, blank=True)   # fue víctima del First Blood

    # Teamfight (extraído del timeline)
    tf_count         = models.IntegerField(default=0)   # TFs donde participó
    tf_kills         = models.IntegerField(default=0)
    tf_deaths        = models.IntegerField(default=0)
    tf_assists       = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Participación Tracker"
        unique_together = ("summoner", "match")

    def __str__(self):
        return f"{self.summoner} - {self.match.match_id} ({self.champion})"

    @property
    def kda(self):
        return (self.kills + self.assists) / max(self.deaths, 1)
