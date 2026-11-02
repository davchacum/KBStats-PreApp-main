import os

from django.conf import settings


def version_estaticos(request):
    """
    Versión de la hoja de estilos (su fecha de modificación) para añadirla a la URL
    del CSS: así el navegador descarga la nueva en cuanto cambia, sin quedarse con la de caché.
    """
    version = 0
    for carpeta in list(getattr(settings, 'STATICFILES_DIRS', [])) + [getattr(settings, 'STATIC_ROOT', '')]:
        ruta = os.path.join(str(carpeta), 'css', 'kbstats.css')
        if carpeta and os.path.exists(ruta):
            version = int(os.path.getmtime(ruta))
            break
    return {'css_version': version}
