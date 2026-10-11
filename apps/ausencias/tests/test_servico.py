"""criar/atualizar/excluir/restaurar/apagar em ausencias_service."""

import re
from datetime import date, timedelta

import pytest

from apps.ausencias import ausencias_service
from apps.ausencias.ausencias_service import (
    ErroValidacaoAusencia,
    PeriodoInformado,
    apagar_definitivamente,
    atualizar_ausencia,
    criar_ausencia,
    excluir_ausencia,
    restaurar_ausencia,
)
from apps.ausencias.models import Ausencia, PeriodoAusencia
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db


def p(inicio, fim, situacao=None, id=None):
    return PeriodoInformado(d(inicio), d(fim), situacao, id)


def semanal(quantidade):
    """``quantidade`` períodos sem sobreposição: segunda a sexta de semanas seguidas."""
    segunda = date(2026, 3, 2)
    return [
        PeriodoInformado(segunda + timedelta(weeks=i), segunda + timedelta(weeks=i, days=4))
        for i in range(quantidade)
    ]


def datas(ausencia):
    return [(f'{x.data_inicio:%d/%m/%Y}', f'{x.data_fim:%d/%m/%Y}') for x in ausencia.periodos.all()]


@pytest.fixture
def ausencia(colaborador, ferias, gestor):
    """Férias de Ana com dois períodos: 02 a 06/03 e 16 a 20/03/2026."""
    return criar_ausencia(
        colaborador, ferias, [p('02/03/2026', '06/03/2026'), p('16/03/2026', '20/03/2026')], 'Viagem', gestor,
    )


# ---------------------------------------------------------------------------
# Criar
# ---------------------------------------------------------------------------
def test_criar_com_um_periodo(colaborador, ferias, gestor, planejado):
    ausencia = criar_ausencia(colaborador, ferias, [p('10/03/2026', '10/03/2026')], '  Consulta  ', gestor)

    ausencia = Ausencia.objects.get(pk=ausencia.pk)
    assert ausencia.colaborador == colaborador
    assert ausencia.tipo == ferias
    assert ausencia.observacoes == 'Consulta'
    periodo = ausencia.periodos.get()
    assert (periodo.data_inicio, periodo.dias, periodo.situacao) == (d('10/03/2026'), 1, planejado)


def test_criar_com_doze_periodos(colaborador, ferias, gestor):
    ausencia = criar_ausencia(colaborador, ferias, semanal(12), '', gestor)
    assert ausencia.periodos.count() == 12


@pytest.mark.parametrize('quantidade', [0, 13])
def test_criar_recusa_quantidade_invalida(colaborador, ferias, gestor, quantidade):
    with pytest.raises(ErroValidacaoAusencia) as erro:
        criar_ausencia(colaborador, ferias, semanal(quantidade), '', gestor)

    assert len(erro.value.erros_gerais) == 1
    assert not Ausencia.todos.exists()


def test_criar_preenche_auditoria(ausencia, gestor):
    assert ausencia.criado_por == gestor
    assert ausencia.atualizado_por == gestor
    for periodo in ausencia.periodos.all():
        assert periodo.criado_por == gestor
        assert periodo.atualizado_por == gestor


def test_criar_aplica_a_situacao_padrao_e_respeita_a_informada(colaborador, ferias, gestor, planejado, aprovado):
    ausencia = criar_ausencia(colaborador, ferias, [
        p('01/03/2026', '02/03/2026'), p('10/03/2026', '11/03/2026', aprovado),
    ], '', gestor)

    assert [x.situacao for x in ausencia.periodos.all()] == [planejado, aprovado]


def test_codigos_gerados_unicos_e_no_formato(colaborador, ferias, gestor):
    codigos = [
        criar_ausencia(colaborador, ferias, [PeriodoInformado(date(2026, mes, 1), date(2026, mes, 2))], '', gestor).codigo
        for mes in range(1, 13)
    ]

    assert len(set(codigos)) == 12
    for codigo in codigos:
        assert re.fullmatch(r'[ABCDEFGHJKMNPQRSTUVWXYZ2-9]{8}', codigo)


