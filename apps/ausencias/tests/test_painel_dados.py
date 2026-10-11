"""Endpoint JSON do painel: ``GET painel/dados/``."""

from datetime import datetime, timezone as dt_timezone

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.ausencias.models import Ausencia, TipoAusencia
from apps.colaboradores.models import Colaborador, Departamento

pytestmark = pytest.mark.django_db

URL = reverse('painel:dados')


@pytest.fixture
def logado(client, usuario_ativo):
    """Autenticado sem grupo: o painel é de todos."""
    client.force_login(usuario_ativo)
    return client


def dados(client, **parametros):
    resposta = client.get(URL, parametros)
    assert resposta.status_code == 200
    return resposta.json()


def nomes(client, **parametros):
    return [pessoa['nome'] for pessoa in dados(client, **parametros)['pessoas']]


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------
def test_formato_da_resposta(logado, colaborador, ferias, aprovado, gravar_ausencia):
    departamento = Departamento.objects.create(nome='TI')
    Colaborador.objects.filter(pk=colaborador.pk).update(departamento=departamento)
    ausencia = gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026', aprovado))

    corpo = dados(logado)

    assert set(corpo) == {'hoje', 'tipos', 'pessoas', 'avisos'}
    assert corpo['avisos'] == []
    assert {'id': ferias.pk, 'nome': 'Férias', 'cor': ferias.cor} in corpo['tipos']
    assert corpo['pessoas'] == [{
        'id': colaborador.pk,
        'nome': 'Ana Souza',
        'departamento': 'TI',
        'periodos': [{
            'inicio': '2026-03-10',
            'fim': '2026-03-12',
            'dias': 3,
            'tipo_id': ferias.pk,
            'situacao': 'Aprovado',
            'url': reverse('ausencias:detalhe', args=[ausencia.pk]),
        }],
    }]


def test_json_sem_cache_compartilhado(logado):
    resposta = logado.get(URL)

    assert resposta['Content-Type'] == 'application/json'
    assert resposta['Cache-Control'] == 'no-store'


def test_observacoes_nao_sao_enviadas(logado, colaborador, ferias, gravar_ausencia):
    ausencia = gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026'))
    Ausencia.objects.filter(pk=ausencia.pk).update(observacoes='Texto reservado XYZ')

    conteudo = logado.get(URL).content.decode()

    assert 'XYZ' not in conteudo
    assert 'observacoes' not in conteudo
    assert ausencia.codigo not in conteudo


def test_sem_departamento_vem_null(logado, colaborador):
    assert dados(logado)['pessoas'][0]['departamento'] is None


def test_hoje_e_a_data_do_servidor_em_sao_paulo(logado, monkeypatch):
    # 02:00 UTC de 16/03 = 23:00 de 15/03 em São Paulo.
    monkeypatch.setattr(timezone, 'now', lambda: datetime(2026, 3, 16, 2, 0, tzinfo=dt_timezone.utc))

    assert dados(logado)['hoje'] == '2026-03-15'


def test_tipo_inativo_com_periodo_aparece_na_legenda(logado, colaborador, gravar_ausencia):
    antigo = TipoAusencia.objects.create(nome='Antigo', cor='#123456', ativo=False)
    gravar_ausencia(colaborador, antigo, ('10/03/2026', '12/03/2026'))

    assert 'Antigo' in [tipo['nome'] for tipo in dados(logado)['tipos']]


