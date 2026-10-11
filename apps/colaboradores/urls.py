from django.urls import path

from apps.colaboradores import views

app_name = 'colaboradores'

urlpatterns = [
    # Departamentos (só administrador).
    path('administracao/departamentos/', views.DepartamentosView.as_view(), name='departamentos'),
    path('administracao/departamentos/novo/', views.DepartamentoCriarView.as_view(), name='departamento_criar'),
    path(
        'administracao/departamentos/<int:pk>/editar/',
        views.DepartamentoEditarView.as_view(),
        name='departamento_editar',
    ),
    path(
        'administracao/departamentos/<int:pk>/excluir/',
        views.DepartamentoExcluirView.as_view(),
        name='departamento_excluir',
    ),
]
