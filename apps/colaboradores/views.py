from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from apps.colaboradores import colaboradores_service
from apps.colaboradores.forms import DepartamentoForm
from apps.colaboradores.models import Departamento
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
