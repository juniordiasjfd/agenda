from django import forms
from django.contrib.auth.forms import (
    AdminUserCreationForm,
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserChangeForm,
)
from django.core.exceptions import ValidationError

from apps.core.forms import TablerFormMixin
from apps.usuarios.models import User


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginForm(TablerFormMixin, AuthenticationForm):
    """Login por e-mail com mensagens distintas para pendente e desativado.

    O ``EmailBackend`` devolve usuários inativos no ``authenticate()`` só
    quando a senha confere; aqui eles são recusados (o form fica inválido e a
    ``LoginView`` não chama ``login()``). Senha errada — de qualquer usuário,
    ativo ou não — cai na mensagem genérica, sem revelar a situação da conta.
    """
    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'E-mail ou senha incorretos.',
        'pendente': 'Seu cadastro está aguardando aprovação do administrador.',
        'inactive': 'Este usuário está desativado.',
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields['username'].widget = forms.EmailInput(attrs={
            'autofocus': True,
            'autocomplete': 'email',
            'class': 'form-control',
            'maxlength': self.fields['username'].max_length,
        })

    def confirm_login_allowed(self, user):
        if not user.is_active:
            if user.aprovado_em is None:
                raise ValidationError(self.error_messages['pendente'], code='pendente')
            raise ValidationError(self.error_messages['inactive'], code='inactive')


# ---------------------------------------------------------------------------
# Senha (views padrão do Django; só o visual muda).
#
# Envio do e-mail de redefinição: o PasswordResetForm.send_mail do Django 5.2
# já envolve o send() em try/except e registra a falha com logger.exception
# (logger "django.contrib.auth"), sem derrubar a requisição — por isso não é
# sobrescrito aqui.
# ---------------------------------------------------------------------------
class RedefinirSenhaForm(TablerFormMixin, PasswordResetForm):
    pass


class DefinirSenhaForm(TablerFormMixin, SetPasswordForm):
    pass


class AlterarSenhaForm(TablerFormMixin, PasswordChangeForm):
    pass


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
class UserAdminCreationForm(AdminUserCreationForm):
    class Meta:
        model = User
        fields = ('email', 'nome')

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data.get('email'))
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError('Já existe um usuário com este e-mail.', code='unique')
        return email


class UserAdminChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = '__all__'

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data.get('email'))
        duplicados = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if email and duplicados.exists():
            raise ValidationError('Já existe um usuário com este e-mail.', code='unique')
        return email