def test_erros_por_linha_com_indices_certos(colaborador, ferias, gestor):
    with pytest.raises(ErroValidacaoAusencia) as erro:
        criar_ausencia(colaborador, ferias, [
            p('01/03/2026', '02/03/2026'),
            PeriodoInformado(None, d('10/03/2026')),
            p('20/03/2026', '19/03/2026'),
            p('01/04/2026', '02/04/2026'),
        ], '', gestor)

    assert sorted(erro.value.erros_por_periodo) == [1, 2]


def test_atomicidade_terceiro_periodo_invalido_nada_e_gravado(colaborador, ferias, gestor):
    with pytest.raises(ErroValidacaoAusencia) as erro:
        criar_ausencia(colaborador, ferias, [
            p('01/03/2026', '02/03/2026'), p('05/03/2026', '06/03/2026'), p('10/03/2026', '01/03/2026'),
        ], '', gestor)

    assert list(erro.value.erros_por_periodo) == [2]
    assert not Ausencia.todos.exists()
    assert not PeriodoAusencia.objects.exists()


def test_atomicidade_falha_ao_gravar_o_terceiro_periodo(monkeypatch, colaborador, ferias, gestor):
    original = ausencias_service._criar_periodo
    chamadas = []

    def falha_no_terceiro(*args):
        chamadas.append(1)
        if len(chamadas) == 3:
            raise RuntimeError('falha simulada no banco')
        return original(*args)

    monkeypatch.setattr(ausencias_service, '_criar_periodo', falha_no_terceiro)

    with pytest.raises(RuntimeError):
        criar_ausencia(colaborador, ferias, [
            p('01/03/2026', '02/03/2026'), p('05/03/2026', '06/03/2026'), p('10/03/2026', '11/03/2026'),
        ], '', gestor)

    assert not Ausencia.todos.exists()
    assert not PeriodoAusencia.objects.exists()


def test_criar_recusa_sobreposicao_com_o_banco(ausencia, colaborador, banco_horas, gestor):
    with pytest.raises(ErroValidacaoAusencia) as erro:
        criar_ausencia(colaborador, banco_horas, [p('06/03/2026', '06/03/2026')], '', gestor)

    assert erro.value.erros_por_periodo == {0: ['Sobrepõe Férias já registrado de 02/03/2026 a 06/03/2026.']}
    assert Ausencia.objects.count() == 1


def test_criar_recusa_colaborador_inativo(colaborador, ferias, gestor):
    colaborador.ativo = False
    colaborador.save()

    with pytest.raises(ErroValidacaoAusencia) as erro:
        criar_ausencia(colaborador, ferias, [p('01/03/2026', '02/03/2026')], '', gestor)
    assert 'colaborador' in erro.value.erros_campos


def test_criar_usa_o_estado_atual_do_colaborador(colaborador, ferias, gestor):
    """O objeto em memória diz ativo, mas o banco diz inativo: vale o banco
    (o colaborador é recarregado ao ser travado)."""
    type(colaborador).objects.filter(pk=colaborador.pk).update(ativo=False)

    with pytest.raises(ErroValidacaoAusencia):
        criar_ausencia(colaborador, ferias, [p('01/03/2026', '02/03/2026')], '', gestor)


def test_criar_recusa_tipo_inativo(colaborador, ferias, gestor):
    ferias.ativo = False
    ferias.save()

    with pytest.raises(ErroValidacaoAusencia) as erro:
        criar_ausencia(colaborador, ferias, [p('01/03/2026', '02/03/2026')], '', gestor)
    assert 'tipo' in erro.value.erros_campos


def test_criar_recusa_situacao_inativa(colaborador, ferias, gestor, aprovado):
    aprovado.ativo = False
    aprovado.save()

    with pytest.raises(ErroValidacaoAusencia) as erro:
        criar_ausencia(colaborador, ferias, [p('01/03/2026', '02/03/2026', aprovado)], '', gestor)
    assert erro.value.erros_por_periodo == {0: ['A situação "Aprovado" está inativa.']}


# ---------------------------------------------------------------------------
# Atualizar
# ---------------------------------------------------------------------------
def ids(ausencia):
    return [x.pk for x in ausencia.periodos.all()]


def test_atualizar_alterando_datas(ausencia, colaborador, ferias, admin):
    primeiro, segundo = ids(ausencia)

    atualizada = atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '09/03/2026', id=primeiro), p('16/03/2026', '20/03/2026', id=segundo),
    ], 'Viagem', admin)

    assert datas(atualizada) == [('02/03/2026', '09/03/2026'), ('16/03/2026', '20/03/2026')]
    assert ids(atualizada) == [primeiro, segundo]


