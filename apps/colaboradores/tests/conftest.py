import pytest

from apps.colaboradores.models import Colaborador, Departamento


@pytest.fixture
def admin_client(client, admin):
    client.force_login(admin)
    return client


@pytest.fixture
def gestor_client(client, gestor):
    client.force_login(gestor)
    return client


@pytest.fixture
def departamento(db):
    return Departamento.objects.create(nome='Financeiro')


@pytest.fixture
def colaborador(db, departamento):
    return Colaborador.objects.create(nome='José da Silva', departamento=departamento)
