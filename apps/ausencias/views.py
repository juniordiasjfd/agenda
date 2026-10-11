from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView, ListView

from apps.ausencias import ausencias_service
from apps.ausencias.forms import ConfirmarApagarForm, FiltroAusenciasForm, FiltroLixeiraForm, montar_formularios
from apps.ausencias.models import Ausencia
from apps.core.permissions import AdministradorMixin, GestorMixin


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
class AusenciasView(LoginRequiredMixin, ListView):
    """Lista com filtros por GET (URL compartilhável). Com HTMX mirando a
    tabela, devolve só o parcial; sem JavaScript, a página inteira."""
    template_name = 'ausencias/ausencias.html'
    template_parcial = 'ausencias/_tabela_ausencias.html'
    alvo_htmx = 'tabela-ausencias'
    context_object_name = 'ausencias'
    paginate_by = 25
    extra_context = {'active_nav': 'ausencias'}

    def get_queryset(self):
        self.filtro = FiltroAusenciasForm(self.request.GET or None)
        return ausencias_service.ausencias_filtradas(**self.filtro.filtros())

    def get_template_names(self):
        if self.request.headers.get('HX-Target') == self.alvo_htmx:
            return [self.template_parcial]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        kwargs['filtro'] = self.filtro
        kwargs['hoje'] = timezone.localdate()
        # Para voltar à lista com os mesmos filtros depois de excluir. No
        # parcial HTMX, a URL da requisição tem os mesmos parâmetros.
        kwargs['voltar'] = reverse('ausencias:lista') + (f'?{self.request.GET.urlencode()}' if self.request.GET else '')
        return super().get_context_data(**kwargs)


# ---------------------------------------------------------------------------
# Registro e edição (mesma tela)
# ---------------------------------------------------------------------------
class AusenciaFormMixin(GestorMixin):
    """GET mostra o formulário; POST valida (o formset chama o serviço) e
    grava pelo serviço. Erro de validação na gravação (ex.: outro registro
    do mesmo colaborador gravado entre a validação e a trava) volta para a
    tela com as mensagens nos lugares certos."""
    template_name = 'ausencias/ausencia_form.html'
    ausencia = None

    def get(self, request, *args, **kwargs):
        cabecalho, periodos = montar_formularios(ausencia=self.ausencia, usuario=request.user)
        return self.renderizar(cabecalho, periodos)

    def post(self, request, *args, **kwargs):
        cabecalho, periodos = montar_formularios(request.POST, ausencia=self.ausencia, usuario=request.user)
        valido = periodos.is_valid()
        valido = cabecalho.is_valid() and valido
        if valido:
            try:
                ausencia = self.gravar(cabecalho.cleaned_data, periodos.periodos_informados)
            except ausencias_service.AusenciaAlterada:
                cabecalho.add_error(None, ausencias_service.MENSAGEM_ALTERADA_POR_OUTRO)
            except ausencias_service.ErroValidacaoAusencia as erro:
                periodos.aplicar_erros(erro)
            else:
                messages.success(request, self.mensagem_sucesso(ausencia))
                return redirect('ausencias:detalhe', ausencia.pk)
        return self.renderizar(cabecalho, periodos)

    def renderizar(self, cabecalho, periodos):
        return render(self.request, self.template_name, {
            'cabecalho': cabecalho,
            'periodos': periodos,
            'ausencia': self.ausencia,
            'hoje': timezone.localdate(),
            'max_periodos': ausencias_service.MAX_PERIODOS,
            'active_nav': 'registrar' if self.ausencia is None else 'ausencias',
        })


class AusenciaCriarView(AusenciaFormMixin, View):
    def gravar(self, dados, periodos):
        return ausencias_service.criar_ausencia(
            dados['colaborador'], dados['tipo'], periodos, dados['observacoes'], self.request.user,
        )

    def mensagem_sucesso(self, ausencia):
        return f'Ausência {ausencia.codigo} registrada ({ausencia.titulo}).'


class AusenciaEditarView(AusenciaFormMixin, View):
    def dispatch(self, request, *args, **kwargs):
        # A permissão (GestorMixin.dispatch) vem antes de qualquer consulta.
        if not request.user.is_authenticated or not self.test_func():
            return self.handle_no_permission()
        self.ausencia = get_object_or_404(
            Ausencia.todos.select_related('colaborador', 'tipo'), pk=kwargs['pk'],
        )
        if self.ausencia.esta_excluido:
            messages.warning(request, 'Esta ausência está na lixeira. Restaure antes de editar.')
            return redirect('ausencias:detalhe', self.ausencia.pk)
        return super().dispatch(request, *args, **kwargs)

    def gravar(self, dados, periodos):
        return ausencias_service.atualizar_ausencia(
            self.ausencia, dados['colaborador'], dados['tipo'], periodos, dados['observacoes'], self.request.user,
            versao=dados['versao'],
        )

    def mensagem_sucesso(self, ausencia):
        return f'Ausência {ausencia.codigo} atualizada ({ausencia.titulo}).'