def test_atualizar_adicionando_removendo_e_mantendo(ausencia, colaborador, ferias, admin):
    primeiro, segundo = ids(ausencia)

    atualizada = atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '06/03/2026', id=primeiro),
        p('01/04/2026', '03/04/2026'),
    ], 'Viagem', admin)

    assert datas(atualizada) == [('02/03/2026', '06/03/2026'), ('01/04/2026', '03/04/2026')]
    assert ids(atualizada)[0] == primeiro
    assert not PeriodoAusencia.objects.filter(pk=segundo).exists()


def test_atualizar_auditoria_so_nos_periodos_alterados(ausencia, colaborador, ferias, gestor, admin):
    primeiro, segundo = ids(ausencia)

    atualizada = atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '06/03/2026', id=primeiro), p('16/03/2026', '21/03/2026', id=segundo),
    ], 'Viagem', admin)

    assert atualizada.criado_por == gestor
    assert atualizada.atualizado_por == admin
    mantido, alterado = atualizada.periodos.all()
    assert mantido.atualizado_por == gestor
    assert alterado.atualizado_por == admin
    assert alterado.criado_por == gestor


def test_atualizar_cabecalho(ausencia, outro_colaborador, banco_horas, admin):
    atualizada = atualizar_ausencia(ausencia, outro_colaborador, banco_horas, [
        p('02/03/2026', '06/03/2026', id=ids(ausencia)[0]),
    ], '  Nova obs ', admin)

    atualizada.refresh_from_db()
    assert atualizada.colaborador == outro_colaborador
    assert atualizada.tipo == banco_horas
    assert atualizada.observacoes == 'Nova obs'
    assert atualizada.codigo == ausencia.codigo


def test_atualizar_sem_mudar_datas_nao_gera_falso_conflito(ausencia, colaborador, ferias, admin):
    primeiro, segundo = ids(ausencia)

    atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '06/03/2026', id=primeiro), p('16/03/2026', '20/03/2026', id=segundo),
    ], 'Só a observação', admin)


def test_atualizar_conflita_com_outra_ausencia_do_colaborador(ausencia, colaborador, ferias, banco_horas, gestor):
    criar_ausencia(colaborador, banco_horas, [p('10/03/2026', '10/03/2026')], '', gestor)
    primeiro, segundo = ids(ausencia)

    with pytest.raises(ErroValidacaoAusencia) as erro:
        atualizar_ausencia(ausencia, colaborador, ferias, [
            p('02/03/2026', '12/03/2026', id=primeiro), p('16/03/2026', '20/03/2026', id=segundo),
        ], '', gestor)

    assert erro.value.erros_por_periodo == {0: ['Sobrepõe Banco de horas já registrado de 10/03/2026 a 10/03/2026.']}
    assert datas(Ausencia.objects.get(pk=ausencia.pk))[0] == ('02/03/2026', '06/03/2026')


def test_atualizar_trocando_para_colaborador_com_conflito(ausencia, outro_colaborador, ferias, gestor):
    criar_ausencia(outro_colaborador, ferias, [p('05/03/2026', '05/03/2026')], '', gestor)

    with pytest.raises(ErroValidacaoAusencia):
        atualizar_ausencia(ausencia, outro_colaborador, ferias, [
            p('02/03/2026', '06/03/2026', id=ids(ausencia)[0]),
        ], '', gestor)


def test_atualizar_falha_nao_altera_nada(ausencia, colaborador, ferias, admin):
    primeiro, segundo = ids(ausencia)

    with pytest.raises(ErroValidacaoAusencia):
        atualizar_ausencia(ausencia, colaborador, ferias, [
            p('02/03/2026', '09/03/2026', id=primeiro), p('16/03/2026', '15/03/2026', id=segundo),
        ], 'Mudou', admin)

    gravada = Ausencia.objects.get(pk=ausencia.pk)
    assert gravada.observacoes == 'Viagem'
    assert datas(gravada) == [('02/03/2026', '06/03/2026'), ('16/03/2026', '20/03/2026')]


