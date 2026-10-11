"""Detalhe (somente leitura) e exclusão lógica com modal."""

import pytest
from django.urls import reverse

from apps.ausencias import ausencias_service
from apps.ausencias.models import Ausencia
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db


@pytest.fixture
def ausencia(colaborador, ferias, gestor, aprovado):
    return ausencias_service.criar_ausencia(
        colaborador, ferias,
        [ausencias_service.PeriodoInformado(d('02/03/2026'), d('06/03/2026')),
         ausencias_service.PeriodoInformado(d('16/03/2026'), d('20/03/2026'), aprovado)],
        'Viagem\nde família', gestor,
    )


def url(nome, ausencia):
    return reverse(f'ausencias:{nome}', args=[ausencia.pk])


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------
def test_detalhe_mostra_periodos_situacoes_observacoes_e_auditoria(client, usuario_ativo, ausencia):
    client.force_login(usuario_ativo)

    html = client.get(url('detalhe', ausencia)).content.decode()

    assert ausencia.codigo in html
    assert '02/03/2026' in html and '20/03/2026' in html
    assert 'Planejado' in html and 'Aprovado' in html
    assert 'Viagem<br>de família' in html
    assert 'Criada por' in html and 'Gestor' in html
    # Usuário sem grupo não vê botões de gestão.
    assert url('editar', ausencia) not in html
    assert url('excluir', ausencia) not in html


def test_detalhe_do_gestor_tem_editar_e_excluir_em_modal(gestor_client, ausencia):
    html = gestor_client.get(url('detalhe', ausencia)).content.decode()

    assert url('editar', ausencia) in html
    assert f'hx-get="{url("excluir", ausencia)}"' in html
    assert 'id="modal-acao"' in html


def test_detalhe_de_excluida_mostra_quem_e_quando(gestor_client, ausencia, admin):
    ausencias_service.excluir_ausencia(ausencia, admin)

    response = gestor_client.get(url('detalhe', ausencia))

    html = response.content.decode()
    assert 'Na lixeira' in html
    assert 'Excluída por' in html and 'Admin' in html
    assert url('editar', ausencia) not in html


def test_detalhe_inexistente_404(gestor_client):
    assert gestor_client.get(reverse('ausencias:detalhe', args=[999999])).status_code == 404


def test_registrar_e_editar_redirecionam_para_o_detalhe(gestor_client, ausencia):
    response = gestor_client.get(url('editar', ausencia))
    assert response.status_code == 200
    ausencias_service.excluir_ausencia(ausencia, response.wsgi_request.user)

    response = gestor_client.get(url('editar', ausencia))

    assert response.status_code == 302
    assert response.url == url('detalhe', ausencia)


# ---------------------------------------------------------------------------
# Exclusão
# ---------------------------------------------------------------------------
def test_excluir_get_htmx_devolve_conteudo_do_modal(gestor_client, ausencia):
    response = gestor_client.get(url('excluir', ausencia), HTTP_HX_REQUEST='true')

    assert [t.name for t in response.templates][0] == 'ausencias/_modal_excluir.html'
    assert 'modal-content' in response.content.decode()


def test_excluir_get_sem_js_devolve_pagina(gestor_client, ausencia):
    response = gestor_client.get(url('excluir', ausencia))

    assert 'ausencias/excluir.html' in [t.name for t in response.templates]


def test_excluir_post_manda_para_a_lixeira_e_volta_a_lista(gestor_client, gestor, ausencia):
    response = gestor_client.post(url('excluir', ausencia), follow=True)

    assert response.redirect_chain[-1][0] == reverse('ausencias:lista')
    assert 'enviada para a lixeira' in response.content.decode()
    assert not Ausencia.objects.filter(pk=ausencia.pk).exists()
    excluida = Ausencia.todos.get(pk=ausencia.pk)
    assert excluida.excluido_por == gestor
    assert excluida.periodos.count() == 2


def test_excluir_volta_a_lista_com_os_filtros(gestor_client, ausencia):
    voltar = reverse('ausencias:lista') + '?nome=ana'

    response = gestor_client.post(url('excluir', ausencia), {'next': voltar})

    assert response.url == voltar


def test_excluir_ignora_next_externo(gestor_client, ausencia):
    response = gestor_client.post(url('excluir', ausencia), {'next': 'https://exemplo.com/'})

    assert response.url == reverse('ausencias:lista')


def test_lista_leva_o_next_com_os_filtros_para_o_modal(gestor_client, ausencia):
    html = gestor_client.get(reverse('ausencias:lista'), {'nome': 'ana'}).content.decode()

    assert f'{url("excluir", ausencia)}?next=/ausencias/%3Fnome%3Dana' in html


def test_excluir_get_de_ja_excluida_404(gestor_client, ausencia, gestor):
    ausencias_service.excluir_ausencia(ausencia, gestor)

    assert gestor_client.get(url('excluir', ausencia)).status_code == 404
