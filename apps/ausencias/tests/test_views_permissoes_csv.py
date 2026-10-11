"""Matriz de permissões das telas de CSV: anônimo / autenticado sem grupo
/ gestor / administrador. Importação: só administrador. Exportação:
qualquer autenticado. O controle é na view (o menu escondido é só
conveniência)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ausencias import csv_service
from apps.ausencias.models import Ausencia, ImportacaoCSV
from apps.ausencias.tests.test_views_permissoes import esperado, perfil  # noqa: F401 (fixture)

pytestmark = pytest.mark.django_db


def arquivo():
    texto = 'Colaborador;TipoEvento;DataInicio;DataFim\r\nAna Souza;Férias;2026-03-02;2026-03-06\r\n'
    return SimpleUploadedFile('a.csv', texto.encode())


@pytest.fixture
def importacao(admin, colaborador, ferias):
    return csv_service.criar_importacao([arquivo()], admin)


@pytest.fixture
def aplicada(admin, colaborador, ferias):
    importacao = csv_service.criar_importacao([arquivo()], admin)
    previa = csv_service.analisar_importacao(importacao)
    return csv_service.aplicar_importacao(importacao, None, previa.assinatura, admin)


def _verificar(perfil_nome, resposta, ok):
    assert resposta.status_code == esperado(perfil_nome, admin=True, ok=ok)
    if perfil_nome == 'anonimo':
        assert reverse('usuarios:login') in resposta['Location']
    elif ok == 302 and perfil_nome == 'admin':
        assert reverse('usuarios:login') not in resposta['Location']


def test_exportar(perfil):
    nome, client = perfil
    resposta = client.get(reverse('ausencias:exportar'))
    assert resposta.status_code == esperado(nome, visualizar=True)


def test_importar_get(perfil):
    nome, client = perfil
    _verificar(nome, client.get(reverse('ausencias:importar')), ok=200)


def test_importar_post(perfil, colaborador, ferias):
    nome, client = perfil
    _verificar(nome, client.post(reverse('ausencias:importar'), {'arquivos': [arquivo()]}), ok=302)
    assert ImportacaoCSV.objects.exists() is (nome == 'admin')


def test_previa_get(perfil, importacao):
    nome, client = perfil
    _verificar(nome, client.get(reverse('ausencias:importacao_previa', args=[importacao.pk])), ok=200)


def test_previa_post_recalcular(perfil, importacao):
    nome, client = perfil
    resposta = client.post(reverse('ausencias:importacao_previa', args=[importacao.pk]), {'criar_tipos': ['x']})
    _verificar(nome, resposta, ok=302)
    importacao.refresh_from_db()
    assert bool(importacao.decisoes) is (nome == 'admin')


def test_confirmar(perfil, importacao):
    nome, client = perfil
    assinatura = csv_service.analisar_importacao(importacao).assinatura
    resposta = client.post(reverse('ausencias:importacao_confirmar', args=[importacao.pk]), {'assinatura': assinatura})
    _verificar(nome, resposta, ok=302)
    assert Ausencia.objects.exists() is (nome == 'admin')


def test_cancelar(perfil, importacao):
    nome, client = perfil
    _verificar(nome, client.post(reverse('ausencias:importacao_cancelar', args=[importacao.pk])), ok=302)
    importacao.refresh_from_db()
    assert (importacao.status == ImportacaoCSV.CANCELADA) is (nome == 'admin')


def test_resultado(perfil, aplicada):
    nome, client = perfil
    _verificar(nome, client.get(reverse('ausencias:importacao_resultado', args=[aplicada.pk])), ok=200)


def test_nao_importadas_da_previa(perfil, importacao):
    nome, client = perfil
    _verificar(nome, client.get(reverse('ausencias:importacao_nao_importadas', args=[importacao.pk])), ok=200)


def test_nao_importadas_do_resultado(perfil, aplicada):
    nome, client = perfil
    _verificar(nome, client.get(reverse('ausencias:importacao_nao_importadas', args=[aplicada.pk])), ok=200)


@pytest.mark.parametrize('rota', ['importacao_confirmar', 'importacao_cancelar'])
def test_acoes_so_por_post(admin_client, importacao, rota):
    assert admin_client.get(reverse(f'ausencias:{rota}', args=[importacao.pk])).status_code == 405