def test_atualizar_situacao_none_aplica_a_padrao(ausencia, colaborador, ferias, aprovado, planejado, admin):
    primeiro, segundo = ids(ausencia)
    atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '06/03/2026', aprovado, id=primeiro), p('16/03/2026', '20/03/2026', aprovado, id=segundo),
    ], '', admin)

    atualizada = atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '06/03/2026', aprovado, id=primeiro), p('16/03/2026', '20/03/2026', None, id=segundo),
    ], '', admin)

    assert [x.situacao for x in atualizada.periodos.all()] == [aprovado, planejado]


def test_atualizar_ausencia_na_lixeira_recusado(ausencia, colaborador, ferias, admin):
    excluir_ausencia(ausencia, admin)

    with pytest.raises(ErroValidacaoAusencia) as erro:
        atualizar_ausencia(ausencia, colaborador, ferias, [p('02/03/2026', '06/03/2026')], '', admin)
    assert erro.value.erros_gerais == ['Este registro está na lixeira: restaure-o antes de editar.']


# Trava otimista ------------------------------------------------------------
def test_atualizar_com_versao_atual_grava(ausencia, colaborador, ferias, admin):
    atualizar_ausencia(
        ausencia, colaborador, ferias, [p('02/03/2026', '06/03/2026')], 'Nova', admin, versao=ausencia.atualizado_em,
    )

    ausencia.refresh_from_db()
    assert ausencia.observacoes == 'Nova'


def test_atualizar_com_versao_desatualizada_recusa_sem_gravar(ausencia, colaborador, ferias, admin):
    versao_aberta = ausencia.atualizado_em
    # Outra pessoa salvou depois (atualizado_em explícito: no Windows o
    # relógio pode repetir o mesmo instante em gravações seguidas).
    Ausencia.todos.filter(pk=ausencia.pk).update(
        observacoes='Do outro', atualizado_em=versao_aberta + timedelta(milliseconds=1),
    )

    with pytest.raises(ausencias_service.AusenciaAlterada) as erro:
        atualizar_ausencia(
            ausencia, colaborador, ferias, [p('02/03/2026', '06/03/2026')], 'Minha', admin, versao=versao_aberta,
        )
    assert erro.value.erros_gerais == [ausencias_service.MENSAGEM_ALTERADA_POR_OUTRO]
    assert isinstance(erro.value, ErroValidacaoAusencia)
    ausencia.refresh_from_db()
    assert ausencia.observacoes == 'Do outro'
    assert ausencia.periodos.count() == 2


# Inativos na edição -------------------------------------------------------
def test_editar_ausencia_de_colaborador_inativo_sem_trocar_e_aceito(ausencia, colaborador, ferias, admin):
    colaborador.ativo = False
    colaborador.save()

    atualizada = atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '07/03/2026', id=ids(ausencia)[0]),
    ], 'Ajuste', admin)

    assert atualizada.colaborador == colaborador


def test_trocar_para_colaborador_inativo_recusado(ausencia, outro_colaborador, ferias, admin):
    outro_colaborador.ativo = False
    outro_colaborador.save()

    with pytest.raises(ErroValidacaoAusencia) as erro:
        atualizar_ausencia(ausencia, outro_colaborador, ferias, [p('02/03/2026', '06/03/2026')], '', admin)
    assert 'colaborador' in erro.value.erros_campos


def test_tipo_inativo_aceito_em_ausencia_que_ja_o_usa(ausencia, colaborador, ferias, admin):
    ferias.ativo = False
    ferias.save()

    atualizar_ausencia(ausencia, colaborador, ferias, [p('02/03/2026', '06/03/2026', id=ids(ausencia)[0])], '', admin)


def test_trocar_para_tipo_inativo_recusado(ausencia, colaborador, banco_horas, admin):
    banco_horas.ativo = False
    banco_horas.save()

    with pytest.raises(ErroValidacaoAusencia) as erro:
        atualizar_ausencia(ausencia, colaborador, banco_horas, [p('02/03/2026', '06/03/2026')], '', admin)
    assert 'tipo' in erro.value.erros_campos


def test_situacao_inativa_mantida_em_periodo_existente_e_aceita(ausencia, colaborador, ferias, aprovado, admin):
    primeiro, segundo = ids(ausencia)
    atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '06/03/2026', aprovado, id=primeiro), p('16/03/2026', '20/03/2026', id=segundo),
    ], '', admin)
    aprovado.ativo = False
    aprovado.save()

    # Mantém a situação inativa no período 1 (até mudando as datas) e altera o 2.
    atualizar_ausencia(ausencia, colaborador, ferias, [
        p('02/03/2026', '08/03/2026', aprovado, id=primeiro), p('16/03/2026', '21/03/2026', id=segundo),
    ], '', admin)


