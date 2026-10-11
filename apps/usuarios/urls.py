from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from apps.usuarios import views
from apps.usuarios.forms import AlterarSenhaForm, DefinirSenhaForm, RedefinirSenhaForm

app_name = 'usuarios'

urlpatterns = [
    path('entrar/', views.LoginView.as_view(), name='login'),
    # LogoutView do Django 5 só aceita POST.
    path('sair/', auth_views.LogoutView.as_view(), name='logout'),

    # Autocadastro (público).
    path('cadastro/', views.CadastroView.as_view(), name='cadastro'),
    path('cadastro/recebido/', views.CadastroRecebidoView.as_view(), name='cadastro_recebido'),

    # Cadastros pendentes (só administrador).
    path('administracao/cadastros-pendentes/', views.PendentesView.as_view(), name='pendentes'),
    path(
        'administracao/cadastros-pendentes/<int:pk>/aprovar/',
        views.AprovarUsuarioView.as_view(),
        name='aprovar_usuario',
    ),
    path(
        'administracao/cadastros-pendentes/<int:pk>/rejeitar/',
        views.RejeitarUsuarioView.as_view(),
        name='rejeitar_usuario',
    ),

    # Redefinição de senha (esqueci minha senha) — usuário deslogado.
    path(
        'senha/redefinir/',
        auth_views.PasswordResetView.as_view(
            form_class=RedefinirSenhaForm,
            template_name='usuarios/redefinir_senha.html',
            email_template_name='usuarios/emails/redefinir_senha.txt',
            subject_template_name='usuarios/emails/redefinir_senha_assunto.txt',
            success_url=reverse_lazy('usuarios:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'senha/redefinir/enviado/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='usuarios/redefinir_senha_enviado.html',
        ),
        name='password_reset_done',
    ),
    path(
        'senha/redefinir/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            form_class=DefinirSenhaForm,
            template_name='usuarios/redefinir_senha_confirmar.html',
            success_url=reverse_lazy('usuarios:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'senha/redefinir/concluido/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='usuarios/redefinir_senha_concluido.html',
        ),
        name='password_reset_complete',
    ),

    # Alterar senha — usuário logado (as views já exigem login).
    path(
        'senha/alterar/',
        auth_views.PasswordChangeView.as_view(
            form_class=AlterarSenhaForm,
            template_name='usuarios/alterar_senha.html',
            success_url=reverse_lazy('usuarios:password_change_done'),
            extra_context={'active_nav': 'alterar_senha'},
        ),
        name='password_change',
    ),
    path(
        'senha/alterar/concluido/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='usuarios/alterar_senha_concluido.html',
            extra_context={'active_nav': 'alterar_senha'},
        ),
        name='password_change_done',
    ),
]
