"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# Vistas necesarias para declarar las rutas URL del proyecto.
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from django.views.decorators.cache import never_cache

# Formulario de acceso con mensajes en español.
from cotizador.forms import CintacAuthenticationForm

# Vistas que presentan el cotizador y las tarifas disponibles.
from cotizador.views import (
    CintacLoginView,
    clear_quote_history,
    delete_managed_user,
    edit_managed_user,
    create_managed_user,
    manage_users,
    quote,
    quote_history_detail,
    quote_history,
    rate_create,
    rate_delete,
    rate_edit,
    rates,
    quote_history_excel,
    user_profile,
)

# Asocia la página principal al cotizador y expone el administrador de Django.
urlpatterns = [
    path(
        'accounts/login/',
        never_cache(
            CintacLoginView.as_view(
                template_name='registration/login.html',
                authentication_form=CintacAuthenticationForm,
            )
        ),
        name='login',
    ),
    path(
        'accounts/logout/',
        never_cache(auth_views.LogoutView.as_view()),
        name='logout',
    ),
    path('', quote, name='quote'),
    path('historial/', quote_history, name='quote_history'),
    path('historial/<int:quote_id>/', quote_history_detail, name='quote_history_detail'),
    path('historial/<int:quote_id>/excel/', quote_history_excel, name='quote_history_excel'),
    path('historial/limpiar/', clear_quote_history, name='clear_quote_history'),
    path('tarifas/', rates, name='rates'),
    path('tarifas/nueva/', rate_create, name='rate_create'),
    path('tarifas/<int:rate_id>/editar/', rate_edit, name='rate_edit'),
    path('tarifas/<int:rate_id>/eliminar/', rate_delete, name='rate_delete'),
    path('perfil/', user_profile, name='user_profile'),
    path('usuarios/', manage_users, name='manage_users'),
    path('usuarios/nuevo/', create_managed_user, name='create_managed_user'),
    path('usuarios/<int:user_id>/editar/', edit_managed_user, name='edit_managed_user'),
    path('usuarios/<int:user_id>/eliminar/', delete_managed_user, name='delete_managed_user'),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
