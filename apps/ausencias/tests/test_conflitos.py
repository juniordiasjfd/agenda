"""Sobreposição de períodos: ``periodos_conflitantes`` e a checagem dentro
de ``validar_periodos``/``validar_ausencia``."""

import pytest

from apps.ausencias.ausencias_service import (
    ErroValidacaoAusencia,
    PeriodoInformado,
    periodos_conflitantes,
    validar_ausencia,
    validar_periodos,
)
from apps.ausencias.models import SituacaoAusencia
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db


def p(inicio, fim, situacao=None, id=None):
    return PeriodoInformado(d(inicio), d(fim), situacao, id)


@pytest.fixture
def registrado(gravar_ausencia, colaborador, ferias):
    """Férias de Ana, Planejado, de 10/03/2026 a 20/03/2026."""
    return gravar_ausencia(colaborador, ferias, ('10/03/2026', '20/03/2026'))


# ---------------------------------------------------------------------------
# Tabela de casos contra um período gravado (10/03 a 20/03, fim inclusivo)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('inicio, fim, conflita', [
    ('01/03/2026', '05/03/2026', False),   # sem contato, antes
    ('25/03/2026', '30/03/2026', False),   # sem contato, depois
    ('01/03/2026', '09/03/2026', False),   # encosta: termina 09, gravado começa 10
    ('21/03/2026', '25/03/2026', False),   # encosta: gravado termina 20, começa 21
    ('05/03/2026', '10/03/2026', True),    # compartilha exatamente o dia 10
    ('20/03/2026', '25/03/2026', True),    # compartilha exatamente o dia 20
    ('12/03/2026', '15/03/2026', True),    # contido no gravado
    ('15/03/2026', '15/03/2026', True),    # um dia, dentro
    ('10/03/2026', '20/03/2026', True),    # iguais
    ('01/03/2026', '31/03/2026', True),    # cobre o gravado
    ('09/03/2026', '11/03/2026', True),    # cruza o início
], ids=[
    'antes', 'depois', 'encosta-antes', 'encosta-depois', 'um-dia-no-inicio',
    'um-dia-no-fim', 'contido', 'um-dia-dentro', 'iguais', 'cobre', 'cruza-inicio',
])
def test_tabela_de_sobreposicao(registrado, colaborador, inicio, fim, conflita):
    conflitos = periodos_conflitantes(colaborador, [p(inicio, fim)])

    assert bool(conflitos) is conflita
    if conflita:
        with pytest.raises(ErroValidacaoAusencia) as erro:
            validar_periodos(colaborador, [p(inicio, fim)])
        assert erro.value.erros_por_periodo == {
            0: ['Sobrepõe Férias já registrado de 10/03/2026 a 20/03/2026.'],
        }
    else:
        validar_periodos(colaborador, [p(inicio, fim)])


def test_conflito_traz_o_periodo_gravado_e_o_indice(registrado, colaborador):
    conflitos = periodos_conflitantes(colaborador, [p('01/01/2026', '02/01/2026'), p('15/03/2026', '16/03/2026')])

    assert len(conflitos) == 1
    assert conflitos[0].indice == 1
    assert conflitos[0].periodo == registrado.periodos.get()
    assert conflitos[0].periodo.ausencia == registrado


def test_periodo_longo_cobrindo_varios(gravar_ausencia, colaborador, ferias, banco_horas):
    gravar_ausencia(colaborador, ferias, ('02/03/2026', '03/03/2026'), ('20/03/2026', '22/03/2026'))
    gravar_ausencia(colaborador, banco_horas, ('10/03/2026', '10/03/2026'))

    conflitos = periodos_conflitantes(colaborador, [p('01/03/2026', '31/03/2026')])

    assert [c.periodo.data_inicio for c in conflitos] == [d('02/03/2026'), d('10/03/2026'), d('20/03/2026')]
    with pytest.raises(ErroValidacaoAusencia) as erro:
        validar_periodos(colaborador, [p('01/03/2026', '31/03/2026')])
    assert erro.value.erros_por_periodo[0] == [
        'Sobrepõe Férias já registrado de 02/03/2026 a 03/03/2026.',
        'Sobrepõe Banco de horas já registrado de 10/03/2026 a 10/03/2026.',
        'Sobrepõe Férias já registrado de 20/03/2026 a 22/03/2026.',
    ]


# ---------------------------------------------------------------------------
# O que conta e o que não conta
# ---------------------------------------------------------------------------
def test_tipos_diferentes_tambem_conflitam(registrado, colaborador):
    """Gravado é Férias; o novo pode ser de qualquer tipo: o tipo não entra
    na checagem."""
    assert periodos_conflitantes(colaborador, [p('15/03/2026', '15/03/2026')])


def test_outro_colaborador_nao_conflita(registrado, outro_colaborador):
    assert periodos_conflitantes(outro_colaborador, [p('10/03/2026', '20/03/2026')]) == []
    validar_periodos(outro_colaborador, [p('10/03/2026', '20/03/2026')])


