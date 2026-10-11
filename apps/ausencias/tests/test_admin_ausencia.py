import pytest
from django.urls import reverse

from apps.ausencias.models import Ausencia, PeriodoAusencia
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db

URL_LISTA = 'admin:ausencias_ausencia_changelist'


def dados_admin(colaborador, tipo, periodos, iniciais=(), observacoes=''):
    """POST do change form da ausência com o inline de períodos.

    ``periodos``: tuplas (inicio, fim, situacao[, id[, apagar]]). ``iniciais``
    quantos dos primeiros já existem (INITIAL_FORMS)."""
    dados = {
        'colaborador': colaborador.pk,
        'tipo': tipo.pk,
        'observacoes': observacoes,
        'periodos-TOTAL_FORMS': len(periodos),
        'periodos-INITIAL_FORMS': len(iniciais),
        'periodos-MIN_NUM_FORMS': 1,
        'periodos-MAX_NUM_FORMS': 12,
    }
    for indice, (inicio, fim, situacao, *resto) in enumerate(periodos):
        prefixo = f'periodos-{indice}-'
        dados[prefixo + 'data_inicio'] = inicio
        dados[prefixo + 'data_fim'] = fim
        dados[prefixo + 'situacao'] = situacao.pk
        if resto:
            dados[prefixo + 'id'] = resto[0]
            if len(resto) > 1 and resto[1]:
                dados[prefixo + 'DELETE'] = 'on'
    return dados


def test_lista_mostra_ausencias_excluidas(admin_client, gravar_ausencia, colaborador, ferias, admin):
    ativa = gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))
    excluida = gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026'))
    excluida.excluir(admin)

    response = admin_client.get(reverse(URL_LISTA))
    conteudo = response.content.decode()

    assert response.status_code == 200
    assert ativa.codigo in conteudo
    assert excluida.codigo in conteudo


def test_filtro_lixeira(admin_client, gravar_ausencia, colaborador, ferias, admin):
    ativa = gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))
    excluida = gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026'))
    excluida.excluir(admin)

    conteudo = admin_client.get(reverse(URL_LISTA), {'excluida': 'sim'}).content.decode()

    assert excluida.codigo in conteudo
    assert ativa.codigo not in conteudo


def test_ausencia_excluida_abre_no_admin(admin_client, gravar_ausencia, colaborador, ferias, admin):
    excluida = gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026'))
    excluida.excluir(admin)

    response = admin_client.get(reverse('admin:ausencias_ausencia_change', args=[excluida.pk]))

    assert response.status_code == 200


def test_sem_exclusao_fisica(admin_client, gravar_ausencia, colaborador, ferias):
    ausencia = gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))

    lista = admin_client.get(reverse(URL_LISTA))
    # Sem nenhuma ação disponível o admin nem monta o formulário de ações.
    action_form = lista.context['action_form']
    assert action_form is None or 'delete_selected' not in dict(action_form.fields['action'].choices)

    response = admin_client.post(reverse('admin:ausencias_ausencia_delete', args=[ausencia.pk]), {'post': 'yes'})
    assert response.status_code == 403

    response = admin_client.post(reverse(URL_LISTA), {
        'action': 'delete_selected', '_selected_action': [ausencia.pk], 'post': 'yes',
    })
    assert Ausencia.todos.filter(pk=ausencia.pk).exists()


def test_criar_com_periodos_pelo_inline(admin_client, admin, colaborador, ferias, planejado, aprovado):
    response = admin_client.post(reverse('admin:ausencias_ausencia_add'), dados_admin(colaborador, ferias, [
        ('01/03/2026', '05/03/2026', planejado),
        ('10/03/2026', '10/03/2026', aprovado),
    ], observacoes='Pelo admin'))

    assert response.status_code == 302, response.context['errors'] if response.context else ''
    ausencia = Ausencia.objects.get()
    assert len(ausencia.codigo) == 8
    assert ausencia.criado_por == admin
    assert [(p.data_inicio, p.dias, p.situacao) for p in ausencia.periodos.all()] == [
        (d('01/03/2026'), 5, planejado),
        (d('10/03/2026'), 1, aprovado),
    ]
    assert all(p.criado_por == admin for p in ausencia.periodos.all())


