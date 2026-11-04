"""Configuración global que Django utiliza al ejecutar este proyecto."""

# Herramienta para construir rutas del sistema de archivos sin depender del SO.
from pathlib import Path
import os

# Ruta raíz del proyecto, usada para localizar recursos como la base de datos.
BASE_DIR = Path(__file__).resolve().parent.parent


# Estas opciones son propias del entorno de desarrollo; revisar para producción.

# Clave que Django utiliza para firmas y funciones criptográficas.
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-local-development-only',
)

# Activa páginas de diagnóstico detalladas; debe desactivarse en producción.
DEBUG = True

# Dominios permitidos para atender solicitudes HTTP.
ALLOWED_HOSTS = []


# Aplicaciones integradas de Django y aplicación del cotizador que se cargan.
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cotizador.apps.CotizadorConfig',
]

# Procesamiento de seguridad, sesiones, formularios, autenticación y mensajes.
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Archivo que declara las rutas principales del sitio.
ROOT_URLCONF = 'config.urls'

# Motor de plantillas, carga automática y datos de contexto disponibles.
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Punto de entrada para servidores WSGI tradicionales.
WSGI_APPLICATION = 'config.wsgi.application'


# Base de datos SQLite almacenada en la carpeta raíz del proyecto.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Validadores que protegen las contraseñas creadas mediante Django.
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Idioma predeterminado de las traducciones de Django.
LANGUAGE_CODE = 'en-us'

# Zona horaria usada para almacenar y presentar fechas.
TIME_ZONE = 'UTC'

# Habilita la infraestructura de traducciones.
USE_I18N = True

# Almacena fechas con zona horaria para mantener consistencia temporal.
USE_TZ = True


# Prefijo URL para servir los recursos estáticos, como el CSS del cotizador.
STATIC_URL = 'static/'

# Almacenamiento local de fotos de perfil.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Rutas de autenticación y destino al iniciar/cerrar sesión.
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'quote'
LOGOUT_REDIRECT_URL = 'login'


# Backend de correo de desarrollo: muestra los mensajes en la consola.
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}
