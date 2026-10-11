"""``criar_ausencia(codigo=...)`` e a regra de sobreposição única.

A mesma função pura (``conflitam``) decide o conflito contra o banco
(``periodos_conflitantes``) e entre períodos ainda não gravados (envio do
formulário e lote da importação). Os casos de borda abaixo rodam nos dois
caminhos e precisam dar o mesmo resultado.
"""

import pytest

from apps.ausencias import ausencias_service
from apps.ausencias.ausencias_service import ErroValidacaoAusencia, PeriodoInformado
from apps.ausencias.models import Ausencia
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Código informado
# ---------------------------------------------------------------------------
def _criar(colaborador, tipo, usuario, codigo=None, inicio='02/03/2026', fim='06/03/2026'):
    return ausencias_service.criar_ausencia(
        colaborador, tipo, [PeriodoInformado(d(inicio), d(fim))], '', usuario, codigo=codigo,
    )


def test_sem_codigo_gera_um(colaborador, ferias, admin):
    ausencia = _criar(colaborador, ferias, admin)
    assert len(ausencia.codigo) == ausencias_service.TAMANHO_CODIGO


@pytest.mark.parametrize('codigo', ['SMG7X3K2AB', 'abc-123_X', 'A' * 32, '  SLEGADO1  '])
def test_codigo_informado_valido_e_gravado(colaborador, ferias, admin, codigo):
    ausencia = _criar(colaborador, ferias, admin, codigo=codigo)
    assert ausencia.codigo == codigo.strip()


@pytest.mark.parametrize('codigo, trecho', [
    ('A' * 33, 'no máximo 32'),
    ('COM ESPACO', 'letras, números, hífen e sublinhado'),
    ('ÇÃO1', 'letras, números, hífen e sublinhado'),
    ('A;B', 'letras, números, hífen e sublinhado'),
    ('', 'Informe o código'),
])
def test_codigo_informado_invalido(colaborador, ferias, admin, codigo, trecho):
    with pytest.raises(ErroValidacaoAusencia) as erro:
        _criar(colaborador, ferias, admin, codigo=codigo)
    assert trecho in erro.value.erros_campos['codigo'][0]
    assert not Ausencia.todos.exists()


def test_codigo_em_uso_e_recusado(colaborador, ferias, admin):
    _criar(colaborador, ferias, admin, codigo='SLEGADO1')
    with pytest.raises(ErroValidacaoAusencia) as erro:
        _criar(colaborador, ferias, admin, codigo='SLEGADO1', inicio='01/04/2026', fim='02/04/2026')
    assert 'Já existe uma ausência com o código SLEGADO1' in erro.value.erros_campos['codigo'][0]


def test_codigo_em_uso_sem_diferenca_de_caixa(colaborador, ferias, admin):
    _criar(colaborador, ferias, admin, codigo='SLEGADO1')
    with pytest.raises(ErroValidacaoAusencia):
        _criar(colaborador, ferias, admin, codigo='slegado1', inicio='01/04/2026', fim='02/04/2026')


def test_codigo_de_ausencia_na_lixeira_tambem_conta(colaborador, ferias, admin):
    ausencia = _criar(colaborador, ferias, admin, codigo='SLEGADO1')
    ausencias_service.excluir_ausencia(ausencia, admin)
    with pytest.raises(ErroValidacaoAusencia):
        _criar(colaborador, ferias, admin, codigo='SLEGADO1', inicio='01/04/2026', fim='02/04/2026')
    assert Ausencia.todos.count() == 1


def test_codigos_em_uso_numa_query(colaborador, ferias, admin, django_assert_num_queries):
    _criar(colaborador, ferias, admin, codigo='AAA')
    with django_assert_num_queries(1):
        assert ausencias_service.codigos_em_uso(['aaa', 'BBB', '']) == {'AAA'}


