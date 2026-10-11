"""Painel: filtros e montagem (``painel_service``)."""

import random
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.ausencias import ausencias_service, painel_service
from apps.ausencias.models import Ausencia, PeriodoAusencia, SituacaoAusencia, TipoAusencia
from apps.ausencias.painel_service import Intervalo, ler_filtros, montar_painel
from apps.ausencias.tests.conftest import d
from apps.colaboradores.models import Colaborador, Departamento

pytestmark = pytest.mark.django_db

HOJE = date(2026, 3, 15)


def nomes(filtros=None, **parametros):
    """Nomes das pessoas do painel com os parâmetros da querystring."""
    filtros = filtros or ler_filtros(**parametros)
    return [pessoa.nome for pessoa in montar_painel(filtros, HOJE).pessoas]


def excluir(ausencia):
    Ausencia.objects.filter(pk=ausencia.pk).update(excluido_em=timezone.now())


@pytest.fixture
def ti(db):
    return Departamento.objects.create(nome='TI')


@pytest.fixture
def rh(db):
    return Departamento.objects.create(nome='RH')


# ---------------------------------------------------------------------------
# Leitura dos filtros
# ---------------------------------------------------------------------------
def test_sem_parametros_tudo_aberto():
    filtros = ler_filtros()

    assert (filtros.nome, filtros.departamentos, filtros.ausente, filtros.presente) == ('', (), None, None)
    assert filtros.sem_registros is True
    assert filtros.avisos == []


@pytest.mark.parametrize('valor, esperado', [(None, True), ('', True), ('1', True), ('0', False)])
def test_sem_registros(valor, esperado):
    assert ler_filtros(sem_registros=valor).sem_registros is esperado


def test_intervalo_com_uma_data_so_e_dia_unico():
    assert ler_filtros(ausente_de='2026-03-10').ausente == Intervalo(d('10/03/2026'), d('10/03/2026'))
    assert ler_filtros(presente_ate='10/03/2026').presente == Intervalo(d('10/03/2026'), d('10/03/2026'))


def test_intervalo_invertido_e_trocado():
    filtros = ler_filtros(ausente_de='2026-03-20', ausente_ate='2026-03-10')

    assert filtros.ausente == Intervalo(d('10/03/2026'), d('20/03/2026'))
    assert filtros.avisos == []


@pytest.mark.parametrize('texto', ['2026-02-30', 'ontem', '1999-12-31', '2101-01-01'])
def test_data_invalida_ignora_o_filtro_com_aviso(texto):
    filtros = ler_filtros(ausente_de='2026-03-01', ausente_ate=texto, presente_de='2026-04-01')

    assert filtros.ausente is None
    assert filtros.presente == Intervalo(d('01/04/2026'), d('01/04/2026'))
    assert len(filtros.avisos) == 1
    assert '"Ausência em" foi ignorado' in filtros.avisos[0]


def test_departamentos_ids_sem_e_invalidos():
    filtros = ler_filtros(departamentos=['3', 'sem', '3', 'abc', '', '-1'])

    assert filtros.departamentos == (3, 'sem')
    assert len(filtros.avisos) == 2


def test_nome_normalizado():
    assert ler_filtros(q='  JOSÉ   da ').nome == 'jose da'


# ---------------------------------------------------------------------------
# Base: quem e o que aparece
# ---------------------------------------------------------------------------
def test_so_colaboradores_ativos(colaborador, outro_colaborador, ferias, gravar_ausencia):
    gravar_ausencia(outro_colaborador, ferias, ('01/03/2026', '05/03/2026'))
    Colaborador.objects.filter(pk=outro_colaborador.pk).update(ativo=False)

    assert nomes() == ['Ana Souza']


def test_ausencia_excluida_e_situacao_que_nao_conta_ficam_de_fora(colaborador, ferias, cancelado, gravar_ausencia):
    excluir(gravar_ausencia(colaborador, ferias, ('01/03/2026', '05/03/2026')))
    gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026', cancelado))
    gravar_ausencia(colaborador, ferias, ('20/03/2026', '21/03/2026'))

    pessoa, = montar_painel(ler_filtros(), HOJE).pessoas

    assert [(p.inicio, p.fim) for p in pessoa.periodos] == [(d('20/03/2026'), d('21/03/2026'))]


