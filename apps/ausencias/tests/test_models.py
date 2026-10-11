import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.ausencias.models import SituacaoAusencia, TipoAusencia

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# TipoAusencia
# ---------------------------------------------------------------------------
def test_tipo_padroes_e_nome_com_espacos_colapsados():
    tipo = TipoAusencia.objects.create(nome='  Home   office ', cor='#123abc')

    tipo.refresh_from_db()
    assert tipo.nome == 'Home office'
    assert tipo.ativo is True
    assert tipo.ordem == 0
    assert str(tipo) == 'Home office'


@pytest.mark.parametrize('variacao', ['férias', 'FÉRIAS', ' Férias '])
def test_tipo_nome_unico_sem_diferenca_de_caixa_no_banco(variacao):
    with pytest.raises(IntegrityError), transaction.atomic():
        TipoAusencia.objects.create(nome=variacao, cor='#000000')


def test_tipo_nome_duplicado_no_clean_com_mensagem_no_campo():
    tipo = TipoAusencia(nome='FÉRIAS', cor='#000000')

    with pytest.raises(ValidationError) as erro:
        tipo.full_clean()
    assert 'nome' in erro.value.message_dict


@pytest.mark.parametrize('cor', ['2f5fd0', '#2f5fd', '#2f5fd00', '#gggggg', 'azul', '', '#2F5FD0 '])
def test_tipo_cor_invalida_recusada_no_clean(cor):
    tipo = TipoAusencia(nome='Novo', cor=cor)

    with pytest.raises(ValidationError) as erro:
        tipo.full_clean()
    assert 'cor' in erro.value.message_dict


@pytest.mark.parametrize('cor', ['azul', '#12345', '#zzzzzz'])
def test_tipo_cor_invalida_recusada_no_banco(cor):
    with pytest.raises(IntegrityError), transaction.atomic():
        TipoAusencia.objects.create(nome='Novo', cor=cor)


@pytest.mark.parametrize('cor', ['#2f5fd0', '#2F5FD0', '#000000'])
def test_tipo_cor_valida(cor):
    TipoAusencia(nome='Novo', cor=cor).full_clean()


def test_tipos_ordenados_por_ordem_e_nome():
    TipoAusencia.objects.create(nome='Zeta', cor='#000000', ordem=0)
    TipoAusencia.objects.create(nome='Alfa', cor='#000000', ordem=0)

    nomes = list(TipoAusencia.objects.values_list('nome', flat=True))
    assert nomes[:2] == ['Alfa', 'Zeta']


# ---------------------------------------------------------------------------
# SituacaoAusencia
# ---------------------------------------------------------------------------
def test_situacao_padroes():
    situacao = SituacaoAusencia.objects.create(nome='Em análise')

    assert situacao.ativo is True
    assert situacao.padrao is False
    assert situacao.conta_como_ausencia is True
    assert situacao.ordem == 0


@pytest.mark.parametrize('variacao', ['planejado', 'PLANEJADO', 'Planejado  '])
def test_situacao_nome_unico_sem_diferenca_de_caixa(variacao):
    with pytest.raises(IntegrityError), transaction.atomic():
        SituacaoAusencia.objects.create(nome=variacao)


def test_situacao_nome_duplicado_no_clean():
    with pytest.raises(ValidationError) as erro:
        SituacaoAusencia(nome='aprovado').full_clean()
    assert 'nome' in erro.value.message_dict


def test_no_maximo_uma_situacao_padrao_no_banco():
    with pytest.raises(IntegrityError), transaction.atomic():
        SituacaoAusencia.objects.create(nome='Outra padrão', padrao=True)


def test_full_clean_de_nova_padrao_nao_esbarra_na_constraint():
    """O serviço desmarca a anterior antes de gravar; o clean não pode
    recusar antes disso."""
    SituacaoAusencia(nome='Nova padrão', padrao=True).full_clean()
