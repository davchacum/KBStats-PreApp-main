# KBStats-PreApp

## Configuración de variables de entorno

Para evitar subir secretos al repositorio, `RIOT_API_KEY` se toma desde la variable de entorno `RIOT_API_KEY`. En desarrollo puedes usar un archivo `.env` (no lo subas) o fijarlo en la sesión de PowerShell.

### Desarrollo (Windows - PowerShell)

- Copia el fichero de ejemplo:

```powershell
cp .env.example .env
```

- Edita `.env` y pon tu clave real:

```
RIOT_API_KEY=tu_clave_aquí
```

- Instala dependencias e inicia:

```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

- Alternativa (sin `.env`) — variable en la sesión actual:

```powershell
$env:RIOT_API_KEY = "TU_NUEVA_CLAVE"
python manage.py runserver
```

- Para fijarla permanentemente para el usuario:

```powershell
setx RIOT_API_KEY "TU_NUEVA_CLAVE"
# Cierra y vuelve a abrir la terminal para que tenga efecto
```

### Despliegue en Render

En Render debes añadir la variable de entorno `RIOT_API_KEY` en la configuración del servicio web:

1. Accede a tu panel de Render y selecciona tu servicio (Web Service).
2. Ve a la pestaña **Environment** o **Environment > Environment Variables**.
3. Añade una nueva variable con **Key** `RIOT_API_KEY` y **Value** tu clave de Riot.
4. Guarda y redeploya la aplicación. Render inyectará la variable en el entorno del proceso, y Django la leerá automáticamente.

Notas:

- No agregues el archivo `.env` al repositorio (está en `.gitignore`).
- Si la clave fue expuesta públicamente, rótala desde el panel de Riot y purga el historial Git si fue comprometida.
