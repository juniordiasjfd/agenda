"""Painel Gantt: endpoint JSON (e, na próxima etapa, a página).

Views finas: leem a querystring, chamam ``painel_service`` e devolvem.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View

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
