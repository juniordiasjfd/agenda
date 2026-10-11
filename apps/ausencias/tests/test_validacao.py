"""Regras de ``validar_periodos``/``validar_ausencia`` que não são de
sobreposição (essas estão em test_conflitos.py)."""

from datetime import date

import pytest

from apps.ausencias.ausencias_service import (
    MAX_PERIODOS,
    ErroValidacaoAusencia,
    PeriodoInformado,
    validar_ausencia,
    validar_periodos,
)
from apps.ausencias.models import SituacaoAusencia
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db


def mensal(quantidade, ano=2026):
    """``quantidade`` períodos sem sobreposição: dias 1 a 5 de meses seguidos."""
    return [
        PeriodoInformado(date(ano + i // 12, i % 12 + 1, 1), date(ano + i // 12, i % 12 + 1, 5))
        for i in range(quantidade)
    ]


def erro_de(funcao, *args, **kwargs):
    with pytest.raises(ErroValidacaoAusencia) as erro:
        funcao(*args, **kwargs)
    return erro.value


# ---------------------------------------------------------------------------
# Quantidade
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('quantidade', [1, MAX_PERIODOS])
def test_quantidade_aceita(colaborador, quantidade):
    assert len(validar_periodos(colaborador, mensal(quantidade))) == quantidade


def test_nenhum_periodo_recusado(colaborador):
    erro = erro_de(validar_periodos, colaborador, [])
    assert erro.erros_gerais == ['Informe pelo menos um período.']
    assert erro.erros_por_periodo == {}


def test_treze_periodos_recusados(colaborador):
    erro = erro_de(validar_periodos, colaborador, mensal(13))
    assert erro.erros_gerais == ['No máximo 12 períodos por registro (foram 13).']


# ---------------------------------------------------------------------------
# Datas, com erros por linha nos índices certos
# ---------------------------------------------------------------------------
def test_datas_faltando(colaborador):
    erro = erro_de(validar_periodos, colaborador, [
        PeriodoInformado(d('01/03/2026'), d('02/03/2026')),
        PeriodoInformado(None, d('10/03/2026')),
        PeriodoInformado(d('20/03/2026'), None),
        PeriodoInformado(None, None),
    ])

    assert erro.erros_por_periodo == {
        1: ['Informe a data de início.'],
        2: ['Informe a data de fim.'],
        3: ['Informe a data de início.', 'Informe a data de fim.'],
    }
    assert erro.erros_gerais == []


def test_fim_antes_do_inicio(colaborador):
    erro = erro_de(validar_periodos, colaborador, [
        PeriodoInformado(d('01/03/2026'), d('02/03/2026')),
        PeriodoInformado(d('10/03/2026'), d('09/03/2026')),
    ])

    assert erro.erros_por_periodo == {1: ['A data de fim deve ser igual ou posterior à de início.']}


@pytest.mark.parametrize('inicio, fim', [
    (date(1999, 12, 31), date(2000, 1, 5)),
    (date(2100, 12, 30), date(2101, 1, 2)),
    (date(1999, 1, 1), date(1999, 1, 2)),
    (date(2101, 1, 1), date(2101, 1, 1)),
])
def test_ano_fora_do_intervalo(colaborador, inicio, fim):
    erro = erro_de(validar_periodos, colaborador, [PeriodoInformado(inicio, fim)])
    assert erro.erros_por_periodo == {0: ['O ano deve estar entre 2000 e 2100.']}


@pytest.mark.parametrize('inicio, fim', [
    (date(2000, 1, 1), date(2000, 1, 1)),
    (date(2100, 12, 31), date(2100, 12, 31)),
])
def test_anos_limite_aceitos(colaborador, inicio, fim):
    validar_periodos(colaborador, [PeriodoInformado(inicio, fim)])


def test_periodo_no_passado_e_aceito(colaborador):
    validar_periodos(colaborador, [PeriodoInformado(d('01/01/2001'), d('05/01/2001'))])


def test_mensagens_planas_numeram_a_partir_de_1(colaborador):
    erro = erro_de(validar_periodos, colaborador, [
        PeriodoInformado(d('01/03/2026'), d('02/03/2026')),
        PeriodoInformado(None, d('10/03/2026')),
    ])
    assert erro.mensagens() == ['Período 2: Informe a data de início.']


# ---------------------------------------------------------------------------
# Situação
# ---------------------------------------------------------------------------
def test_sem_situacao_usa_a_padrao(colaborador, planejado):
    resolvidos = validar_periodos(colaborador, [PeriodoInformado(d('01/03/2026'), d('02/03/2026'))])
    assert resolvidos[0].situacao == planejado


def test_sem_situacao_padrao_definida(colaborador, planejado):
    SituacaoAusencia.objects.filter(pk=planejado.pk).update(padrao=False)

    erro = erro_de(validar_periodos, colaborador, [PeriodoInformado(d('01/03/2026'), d('02/03/2026'))])
    assert erro.erros_por_periodo == {0: ['Não há situação padrão definida: informe a situação.']}


def test_situacao_recarregada_do_banco(colaborador, ferias, aprovado):
    """Objeto em memória desatualizado não engana a checagem."""
    SituacaoAusencia.objects.filter(pk=aprovado.pk).update(ativo=False)

    erro = erro_de(validar_ausencia, colaborador, ferias, [
        PeriodoInformado(d('01/03/2026'), d('02/03/2026'), aprovado),
    ])
    assert erro.erros_por_periodo == {0: ['A situação "Aprovado" está inativa.']}


# ---------------------------------------------------------------------------
# Cabeçalho (validar_ausencia)
# ---------------------------------------------------------------------------
def test_colaborador_e_tipo_obrigatorios():
    erro = erro_de(validar_ausencia, None, None, [PeriodoInformado(d('01/03/2026'), d('02/03/2026'))])

    assert erro.erros_campos == {
        'colaborador': ['Informe o colaborador.'],
        'tipo': ['Informe o tipo de ausência.'],
    }


def test_colaborador_inativo_recusado_em_registro_novo(colaborador, ferias):
    colaborador.ativo = False
    colaborador.save()

    erro = erro_de(validar_ausencia, colaborador, ferias, [PeriodoInformado(d('01/03/2026'), d('02/03/2026'))])
    assert erro.erros_campos == {'colaborador': ['Colaborador inativo não pode receber ausências.']}


def test_tipo_inativo_recusado_em_registro_novo(colaborador, ferias):
    ferias.ativo = False
    ferias.save()

    erro = erro_de(validar_ausencia, colaborador, ferias, [PeriodoInformado(d('01/03/2026'), d('02/03/2026'))])
    assert erro.erros_campos == {'tipo': ['O tipo "Férias" está inativo.']}


def test_erros_de_cabecalho_e_de_linha_juntos(colaborador, ferias):
    colaborador.ativo = False
    colaborador.save()

    erro = erro_de(validar_ausencia, colaborador, ferias, [PeriodoInformado(None, d('02/03/2026'))])
    assert set(erro.erros_campos) == {'colaborador'}
    assert erro.erros_por_periodo == {0: ['Informe a data de início.']}


def test_id_de_periodo_de_outra_ausencia(gravar_ausencia, colaborador, ferias):
    outra = gravar_ausencia(colaborador, ferias, ('01/01/2026', '02/01/2026'))
    estranho = outra.periodos.get()

    erro = erro_de(validar_ausencia, colaborador, ferias, [
        PeriodoInformado(d('01/03/2026'), d('02/03/2026'), id=estranho.pk),
    ])
    assert erro.erros_por_periodo == {0: ['Este período não pertence a este registro.']}


def test_id_repetido(gravar_ausencia, colaborador, ferias):
    ausencia = gravar_ausencia(colaborador, ferias, ('01/01/2026', '02/01/2026'))
    periodo = ausencia.periodos.get()

    erro = erro_de(validar_ausencia, colaborador, ferias, [
        PeriodoInformado(d('01/01/2026'), d('02/01/2026'), id=periodo.pk),
        PeriodoInformado(d('01/03/2026'), d('02/03/2026'), id=periodo.pk),
    ], ausencia=ausencia)
    assert erro.erros_por_periodo == {1: ['Período repetido no envio.']}
