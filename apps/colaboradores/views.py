from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from apps.colaboradores import colaboradores_service
from apps.colaboradores.forms import ColaboradorForm, DepartamentoForm, FiltroColaboradoresForm
from apps.colaboradores.models import Colaborador, Departamento
from apps.core.permissions import AdministradorMixin


# ---------------------------------------------------------------------------
# Departamentos (só administrador)
# ---------------------------------------------------------------------------
class DepartamentosView(AdministradorMixin, ListView):
    template_name = 'colaboradores/departamentos.html'
    context_object_name = 'departamentos'
    extra_context = {'active_nav': 'departamentos'}

    def get_queryset(self):
        return colaboradores_service.listar_departamentos()


class DepartamentoFormMixin(AdministradorMixin):
    model = Departamento
    form_class = DepartamentoForm
    template_name = 'colaboradores/departamento_form.html'
    success_url = reverse_lazy('colaboradores:departamentos')
    extra_context = {'active_nav': 'departamentos'}

    def form_valid(self, form):
        self.object = colaboradores_service.salvar_departamento(form.instance, self.request.user)
        messages.success(self.request, f'Departamento "{self.object.nome}" salvo.')
        return redirect(self.get_success_url())


class DepartamentoCriarView(DepartamentoFormMixin, CreateView):
    pass


class DepartamentoEditarView(DepartamentoFormMixin, UpdateView):
    pass


class DepartamentoExcluirView(AdministradorMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        try:
            nome = colaboradores_service.excluir_departamento(pk)
        except Departamento.DoesNotExist:
            raise Http404('Departamento não encontrado.')
        except colaboradores_service.DepartamentoEmUso as erro:
            messages.error(
                request,
                f'O departamento "{erro}" tem colaboradores e não pode ser excluído. '
                'Mude o departamento desses colaboradores antes.',
            )
        else:
            messages.success(request, f'Departamento "{nome}" excluído.')
        return redirect('colaboradores:departamentos')


# ---------------------------------------------------------------------------
# Colaboradores (só administrador)
# ---------------------------------------------------------------------------
class ColaboradoresView(AdministradorMixin, ListView):
    template_name = 'colaboradores/colaboradores.html'
    context_object_name = 'colaboradores'
    paginate_by = 50
    extra_context = {'active_nav': 'colaboradores'}

    def get_queryset(self):
        self.filtro = FiltroColaboradoresForm(self.request.GET or None)
        return colaboradores_service.filtrar_colaboradores(**self.filtro.filtros())

    def get_context_data(self, **kwargs):
        kwargs['filtro'] = self.filtro
        kwargs['sem_departamento'] = colaboradores_service.contar_sem_departamento()
        kwargs['filtro_sem_departamento'] = colaboradores_service.SEM_DEPARTAMENTO
        return super().get_context_data(**kwargs)


class ColaboradorFormMixin(AdministradorMixin):
    model = Colaborador
    form_class = ColaboradorForm
    template_name = 'colaboradores/colaborador_form.html'
    success_url = reverse_lazy('colaboradores:colaboradores')
    extra_context = {'active_nav': 'colaboradores'}

    def form_valid(self, form):
        self.object = colaboradores_service.salvar_colaborador(form.instance, self.request.user)
        messages.success(self.request, f'Colaborador "{self.object.nome}" salvo.')
        return redirect(self.get_success_url())


class ColaboradorCriarView(ColaboradorFormMixin, CreateView):
    pass


class ColaboradorEditarView(ColaboradorFormMixin, UpdateView):
    pass


class AlterarAtivoView(AdministradorMixin, View):
    """POST de ativar/desativar; volta para a lista com os mesmos filtros
    (``next``, só se for do próprio site)."""
    http_method_names = ['post']
    ativo = None

    def post(self, request, pk):
        try:
            colaborador = colaboradores_service.alterar_ativo(pk, self.ativo, request.user)
        except Colaborador.DoesNotExist:
            raise Http404('Colaborador não encontrado.')
        situacao = 'ativado' if self.ativo else 'desativado'
        messages.success(request, f'Colaborador "{colaborador.nome}" {situacao}.')
        destino = request.POST.get('next', '')
        if url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
            return redirect(destino)
        return redirect('colaboradores:colaboradores')
