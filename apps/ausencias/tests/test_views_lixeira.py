"""Lixeira: listagem, restaurar (com e sem conflito) e apagar de vez."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.ausencias import ausencias_service
from apps.ausencias.models import Ausencia, PeriodoAusencia
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db

URL_LIXEIRA = reverse('ausencias:lixeira')


def url(nome, ausencia):
    return reverse(f'ausencias:{nome}', args=[ausencia.pk])


@pytest.fixture
def excluida(colaborador, ferias, gestor, admin):
    """Férias de Ana (02 a 06/03/2026), na lixeira (excluída pelo admin)."""
    ausencia = ausencias_service.criar_ausencia(
        colaborador, ferias, [ausencias_service.PeriodoInformado(d('02/03/2026'), d('06/03/2026'))], '', gestor,
    )
    return ausencias_service.excluir_ausencia(ausencia, admin)


@pytest.fixture
def ativa(outro_colaborador, ferias, gestor):
    return ausencias_service.criar_ausencia(
        outro_colaborador, ferias, [ausencias_service.PeriodoInformado(d('02/03/2026'), d('06/03/2026'))], '', gestor,
    )


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
def test_lixeira_lista_so_excluidas_com_quem_e_quando(client, usuario_ativo, excluida, ativa):
    client.force_login(usuario_ativo)

    response = client.get(URL_LIXEIRA)

    assert [a.pk for a in response.context['ausencias']] == [excluida.pk]
    html = response.content.decode()
    assert 'Admin' in html
    assert f'{timezone.localtime(excluida.excluido_em):%d/%m/%Y %H:%M}' in html
    # Sem grupo: nada de ações.
    assert url('restaurar', excluida) not in html
    assert url('apagar', excluida) not in html


def test_lixeira_filtro_por_nome(gestor_client, excluida, ativa, gestor):
    ausencias_service.excluir_ausencia(ativa, gestor)

    response = gestor_client.get(URL_LIXEIRA, {'nome': 'bruno'})

    assert [a.pk for a in response.context['ausencias']] == [ativa.pk]


def test_lixeira_acoes_por_perfil(client, gestor, admin, excluida):
    client.force_login(gestor)
    html = client.get(URL_LIXEIRA).content.decode()
    assert url('restaurar', excluida) in html
    assert url('apagar', excluida) not in html

    client.force_login(admin)
    html = client.get(URL_LIXEIRA).content.decode()
    assert url('restaurar', excluida) in html
    assert url('apagar', excluida) in html


# ---------------------------------------------------------------------------
# Restaurar
# ---------------------------------------------------------------------------
def test_restaurar_sem_conflito(gestor_client, gestor, excluida):
    response = gestor_client.post(url('restaurar', excluida), follow=True)

    assert response.redirect_chain[-1][0] == url('detalhe', excluida)
    assert 'restaurada' in response.content.decode()
    excluida.refresh_from_db()
    assert not excluida.esta_excluido
    assert excluida.atualizado_por == gestor


def test_restaurar_com_conflito_mostra_mensagens_e_continua_na_lixeira(gestor_client, excluida, colaborador, banco_horas, gestor):
    ausencias_service.criar_ausencia(
        colaborador, banco_horas, [ausencias_service.PeriodoInformado(d('05/03/2026'), d('05/03/2026'))], '', gestor,
    )

    response = gestor_client.post(url('restaurar', excluida), {'next': URL_LIXEIRA}, follow=True)

    assert response.redirect_chain[-1][0] == URL_LIXEIRA
    html = response.content.decode()
    assert 'Não é possível restaurar: há ausências registradas no mesmo período.' in html
    assert 'Período 1: Sobrepõe Banco de horas já registrado de 05/03/2026 a 05/03/2026.' in html
    assert Ausencia.todos.get(pk=excluida.pk).esta_excluido


def test_restaurar_ativa_404(gestor_client, ativa):
    assert gestor_client.post(url('restaurar', ativa)).status_code == 404


def test_restaurar_so_por_post(gestor_client, excluida):
    assert gestor_client.get(url('restaurar', excluida)).status_code == 405


# ---------------------------------------------------------------------------
# Apagar de vez
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_client(client, admin):
    client.force_login(admin)
    return client


def test_apagar_pede_o_codigo(admin_client, excluida):
    response = admin_client.get(url('apagar', excluida))

    assert response.status_code == 200
    assert excluida.codigo in response.content.decode()


def test_apagar_com_codigo_errado_nao_apaga(admin_client, excluida):
    response = admin_client.post(url('apagar', excluida), {'confirmacao': 'ERRADO'})

    assert response.status_code == 200
    assert response.context['form'].errors['confirmacao'] == ['O código digitado não confere.']
    assert Ausencia.todos.filter(pk=excluida.pk).exists()


def test_apagar_com_codigo_certo(admin_client, excluida):
    periodos = list(excluida.periodos.values_list('pk', flat=True))

    response = admin_client.post(url('apagar', excluida), {'confirmacao': f' {excluida.codigo.lower()} '}, follow=True)

    assert response.redirect_chain[-1][0] == URL_LIXEIRA
    assert 'apagada definitivamente' in response.content.decode()
    assert not Ausencia.todos.filter(pk=excluida.pk).exists()
    assert not PeriodoAusencia.objects.filter(pk__in=periodos).exists()


def test_apagar_ativa_404(admin_client, ativa):
    assert admin_client.get(url('apagar', ativa)).status_code == 404
    assert admin_client.post(url('apagar', ativa), {'confirmacao': ativa.codigo}).status_code == 404
    assert Ausencia.objects.filter(pk=ativa.pk).exists()


def test_gestor_nao_apaga(gestor_client, excluida):
    response = gestor_client.post(url('apagar', excluida), {'confirmacao': excluida.codigo})

    assert response.status_code == 403
    assert Ausencia.todos.filter(pk=excluida.pk).exists()


def test_detalhe_de_excluida_tem_restaurar_e_apagar_para_admin(admin_client, excluida):
    html = admin_client.get(url('detalhe', excluida)).content.decode()

    assert url('restaurar', excluida) in html
    assert url('apagar', excluida) in html
