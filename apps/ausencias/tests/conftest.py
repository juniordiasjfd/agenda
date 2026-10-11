import pytest

from apps.ausencias.models import SituacaoAusencia, TipoAusencia
from apps.colaboradores.models import Colaborador


@pytest.fixture
def admin_client(client, admin):
    client.force_login(admin)
    return client


# Tipos e situações vêm da data migration 0002_carga_inicial.
@pytest.fixture
def ferias(db):
    return TipoAusencia.objects.get(nome='Férias')


@pytest.fixture
def banco_horas(db):
    return TipoAusencia.objects.get(nome='Banco de horas')


@pytest.fixture
def planejado(db):
    return SituacaoAusencia.objects.get(nome='Planejado')


@pytest.fixture
def aprovado(db):
    return SituacaoAusencia.objects.get(nome='Aprovado')


@pytest.fixture
def cancelado(db):
    return SituacaoAusencia.objects.get(nome='Cancelado')


@pytest.fixture
def colaborador(db):
    return Colaborador.objects.create(nome='Ana Souza')


@pytest.fixture
def outro_colaborador(db):
    return Colaborador.objects.create(nome='Bruno Lima')
