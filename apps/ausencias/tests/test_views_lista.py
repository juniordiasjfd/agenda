"""Listagem: filtros (serviço e tela), parcial HTMX, atalho e queries."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.ausencias import ausencias_service
from apps.ausencias.ausencias_service import ausencias_filtradas
from apps.ausencias.tests.conftest import d
from apps.colaboradores.colaboradores_service import SEM_DEPARTAMENTO
from apps.colaboradores.models import Colaborador, Departamento

pytestmark = pytest.mark.django_db

URL = reverse('ausencias:lista')


@pytest.fixture
def ti(db):
    return Departamento.objects.create(nome='TI')


@pytest.fixture
def cenario(gravar_ausencia, colaborador, outro_colaborador, ferias, banco_horas, aprovado, cancelado, ti):
    """Ana (TI) e Bruno (sem departamento).

    a1: Ana, Férias, 02-06/03 (Planejado) e 16-20/03/2026 (Aprovado)
    a2: Ana, Banco de horas, 10/04/2026 (Cancelado)
    a3: Bruno, Férias, 01-05/06/2026 (Planejado)
    """
    colaborador.nome = 'Ana  Conceição'
    colaborador.departamento = ti
    colaborador.save()
    return {
        'a1': gravar_ausencia(colaborador, ferias, ('02/03/2026', '06/03/2026'), ('16/03/2026', '20/03/2026', aprovado)),
        'a2': gravar_ausencia(colaborador, banco_horas, ('10/04/2026', '10/04/2026', cancelado)),
        'a3': gravar_ausencia(outro_colaborador, ferias, ('01/06/2026', '05/06/2026')),
    }


def codigos(queryset):
    return {a.codigo for a in queryset}


def chaves(cenario, *nomes):
    return {cenario[nome].codigo for nome in nomes}


# ---------------------------------------------------------------------------
# Serviço
# ---------------------------------------------------------------------------
def test_sem_filtro_traz_tudo_menos_excluidas(cenario, gestor):
    ausencias_service.excluir_ausencia(cenario['a2'], gestor)

    assert codigos(ausencias_filtradas()) == chaves(cenario, 'a1', 'a3')


def test_ordem_inicio_mais_recente_primeiro(cenario):
    assert [a.codigo for a in ausencias_filtradas()] == [cenario[n].codigo for n in ('a3', 'a2', 'a1')]


@pytest.mark.parametrize('busca', ['conceicao', 'ANA   CONCEIÇÃO', ' ana conc'])
def test_filtro_nome_sem_acento_caixa_e_espacos(cenario, busca):
    assert codigos(ausencias_filtradas(nome=busca)) == chaves(cenario, 'a1', 'a2')


def test_filtro_departamento(cenario, ti):
    assert codigos(ausencias_filtradas(departamento=str(ti.pk))) == chaves(cenario, 'a1', 'a2')


def test_filtro_sem_departamento(cenario):
    assert codigos(ausencias_filtradas(departamento=SEM_DEPARTAMENTO)) == chaves(cenario, 'a3')


def test_filtro_tipo(cenario, banco_horas):
    assert codigos(ausencias_filtradas(tipo=banco_horas)) == chaves(cenario, 'a2')


def test_filtro_situacao_em_algum_periodo(cenario, aprovado, planejado):
    assert codigos(ausencias_filtradas(situacao=aprovado)) == chaves(cenario, 'a1')
    assert codigos(ausencias_filtradas(situacao=planejado)) == chaves(cenario, 'a1', 'a3')


@pytest.mark.parametrize('de, ate, esperadas', [
    ('06/03/2026', '06/03/2026', {'a1'}),              # toca o último dia (fim inclusivo)
    ('07/03/2026', '15/03/2026', set()),               # entre os dois períodos de a1
    ('01/04/2026', '30/06/2026', {'a2', 'a3'}),
    ('20/03/2026', None, {'a1', 'a2', 'a3'}),          # só "de": em aberto à direita
    (None, '01/03/2026', set()),
    (None, '02/03/2026', {'a1'}),                      # só "até"
])
def test_filtro_ausencia_em(cenario, de, ate, esperadas):
    resultado = ausencias_filtradas(de=d(de) if de else None, ate=d(ate) if ate else None)

    assert codigos(resultado) == chaves(cenario, *esperadas)


def test_situacao_e_periodo_no_mesmo_periodo(cenario, aprovado):
    """a1 tem Aprovado só em 16-20/03: filtrar Aprovado em 02-06/03 não traz."""
    assert codigos(ausencias_filtradas(situacao=aprovado, de=d('02/03/2026'), ate=d('06/03/2026'))) == set()
    assert codigos(ausencias_filtradas(situacao=aprovado, de=d('18/03/2026'))) == chaves(cenario, 'a1')


def test_lixeira_so_excluidas(cenario, gestor):
    ausencias_service.excluir_ausencia(cenario['a3'], gestor)

    assert codigos(ausencias_filtradas(na_lixeira=True)) == chaves(cenario, 'a3')
    assert codigos(ausencias_filtradas(na_lixeira=True, nome='ana')) == set()


# ---------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------
def lista(response):
    return {a.codigo for a in response.context['ausencias']}


def test_tela_sem_filtro(gestor_client, cenario):
    response = gestor_client.get(URL)

    assert response.status_code == 200
    assert lista(response) == chaves(cenario, 'a1', 'a2', 'a3')
    assert 'ausencias/ausencias.html' in [t.name for t in response.templates]


@pytest.mark.parametrize('parametros, esperadas', [
    ({'nome': 'conceição'}, {'a1', 'a2'}),
    ({'departamento': SEM_DEPARTAMENTO}, {'a3'}),
    ({'de': '2026-04-01', 'ate': '2026-04-30'}, {'a2'}),
])
def test_tela_filtros_por_get(gestor_client, cenario, parametros, esperadas):
    assert lista(gestor_client.get(URL, parametros)) == chaves(cenario, *esperadas)


def test_tela_filtros_tipo_situacao_e_departamento(gestor_client, cenario, banco_horas, aprovado, ti):
    assert lista(gestor_client.get(URL, {'tipo': banco_horas.pk})) == chaves(cenario, 'a2')
    assert lista(gestor_client.get(URL, {'situacao': aprovado.pk})) == chaves(cenario, 'a1')
    assert lista(gestor_client.get(URL, {'departamento': ti.pk})) == chaves(cenario, 'a1', 'a2')


def test_tela_filtro_invalido_e_ignorado(gestor_client, cenario):
    response = gestor_client.get(URL, {'tipo': 'xyz', 'de': '2026-99-99', 'nome': 'bruno'})

    assert lista(response) == chaves(cenario, 'a3')


def test_tela_mostra_dados_da_linha(gestor_client, cenario):
    html = gestor_client.get(URL).content.decode()

    assert 'Ana Conceição' in html
    assert '02/03/2026 a 06/03/2026' in html
    assert 'Sem departamento' in html
    assert '>10<' in html  # total de dias de a1 (5 + 5)


def test_parcial_htmx(gestor_client, cenario):
    response = gestor_client.get(URL, {'nome': 'bruno'}, HTTP_HX_REQUEST='true', HTTP_HX_TARGET='tabela-ausencias')

    nomes = [t.name for t in response.templates]
    assert 'ausencias/_tabela_ausencias.html' in nomes
    assert 'ausencias/ausencias.html' not in nomes
    assert lista(response) == chaves(cenario, 'a3')
    assert not response.content.decode().lstrip().startswith('<!DOCTYPE')


def test_htmx_sem_alvo_da_tabela_devolve_pagina_inteira(gestor_client, cenario):
    """Ex.: restauração de histórico do HTMX."""
    response = gestor_client.get(URL, HTTP_HX_REQUEST='true', HTTP_HX_HISTORY_RESTORE_REQUEST='true')

    assert 'ausencias/ausencias.html' in [t.name for t in response.templates]


def test_formulario_de_filtros_com_htmx_e_url_compartilhavel(gestor_client, cenario):
    html = gestor_client.get(URL).content.decode()

    assert 'hx-target="#tabela-ausencias"' in html
    assert 'hx-push-url="true"' in html


def test_atalho_a_partir_de_hoje(gestor_client, cenario, colaborador, ferias, gravar_ausencia):
    hoje = timezone.localdate()
    ontem, amanha = hoje - timedelta(days=1), hoje + timedelta(days=1)
    passada = gravar_ausencia(colaborador, ferias, (f'{ontem - timedelta(days=5):%d/%m/%Y}', f'{ontem:%d/%m/%Y}'))
    futura = gravar_ausencia(colaborador, ferias, (f'{amanha:%d/%m/%Y}', f'{amanha:%d/%m/%Y}'))
    em_curso = gravar_ausencia(colaborador, ferias, (f'{ontem:%d/%m/%Y}', f'{amanha:%d/%m/%Y}'))

    html = gestor_client.get(URL, {'nome': 'ana'}).content.decode()
    atalho = f'{URL}?nome=ana&amp;de={hoje:%Y-%m-%d}'
    assert atalho in html

    response = gestor_client.get(URL, {'nome': 'ana', 'de': f'{hoje:%Y-%m-%d}'})
    encontrados = lista(response)
    assert futura.codigo in encontrados and em_curso.codigo in encontrados
    assert passada.codigo not in encontrados


def test_paginacao(gestor_client, colaborador, ferias, gravar_ausencia):
    for dia in range(1, 28):
        gravar_ausencia(colaborador, ferias, (f'{dia:02d}/01/2026', f'{dia:02d}/01/2026'))

    pagina1 = gestor_client.get(URL)
    pagina2 = gestor_client.get(URL, {'page': 2})

    assert len(pagina1.context['ausencias']) == 25
    assert len(pagina2.context['ausencias']) == 2
    assert 'hx-get="?page=2"' in pagina1.content.decode()


def test_sem_n_mais_1(gestor_client, ferias, gravar_ausencia):
    """O número de queries não cresce com o número de ausências."""
    def contar():
        with CaptureQueriesContext(connection) as contexto:
            assert gestor_client.get(URL).status_code == 200
        return len(contexto)

    departamento = Departamento.objects.create(nome='RH')
    for i in range(2):
        pessoa = Colaborador.objects.create(nome=f'Pessoa {i}', departamento=departamento)
        gravar_ausencia(pessoa, ferias, ('01/02/2026', '02/02/2026'), ('10/02/2026', '11/02/2026'))
    poucas = contar()

    for i in range(2, 12):
        pessoa = Colaborador.objects.create(nome=f'Pessoa {i}', departamento=departamento)
        gravar_ausencia(pessoa, ferias, ('01/02/2026', '02/02/2026'), ('10/02/2026', '11/02/2026'))
    muitas = contar()

    assert muitas == poucas
