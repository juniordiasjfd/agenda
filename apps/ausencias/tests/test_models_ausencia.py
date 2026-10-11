import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.ausencias.models import Ausencia, PeriodoAusencia
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# PeriodoAusencia
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('inicio, fim, dias', [
    ('10/03/2026', '10/03/2026', 1),      # um dia só (fim inclusivo)
    ('10/03/2026', '20/03/2026', 11),
    ('28/03/2026', '02/04/2026', 6),      # virada de mês
    ('30/12/2025', '02/01/2026', 4),      # virada de ano
    ('27/02/2028', '01/03/2028', 4),      # bissexto: 27, 28, 29/02 e 01/03
    ('27/02/2026', '01/03/2026', 3),      # não bissexto
    ('01/01/2026', '31/12/2026', 365),
])
def test_dias(inicio, fim, dias):
    assert PeriodoAusencia(data_inicio=d(inicio), data_fim=d(fim)).dias == dias


def test_fim_antes_do_inicio_recusado_no_banco(gravar_ausencia, colaborador, ferias):
    with pytest.raises(IntegrityError), transaction.atomic():
        gravar_ausencia(colaborador, ferias, ('10/03/2026', '09/03/2026'))


def test_fim_igual_ao_inicio_aceito_no_banco(gravar_ausencia, colaborador, ferias):
    ausencia = gravar_ausencia(colaborador, ferias, ('10/03/2026', '10/03/2026'))
    assert ausencia.periodos.get().dias == 1


def test_periodos_ordenados_por_data_inicio(gravar_ausencia, colaborador, ferias):
    ausencia = gravar_ausencia(
        colaborador, ferias, ('20/03/2026', '21/03/2026'), ('01/03/2026', '02/03/2026'),
    )

    assert [p.data_inicio for p in ausencia.periodos.all()] == [d('01/03/2026'), d('20/03/2026')]


def test_periodos_apagados_junto_com_a_ausencia(gravar_ausencia, colaborador, ferias):
    ausencia = gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))

    ausencia.delete()

    assert not PeriodoAusencia.objects.exists()


def test_indice_nas_datas():
    nomes = [indice.name for indice in PeriodoAusencia._meta.indexes]
    assert 'ausencias_periodo_datas_idx' in nomes


def test_fks_indexadas():
    assert Ausencia._meta.get_field('colaborador').db_index
    assert PeriodoAusencia._meta.get_field('ausencia').db_index


# ---------------------------------------------------------------------------
# Ausencia
# ---------------------------------------------------------------------------
def test_titulo(gravar_ausencia, colaborador, ferias):
    ausencia = gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))

    assert ausencia.titulo == 'Ana Souza - Férias'
    assert ausencia.codigo in str(ausencia)


def test_codigo_unico(gravar_ausencia, colaborador, ferias):
    ausencia = gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))

    with pytest.raises(IntegrityError), transaction.atomic():
        Ausencia.objects.create(colaborador=colaborador, tipo=ferias, codigo=ausencia.codigo)


def test_codigo_aceita_id_legado_de_32_caracteres(colaborador, ferias):
    codigo = 'SOL-2025-0001-ABCDEFGHIJKLMNOPQR'
    assert len(codigo) == 32

    ausencia = Ausencia.objects.create(colaborador=colaborador, tipo=ferias, codigo=codigo)
    ausencia.full_clean()


# ---------------------------------------------------------------------------
# PROTECT
# ---------------------------------------------------------------------------
def test_tipo_em_uso_nao_pode_ser_excluido(gravar_ausencia, colaborador, ferias):
    gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))

    with pytest.raises(ProtectedError):
        ferias.delete()


def test_tipo_em_uso_por_ausencia_excluida_tambem_protegido(gravar_ausencia, colaborador, ferias, admin):
    gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026')).excluir(admin)

    with pytest.raises(ProtectedError):
        ferias.delete()


def test_situacao_em_uso_nao_pode_ser_excluida(gravar_ausencia, colaborador, ferias, aprovado):
    gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026', aprovado))

    with pytest.raises(ProtectedError):
        aprovado.delete()


def test_colaborador_com_ausencia_nao_pode_ser_excluido(gravar_ausencia, colaborador, ferias):
    gravar_ausencia(colaborador, ferias, ('01/03/2026', '02/03/2026'))

    with pytest.raises(ProtectedError):
        colaborador.delete()


def test_tipo_sem_uso_pode_ser_excluido(banco_horas):
    banco_horas.delete()