# ---------------------------------------------------------------------------
# Filtros pela querystring
# ---------------------------------------------------------------------------
class TestFiltros:
    """Ana (TI): 10 a 12/03. Bruno (RH): 13/03, Cancelado. Carla (sem
    departamento): 13 a 14/03. Dora: inativa, 10/03. Eva (sem
    departamento): ausência excluída em 10/03."""

    @pytest.fixture(autouse=True)
    def _cenario(self, colaborador, outro_colaborador, ferias, cancelado, gravar_ausencia):
        self.ti = Departamento.objects.create(nome='TI')
        self.rh = Departamento.objects.create(nome='RH')
        Colaborador.objects.filter(pk=colaborador.pk).update(departamento=self.ti)
        Colaborador.objects.filter(pk=outro_colaborador.pk).update(departamento=self.rh)
        gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026'))
        gravar_ausencia(outro_colaborador, ferias, ('13/03/2026', '13/03/2026', cancelado))
        gravar_ausencia(Colaborador.objects.create(nome='Carla Dias'), ferias, ('13/03/2026', '14/03/2026'))
        gravar_ausencia(Colaborador.objects.create(nome='Dora Reis', ativo=False), ferias, ('10/03/2026', '10/03/2026'))
        eva = gravar_ausencia(Colaborador.objects.create(nome='Eva Melo'), ferias, ('10/03/2026', '10/03/2026'))
        Ausencia.objects.filter(pk=eva.pk).update(excluido_em=timezone.now())

    def test_sem_filtros(self, logado):
        assert nomes(logado) == ['Ana Souza', 'Bruno Lima', 'Carla Dias', 'Eva Melo']

    def test_q(self, logado):
        assert nomes(logado, q='CARLA') == ['Carla Dias']

    def test_departamento_um(self, logado):
        assert nomes(logado, departamento=[self.ti.pk]) == ['Ana Souza']

    def test_departamento_varios(self, logado):
        assert nomes(logado, departamento=[self.ti.pk, self.rh.pk]) == ['Ana Souza', 'Bruno Lima']

    def test_departamento_so_sem(self, logado):
        assert nomes(logado, departamento='sem') == ['Carla Dias', 'Eva Melo']

    def test_departamento_ids_e_sem(self, logado):
        assert nomes(logado, departamento=['sem', self.rh.pk]) == ['Bruno Lima', 'Carla Dias', 'Eva Melo']

    def test_ausente_bordas_inclusivas(self, logado):
        assert nomes(logado, ausente_de='2026-03-12', ausente_ate='2026-03-13') == ['Ana Souza', 'Carla Dias']

    def test_ausente_invertido(self, logado):
        assert nomes(logado, ausente_de='2026-03-14', ausente_ate='2026-03-14') == ['Carla Dias']
        assert nomes(logado, ausente_de='2026-03-14', ausente_ate='2026-03-11') == ['Ana Souza', 'Carla Dias']

    def test_ausente_so_uma_data(self, logado):
        assert nomes(logado, ausente_ate='2026-03-10') == ['Ana Souza']

    def test_situacao_que_nao_conta_e_excluida_nao_sao_ausencia(self, logado):
        assert nomes(logado, ausente_de='2026-03-13') == ['Carla Dias']
        assert nomes(logado, ausente_de='2026-03-10') == ['Ana Souza']

    def test_presente(self, logado):
        assert nomes(logado, presente_de='2026-03-13', presente_ate='2026-03-31') == [
            'Ana Souza', 'Bruno Lima', 'Eva Melo',
        ]

    def test_sem_registros_0(self, logado):
        assert nomes(logado, sem_registros='0') == ['Ana Souza', 'Carla Dias']

    def test_sem_registros_0_com_presenca(self, logado):
        assert nomes(logado, sem_registros='0', presente_de='2026-03-13') == ['Ana Souza']
        assert nomes(logado, sem_registros='1', presente_de='2026-03-13') == ['Ana Souza', 'Bruno Lima', 'Eva Melo']

    def test_sem_registros_hidden_mais_caixa_vale_o_ultimo(self, logado):
        assert nomes(logado, sem_registros=['0', '1']) == nomes(logado)

    def test_combinados(self, logado):
        assert nomes(
            logado, departamento=['sem', self.ti.pk], ausente_de='2026-03-01', ausente_ate='2026-03-31',
            presente_de='2026-03-14', q='a',
        ) == ['Ana Souza']

    def test_data_invalida_vira_aviso(self, logado):
        corpo = dados(logado, ausente_de='31/02/2026')

        assert len(corpo['avisos']) == 1
        assert len(corpo['pessoas']) == 4

    def test_todos_os_periodos_da_pessoa_filtrada(self, logado, colaborador, ferias, gravar_ausencia):
        gravar_ausencia(colaborador, ferias, ('01/01/2027', '02/01/2027'))

        pessoa, = dados(logado, ausente_de='2026-03-11')['pessoas']

        assert [p['inicio'] for p in pessoa['periodos']] == ['2026-03-10', '2027-01-01']


# ---------------------------------------------------------------------------
# Permissões e queries
# ---------------------------------------------------------------------------
def test_anonimo_vai_para_o_login(client):
    resposta = client.get(URL)

    assert resposta.status_code == 302
    assert resposta.url.startswith(reverse('usuarios:login'))


@pytest.mark.parametrize('perfil', ['usuario_ativo', 'gestor', 'admin'])
def test_qualquer_autenticado(client, request, perfil):
    client.force_login(request.getfixturevalue(perfil))

    assert client.get(URL).status_code == 200


def _contar(client):
    with CaptureQueriesContext(connection) as contexto:
        assert client.get(URL, {'ausente_de': '2026-03-01', 'ausente_ate': '2026-03-31'}).status_code == 200
    return len(contexto)


def test_numero_de_queries_nao_cresce(logado, ferias, gravar_ausencia):
    gravar_ausencia(Colaborador.objects.create(nome='P 0'), ferias, ('10/03/2026', '12/03/2026'))
    poucas = _contar(logado)
    for i in range(1, 15):
        gravar_ausencia(Colaborador.objects.create(nome=f'P {i}'), ferias, ('10/03/2026', '12/03/2026'),
                        ('20/03/2026', '21/03/2026'))

    assert _contar(logado) == poucas
