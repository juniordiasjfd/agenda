from django.urls import path

from apps.colaboradores import views

app_name = 'colaboradores'

urlpatterns = [
    # Colaboradores (só administrador). Nunca são excluídos: só desativados.
    path('administracao/colaboradores/', views.ColaboradoresView.as_view(), name='colaboradores'),
    path('administracao/colaboradores/novo/', views.ColaboradorCriarView.as_view(), name='colaborador_criar'),
    path(
        'administracao/colaboradores/<int:pk>/editar/',
        views.ColaboradorEditarView.as_view(),
        name='colaborador_editar',
    ),
    path(
        'administracao/colaboradores/<int:pk>/departamento/',
        views.AlterarDepartamentoView.as_view(),
        name='colaborador_departamento',
    ),
    path(
        'administracao/colaboradores/<int:pk>/ativar/',
        views.AlterarAtivoView.as_view(ativo=True),
        name='colaborador_ativar',
    ),
    path(
        'administracao/colaboradores/<int:pk>/desativar/',
        views.AlterarAtivoView.as_view(ativo=False),
        name='colaborador_desativar',
    ),

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
