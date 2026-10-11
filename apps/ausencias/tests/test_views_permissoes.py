"""Permissões por perfil em todas as telas de ausências.

anônimo -> login; autenticado sem grupo -> só visualiza; gestor -> grava;
superuser -> também apaga de vez.
"""

import pytest
from django.urls import reverse

from apps.ausencias import ausencias_service
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db

LOGIN = 302
NEGADO = 403


@pytest.fixture
def ausencia(colaborador, ferias, gestor):
    return ausencias_service.criar_ausencia(
        colaborador, ferias, [ausencias_service.PeriodoInformado(d('02/03/2026'), d('06/03/2026'))], '', gestor,
    )


@pytest.fixture(params=['anonimo', 'sem_grupo', 'gestor', 'admin'])
def perfil(request, client):
    """(nome do perfil, client logado como ele)."""
    nome = request.param
    if nome != 'anonimo':
        usuario = request.getfixturevalue({'sem_grupo': 'usuario_ativo', 'gestor': 'gestor', 'admin': 'admin'}[nome])
        client.force_login(usuario)
    return nome, client


def esperado(perfil_nome, visualizar=False, gestor=False, admin=False, ok=200):
    """Status esperado para o perfil, dado quem pode acessar."""
    if perfil_nome == 'anonimo':
        return LOGIN
    permitido = {
        'sem_grupo': visualizar,
        'gestor': visualizar or gestor,
        'admin': visualizar or gestor or admin,
    }[perfil_nome]
    return ok if permitido else NEGADO


def test_lista(perfil):
    nome, client = perfil
    assert client.get(reverse('ausencias:lista')).status_code == esperado(nome, visualizar=True)


def test_lixeira(perfil):
    nome, client = perfil
    assert client.get(reverse('ausencias:lixeira')).status_code == esperado(nome, visualizar=True)


def test_registrar_get(perfil):
    nome, client = perfil
    assert client.get(reverse('ausencias:registrar')).status_code == esperado(nome, gestor=True)


def test_registrar_post(perfil):
    nome, client = perfil
    status = client.post(reverse('ausencias:registrar'), {}).status_code
    # Gestor/admin: POST vazio volta o formulário com erros (200).
    assert status == esperado(nome, gestor=True)


def test_editar_get(perfil, ausencia):
    nome, client = perfil
    assert client.get(reverse('ausencias:editar', args=[ausencia.pk])).status_code == esperado(nome, gestor=True)


def test_editar_post(perfil, ausencia):
    nome, client = perfil
    status = client.post(reverse('ausencias:editar', args=[ausencia.pk]), {}).status_code
    assert status == esperado(nome, gestor=True)
    ausencia.refresh_from_db()
    assert ausencia.periodos.count() == 1


def test_editar_inexistente_nao_revela_para_quem_nao_pode(perfil):
    """Sem permissão, a resposta é a mesma exista ou não a ausência."""
    nome, client = perfil
    status = client.get(reverse('ausencias:editar', args=[999999])).status_code
    assert status == esperado(nome, gestor=True, ok=404)
