from django import forms
from django.contrib.auth.forms import (
    AdminUserCreationForm,
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    SetPasswordMixin,
    UserChangeForm,
)
from django.core.exceptions import ValidationError

from apps.colaboradores import colaboradores_service
from apps.colaboradores.models import Colaborador
from apps.core.forms import TablerFormMixin
from apps.usuarios import usuarios_service
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
# Autocadastro
# ---------------------------------------------------------------------------
class AutocadastroForm(TablerFormMixin, SetPasswordMixin, forms.Form):
    """Nome, e-mail e senha com os validadores do Django.

    Não é ModelForm de propósito: a validação de unicidade revelaria quem já
    tem conta. E-mail repetido passa aqui e é tratado, em silêncio, pelo
    ``usuarios_service.registrar_autocadastro``.
    """
    nome = forms.CharField(
        label='Nome', max_length=150,
        widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'name'}),
    )
    email = forms.EmailField(
        label='E-mail', max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}),
    )
    password1, password2 = SetPasswordMixin.create_password_fields(label1='Senha', label2='Confirmação da senha')

    def clean_nome(self):
        return ' '.join(self.cleaned_data['nome'].split())

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])
        if not usuarios_service.email_permitido(email):
            raise ValidationError(
                'Somente e-mails de domínios autorizados podem se cadastrar. '
                'Use seu e-mail corporativo ou peça um convite ao administrador.',
                code='dominio_nao_permitido',
            )
        return email

    def clean(self):
        self.validate_passwords()
        return super().clean()

    def _post_clean(self):
        super()._post_clean()
        # Usuário provisório só para o UserAttributeSimilarityValidator
        # comparar a senha com nome e e-mail.
        provisorio = User(email=self.cleaned_data.get('email', ''), nome=self.cleaned_data.get('nome', ''))
        self.validate_password_for_user(provisorio)


# ---------------------------------------------------------------------------
# Aprovação
# ---------------------------------------------------------------------------
class AprovarCadastroForm(forms.Form):
    """POST do botão "Aprovar". O colaborador é só o id: as regras (ativo,
    sem usuário, trava) ficam em ``usuarios_service.aprovar_usuario``."""
    colaborador = forms.IntegerField(required=False, min_value=1)


# ---------------------------------------------------------------------------
# Convite
# ---------------------------------------------------------------------------
class ConviteForm(TablerFormMixin, forms.Form):
    """Criação de convite pelo administrador. As regras (usuário existente,
    convite pendente) ficam em ``usuarios_service.criar_convite``."""
    email = forms.EmailField(
        label='E-mail do convidado', max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'off'}),
    )
    validade_dias = forms.IntegerField(
        label='Validade (dias)', min_value=1, max_value=90,
        initial=usuarios_service.VALIDADE_PADRAO_DIAS,
    )
    colaborador = forms.ModelChoiceField(
        label='Colaborador', required=False, queryset=Colaborador.objects.none(),
        empty_label='Nenhum (sem vínculo)',
        help_text='Opcional. O usuário criado no aceite fica vinculado a este colaborador. '
                  'Só aparecem colaboradores ativos e sem usuário.',
    )
    enviar_por_email = forms.BooleanField(
        label='Enviar o convite por e-mail agora', required=False, initial=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['colaborador'].queryset = colaboradores_service.colaboradores_vinculaveis()

    def clean_email(self):
        return User.objects.normalize_email(self.cleaned_data['email'])


class AceitarConviteForm(TablerFormMixin, SetPasswordMixin, forms.Form):
    """Nome e senha. O e-mail NÃO é campo: vem do convite e é só exibido."""
    nome = forms.CharField(
        label='Nome', max_length=150,
        widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'name'}),
    )
    password1, password2 = SetPasswordMixin.create_password_fields(label1='Senha', label2='Confirmação da senha')

    def __init__(self, *args, email, **kwargs):
        self.email = email
        super().__init__(*args, **kwargs)

    def clean_nome(self):
        return ' '.join(self.cleaned_data['nome'].split())

    def clean(self):
        self.validate_passwords()
        return super().clean()

    def _post_clean(self):
        super()._post_clean()
        provisorio = User(email=self.email, nome=self.cleaned_data.get('nome', ''))
        self.validate_password_for_user(provisorio)


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
