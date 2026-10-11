import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.ausencias import ausencias_service
from apps.ausencias.models import SituacaoAusencia

pytestmark = pytest.mark.django_db


def _padroes():
    return list(SituacaoAusencia.objects.filter(padrao=True).values_list('nome', flat=True))


# ---------------------------------------------------------------------------
# Serviço
# ---------------------------------------------------------------------------
def test_situacao_padrao(planejado):
    assert ausencias_service.situacao_padrao() == planejado


def test_definir_padrao_desmarca_a_anterior(aprovado, admin):
    ausencias_service.definir_situacao_padrao(aprovado, admin)

    assert _padroes() == ['Aprovado']
    aprovado.refresh_from_db()
    assert aprovado.atualizado_por == admin


def test_definir_padrao_idempotente(planejado):
    ausencias_service.definir_situacao_padrao(planejado)
    assert _padroes() == ['Planejado']


def test_situacao_inativa_nao_pode_ser_padrao(aprovado):
    aprovado.ativo = False
    aprovado.save()

    with pytest.raises(ValidationError):
        ausencias_service.definir_situacao_padrao(aprovado)
    assert _padroes() == ['Planejado']


def test_salvar_nova_situacao_padrao_desmarca_a_anterior(admin):
    nova = ausencias_service.salvar_situacao(SituacaoAusencia(nome='Solicitado', padrao=True), admin)

    assert _padroes() == ['Solicitado']
    assert nova.criado_por == admin
    assert nova.atualizado_por == admin


def test_padrao_nao_pode_ser_desativada(planejado, admin):
    planejado.ativo = False

    with pytest.raises(ValidationError) as erro:
        ausencias_service.salvar_situacao(planejado, admin)
    assert 'ativo' in erro.value.message_dict
    planejado.refresh_from_db()
    assert planejado.ativo


def test_padrao_nao_pode_perder_a_flag(planejado, admin):
    planejado.padrao = False

    with pytest.raises(ValidationError) as erro:
        ausencias_service.salvar_situacao(planejado, admin)
    assert 'padrao' in erro.value.message_dict
    assert _padroes() == ['Planejado']


def test_nova_situacao_nao_pode_nascer_padrao_inativa(admin):
    with pytest.raises(ValidationError):
        ausencias_service.salvar_situacao(SituacaoAusencia(nome='X', padrao=True, ativo=False), admin)
    assert _padroes() == ['Planejado']


def test_situacao_nao_padrao_pode_ser_desativada(aprovado, admin):
    aprovado.ativo = False
    ausencias_service.salvar_situacao(aprovado, admin)

    aprovado.refresh_from_db()
    assert not aprovado.ativo


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
def _dados(situacao, **alteracoes):
    """POST do formulário do admin (checkbox desmarcado = campo ausente)."""
    dados = {
        'nome': situacao.nome, 'ativo': situacao.ativo, 'ordem': situacao.ordem,
        'padrao': situacao.padrao, 'conta_como_ausencia': situacao.conta_como_ausencia,
    }
    dados.update(alteracoes)
    return {chave: ('on' if valor is True else valor) for chave, valor in dados.items() if valor is not False}


def test_admin_marcar_outra_como_padrao(admin_client, aprovado):
    url = reverse('admin:ausencias_situacaoausencia_change', args=[aprovado.pk])

    response = admin_client.post(url, _dados(aprovado, padrao=True))

    assert response.status_code == 302
    assert _padroes() == ['Aprovado']


def test_admin_nova_situacao_padrao(admin_client, admin):
    response = admin_client.post(reverse('admin:ausencias_situacaoausencia_add'), {
        'nome': 'Solicitado', 'ativo': 'on', 'ordem': 0, 'padrao': 'on', 'conta_como_ausencia': 'on',
    })

    assert response.status_code == 302
    assert _padroes() == ['Solicitado']
    assert SituacaoAusencia.objects.get(nome='Solicitado').criado_por == admin


def test_admin_recusa_desmarcar_a_padrao(admin_client, planejado):
    url = reverse('admin:ausencias_situacaoausencia_change', args=[planejado.pk])

    response = admin_client.post(url, _dados(planejado, padrao=False))

    assert response.status_code == 200
    assert 'padrao' in response.context['adminform'].form.errors
    assert _padroes() == ['Planejado']


def test_admin_recusa_desativar_a_padrao(admin_client, planejado):
    url = reverse('admin:ausencias_situacaoausencia_change', args=[planejado.pk])

    response = admin_client.post(url, _dados(planejado, ativo=False))

    assert response.status_code == 200
    assert 'ativo' in response.context['adminform'].form.errors
    planejado.refresh_from_db()
    assert planejado.ativo


def test_admin_acao_definir_padrao(admin_client):
    realizado = SituacaoAusencia.objects.get(nome='Realizado')

    admin_client.post(reverse('admin:ausencias_situacaoausencia_changelist'), {
        'action': 'marcar_como_padrao', '_selected_action': [realizado.pk],
    })

    assert _padroes() == ['Realizado']


def test_admin_nao_exclui_a_padrao(admin_client, planejado):
    response = admin_client.get(reverse('admin:ausencias_situacaoausencia_delete', args=[planejado.pk]))

    assert response.status_code == 403


def test_admin_sem_exclusao_em_massa_de_situacoes(admin_client):
    response = admin_client.get(reverse('admin:ausencias_situacaoausencia_changelist'))

    acoes = [valor for valor, _ in response.context['action_form'].fields['action'].choices]
    assert 'delete_selected' not in acoes
    assert 'marcar_como_padrao' in acoes


def test_admin_exclui_situacao_sem_uso_e_nao_padrao(admin_client, aprovado):
    url = reverse('admin:ausencias_situacaoausencia_delete', args=[aprovado.pk])

    response = admin_client.post(url, {'post': 'yes'})

    assert response.status_code == 302
    assert not SituacaoAusencia.objects.filter(pk=aprovado.pk).exists()


def test_admin_tipo_cor_invalida(admin_client):
    response = admin_client.post(reverse('admin:ausencias_tipoausencia_add'), {
        'nome': 'Home office', 'cor': 'verde', 'ativo': 'on', 'ordem': 0,
    })

    assert response.status_code == 200
    assert 'cor' in response.context['adminform'].form.errors
