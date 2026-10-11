from django.urls import path

from apps.ausencias import views

app_name = 'ausencias'

urlpatterns = [
    # Visualizar: qualquer autenticado. Gravar: gestor ou administrador.
    path('', views.AusenciasView.as_view(), name='lista'),
    path('registrar/', views.AusenciaCriarView.as_view(), name='registrar'),
    path('lixeira/', views.LixeiraView.as_view(), name='lixeira'),
]
