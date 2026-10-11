from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'Agenda — Administração'
admin.site.site_title = 'Agenda'
admin.site.index_title = 'Administração'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.usuarios.urls')),
    path('', include('apps.colaboradores.urls')),
    path('ausencias/', include('apps.ausencias.urls')),
    path('painel/', include('apps.ausencias.urls_painel')),
    path('', include('apps.core.urls')),
]