def test_situacao_inativa_recusada_em_periodo_novo_ou_alterado(ausencia, colaborador, ferias, aprovado, admin):
    aprovado.ativo = False
    aprovado.save()
    primeiro, segundo = ids(ausencia)

    with pytest.raises(ErroValidacaoAusencia) as erro:
        atualizar_ausencia(ausencia, colaborador, ferias, [
            p('02/03/2026', '06/03/2026', aprovado, id=primeiro),   # mudou para a inativa
            p('16/03/2026', '20/03/2026', id=segundo),
            p('01/04/2026', '02/04/2026', aprovado),                # novo com a inativa
        ], '', admin)

    assert sorted(erro.value.erros_por_periodo) == [0, 2]


# ---------------------------------------------------------------------------
# Excluir / restaurar / apagar
# ---------------------------------------------------------------------------
def test_excluir(ausencia, admin):
    excluida = excluir_ausencia(ausencia, admin)

    assert excluida.esta_excluido
    assert excluida.excluido_por == admin
    assert not Ausencia.objects.filter(pk=ausencia.pk).exists()


def test_excluir_idempotente(ausencia, admin, gestor):
    primeira = excluir_ausencia(ausencia, admin)
    segunda = excluir_ausencia(ausencia, gestor)

    assert segunda.excluido_em == primeira.excluido_em
    assert segunda.excluido_por == admin


def test_restaurar_sem_conflito(ausencia, admin, gestor):
    excluir_ausencia(ausencia, admin)

    restaurada = restaurar_ausencia(ausencia, gestor)

    assert not restaurada.esta_excluido
    assert restaurada.excluido_por is None
    assert restaurada.atualizado_por == gestor
    assert Ausencia.objects.filter(pk=ausencia.pk).exists()


def test_restaurar_idempotente_se_ja_ativa(ausencia, gestor):
    restaurada = restaurar_ausencia(ausencia, gestor)

    assert not restaurada.esta_excluido
    assert restaurada.atualizado_por == ausencia.atualizado_por


def test_restaurar_com_conflito_recusa_e_continua_excluida(ausencia, colaborador, banco_horas, admin, gestor):
    excluir_ausencia(ausencia, admin)
    criar_ausencia(colaborador, banco_horas, [p('18/03/2026', '18/03/2026')], '', gestor)

    with pytest.raises(ErroValidacaoAusencia) as erro:
        restaurar_ausencia(ausencia, gestor)

    assert erro.value.erros_gerais == ['Não é possível restaurar: há ausências registradas no mesmo período.']
    assert erro.value.erros_por_periodo == {1: ['Sobrepõe Banco de horas já registrado de 18/03/2026 a 18/03/2026.']}
    assert Ausencia.todos.get(pk=ausencia.pk).esta_excluido


def test_restaurar_ignora_conflito_com_periodo_cancelado(ausencia, colaborador, banco_horas, cancelado, admin, gestor):
    excluir_ausencia(ausencia, admin)
    criar_ausencia(colaborador, banco_horas, [p('18/03/2026', '18/03/2026', cancelado)], '', gestor)

    assert not restaurar_ausencia(ausencia, gestor).esta_excluido


def test_restaurar_com_colaborador_inativo(ausencia, colaborador, admin):
    excluir_ausencia(ausencia, admin)
    colaborador.ativo = False
    colaborador.save()

    assert not restaurar_ausencia(ausencia, admin).esta_excluido


def test_apagar_definitivamente(ausencia, admin):
    excluir_ausencia(ausencia, admin)

    assert apagar_definitivamente(ausencia) == ausencia.codigo
    assert not Ausencia.todos.filter(pk=ausencia.pk).exists()
    assert not PeriodoAusencia.objects.exists()


def test_apagar_definitivamente_exige_lixeira(ausencia):
    with pytest.raises(ErroValidacaoAusencia):
        apagar_definitivamente(ausencia)
    assert Ausencia.objects.filter(pk=ausencia.pk).exists()
