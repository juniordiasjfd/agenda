"""Edição rápida do departamento na lista de colaboradores (HTMX)."""

import pytest
from django.urls import reverse

from apps.colaboradores.models import Colaborador, Departamento

pytestmark = pytest.mark.django_db

HTMX = {'HTTP_HX_REQUEST': 'true', 'HTTP_HX_CURRENT_URL': 'http://testserver/administracao/colaboradores/?busca=jo'}


def _url(colaborador):
    return reverse('colaboradores:colaborador_departamento', args=[colaborador.pk])


@pytest.fixture
def sem_depto(db):
    return Colaborador.objects.create(nome='Joana Prado')


def test_anonimo_vai_para_o_login(client, sem_depto, departamento):
    response = client.post(_url(sem_depto), {'departamento': departamento.pk}, **HTMX)

    assert response.status_code == 302
    sem_depto.refresh_from_db()
    assert sem_depto.departamento is None


def test_gestor_recebe_403(gestor_client, sem_depto, departamento):
    response = gestor_client.post(_url(sem_depto), {'departamento': departamento.pk}, **HTMX)

    assert response.status_code == 403
    sem_depto.refresh_from_db()
    assert sem_depto.departamento is None


def test_so_por_post(admin_client, sem_depto):
    assert admin_client.get(_url(sem_depto), **HTMX).status_code == 405


def test_define_departamento_e_devolve_a_linha(admin_client, admin, sem_depto, departamento):
    response = admin_client.post(_url(sem_depto), {'departamento': departamento.pk}, **HTMX)

    assert response.status_code == 200
    sem_depto.refresh_from_db()
    assert sem_depto.departamento == departamento
    assert sem_depto.atualizado_por == admin
    conteudo = response.content.decode()
    assert f'<tr id="colaborador-{sem_depto.pk}">' in conteudo
    assert f'<option value="{departamento.pk}" selected>Financeiro</option>' in conteudo
    # "next" dos botões de ativar/desativar mantém a lista filtrada.
    assert 'value="http://testserver/administracao/colaboradores/?busca=jo"' in conteudo


def test_atualiza_aviso_sem_departamento_fora_da_banda(admin_client, sem_depto, departamento):
    Colaborador.objects.create(nome='Outro Sem')

    conteudo = admin_client.post(_url(sem_depto), {'departamento': departamento.pk}, **HTMX).content.decode()

    assert 'id="aviso-sem-departamento" hx-swap-oob="true"' in conteudo
    assert '1 colaborador ativo' in conteudo


def test_aviso_some_quando_o_ultimo_ganha_departamento(admin_client, sem_depto, departamento):
    conteudo = admin_client.post(_url(sem_depto), {'departamento': departamento.pk}, **HTMX).content.decode()

    assert 'hx-swap-oob="true"' in conteudo
    assert 'sem departamento.' not in conteudo


def test_volta_para_sem_departamento(admin_client, colaborador):
    response = admin_client.post(_url(colaborador), {'departamento': ''}, **HTMX)

    assert response.status_code == 200
    colaborador.refresh_from_db()
    assert colaborador.departamento is None


@pytest.mark.parametrize('valor', ['999', 'abc'])
def test_departamento_invalido_400(admin_client, colaborador, departamento, valor):
    response = admin_client.post(_url(colaborador), {'departamento': valor}, **HTMX)

    assert response.status_code == 400
    colaborador.refresh_from_db()
    assert colaborador.departamento == departamento


def test_colaborador_inexistente_404(admin_client, departamento):
    url = reverse('colaboradores:colaborador_departamento', args=[999])
    assert admin_client.post(url, {'departamento': departamento.pk}, **HTMX).status_code == 404


def test_sem_htmx_redireciona_para_a_lista(admin_client, sem_depto, departamento):
    response = admin_client.post(_url(sem_depto), {'departamento': departamento.pk})

    assert response.status_code == 302
    assert response.url == reverse('colaboradores:colaboradores')
    sem_depto.refresh_from_db()
    assert sem_depto.departamento == departamento


def test_lista_renderiza_select_com_hx_post(admin_client, sem_depto, departamento):
    Departamento.objects.create(nome='Jurídico')

    conteudo = admin_client.get(reverse('colaboradores:colaboradores')).content.decode()

    assert f'hx-post="{_url(sem_depto)}"' in conteudo
    assert 'hx-trigger="change"' in conteudo
    assert '<option value="" selected>Sem departamento</option>' in conteudo
