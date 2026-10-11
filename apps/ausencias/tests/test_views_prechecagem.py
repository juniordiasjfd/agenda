"""Pré-checagem (aviso antecipado) e linha do ano da tela de registro/edição."""

import re

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.ausencias import ausencias_service
from apps.ausencias.tests.conftest import d, dados_formulario, linha

pytestmark = pytest.mark.django_db

URL = reverse('ausencias:prechecagem')


def avisos(response):
    """{id do aviso: [mensagens]} dos blocos fora da banda."""
    html = response.content.decode()
    blocos = re.findall(r'<div id="aviso-([^"]+)" hx-swap-oob="true">(.*?)\n  </div>', html, re.S)
    return {
        prefixo: [m.strip() for m in re.findall(r'</i>([^<]+)</div>', corpo)]
        for prefixo, corpo in blocos
    }


def segmentos(response):
    return re.findall(r'class="linha-ano-seg ([^"]+)" title="([^"]+)"', response.content.decode())


@pytest.fixture
def hoje():
    return timezone.localdate()


@pytest.fixture
def registrada(colaborador, ferias, gestor, hoje):
    """Férias de Ana em 10 a 12 de março do ano corrente."""
    return ausencias_service.criar_ausencia(
        colaborador, ferias,
        [ausencias_service.PeriodoInformado(hoje.replace(month=3, day=10), hoje.replace(month=3, day=12))],
        '', gestor,
    )


def data(hoje, dia, mes=3):
    return f'{dia:02d}/{mes:02d}/{hoje.year}'


def test_mesmas_mensagens_do_servico_por_linha(gestor_client, registrada, colaborador, banco_horas, hoje):
    linhas = [linha(data(hoje, 1), data(hoje, 2)), linha(data(hoje, 11), data(hoje, 11))]

    response = gestor_client.post(URL, dados_formulario(colaborador, banco_horas, *linhas))

    esperado = [
        c.mensagem for c in ausencias_service.periodos_conflitantes(
            colaborador, [ausencias_service.PeriodoInformado(d(l['inicio']), d(l['fim'])) for l in linhas],
        )
    ]
    assert avisos(response) == {'periodos-0': [], 'periodos-1': esperado}
    assert esperado == [f'Sobrepõe Férias já registrado de 10/03/{hoje.year} a 12/03/{hoje.year}.']


def test_linha_removida_no_meio_nao_desloca_os_avisos(gestor_client, registrada, colaborador, banco_horas, hoje):
    response = gestor_client.post(URL, dados_formulario(
        colaborador, banco_horas,
        linha(data(hoje, 11), data(hoje, 11), remover=True),
        linha(data(hoje, 1), data(hoje, 2)),
        linha(data(hoje, 12), data(hoje, 12)),
    ))

    resultado = avisos(response)
    assert resultado['periodos-0'] == [] and resultado['periodos-1'] == []
    assert len(resultado['periodos-2']) == 1


def test_edicao_ignora_os_proprios_periodos(gestor_client, registrada, colaborador, ferias, hoje):
    periodo = registrada.periodos.get()

    response = gestor_client.post(
        reverse('ausencias:prechecagem_edicao', args=[registrada.pk]),
        dados_formulario(colaborador, ferias, linha(data(hoje, 10), data(hoje, 13), id=periodo.pk), iniciais=1),
    )

    assert avisos(response) == {'periodos-0': []}


def test_situacao_que_nao_conta_nao_avisa(gestor_client, registrada, colaborador, banco_horas, cancelado, hoje):
    response = gestor_client.post(URL, dados_formulario(
        colaborador, banco_horas, linha(data(hoje, 11), data(hoje, 11), situacao=cancelado),
    ))

    assert avisos(response) == {'periodos-0': []}


def test_linha_do_ano_mostra_registrados_e_os_do_formulario(gestor_client, registrada, colaborador, banco_horas, hoje, gestor, ferias):
    excluida = ausencias_service.criar_ausencia(
        colaborador, ferias,
        [ausencias_service.PeriodoInformado(hoje.replace(month=5, day=1), hoje.replace(month=5, day=1))], '', gestor,
    )
    ausencias_service.excluir_ausencia(excluida, gestor)

    response = gestor_client.post(URL, dados_formulario(
        colaborador, banco_horas, linha(data(hoje, 1), data(hoje, 2)), linha(data(hoje, 11), data(hoje, 11)),
    ))

    ano = hoje.year
    assert segmentos(response) == [
        ('registrado', f'Férias (Planejado) 10/03/{ano} a 12/03/{ano}'),
        ('novo', f'Neste registro: 01/03/{ano} a 02/03/{ano}'),
        ('conflito', f'Neste registro: 11/03/{ano} a 11/03/{ano}'),
    ]
    html = response.content.decode()
    assert f'<b>{ano}</b>' in html and f'<b>{ano + 1}</b>' in html
    assert 'linha-ano-hoje' in html


def test_linha_do_ano_posicao_sem_virgula_decimal(gestor_client, registrada, colaborador, ferias):
    """Com pt-BR, um float no template sairia "12,5%": o CSS precisa de ponto."""
    response = gestor_client.post(URL, dados_formulario(colaborador, ferias))

    assert re.search(r'left: \d+\.\d\d%', response.content.decode())
    assert not re.search(r'left: \d+,\d', response.content.decode())


def test_periodo_que_atravessa_o_ano_aparece_nos_dois(gestor_client, colaborador, ferias, hoje):
    response = gestor_client.post(URL, dados_formulario(
        colaborador, ferias, linha(data(hoje, 20, 12), f'05/01/{hoje.year + 1}'),
    ))

    assert [classe for classe, _ in segmentos(response)] == ['novo', 'novo']


def test_sem_colaborador_mostra_dica(gestor_client, ferias, hoje):
    response = gestor_client.post(URL, dados_formulario(None, ferias, linha(data(hoje, 1), data(hoje, 2))))

    html = response.content.decode()
    assert 'Escolha o colaborador' in html
    assert avisos(response) == {'periodos-0': []}


def test_no_carregamento_so_a_linha_do_ano(gestor_client, registrada, colaborador, banco_horas, hoje):
    dados = dados_formulario(colaborador, banco_horas, linha(data(hoje, 11), data(hoje, 11)))
    dados['evento_prechecagem'] = 'load'

    response = gestor_client.post(URL, dados)

    assert avisos(response) == {}
    assert ('conflito', f'Neste registro: 11/03/{hoje.year} a 11/03/{hoje.year}') in segmentos(response)


def test_nao_grava_nada(gestor_client, colaborador, ferias, hoje):
    gestor_client.post(URL, dados_formulario(colaborador, ferias, linha(data(hoje, 1), data(hoje, 2))))

    assert not colaborador.ausencias.exists()


def test_formulario_dispara_a_prechecagem(gestor_client, registrada):
    html = gestor_client.get(reverse('ausencias:registrar')).content.decode()
    assert f'hx-post="{URL}"' in html
    assert 'id="aviso-periodos-0"' in html

    html = gestor_client.get(reverse('ausencias:editar', args=[registrada.pk])).content.decode()
    assert f'hx-post="{reverse("ausencias:prechecagem_edicao", args=[registrada.pk])}"' in html