def test_periodo_traz_tipo_situacao_dias_e_ausencia(colaborador, ferias, aprovado, gravar_ausencia):
    ausencia = gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026', aprovado))

    periodo, = montar_painel(ler_filtros(), HOJE).pessoas[0].periodos

    assert periodo == painel_service.PeriodoPainel(
        d('10/03/2026'), d('12/03/2026'), 3, ferias.pk, 'Aprovado', ausencia.pk,
    )


def test_periodos_em_ordem_de_inicio_de_varias_ausencias(colaborador, ferias, banco_horas, gravar_ausencia):
    gravar_ausencia(colaborador, ferias, ('20/03/2026', '21/03/2026'), ('01/01/2026', '02/01/2026'))
    gravar_ausencia(colaborador, banco_horas, ('10/02/2026', '10/02/2026'))

    pessoa, = montar_painel(ler_filtros(), HOJE).pessoas

    assert [p.inicio for p in pessoa.periodos] == [d('01/01/2026'), d('10/02/2026'), d('20/03/2026')]


def test_ordem_por_nome_sem_acento_nem_caixa(db):
    for nome in ['carla', 'Ábner', 'Bruno', 'Aaron', 'ana b', 'Anab']:
        Colaborador.objects.create(nome=nome)

    assert nomes() == ['Aaron', 'Ábner', 'ana b', 'Anab', 'Bruno', 'carla']


def test_departamento_no_resultado(colaborador, outro_colaborador, ti):
    Colaborador.objects.filter(pk=colaborador.pk).update(departamento=ti)

    pessoas = montar_painel(ler_filtros(), HOJE).pessoas

    assert [(p.nome, p.departamento) for p in pessoas] == [('Ana Souza', 'TI'), ('Bruno Lima', None)]


def test_legenda_tipos_ativos_e_inativos_presentes(colaborador, ferias, gravar_ausencia):
    inativo_usado = TipoAusencia.objects.create(nome='Antigo', cor='#123456', ativo=False, ordem=99)
    TipoAusencia.objects.create(nome='Sem uso', cor='#654321', ativo=False, ordem=98)
    gravar_ausencia(colaborador, inativo_usado, ('01/03/2026', '02/03/2026'))

    tipos = montar_painel(ler_filtros(), HOJE).tipos

    assert [t.nome for t in tipos] == ['Férias', 'Banco de horas', 'Licença', 'Outro', 'Antigo']
    assert tipos[-1] == painel_service.TipoPainel(inativo_usado.pk, 'Antigo', '#123456')


def test_hoje_e_avisos_no_painel():
    painel = montar_painel(ler_filtros(ausente_de='xx'), HOJE)

    assert painel.hoje == HOJE
    assert len(painel.avisos) == 1


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def test_filtro_nome_sem_acento(colaborador, outro_colaborador):
    Colaborador.objects.create(nome='José Antônio')

    assert nomes(q='antonio') == ['José Antônio']
    assert nomes(q='SOUZA') == ['Ana Souza']


class TestDepartamentos:
    @pytest.fixture(autouse=True)
    def _cenario(self, ti, rh):
        Colaborador.objects.create(nome='Tânia TI', departamento=ti)
        Colaborador.objects.create(nome='Rui RH', departamento=rh)
        Colaborador.objects.create(nome='Sílvia Sem')

    def test_sem_parametro_todos(self):
        assert nomes() == ['Rui RH', 'Sílvia Sem', 'Tânia TI']

    def test_um(self, ti):
        assert nomes(departamentos=[str(ti.pk)]) == ['Tânia TI']

    def test_varios_uniao(self, ti, rh):
        assert nomes(departamentos=[str(ti.pk), str(rh.pk)]) == ['Rui RH', 'Tânia TI']

    def test_so_sem_departamento(self):
        assert nomes(departamentos=['sem']) == ['Sílvia Sem']

    def test_ids_mais_sem_departamento(self, rh):
        assert nomes(departamentos=['sem', str(rh.pk)]) == ['Rui RH', 'Sílvia Sem']

    def test_departamento_criado_depois_entra_em_todos(self):
        novo = Departamento.objects.create(nome='Novo')
        Colaborador.objects.create(nome='Nina Nova', departamento=novo)

        assert 'Nina Nova' in nomes()

    def test_id_inexistente_nao_traz_ninguem(self):
        assert nomes(departamentos=['999999']) == []

    def test_so_valores_invalidos_vale_todos(self):
        assert len(nomes(departamentos=['x'])) == 3


