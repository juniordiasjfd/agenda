from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.ausencias import ausencias_service
from apps.ausencias.forms import montar_formularios
from apps.ausencias.models import Ausencia
from apps.core.permissions import GestorMixin


class AusenciasView(LoginRequiredMixin, TemplateView):
    template_name = 'ausencias/em_construcao.html'
    extra_context = {'active_nav': 'ausencias', 'titulo': 'Ausências'}


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
            except ausencias_service.ErroValidacaoAusencia as erro:
                periodos.aplicar_erros(erro)
            else:
                messages.success(request, self.mensagem_sucesso(ausencia))
                return redirect('ausencias:lista')
        return self.renderizar(cabecalho, periodos)

    def renderizar(self, cabecalho, periodos):
        return render(self.request, self.template_name, {
            'cabecalho': cabecalho,
            'periodos': periodos,
            'ausencia': self.ausencia,
            'hoje': timezone.localdate(),
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
            return redirect('ausencias:lista')
        return super().dispatch(request, *args, **kwargs)

    def gravar(self, dados, periodos):
        return ausencias_service.atualizar_ausencia(
            self.ausencia, dados['colaborador'], dados['tipo'], periodos, dados['observacoes'], self.request.user,
        )

    def mensagem_sucesso(self, ausencia):
        return f'Ausência {ausencia.codigo} atualizada ({ausencia.titulo}).'


# ---------------------------------------------------------------------------
# Lixeira
# ---------------------------------------------------------------------------
class LixeiraView(LoginRequiredMixin, TemplateView):
    template_name = 'ausencias/em_construcao.html'
    extra_context = {'active_nav': 'lixeira', 'titulo': 'Lixeira'}
