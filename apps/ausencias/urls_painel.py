from django.urls import path

from apps.ausencias import views_painel

app_name = 'painel'

urlpatterns = [
    # Qualquer autenticado.
    path('', views_painel.PainelView.as_view(), name='painel'),
    path('dados/', views_painel.PainelDadosView.as_view(), name='dados'),
]
