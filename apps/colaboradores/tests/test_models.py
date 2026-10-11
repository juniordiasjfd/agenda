import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.colaboradores.models import Colaborador, Departamento

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Colaborador: nome
# ---------------------------------------------------------------------------
def test_nome_colapsa_espacos_e_preserva_caixa_e_acentos():
    colaborador = Colaborador.objects.create(nome='  Helena   Teixeira  Exemplo ')

    colaborador.refresh_from_db()
    assert colaborador.nome == 'Helena Teixeira Exemplo'
    assert colaborador.nome_normalizado == 'helena teixeira exemplo'


def test_nome_normalizado_acompanha_update_fields():
    colaborador = Colaborador.objects.create(nome='Ana Souza')
    colaborador.nome = 'Ána  Souza Lima'
    colaborador.save(update_fields=['nome'])

    colaborador.refresh_from_db()
    assert colaborador.nome == 'Ána Souza Lima'
    assert colaborador.nome_normalizado == 'ana souza lima'


def test_padroes():
    colaborador = Colaborador.objects.create(nome='Fulano')
    assert colaborador.ativo is True
    assert colaborador.departamento is None
    assert colaborador.usuario is None


@pytest.mark.parametrize('variacao', ['jose da silva', 'JOSÉ DA SILVA', 'José  da Silva', ' Jose da Sílva '])
def test_unicidade_por_nome_normalizado(colaborador, variacao):
    with pytest.raises(IntegrityError), transaction.atomic():
        Colaborador.objects.create(nome=variacao)


def test_full_clean_aponta_nome_duplicado_no_campo(colaborador):
    with pytest.raises(ValidationError) as erro:
        Colaborador(nome='JOSE  DA SILVA').full_clean()
    assert 'nome' in erro.value.message_dict


def test_full_clean_aceita_o_proprio_nome_na_edicao(colaborador):
    colaborador.nome = 'JOSÉ DA SILVA'
    colaborador.full_clean()


def test_ordenacao_por_nome_normalizado():
    for nome in ['Bruna', 'álvaro', 'Ana', 'Úrsula', 'carlos']:
        Colaborador.objects.create(nome=nome)

    assert [c.nome for c in Colaborador.objects.all()] == ['álvaro', 'Ana', 'Bruna', 'carlos', 'Úrsula']


def test_usuario_one_to_one(usuario_ativo):
    Colaborador.objects.create(nome='Primeiro', usuario=usuario_ativo)

    with pytest.raises(IntegrityError), transaction.atomic():
        Colaborador.objects.create(nome='Segundo', usuario=usuario_ativo)


def test_excluir_usuario_desvincula_colaborador(usuario_ativo):
    colaborador = Colaborador.objects.create(nome='Vinculado', usuario=usuario_ativo)
    usuario_ativo.delete()

    colaborador.refresh_from_db()
    assert colaborador.usuario is None


# ---------------------------------------------------------------------------
# Departamento
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('variacao', ['financeiro', 'FINANCEIRO', 'FinanCeiro'])
def test_departamento_unico_sem_diferenca_de_caixa(departamento, variacao):
    with pytest.raises(IntegrityError), transaction.atomic():
        Departamento.objects.create(nome=variacao)


def test_departamento_full_clean_aponta_duplicado_no_campo(departamento):
    with pytest.raises(ValidationError) as erro:
        Departamento(nome=' FINANCEIRO ').full_clean()
    assert erro.value.message_dict == {'nome': ['Já existe um departamento com este nome.']}


def test_departamento_colapsa_espacos():
    departamento = Departamento.objects.create(nome='  Recursos   Humanos ')
    assert departamento.nome == 'Recursos Humanos'


def test_departamento_com_colaboradores_nao_e_excluido(colaborador, departamento):
    with pytest.raises(ProtectedError):
        departamento.delete()
    assert Departamento.objects.filter(pk=departamento.pk).exists()


def test_departamento_sem_colaboradores_e_excluido(departamento):
    departamento.delete()
    assert not Departamento.objects.exists()
