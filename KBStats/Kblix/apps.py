from django.apps import AppConfig


class KblixConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'KBStats.Kblix'
    label = 'Kblix'
    verbose_name = 'KBLIX'

    def ready(self):
        # Limpiar is_updating atascado en el arranque.
        # Usamos post_migrate para evitar acceder a la BD antes de que las
        # migraciones estén aplicadas (evita RuntimeWarning en manage.py).
        from django.db.models.signals import post_migrate
        post_migrate.connect(_reset_ladder_lock, sender=self)


def _reset_ladder_lock(sender, **kwargs):
    try:
        from KBStats.Kblix.models import LadderUpdateState
        LadderUpdateState.objects.filter(pk=1, is_updating=True).update(is_updating=False)
    except Exception:
        pass
