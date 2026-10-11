"""Painel Gantt: a página (filtros) e o endpoint JSON que o painel.js desenha.

Views finas: leem a querystring, chamam ``painel_service`` e devolvem.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.ausencias import painel_service


def filtros_da_querystring(get):
    """``FiltrosPainel`` a partir de ``request.GET``. ``sem_registros``: vale
    o ÚLTIMO valor (o formulário manda um hidden "0" antes da caixa "1")."""
    return painel_service.ler_filtros(
        q=get.get('q', ''),
        departamentos=get.getlist('departamento'),
        ausente_de=get.get('ausente_de', ''),
        ausente_ate=get.get('ausente_ate', ''),
        presente_de=get.get('presente_de', ''),
        presente_ate=get.get('presente_ate', ''),
        sem_registros=(get.getlist('sem_registros') or [None])[-1],
    )


class PainelDadosView(LoginRequiredMixin, View):
    """``GET painel/dados/``: pessoas e períodos do painel em JSON. Qualquer
    autenticado; anônimo vai para o login (302), como nas demais telas.
    ``hoje`` é a data do servidor (America/Sao_Paulo), não a do navegador."""

    def get(self, request):
        painel = painel_service.montar_painel(filtros_da_querystring(request.GET), timezone.localdate())
        resposta = JsonResponse(painel_service.painel_para_json(painel), json_dumps_params={'ensure_ascii': False})
        resposta['Cache-Control'] = 'no-store'
        return resposta


class PainelView(LoginRequiredMixin, TemplateView):
    """``GET painel/``: página inicial depois do login. O formulário de
    filtros é um GET comum (URL compartilhável); o Gantt é desenhado pelo
    painel.js com os dados de ``painel/dados/`` e a mesma querystring."""
    template_name = 'ausencias/painel.html'
    extra_context = {'active_nav': 'painel'}

    def get_context_data(self, **kwargs):
        get = self.request.GET
        filtros = filtros_da_querystring(get)
        departamentos = list(painel_service.departamentos_para_escolha())
        kwargs.update(
            filtros=filtros,
            departamentos=departamentos,
            rotulo_departamentos=painel_service.rotulo_departamentos(filtros.departamentos, departamentos),
            # Textos como vieram, para o formulário mostrar o que foi digitado.
            valores={campo: get.get(campo, '') for campo in (
                'q', 'ausente_de', 'ausente_ate', 'presente_de', 'presente_ate',
            )},
        )
        return super().get_context_data(**kwargs)
