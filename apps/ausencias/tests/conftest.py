from datetime import date

import pytest

from apps.ausencias import ausencias_service
from apps.ausencias.models import Ausencia, PeriodoAusencia, SituacaoAusencia, TipoAusencia
from apps.colaboradores.models import Colaborador


def d(texto):
    """'10/03/2026' -> date(2026, 3, 10): deixa as tabelas de casos legíveis."""
    dia, mes, ano = map(int, texto.split('/'))
    return date(ano, mes, dia)


@pytest.fixture
def gravar_ausencia(db):
    """Grava direto no banco, SEM o serviço (sem validação), para montar o
    cenário: ``gravar_ausencia(colaborador, tipo, ('01/03/2026', '10/03/2026'),
    ('20/03/2026', '22/03/2026', situacao))``."""
    def _gravar(colaborador, tipo, *periodos):
        ausencia = Ausencia.objects.create(
            colaborador=colaborador, tipo=tipo, codigo=ausencias_service.gerar_codigo(),
        )
        padrao = SituacaoAusencia.objects.get(padrao=True)
        for periodo in periodos:
            inicio, fim, situacao = (*periodo, padrao)[:3]
            PeriodoAusencia.objects.create(ausencia=ausencia, data_inicio=d(inicio), data_fim=d(fim), situacao=situacao)
        return ausencia
    return _gravar


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
