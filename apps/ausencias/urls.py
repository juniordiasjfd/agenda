from django.urls import path

from apps.ausencias import views

app_name = 'ausencias'

urlpatterns = [
    # Visualizar: qualquer autenticado. Gravar: gestor ou administrador.
    path('', views.AusenciasView.as_view(), name='lista'),
    path('registrar/', views.AusenciaCriarView.as_view(), name='registrar'),
    path('<int:pk>/', views.AusenciaDetalheView.as_view(), name='detalhe'),
    path('<int:pk>/editar/', views.AusenciaEditarView.as_view(), name='editar'),
    path('<int:pk>/excluir/', views.AusenciaExcluirView.as_view(), name='excluir'),
    path('<int:pk>/restaurar/', views.AusenciaRestaurarView.as_view(), name='restaurar'),
    path('<int:pk>/apagar/', views.AusenciaApagarView.as_view(), name='apagar'),
    path('lixeira/', views.LixeiraView.as_view(), name='lixeira'),
    # Fragmento HTMX da tela de registro/edição (linha do ano + avisos).
    path('prechecagem/', views.PrechecagemView.as_view(), name='prechecagem'),
    path('<int:pk>/prechecagem/', views.PrechecagemView.as_view(), name='prechecagem_edicao'),
]
