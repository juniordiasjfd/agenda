import pytest

from apps.ausencias.models import SituacaoAusencia, TipoAusencia

pytestmark = pytest.mark.django_db


def test_tipos_iniciais_em_ordem_com_cores_do_legado():
    tipos = list(TipoAusencia.objects.values_list('nome', 'cor', 'ativo'))

    assert tipos == [
        ('Férias', '#2f5fd0', True),
        ('Banco de horas', '#d9822b', True),
        ('Licença', '#8a4fbf', True),
        ('Outro', '#6b7a89', True),
    ]


def test_cores_iniciais_distintas():
    cores = list(TipoAusencia.objects.values_list('cor', flat=True))
    assert len(set(cores)) == len(cores)


def test_situacoes_iniciais():
    situacoes = list(SituacaoAusencia.objects.values_list('nome', 'ativo', 'padrao', 'conta_como_ausencia'))

    assert situacoes == [
        ('Planejado', True, True, True),
        ('Aprovado', True, False, True),
        ('Realizado', True, False, True),
        ('Cancelado', True, False, False),
    ]


def test_uma_unica_situacao_padrao_planejado():
    assert list(SituacaoAusencia.objects.filter(padrao=True).values_list('nome', flat=True)) == ['Planejado']