# ---------------------------------------------------------------------------
# Regra única: mesmos casos no banco e entre períodos não gravados
# ---------------------------------------------------------------------------
# (gravado/anterior, novo, situação do gravado conta?, situação do novo conta?, conflita?)
CASOS = [
    pytest.param(('01/03/2026', '10/03/2026'), ('10/03/2026', '15/03/2026'), True, True, True, id='fim-igual-inicio'),
    pytest.param(('10/03/2026', '15/03/2026'), ('01/03/2026', '10/03/2026'), True, True, True, id='inicio-igual-fim'),
    pytest.param(('01/03/2026', '10/03/2026'), ('11/03/2026', '15/03/2026'), True, True, False, id='dia-seguinte'),
    pytest.param(('11/03/2026', '15/03/2026'), ('01/03/2026', '10/03/2026'), True, True, False, id='dia-anterior'),
    pytest.param(('01/03/2026', '31/03/2026'), ('10/03/2026', '12/03/2026'), True, True, True, id='contido'),
    pytest.param(('05/03/2026', '05/03/2026'), ('05/03/2026', '05/03/2026'), True, True, True, id='mesmo-dia'),
    pytest.param(('01/03/2026', '10/03/2026'), ('05/03/2026', '15/03/2026'), False, True, False, id='gravado-nao-conta'),
    pytest.param(('01/03/2026', '10/03/2026'), ('05/03/2026', '15/03/2026'), True, False, False, id='novo-nao-conta'),
]


def _situacao(conta, planejado, cancelado):
    return planejado if conta else cancelado


@pytest.mark.parametrize('anterior, novo, anterior_conta, novo_conta, esperado', CASOS)
def test_caminho_banco(
    gravar_ausencia, colaborador, ferias, banco_horas, planejado, cancelado,
    anterior, novo, anterior_conta, novo_conta, esperado,
):
    # Tipos diferentes de propósito: o tipo não importa.
    gravar_ausencia(colaborador, banco_horas, (*anterior, _situacao(anterior_conta, planejado, cancelado)))
    periodo = PeriodoInformado(d(novo[0]), d(novo[1]), _situacao(novo_conta, planejado, cancelado))

    conflitos = ausencias_service.periodos_conflitantes(colaborador, [periodo])

    assert bool(conflitos) is esperado


@pytest.mark.parametrize('anterior, novo, anterior_conta, novo_conta, esperado', CASOS)
def test_caminho_lote(planejado, cancelado, anterior, novo, anterior_conta, novo_conta, esperado):
    a = PeriodoInformado(d(anterior[0]), d(anterior[1]), _situacao(anterior_conta, planejado, cancelado))
    b = PeriodoInformado(d(novo[0]), d(novo[1]), _situacao(novo_conta, planejado, cancelado))

    assert ausencias_service.conflitam(a, b) is esperado
    assert ausencias_service.conflitam(b, a) is esperado


@pytest.mark.parametrize('anterior, novo, anterior_conta, novo_conta, esperado', CASOS)
def test_caminho_mesmo_envio(
    colaborador, ferias, planejado, cancelado, anterior, novo, anterior_conta, novo_conta, esperado,
):
    periodos = [
        PeriodoInformado(d(anterior[0]), d(anterior[1]), _situacao(anterior_conta, planejado, cancelado)),
        PeriodoInformado(d(novo[0]), d(novo[1]), _situacao(novo_conta, planejado, cancelado)),
    ]
    if esperado:
        with pytest.raises(ErroValidacaoAusencia) as erro:
            ausencias_service.validar_periodos(colaborador, periodos)
        assert 'Sobrepõe o período 1' in erro.value.erros_por_periodo[1][0]
    else:
        ausencias_service.validar_periodos(colaborador, periodos)


def test_banco_ignora_ausencia_excluida(gravar_ausencia, colaborador, ferias, admin):
    gravada = gravar_ausencia(colaborador, ferias, ('01/03/2026', '10/03/2026'))
    gravada.excluir(admin)
    periodo = PeriodoInformado(d('05/03/2026'), d('06/03/2026'))

    assert ausencias_service.periodos_conflitantes(colaborador, [periodo]) == []
    assert list(ausencias_service.periodos_gravados([colaborador.pk])) == []


def test_periodos_gravados_inclui_situacao_que_nao_conta(gravar_ausencia, colaborador, ferias, cancelado):
    gravar_ausencia(colaborador, ferias, ('01/03/2026', '10/03/2026', cancelado))
    assert len(ausencias_service.periodos_gravados([colaborador.pk])) == 1