def test_editar_periodos_pelo_inline(admin_client, admin, gravar_ausencia, colaborador, ferias, planejado):
    ausencia = gravar_ausencia(colaborador, ferias, ('01/03/2026', '05/03/2026'), ('10/03/2026', '12/03/2026'))
    primeiro, segundo = ausencia.periodos.all()
    codigo = ausencia.codigo

    response = admin_client.post(
        reverse('admin:ausencias_ausencia_change', args=[ausencia.pk]),
        dados_admin(colaborador, ferias, [
            ('01/03/2026', '07/03/2026', planejado, primeiro.pk),
            ('10/03/2026', '12/03/2026', planejado, segundo.pk, True),
            ('20/03/2026', '21/03/2026', planejado),
        ], iniciais=[primeiro, segundo]),
    )

    assert response.status_code == 302
    ausencia.refresh_from_db()
    assert ausencia.codigo == codigo
    assert [(p.data_inicio, p.data_fim) for p in ausencia.periodos.all()] == [
        (d('01/03/2026'), d('07/03/2026')),
        (d('20/03/2026'), d('21/03/2026')),
    ]
    assert not PeriodoAusencia.objects.filter(pk=segundo.pk).exists()
    primeiro.refresh_from_db()
    assert primeiro.atualizado_por == admin


def test_admin_recusa_sobreposicao_com_outra_ausencia(admin_client, gravar_ausencia, colaborador, ferias, planejado):
    gravar_ausencia(colaborador, ferias, ('10/03/2026', '20/03/2026'))

    response = admin_client.post(reverse('admin:ausencias_ausencia_add'), dados_admin(colaborador, ferias, [
        ('01/03/2026', '02/03/2026', planejado),
        ('15/03/2026', '16/03/2026', planejado),
    ]))

    assert response.status_code == 200
    formset = response.context['inline_admin_formsets'][0].formset
    assert formset.forms[0].errors == {}
    assert formset.forms[1].non_field_errors() == ['Sobrepõe Férias já registrado de 10/03/2026 a 20/03/2026.']
    assert Ausencia.objects.count() == 1


def test_admin_recusa_sobreposicao_dentro_do_envio(admin_client, colaborador, ferias, planejado):
    response = admin_client.post(reverse('admin:ausencias_ausencia_add'), dados_admin(colaborador, ferias, [
        ('01/03/2026', '10/03/2026', planejado),
        ('10/03/2026', '12/03/2026', planejado),
    ]))

    assert response.status_code == 200
    assert not Ausencia.objects.exists()


def test_admin_recusa_colaborador_inativo_em_registro_novo(admin_client, colaborador, ferias, planejado):
    colaborador.ativo = False
    colaborador.save()

    response = admin_client.post(reverse('admin:ausencias_ausencia_add'), dados_admin(colaborador, ferias, [
        ('01/03/2026', '02/03/2026', planejado),
    ]))

    assert response.status_code == 200
    formset = response.context['inline_admin_formsets'][0].formset
    assert formset.non_form_errors() == ['Colaborador inativo não pode receber ausências.']


def test_admin_edicao_mantendo_periodos_nao_gera_falso_conflito(admin_client, gravar_ausencia, colaborador, ferias):
    ausencia = gravar_ausencia(colaborador, ferias, ('10/03/2026', '20/03/2026'))
    periodo = ausencia.periodos.get()

    response = admin_client.post(
        reverse('admin:ausencias_ausencia_change', args=[ausencia.pk]),
        dados_admin(colaborador, ferias, [
            ('10/03/2026', '20/03/2026', periodo.situacao, periodo.pk),
        ], iniciais=[periodo], observacoes='Só a observação mudou'),
    )

    assert response.status_code == 302
    ausencia.refresh_from_db()
    assert ausencia.observacoes == 'Só a observação mudou'


def test_inline_sugere_a_situacao_padrao(admin_client, planejado):
    response = admin_client.get(reverse('admin:ausencias_ausencia_add'))

    formset = response.context['inline_admin_formsets'][0].formset
    assert formset.forms[0]['situacao'].initial == planejado