def test_ausencia_excluida_nao_conflita(registrado, colaborador, admin):
    registrado.excluir(admin)

    assert periodos_conflitantes(colaborador, [p('10/03/2026', '20/03/2026')]) == []


@pytest.mark.parametrize('nome_situacao, conflita', [
    ('Planejado', True),
    ('Aprovado', True),
    ('Realizado', True),
    ('Cancelado', False),
])
def test_situacao_do_gravado(gravar_ausencia, colaborador, ferias, nome_situacao, conflita):
    situacao = SituacaoAusencia.objects.get(nome=nome_situacao)
    gravar_ausencia(colaborador, ferias, ('10/03/2026', '20/03/2026', situacao))

    assert bool(periodos_conflitantes(colaborador, [p('15/03/2026', '16/03/2026')])) is conflita


def test_situacao_que_deixa_de_contar_libera_o_periodo(gravar_ausencia, colaborador, ferias, aprovado):
    gravar_ausencia(colaborador, ferias, ('10/03/2026', '20/03/2026', aprovado))
    aprovado.conta_como_ausencia = False
    aprovado.save()

    assert periodos_conflitantes(colaborador, [p('15/03/2026', '16/03/2026')]) == []


def test_periodo_novo_cancelado_nao_conflita(registrado, colaborador, cancelado):
    assert periodos_conflitantes(colaborador, [p('15/03/2026', '16/03/2026', cancelado)]) == []
    validar_periodos(colaborador, [p('15/03/2026', '16/03/2026', cancelado)])


def test_periodo_novo_sem_situacao_usa_a_padrao_e_conflita(registrado, colaborador):
    with pytest.raises(ErroValidacaoAusencia):
        validar_periodos(colaborador, [p('15/03/2026', '16/03/2026', None)])


# ---------------------------------------------------------------------------
# Períodos do mesmo envio
# ---------------------------------------------------------------------------
def test_periodos_do_mesmo_envio_se_sobrepondo(colaborador):
    with pytest.raises(ErroValidacaoAusencia) as erro:
        validar_periodos(colaborador, [
            p('01/03/2026', '10/03/2026'),
            p('20/03/2026', '25/03/2026'),
            p('10/03/2026', '12/03/2026'),
        ])

    assert erro.value.erros_por_periodo == {
        2: ['Sobrepõe o período 1 deste registro (01/03/2026 a 10/03/2026).'],
    }


def test_periodos_do_mesmo_envio_encostados(colaborador):
    validar_periodos(colaborador, [p('01/03/2026', '10/03/2026'), p('11/03/2026', '12/03/2026')])


def test_periodos_do_mesmo_envio_com_um_cancelado(colaborador, cancelado):
    validar_periodos(colaborador, [p('01/03/2026', '10/03/2026'), p('05/03/2026', '12/03/2026', cancelado)])


def test_periodo_do_envio_conflitando_com_varios_do_envio(colaborador):
    with pytest.raises(ErroValidacaoAusencia) as erro:
        validar_periodos(colaborador, [
            p('01/03/2026', '02/03/2026'),
            p('05/03/2026', '06/03/2026'),
            p('01/03/2026', '31/03/2026'),
        ])

    assert len(erro.value.erros_por_periodo[2]) == 2
    assert set(erro.value.erros_por_periodo) == {2}


# ---------------------------------------------------------------------------
# Edição
# ---------------------------------------------------------------------------
def test_edicao_ignora_os_proprios_periodos(registrado, colaborador):
    assert periodos_conflitantes(colaborador, [p('12/03/2026', '25/03/2026')], excluir_ausencia=registrado) == []
    validar_periodos(colaborador, [p('12/03/2026', '25/03/2026')], excluir_ausencia=registrado)


def test_edicao_conflita_com_outra_ausencia_do_mesmo_colaborador(
    registrado, gravar_ausencia, colaborador, banco_horas,
):
    gravar_ausencia(colaborador, banco_horas, ('24/03/2026', '24/03/2026'))

    conflitos = periodos_conflitantes(colaborador, [p('12/03/2026', '25/03/2026')], excluir_ausencia=registrado)

    assert [c.periodo.ausencia.tipo.nome for c in conflitos] == ['Banco de horas']


def test_editar_sem_mudar_datas_nao_gera_falso_conflito(registrado, colaborador, ferias):
    periodo = registrado.periodos.get()

    validar_ausencia(colaborador, ferias, [
        p('10/03/2026', '20/03/2026', periodo.situacao, id=periodo.pk),
    ], ausencia=registrado)


def test_restauracao_simulada_ignora_a_propria_ausencia_excluida(registrado, colaborador, admin):
    """Os períodos da própria ausência (gravados) não conflitam com eles
    mesmos ao rechecar."""
    registrado.excluir(admin)
    periodos = list(registrado.periodos.all())

    assert periodos_conflitantes(colaborador, periodos, excluir_ausencia=registrado) == []
