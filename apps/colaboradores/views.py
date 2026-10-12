from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from apps.colaboradores import colaboradores_service
from apps.colaboradores.forms import (
    ColaboradorForm,
    DepartamentoForm,
    FiltroColaboradoresForm,
    ImportarColaboradoresForm,
)
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
        kwargs['departamentos'] = Departamento.objects.all()
        kwargs['voltar'] = self.request.get_full_path()
        return super().get_context_data(**kwargs)


class AlterarDepartamentoView(AdministradorMixin, View):
    """Edição rápida do departamento na lista (HTMX, salva ao mudar o
    select). Devolve a linha atualizada e, fora da banda, o aviso de
    colaboradores sem departamento."""
    http_method_names = ['post']

    def post(self, request, pk):
        try:
            colaborador = colaboradores_service.alterar_departamento(
                pk, request.POST.get('departamento') or None, request.user,
            )
        except Colaborador.DoesNotExist:
            raise Http404('Colaborador não encontrado.')
        except (Departamento.DoesNotExist, ValueError):
            return HttpResponseBadRequest('Departamento inválido.')
        if not request.headers.get('HX-Request'):
            messages.success(request, f'Departamento de "{colaborador.nome}" alterado.')
            return redirect('colaboradores:colaboradores')
        return render(request, 'colaboradores/_departamento_alterado.html', {
            'colaborador': colaborador,
            'departamentos': Departamento.objects.all(),
            'sem_departamento': colaboradores_service.contar_sem_departamento(),
            'filtro_sem_departamento': colaboradores_service.SEM_DEPARTAMENTO,
            # Página de onde veio o HTMX, para o "next" de ativar/desativar.
            'voltar': request.headers.get('HX-Current-URL', ''),
        })


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


class ImportarColaboradoresView(AdministradorMixin, View):
    """CSV ``Colaborador;Departamento``: simula (padrão) ou grava e mostra o
    resumo na mesma página. Depois de simular, o formulário volta com a
    simulação desmarcada (próximo passo: gravar)."""
    template_name = 'colaboradores/importar.html'

    def get(self, request):
        return self.renderizar(ImportarColaboradoresForm())

    def post(self, request):
        form = ImportarColaboradoresForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.renderizar(form)
        try:
            linhas = colaboradores_service.ler_csv_colaboradores(form.cleaned_data['arquivo'])
        except colaboradores_service.ArquivoColaboradoresInvalido as erro:
            form.add_error('arquivo', str(erro))
            return self.renderizar(form)
        resultado = colaboradores_service.importar_colaboradores(
            linhas, request.user, simular=form.cleaned_data['simular'],
        )
        if not resultado.simulado:
            messages.success(
                request,
                f'Importação concluída: {len(resultado.criados)} colaborador(es) criado(s) e '
                f'{len(resultado.atualizados)} atualizado(s).',
            )
        return self.renderizar(ImportarColaboradoresForm(initial={'simular': not resultado.simulado}), resultado)

    def renderizar(self, form, resultado=None):
        return render(self.request, self.template_name, {
            'form': form,
            'resultado': resultado,
            'max_registros': settings.CSV_IMPORTACAO_MAX_REGISTROS,
            'max_megas': f'{settings.CSV_IMPORTACAO_MAX_BYTES / (1024 * 1024):g}',
            'active_nav': 'colaboradores',
        })