class TestIntervalos:
    """Ana: 10 a 12/03. Bruno: 13 a 13/03. Carla: sem registros."""

    @pytest.fixture(autouse=True)
    def _cenario(self, colaborador, outro_colaborador, ferias, gravar_ausencia):
        gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026'))
        gravar_ausencia(outro_colaborador, ferias, ('13/03/2026', '13/03/2026'))
        Colaborador.objects.create(nome='Carla Dias')

    @pytest.mark.parametrize('de, ate, esperado', [
        ('2026-03-12', '2026-03-12', ['Ana Souza']),               # último dia (inclusivo)
        ('2026-03-01', '2026-03-10', ['Ana Souza']),               # primeiro dia (inclusivo)
        ('2026-03-12', '2026-03-13', ['Ana Souza', 'Bruno Lima']),
        ('2026-03-14', '2026-03-31', []),                          # depois de todos
        ('2026-03-13', '2026-03-12', ['Ana Souza', 'Bruno Lima']),  # invertido
        ('2026-03-11', '', ['Ana Souza']),                         # só "de"
        ('', '2026-03-13', ['Bruno Lima']),                        # só "até"
    ])
    def test_ausencia_em(self, de, ate, esperado):
        assert nomes(ausente_de=de, ausente_ate=ate) == esperado

    @pytest.mark.parametrize('de, ate, esperado', [
        ('2026-03-12', '2026-03-12', ['Bruno Lima', 'Carla Dias']),
        ('2026-03-13', '2026-03-20', ['Ana Souza', 'Carla Dias']),
        ('2026-03-01', '2026-03-31', ['Carla Dias']),
        ('2026-04-01', '', ['Ana Souza', 'Bruno Lima', 'Carla Dias']),
    ])
    def test_presenca_em(self, de, ate, esperado):
        assert nomes(presente_de=de, presente_ate=ate) == esperado

    def test_sem_registros_desmarcado(self):
        assert nomes(sem_registros='0') == ['Ana Souza', 'Bruno Lima']

    def test_presenca_com_sem_registros_desmarcado_exige_algum_registro(self):
        assert nomes(presente_de='2026-03-12', sem_registros='0') == ['Bruno Lima']
        assert nomes(presente_de='2026-03-12', sem_registros='1') == ['Bruno Lima', 'Carla Dias']

    def test_ausencia_e_presenca_combinadas(self):
        assert nomes(ausente_de='2026-03-10', ausente_ate='2026-03-13', presente_de='2026-03-13') == ['Ana Souza']

    def test_ausencia_combinada_com_nome_e_departamento(self, colaborador, ti):
        Colaborador.objects.filter(pk=colaborador.pk).update(departamento=ti)

        assert nomes(ausente_de='2026-03-01', ausente_ate='2026-03-31', departamentos=[str(ti.pk)], q='ana') == [
            'Ana Souza',
        ]
        assert nomes(ausente_de='2026-03-01', ausente_ate='2026-03-31', departamentos=['sem']) == ['Bruno Lima']

    def test_data_invalida_nao_filtra(self):
        assert nomes(ausente_de='2026-13-01') == ['Ana Souza', 'Bruno Lima', 'Carla Dias']


def test_ausencia_em_ignora_excluida_e_situacao_que_nao_conta(colaborador, outro_colaborador, ferias, cancelado,
                                                              gravar_ausencia):
    excluir(gravar_ausencia(colaborador, ferias, ('10/03/2026', '12/03/2026')))
    gravar_ausencia(outro_colaborador, ferias, ('10/03/2026', '12/03/2026', cancelado))

    assert nomes(ausente_de='2026-03-11') == []
    assert nomes(presente_de='2026-03-11') == ['Ana Souza', 'Bruno Lima']
    assert nomes(sem_registros='0') == []


def test_todos_os_periodos_sem_recorte_pela_janela(colaborador, ferias, gravar_ausencia):
    gravar_ausencia(colaborador, ferias, ('05/01/2026', '06/01/2026'), ('10/03/2026', '12/03/2026'))
    gravar_ausencia(colaborador, ferias, ('01/12/2030', '02/12/2030'))

    pessoa, = montar_painel(ler_filtros(ausente_de='2026-03-11'), HOJE).pessoas

    assert len(pessoa.periodos) == 3


