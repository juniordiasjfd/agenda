"""SoftDeleteMixin (apps.core) com dados reais, pela Ausencia."""

import pytest

from apps.ausencias.models import Ausencia

pytestmark = pytest.mark.django_db


@pytest.fixture
def ativa(gravar_ausencia, colaborador, ferias):
    return gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))


@pytest.fixture
def excluida(gravar_ausencia, colaborador, ferias, admin):
    ausencia = gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026'))
    ausencia.excluir(admin)
    return ausencia


def test_manager_padrao_oculta_excluidas(ativa, excluida):
    assert list(Ausencia.objects.all()) == [ativa]
    assert not Ausencia.objects.filter(pk=excluida.pk).exists()


def test_manager_todos_inclui_excluidas(ativa, excluida):
    assert set(Ausencia.todos.all()) == {ativa, excluida}


def test_relacao_reversa_do_colaborador_oculta_excluidas(ativa, excluida, colaborador):
    assert list(colaborador.ausencias.all()) == [ativa]


def test_excluir_preenche_quando_e_quem(excluida, admin):
    excluida.refresh_from_db()

    assert excluida.esta_excluido
    assert excluida.excluido_em is not None
    assert excluida.excluido_por == admin


def test_excluir_mantem_os_periodos(excluida):
    assert excluida.periodos.count() == 1


def test_restaurar_volta_ao_manager_padrao(excluida):
    excluida.restaurar()

    assert Ausencia.objects.filter(pk=excluida.pk).exists()
    excluida.refresh_from_db()
    assert excluida.excluido_em is None
    assert excluida.excluido_por is None


def test_periodo_acessa_ausencia_excluida(excluida):
    """O acesso pela FK usa o manager base: o período de uma ausência
    excluída continua sabendo de qual ausência é."""
    periodo = excluida.periodos.get()
    assert Ausencia.todos.get(pk=periodo.ausencia_id) == periodo.ausencia
