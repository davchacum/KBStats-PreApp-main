from django.db import models


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
