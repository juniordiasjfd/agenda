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


# ---------------------------------------------------------------------------
# Telas
# ---------------------------------------------------------------------------
def iso(texto):
    """'10/03/2026' -> '2026-03-10' (valor de <input type="date">)."""
    return d(texto).isoformat() if texto else ''


def dados_formulario(colaborador, tipo, *linhas, observacoes='', iniciais=0, **extras):
    """POST da tela de registro/edição. Cada linha é um dict com
    ``inicio``/``fim`` ('dd/mm/aaaa') e, opcionais, ``situacao`` (objeto),
    ``id`` e ``remover``."""
    dados = {
        'colaborador': colaborador.pk if colaborador else '',
        'tipo': tipo.pk if tipo else '',
        'observacoes': observacoes,
        'periodos-TOTAL_FORMS': str(len(linhas)),
        'periodos-INITIAL_FORMS': str(iniciais),
        'periodos-MIN_NUM_FORMS': '0',
        'periodos-MAX_NUM_FORMS': '12',
        **extras,
    }
    padrao = SituacaoAusencia.objects.get(padrao=True)
    for i, linha_ in enumerate(linhas):
        prefixo = f'periodos-{i}-'
        dados[prefixo + 'data_inicio'] = iso(linha_.get('inicio'))
        dados[prefixo + 'data_fim'] = iso(linha_.get('fim'))
        dados[prefixo + 'situacao'] = str(linha_.get('situacao', padrao).pk)
        if linha_.get('id'):
            dados[prefixo + 'id'] = str(linha_['id'])
        if linha_.get('remover'):
            dados[prefixo + 'DELETE'] = 'on'
    return dados


def linha(inicio, fim, **extras):
    return {'inicio': inicio, 'fim': fim, **extras}


@pytest.fixture
def gestor_client(client, gestor):
    client.force_login(gestor)
    return client
