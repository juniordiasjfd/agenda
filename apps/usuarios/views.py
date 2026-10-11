from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from apps.colaboradores import colaboradores_service
from apps.core.permissions import AdministradorMixin
from apps.usuarios import usuarios_service
from apps.usuarios.forms import AceitarConviteForm, AprovarCadastroForm, AutocadastroForm, ConviteForm, LoginForm
from apps.usuarios.models import Convite, User


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
        pendentes = list(usuarios_service.listar_pendentes())
        # Só sugestão: o select já vem com o homônimo marcado, mas nada é
        # vinculado sem o administrador confirmar a aprovação.
        for pendente in pendentes:
            pendente.colaborador_sugerido = colaboradores_service.colaborador_por_nome(pendente.nome)
        return pendentes

    def get_context_data(self, **kwargs):
        kwargs['colaboradores_vinculaveis'] = list(colaboradores_service.colaboradores_vinculaveis())
        return super().get_context_data(**kwargs)


class AprovarUsuarioView(AdministradorMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        form = AprovarCadastroForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Colaborador inválido; nada foi alterado.')
            return redirect('usuarios:pendentes')
        try:
            usuario, aprovado_agora = usuarios_service.aprovar_usuario(
                pk, url_login=request.build_absolute_uri(reverse('usuarios:login')),
                colaborador_id=form.cleaned_data['colaborador'], aprovado_por=request.user,
            )
        except User.DoesNotExist:
            raise Http404('Usuário não encontrado.')
        except usuarios_service.UsuarioNaoPendente as erro:
            messages.error(request, f'{erro} não está aguardando aprovação; nada foi alterado.')
        except usuarios_service.VinculoRecusado as erro:
            messages.error(request, f'{erro} O cadastro não foi aprovado; escolha outro colaborador ou nenhum.')
        else:
            if not aprovado_agora:
                messages.info(request, f'{usuario.email} já estava aprovado.')
            elif hasattr(usuario, 'colaborador'):
                messages.success(
                    request, f'Cadastro de {usuario.email} aprovado e vinculado a "{usuario.colaborador}".',
                )
            else:
                messages.success(request, f'Cadastro de {usuario.email} aprovado.')
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


# ---------------------------------------------------------------------------
# Convites: gestão (só administrador)
# ---------------------------------------------------------------------------
def _link_convite(request, convite):
    return request.build_absolute_uri(reverse('usuarios:convite_aceitar', args=[convite.token]))


def _avisar_envio(request, convite, enviado):
    if enviado:
        messages.success(request, f'Convite enviado por e-mail para {convite.email}.')
    else:
        messages.warning(
            request,
            f'Não foi possível enviar o e-mail para {convite.email}. Copie o link e envie de outra forma.',
        )


class ConvitesView(AdministradorMixin, FormView):
    form_class = ConviteForm
    template_name = 'usuarios/convites.html'
    extra_context = {'active_nav': 'convites'}

    def get_context_data(self, **kwargs):
        convites = list(usuarios_service.listar_convites())
        for convite in convites:
            convite.link = _link_convite(self.request, convite)
        kwargs['convites'] = convites
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        try:
            convite = usuarios_service.criar_convite(
                form.cleaned_data['email'], form.cleaned_data['validade_dias'], criado_por=self.request.user,
                colaborador=form.cleaned_data['colaborador'],
            )
        except usuarios_service.ConviteRecusado as erro:
            form.add_error(erro.campo, str(erro))
            return self.form_invalid(form)
        messages.success(self.request, f'Convite criado para {convite.email}.')
        if form.cleaned_data['enviar_por_email']:
            enviado = usuarios_service.enviar_convite(convite, _link_convite(self.request, convite))
            _avisar_envio(self.request, convite, enviado)
        return redirect('usuarios:convite_detalhe', pk=convite.pk)


class ConviteDetalheView(AdministradorMixin, DetailView):
    model = Convite
    template_name = 'usuarios/convite_detalhe.html'
    extra_context = {'active_nav': 'convites'}

    def get_context_data(self, **kwargs):
        kwargs['link'] = _link_convite(self.request, self.object)
        return super().get_context_data(**kwargs)


class ReenviarConviteView(AdministradorMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        convite = get_object_or_404(Convite, pk=pk)
        try:
            enviado = usuarios_service.enviar_convite(convite, _link_convite(request, convite))
        except usuarios_service.ConviteInvalido:
            messages.error(request, 'Só é possível enviar convites pendentes.')
        else:
            _avisar_envio(request, convite, enviado)
        return redirect('usuarios:convite_detalhe', pk=convite.pk)


class RevogarConviteView(AdministradorMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        try:
            email = usuarios_service.revogar_convite(pk)
        except Convite.DoesNotExist:
            raise Http404('Convite não encontrado.')
        except usuarios_service.ConviteRecusado as erro:
            messages.error(request, str(erro))
        else:
            messages.success(request, f'Convite para {email} revogado.')
        return redirect('usuarios:convites')
