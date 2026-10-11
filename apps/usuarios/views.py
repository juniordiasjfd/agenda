from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from apps.core.permissions import AdministradorMixin
from apps.usuarios import usuarios_service
from apps.usuarios.forms import AceitarConviteForm, AutocadastroForm, LoginForm
from apps.usuarios.models import User


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = 'usuarios/login.html'
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        # O link "Criar conta" só aparece com o autocadastro habilitado.
        kwargs['autocadastro_habilitado'] = usuarios_service.autocadastro_habilitado()
        return super().get_context_data(**kwargs)


# ---------------------------------------------------------------------------
# Autocadastro (público)
# ---------------------------------------------------------------------------
class CadastroView(FormView):
    form_class = AutocadastroForm
    template_name = 'usuarios/cadastro.html'
    success_url = reverse_lazy('usuarios:cadastro_recebido')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('core:home')
        if not usuarios_service.autocadastro_habilitado():
            return render(request, 'usuarios/cadastro_desabilitado.html')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # Mesmo redirecionamento com ou sem e-mail já cadastrado.
        usuarios_service.registrar_autocadastro(
            nome=form.cleaned_data['nome'],
            email=form.cleaned_data['email'],
            senha=form.cleaned_data['password1'],
            url_pendentes=self.request.build_absolute_uri(reverse('usuarios:pendentes')),
        )
        return super().form_valid(form)


class CadastroRecebidoView(TemplateView):
    template_name = 'usuarios/cadastro_recebido.html'


# ---------------------------------------------------------------------------
# Cadastros pendentes (só administrador)
# ---------------------------------------------------------------------------
class PendentesView(AdministradorMixin, ListView):
    template_name = 'usuarios/pendentes.html'
    context_object_name = 'pendentes'
    extra_context = {'active_nav': 'pendentes'}

    def get_queryset(self):
        return usuarios_service.listar_pendentes()


class AprovarUsuarioView(AdministradorMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        try:
            usuario, aprovado_agora = usuarios_service.aprovar_usuario(
                pk, url_login=request.build_absolute_uri(reverse('usuarios:login')),
            )
        except User.DoesNotExist:
            raise Http404('Usuário não encontrado.')
        except usuarios_service.UsuarioNaoPendente as erro:
            messages.error(request, f'{erro} não está aguardando aprovação; nada foi alterado.')
        else:
            if aprovado_agora:
                messages.success(request, f'Cadastro de {usuario.email} aprovado.')
            else:
                messages.info(request, f'{usuario.email} já estava aprovado.')
        return redirect('usuarios:pendentes')


class RejeitarUsuarioView(AdministradorMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        try:
            email = usuarios_service.rejeitar_usuario(pk)
        except User.DoesNotExist:
            raise Http404('Usuário não encontrado.')
        except usuarios_service.UsuarioNaoPendente as erro:
            messages.error(request, f'{erro} não está aguardando aprovação; o usuário não foi excluído.')
        else:
            messages.success(request, f'Cadastro de {email} rejeitado e excluído.')
        return redirect('usuarios:pendentes')


# ---------------------------------------------------------------------------
# Convite: aceite (público)
# ---------------------------------------------------------------------------
class AceitarConviteView(FormView):
    form_class = AceitarConviteForm
    template_name = 'usuarios/convite_aceitar.html'
    template_invalido = 'usuarios/convite_invalido.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            messages.info(request, 'Você já está conectado. Saia da sua conta para aceitar um convite.')
            return redirect('core:home')
        # Inexistente, expirado ou usado: a mesma página neutra.
        self.convite = usuarios_service.obter_convite_valido(kwargs['token'])
        if self.convite is None:
            return render(request, self.template_invalido)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['email'] = self.convite.email
        return kwargs

    def get_context_data(self, **kwargs):
        kwargs['convite'] = self.convite
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        try:
            usuarios_service.aceitar_convite(
                self.convite.token, nome=form.cleaned_data['nome'], senha=form.cleaned_data['password1'],
            )
        except usuarios_service.ConviteInvalido:
            return render(self.request, self.template_invalido)
        except usuarios_service.EmailJaCadastrado:
            form.add_error(
                None,
                'Já existe uma conta com este e-mail. Entre com ela ou use "Esqueci minha senha" no login.',
            )
            return self.form_invalid(form)
        messages.success(self.request, 'Conta criada! Entre com seu e-mail e a senha que você escolheu.')
        return redirect('usuarios:login')