# ---------------------------------------------------------------------------
# Número de queries
# ---------------------------------------------------------------------------
def _povoar(quantidade, tipo):
    padrao = SituacaoAusencia.objects.get(padrao=True)
    for i in range(quantidade):
        colaborador = Colaborador.objects.create(nome=f'Pessoa {i:03d}', departamento=Departamento.objects.create(
            nome=f'Dep {i}'))
        ausencia = Ausencia.objects.create(colaborador=colaborador, tipo=tipo, codigo=f'Q{i:05d}')
        for j in range(3):
            inicio = d('01/03/2026') + timedelta(days=10 * j)
            PeriodoAusencia.objects.create(ausencia=ausencia, data_inicio=inicio, data_fim=inicio, situacao=padrao)


@pytest.mark.parametrize('quantidade', [2, 20])
def test_numero_de_queries_constante(quantidade, ferias, django_assert_num_queries):
    _povoar(quantidade, ferias)
    departamentos = ['sem', *(str(pk) for pk in Departamento.objects.values_list('pk', flat=True))]
    filtros = ler_filtros(q='pessoa', ausente_de='2026-03-01', ausente_ate='2026-03-31', presente_de='2027-01-01',
                          departamentos=departamentos, sem_registros='0')

    with django_assert_num_queries(3):
        assert len(montar_painel(ler_filtros(), HOJE).pessoas) == quantidade
    with django_assert_num_queries(3):
        assert len(montar_painel(filtros, HOJE).pessoas) == quantidade


def test_sem_ninguem_duas_queries(django_assert_num_queries):
    with django_assert_num_queries(2):
        painel = montar_painel(ler_filtros(q='ninguém'), HOJE)

    assert painel.pessoas == []


# ---------------------------------------------------------------------------
# Equivalência com a regra única (funções puras do ausencias_service)
# ---------------------------------------------------------------------------
def _esperado_pelas_funcoes_puras(intervalo):
    """Ids dos colaboradores ativos com algum período que conta como
    ausência (``conta_como_ausencia``), de ausência não excluída, cruzando o
    intervalo (``cruzam``). Tudo em Python."""
    ids = set()
    for periodo in PeriodoAusencia.objects.select_related('ausencia__colaborador', 'situacao'):
        ausencia = Ausencia.todos.get(pk=periodo.ausencia_id)
        if (
            ausencia.colaborador.ativo and ausencia.excluido_em is None
            and ausencias_service.conta_como_ausencia(periodo)
            and ausencias_service.cruzam(periodo.data_inicio, periodo.data_fim, intervalo.de, intervalo.ate)
        ):
            ids.add(ausencia.colaborador_id)
    return ids


def test_consulta_equivale_a_cruzam_e_conta_como_ausencia(ferias, planejado, cancelado):
    sorteio = random.Random(20260315)
    inicio_base = d('01/01/2026')
    colaboradores = [Colaborador.objects.create(nome=f'Pessoa {i}', ativo=i % 7 != 0) for i in range(25)]
    for n in range(80):
        inicio = inicio_base + timedelta(days=sorteio.randrange(0, 90))
        ausencia = Ausencia.objects.create(colaborador=sorteio.choice(colaboradores), tipo=ferias, codigo=f'E{n:04d}')
        PeriodoAusencia.objects.create(
            ausencia=ausencia, data_inicio=inicio, data_fim=inicio + timedelta(days=sorteio.randrange(0, 6)),
            situacao=sorteio.choice([planejado, planejado, cancelado]),
        )
        if sorteio.random() < .15:
            excluir(ausencia)
    ativos = {c.pk for c in colaboradores if c.ativo}

    for _ in range(60):
        de = inicio_base + timedelta(days=sorteio.randrange(-5, 100))
        intervalo = Intervalo(de, de + timedelta(days=sorteio.randrange(0, 4)))
        esperado = _esperado_pelas_funcoes_puras(intervalo)

        ausentes = {c.pk for c in painel_service.colaboradores_filtrados(
            painel_service.FiltrosPainel(ausente=intervalo))}
        presentes = {c.pk for c in painel_service.colaboradores_filtrados(
            painel_service.FiltrosPainel(presente=intervalo))}

        assert ausentes == esperado, intervalo
        assert presentes == ativos - esperado, intervalo