# ---------------------------------------------------------------------------
# Detalhe e exclusão
# ---------------------------------------------------------------------------
def _destino_seguro(request, padrao):
    """``next`` do POST/GET, se for deste site; senão ``padrao``."""
    destino = request.POST.get('next') or request.GET.get('next') or ''
    if url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return destino
    return padrao


class AusenciaDetalheView(LoginRequiredMixin, DetailView):
    """Somente leitura; mostra também as que estão na lixeira."""
    template_name = 'ausencias/ausencia_detalhe.html'
    context_object_name = 'ausencia'

    def get_queryset(self):
        return Ausencia.todos.select_related(
            'colaborador__departamento', 'tipo', 'criado_por', 'atualizado_por', 'excluido_por',
        ).prefetch_related('periodos__situacao')

    def get_context_data(self, **kwargs):
        kwargs['active_nav'] = 'lixeira' if self.object.esta_excluido else 'ausencias'
        return super().get_context_data(**kwargs)


class AusenciaExcluirView(GestorMixin, View):
    """GET: confirmação (conteúdo do modal com HTMX; página própria sem
    JavaScript). POST: manda para a lixeira e volta à lista."""

    def get(self, request, pk):
        ausencia = get_object_or_404(Ausencia.objects.select_related('colaborador', 'tipo'), pk=pk)
        template = 'ausencias/_modal_excluir.html' if request.headers.get('HX-Request') else 'ausencias/excluir.html'
        return render(request, template, {
            'ausencia': ausencia,
            'voltar': _destino_seguro(request, ''),
            'active_nav': 'ausencias',
        })

    def post(self, request, pk):
        ausencia = get_object_or_404(Ausencia.todos, pk=pk)
        ausencia = ausencias_service.excluir_ausencia(ausencia, request.user)
        messages.success(request, f'Ausência {ausencia.codigo} enviada para a lixeira.')
        return redirect(_destino_seguro(request, reverse('ausencias:lista')))


# ---------------------------------------------------------------------------
# Lixeira
# ---------------------------------------------------------------------------
class LixeiraView(LoginRequiredMixin, ListView):
    """Visível a qualquer autenticado; as ações são só para gestor
    (restaurar) e administrador (apagar de vez)."""
    template_name = 'ausencias/lixeira.html'
    context_object_name = 'ausencias'
    paginate_by = 25
    extra_context = {'active_nav': 'lixeira'}

    def get_queryset(self):
        self.filtro = FiltroLixeiraForm(self.request.GET or None)
        return ausencias_service.ausencias_filtradas(na_lixeira=True, **self.filtro.filtros())

    def get_context_data(self, **kwargs):
        kwargs['filtro'] = self.filtro
        kwargs['voltar'] = self.request.get_full_path()
        return super().get_context_data(**kwargs)


def _na_lixeira(pk):
    return get_object_or_404(Ausencia.todos.filter(excluido_em__isnull=False), pk=pk)


class AusenciaRestaurarView(GestorMixin, View):
    """Tira da lixeira. Em conflito com o que foi registrado depois da
    exclusão, mostra as mensagens do serviço e ela continua na lixeira."""
    http_method_names = ['post']

    def post(self, request, pk):
        ausencia = _na_lixeira(pk)
        try:
            ausencia = ausencias_service.restaurar_ausencia(ausencia, request.user)
        except ausencias_service.ErroValidacaoAusencia as erro:
            for mensagem in erro.mensagens():
                messages.error(request, mensagem)
            return redirect(_destino_seguro(request, reverse('ausencias:lixeira')))
        messages.success(request, f'Ausência {ausencia.codigo} restaurada.')
        return redirect('ausencias:detalhe', ausencia.pk)


class AusenciaApagarView(AdministradorMixin, View):
    """Apaga do banco (só administrador, só da lixeira), depois de digitar o
    código da ausência."""
    template_name = 'ausencias/apagar.html'

    def get(self, request, pk):
        ausencia = _na_lixeira(pk)
        return self.renderizar(ausencia, ConfirmarApagarForm(ausencia=ausencia))

    def post(self, request, pk):
        ausencia = _na_lixeira(pk)
        form = ConfirmarApagarForm(request.POST, ausencia=ausencia)
        if not form.is_valid():
            return self.renderizar(ausencia, form)
        try:
            codigo = ausencias_service.apagar_definitivamente(ausencia)
        except ausencias_service.ErroValidacaoAusencia as erro:
            for mensagem in erro.mensagens():
                messages.error(request, mensagem)
            return redirect('ausencias:detalhe', ausencia.pk)
        messages.success(request, f'Ausência {codigo} apagada definitivamente.')
        return redirect('ausencias:lixeira')

    def renderizar(self, ausencia, form):
        return render(self.request, self.template_name, {'ausencia': ausencia, 'form': form, 'active_nav': 'lixeira'})
