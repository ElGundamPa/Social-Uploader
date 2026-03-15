# Social Uploader

CLI para subir vídeos editados a **YouTube**, **TikTok** e **Instagram** de forma automática. El proyecto es modular, listo para producción y fácil de configurar por usuario.

## Overview & Features

- **Un solo comando**: sube el mismo vídeo a varias redes a la vez.
- **Configuración por perfil**: múltiples cuentas (por ejemplo `default`, `client_a`).
- **Credenciales cifradas** en disco (Fernet) con clave derivada de la máquina o PIN.
- **Validación previa**: comprueba duración, tamaño y límites por plataforma antes de subir.
- **Cola de subida** con reintentos (exponential backoff) y hasta 3 subidas en paralelo.
- **Batch**: carpeta con vídeos + JSON de metadatos → subida secuencial y `upload_results.json`.
- **Integración con editor**: una función para llamar al terminar la exportación.

## Installation

```bash
git clone <repo-url>
cd social-uploader
pip install -r requirements.txt
pip install -e .
```

Requisitos: **Python 3.11+**.

## Platform Credential Setup

### YouTube

1. Ve a [Google Cloud Console](https://console.cloud.google.com/).
2. Crea un proyecto (o elige uno) y activa **YouTube Data API v3**.
3. En **Credenciales** → **Crear credenciales** → **ID de cliente OAuth**.
4. Tipo: **Aplicación de escritorio**.
5. Descarga el JSON y guárdalo como `config/youtube_client_secret.json`.
6. En la primera ejecución, el asistente abrirá el navegador para autorizar; el token se guardará en `config/youtube_token.json`.

Variables opcionales en `.env`:

- `YOUTUBE_CLIENT_SECRET_PATH=config/youtube_client_secret.json`

### TikTok

1. Entra en [TikTok for Developers](https://developers.tiktok.com/).
2. Crea una app y solicita acceso a **Content Posting API** (Direct Post o Inbox).
3. Obtén **Client Key** y **Client Secret**.
4. Realiza el flujo OAuth para obtener un **User Access Token** (con scope `video.publish` o `video.upload` según el flujo).
5. En el wizard de `social-uploader setup` introduce Client Key, Client Secret y Access Token.

Variables opcionales en `.env`:

- `TIKTOK_CLIENT_KEY=...`
- `TIKTOK_CLIENT_SECRET=...`

(El token de usuario suele obtenerse una vez por usuario vía OAuth en tu app.)

### Instagram

Se usa **instagrapi** (API no oficial). Requiere usuario y contraseña.

1. Crea un usuario/contraseña o usa una cuenta de pruebas.
2. Si tienes **2FA**, el wizard te pedirá el código en la consola.
3. La sesión se guarda en `config/instagram_session.json` para no tener que iniciar sesión en cada uso.

Variables opcionales en `.env`:

- `INSTAGRAM_USERNAME=...`
- `INSTAGRAM_PASSWORD=...`

**Nota**: Instagram puede mostrar “checkpoint” o bloqueos si detecta uso automatizado; en ese caso hay que resolver el checkpoint en la app o web antes de volver a usar la herramienta.

## Quick Start

```bash
# 1. Configurar credenciales (asistente interactivo)
social-uploader setup

# 2. Ver estado de plataformas y último historial
social-uploader status

# 3. Subir un vídeo
social-uploader upload mi_video.mp4 --title "Mi primer vídeo" --description "Descripción"
```

## CLI Commands

| Comando | Descripción |
|--------|-------------|
| `social-uploader setup [--profile NAME]` | Asistente para elegir plataformas y guardar credenciales (cifradas). |
| `social-uploader upload VIDEO_PATH --title TITLE [opciones]` | Sube un vídeo a las plataformas habilitadas (o las indicadas con `--platforms`). |
| `social-uploader upload-batch FOLDER_PATH [--profile NAME]` | Procesa una carpeta (vídeos + JSON opcionales) y escribe `upload_results.json`. |
| `social-uploader status [--profile NAME]` | Tabla de plataformas (habilitada, auth OK/error) y últimas subidas. |
| `social-uploader config --platform youtube|tiktok|instagram [--profile NAME]` | Vuelve a pedir credenciales para una plataforma y las guarda. |

### Opciones de `upload`

- `--title` (obligatorio)
- `--description`, `--tags` (por defecto vacíos)
- `--platforms youtube,tiktok,instagram` (por defecto: todas las habilitadas)
- `--schedule "2024-12-25 10:00"` (cuando lo soporte la plataforma)
- `--thumbnail PATH` (imagen de miniatura)
- `--private` (subida privada/borrador)
- `--profile NAME` (por defecto: `default`)
- `--verbose` / `-v` (más log en consola)

## Video Editor Integration

Puedes llamar a la función de integración cuando tu editor termine de exportar el vídeo:

```python
from core.integration import upload_after_export

results = upload_after_export(
    video_path="/exports/final_video.mp4",
    title="Mi vídeo editado",
    description="Descripción opcional",
    tags=["edit", "tutorial"],
    platforms=["all"],   # o ["youtube", "tiktok", "instagram"]
    profile="default",
    thumbnail_path=None,  # opcional; si no, se extrae un frame)
    is_private=False,
)

# results:
# {
#     "youtube":   {"success": True,  "url": "https://youtu.be/xxx"},
#     "tiktok":    {"success": True,  "url": "https://tiktok.com/..."},
#     "instagram": {"success": False, "error": "Session expired"}
# }
```

Asegúrate de ejecutar el script con el directorio del proyecto `social-uploader` en `PYTHONPATH`, o después de `pip install -e .` desde ese directorio.

## Batch Upload – JSON schema

Junto a cada vídeo puedes poner un JSON con el mismo nombre base:

- `mi_video.mp4` → `mi_video.json`

Formato del JSON:

```json
{
  "title": "Título del vídeo",
  "description": "Descripción opcional",
  "tags": ["tag1", "tag2"],
  "platforms": ["youtube", "tiktok", "instagram"]
}
```

- Si no hay `platforms`, se usan todas las habilitadas en el perfil.
- Si no hay JSON, se usa el nombre del archivo como título y todas las plataformas habilitadas.

Al finalizar el batch se escribe `upload_results.json` en la carpeta indicada.

## Troubleshooting

### Errores de autenticación

- **YouTube**: “invalid credentials” o token caducado → ejecuta `social-uploader config --platform youtube` y vuelve a autorizar en el navegador.
- **TikTok**: “access_token invalid” → renueva el User Access Token con tu flujo OAuth y vuelve a configurar con `social-uploader config --platform tiktok`.
- **Instagram**: “Session expired” o “checkpoint” → ejecuta `social-uploader config --platform instagram`, inicia sesión (y 2FA si aplica) y resuelve cualquier checkpoint en la app/web.

### Cuota / rate limit

- **YouTube**: “quota exceeded” → la cuota diaria de la API está agotada; el mensaje sugiere reintentar al día siguiente.
- **TikTok**: límites por minuto y por día; espera o reduce el número de subidas.

### Sesión / checkpoint (Instagram)

- Si Instagram pide verificación (checkpoint), hay que completarla en la app o en la web.
- Después, vuelve a ejecutar `social-uploader config --platform instagram` para refrescar la sesión.

### Logs

- Log de aplicación: `logs/uploader.log` (rotación 10 MB, 5 copias).
- Con `--verbose` en `upload` verás más detalle en consola.

## Project structure

```
social-uploader/
├── main.py                 # Punto de entrada CLI
├── config/
│   └── credentials.yaml    # Credenciales por perfil (no subir a git)
├── uploaders/
│   ├── base.py
│   ├── youtube.py
│   ├── tiktok.py
│   └── instagram.py
├── core/
│   ├── config_manager.py
│   ├── video_processor.py
│   ├── queue_manager.py
│   ├── integration.py
│   └── logging_config.py
├── cli/
│   ├── setup_wizard.py
│   └── commands.py
├── logs/
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

## Tests

```bash
pip install -r requirements.txt pytest
pytest tests/ -v
```

## License

MIT.
