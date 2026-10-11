"""Análise da importação (prévia): classificação, grupos, códigos,
pendências e assinatura. Nada aqui grava no banco."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.ausencias import ausencias_service, csv_service
from apps.ausencias.ausencias_service import PeriodoInformado
from apps.ausencias.csv_service import DUPLICATA, IMPORTAR, INVALIDA, PENDENTE, SOBREPOSICAO, analisar, ler_conteudo
from apps.ausencias.models import Ausencia, PeriodoAusencia, SituacaoAusencia, TipoAusencia
from apps.ausencias.tests.conftest import d
from apps.ausencias.tests.test_regra_unica import CASOS
from apps.colaboradores.models import Colaborador

pytestmark = pytest.mark.django_db

CABECALHO = 'Colaborador;TipoEvento;DataInicio;DataFim;Situacao;SolicitacaoID;Observacoes'


def arquivo(*linhas, nome='a.csv'):
    """``linhas``: tuplas (colaborador, tipo, início, fim[, situação[, id[, obs]]])
    com datas dd/mm/aaaa."""
    texto = '\r\n'.join([CABECALHO, *(';'.join((*l, '', '', '')[:7]) for l in linhas)]) + '\r\n'
    lido = ler_conteudo(nome, ('﻿' + texto).encode())
    assert lido.erro == '', lido.erro
    return lido


def categorias(analise):
    return [linha.categoria for linha in analise.linhas]


def registrar(colaborador, tipo, *periodos, codigo=None, usuario=None):
    return ausencias_service.criar_ausencia(
        colaborador, tipo, [PeriodoInformado(d(p[0]), d(p[1]), p[2] if len(p) > 2 else None) for p in periodos],
        '', usuario, codigo=codigo,
    )


# ---------------------------------------------------------------------------
# Duplicatas
# ---------------------------------------------------------------------------
def test_duplicata_do_banco_e_ignorada(colaborador, ferias):
    registrar(colaborador, ferias, ('02/03/2026', '06/03/2026'))
    analise = analisar([arquivo(('ana  souza', 'FERIAS', '02/03/2026', '06/03/2026'))])
    assert categorias(analise) == [DUPLICATA]
    assert analise.grupos == []


def test_duplicata_de_ausencia_excluida_nao_conta(colaborador, ferias, admin):
    ausencias_service.excluir_ausencia(registrar(colaborador, ferias, ('02/03/2026', '06/03/2026')), admin)
    analise = analisar([arquivo(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026'))])
    assert categorias(analise) == [IMPORTAR]


def test_duplicata_com_situacao_que_nao_conta_tambem_e_duplicata(colaborador, ferias, cancelado):
    registrar(colaborador, ferias, ('02/03/2026', '06/03/2026', cancelado))
    analise = analisar([arquivo(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026', 'Planejado'))])
    assert categorias(analise) == [DUPLICATA]


def test_duplicata_dentro_do_arquivo_e_entre_arquivos(colaborador, ferias):
    linha = ('Ana Souza', 'Férias', '02/03/2026', '06/03/2026', '', 'S1')
    analise = analisar([arquivo(linha, linha, nome='a.csv'), arquivo(linha, nome='b.csv')])
    assert categorias(analise) == [IMPORTAR, DUPLICATA, DUPLICATA]


def test_tipo_diferente_nao_e_duplicata_e_sim_sobreposicao(colaborador, ferias, banco_horas):
    registrar(colaborador, banco_horas, ('02/03/2026', '06/03/2026'))
    analise = analisar([arquivo(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026'))])
    assert categorias(analise) == [SOBREPOSICAO]


# ---------------------------------------------------------------------------
# Sobreposição
# ---------------------------------------------------------------------------
def test_sobreposicao_com_o_banco_usa_a_mensagem_do_servico(colaborador, banco_horas):
    registrar(colaborador, banco_horas, ('01/03/2026', '10/03/2026'))
    [linha] = analisar([arquivo(('Ana Souza', 'Férias', '10/03/2026', '12/03/2026'))]).linhas
    assert linha.categoria == SOBREPOSICAO
    assert linha.motivo == 'Sobrepõe Banco de horas já registrado de 01/03/2026 a 10/03/2026.'


def test_sobreposicao_dentro_do_lote_linha_mais_antiga_vence(colaborador, ferias):
    analise = analisar([arquivo(
        ('Ana Souza', 'Férias', '01/03/2026', '10/03/2026', '', 'S1'),
        ('Ana Souza', 'Banco de horas', '05/03/2026', '06/03/2026', '', 'S2'),
    )])
    assert categorias(analise) == [IMPORTAR, SOBREPOSICAO]
    assert analise.linhas[1].motivo == 'Sobrepõe Férias de 01/03/2026 a 10/03/2026 (a.csv, linha 2).'


def test_ordem_alfabetica_dos_arquivos_decide_quem_vence(colaborador, ferias):
    def enviado(nome, inicio, fim):
        texto = f'{CABECALHO}\r\nAna Souza;Férias;{inicio};{fim};;{nome};\r\n'
        return SimpleUploadedFile(nome, texto.encode())

    # Enviados fora de ordem: "a-...csv" é lido primeiro e vence.
    lidos = csv_service.ler_arquivos([enviado('b-depois.csv', '05/03/2026', '06/03/2026'),
                                      enviado('a-antes.csv', '01/03/2026', '10/03/2026')])
    analise = analisar(lidos)

    assert [(l.arquivo, l.categoria) for l in analise.linhas] == [
        ('a-antes.csv', IMPORTAR), ('b-depois.csv', SOBREPOSICAO),
    ]


def test_linha_rejeitada_nao_ocupa_a_agenda(colaborador, ferias, banco_horas):
    registrar(colaborador, banco_horas, ('01/03/2026', '03/03/2026'))
    analise = analisar([arquivo(
        ('Ana Souza', 'Férias', '02/03/2026', '10/03/2026'),   # sobrepõe o banco: fora
        ('Ana Souza', 'Férias', '08/03/2026', '12/03/2026'),   # só cruzaria a de cima
    )])
    assert categorias(analise) == [SOBREPOSICAO, IMPORTAR]


@pytest.mark.parametrize('anterior, novo, anterior_conta, novo_conta, esperado', CASOS)
def test_regra_unica_contra_o_banco(
    gravar_ausencia, colaborador, banco_horas, planejado, cancelado,
    anterior, novo, anterior_conta, novo_conta, esperado,
):
    gravar_ausencia(colaborador, banco_horas, (*anterior, planejado if anterior_conta else cancelado))
    situacao = 'Planejado' if novo_conta else 'Cancelado'
    [linha] = analisar([arquivo(('Ana Souza', 'Férias', *novo, situacao))]).linhas
    assert linha.categoria == (SOBREPOSICAO if esperado else IMPORTAR)


@pytest.mark.parametrize('anterior, novo, anterior_conta, novo_conta, esperado', CASOS)
def test_regra_unica_dentro_do_lote(colaborador, anterior, novo, anterior_conta, novo_conta, esperado):
    analise = analisar([arquivo(
        ('Ana Souza', 'Banco de horas', *anterior, 'Planejado' if anterior_conta else 'Cancelado', 'S1'),
        ('Ana Souza', 'Férias', *novo, 'Planejado' if novo_conta else 'Cancelado', 'S2'),
    )])
    assert categorias(analise) == [IMPORTAR, SOBREPOSICAO if esperado else IMPORTAR]


def test_colaboradores_diferentes_nao_conflitam(colaborador, outro_colaborador, ferias):
    analise = analisar([arquivo(
        ('Ana Souza', 'Férias', '01/03/2026', '10/03/2026'),
        ('Bruno Lima', 'Férias', '01/03/2026', '10/03/2026'),
    )])
    assert categorias(analise) == [IMPORTAR, IMPORTAR]


# ---------------------------------------------------------------------------
# Grupos e códigos
# ---------------------------------------------------------------------------
def test_agrupa_pelo_solicitacao_id(colaborador, ferias):
    analise = analisar([arquivo(
        ('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', '', 'SABC', ''),
        ('Ana Souza', 'Férias', '01/06/2026', '05/06/2026', 'Aprovado', 'SABC', 'Viagem'),
        ('Ana Souza', 'Férias', '01/09/2026', '05/09/2026', '', 'OUTRO'),
    )])
    primeiro, segundo = analise.grupos
    assert (primeiro.codigo, len(primeiro.linhas), primeiro.observacoes) == ('SABC', 2, 'Viagem')
    assert (segundo.codigo, len(segundo.linhas)) == ('OUTRO', 1)
    assert analise.contagens['ausencias'] == 2 and analise.contagens[IMPORTAR] == 3


def test_linhas_sem_solicitacao_id_viram_ausencias_separadas(colaborador, ferias):
    analise = analisar([arquivo(
        ('Ana Souza', 'Férias', '01/03/2026', '05/03/2026'),
        ('Ana Souza', 'Férias', '01/06/2026', '05/06/2026'),
    )])
    assert [(g.codigo, len(g.linhas)) for g in analise.grupos] == [(None, 1), (None, 1)]


def test_mesmo_id_com_colaborador_ou_tipo_divergente(colaborador, outro_colaborador, ferias):
    analise = analisar([arquivo(
        ('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', '', 'S1'),
        ('Bruno Lima', 'Férias', '01/03/2026', '05/03/2026', '', 'S1'),
        ('Ana Souza', 'Banco de horas', '01/04/2026', '02/04/2026', '', 'S1'),
        ('ANA SOUZA', 'férias', '01/05/2026', '02/05/2026', '', 'S1'),
    )])
    assert [(str(g.colaborador), str(g.tipo), g.codigo, len(g.linhas)) for g in analise.grupos] == [
        ('Ana Souza', 'Férias', 'S1', 2),
        ('Bruno Lima', 'Férias', None, 1),
        ('Ana Souza', 'Banco de horas', None, 1),
    ]
    assert 'aparece com outro colaborador ou tipo' in analise.grupos[1].avisos[0]


@pytest.mark.parametrize('na_lixeira', [False, True])
def test_codigo_ja_existente_no_banco_recebe_codigo_novo(colaborador, ferias, admin, na_lixeira):
    existente = registrar(colaborador, ferias, ('01/01/2026', '02/01/2026'), codigo='S1')
    if na_lixeira:
        ausencias_service.excluir_ausencia(existente, admin)
    [grupo] = analisar([arquivo(('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', '', 's1'))]).grupos
    assert grupo.codigo is None
    assert 'já existe no sistema' in grupo.avisos[0]


def test_solicitacao_id_invalido_como_codigo(colaborador, ferias):
    [grupo] = analisar([arquivo(('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', '', 'ID COM ESPAÇO'))]).grupos
    assert grupo.codigo is None and 'não serve como código' in grupo.avisos[0]


def test_primeiro_grupo_com_linhas_validas_fica_com_o_codigo(colaborador, outro_colaborador, ferias):
    analise = analisar([arquivo(
        ('Ana Souza', 'Férias', 'xx', '05/03/2026', '', 'S1'),          # inválida: não forma grupo
        ('Bruno Lima', 'Férias', '01/03/2026', '05/03/2026', '', 'S1'),
    )])
    assert [g.codigo for g in analise.grupos] == ['S1']


def test_grupo_parcial(colaborador, ferias, banco_horas):
    registrar(colaborador, banco_horas, ('01/06/2026', '03/06/2026'))
    analise = analisar([arquivo(
        ('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', '', 'S1'),
        ('Ana Souza', 'Férias', '02/06/2026', '05/06/2026', '', 'S1'),
    )])
    [grupo] = analise.grupos
    assert categorias(analise) == [IMPORTAR, SOBREPOSICAO]
    assert grupo.parcial and len(grupo.linhas) == 1
    assert 'Importação parcial: 1 linha' in grupo.avisos[0]


def test_limite_de_12_periodos_por_ausencia(colaborador, ferias):
    linhas = [('Ana Souza', 'Férias', f'{dia:02d}/03/2026', f'{dia:02d}/03/2026', '', 'S1') for dia in range(1, 14)]
    analise = analisar([arquivo(*linhas)])
    assert categorias(analise) == [IMPORTAR] * 12 + [INVALIDA]
    assert analise.linhas[-1].motivo == 'Excede 12 períodos na mesma ausência (SolicitacaoID S1).'
    assert len(analise.grupos[0].linhas) == 12


# ---------------------------------------------------------------------------
# Cadastros
# ---------------------------------------------------------------------------
def test_colaborador_tipo_e_situacao_inexistentes_ficam_pendentes(colaborador):
    analise = analisar([arquivo(
        ('Carla Nova', 'Férias', '01/03/2026', '05/03/2026'),
        ('Ana Souza', 'Home office', '01/03/2026', '05/03/2026'),
        ('Ana Souza', 'Férias', '01/04/2026', '05/04/2026', 'Em análise'),
        ('carla   NOVA', 'home office', '01/05/2026', '05/05/2026'),
    )])
    assert categorias(analise) == [PENDENTE] * 4
    assert analise.linhas[0].motivo == 'Colaborador "Carla Nova" não cadastrado.'
    assert analise.linhas[3].motivo == 'Colaborador "Carla Nova" não cadastrado. Tipo "Home office" não cadastrado.'
    pendencias = {e: [(p.nome, p.linhas, p.marcada) for p in lista] for e, lista in analise.pendencias.items()}
    assert pendencias == {
        'colaboradores': [('Carla Nova', 2, False)],
        'tipos': [('Home office', 2, False)],
        'situacoes': [('Em análise', 1, False)],
    }
    assert analise.a_criar == {'colaboradores': [], 'tipos': [], 'situacoes': []}


def test_cadastro_marcado_para_criar(colaborador):
    decisoes = {'colaboradores': ['Carla  Nova'], 'tipos': ['HOME OFFICE'], 'situacoes': []}
    analise = analisar([arquivo(
        ('Carla Nova', 'Home office', '01/03/2026', '05/03/2026', '', 'S1'),
        ('carla nova', 'Home Office', '01/04/2026', '05/04/2026', 'Em análise', 'S1'),
        ('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', 'Em análise'),
    )], decisoes)
    assert categorias(analise) == [IMPORTAR, PENDENTE, PENDENTE]
    assert [n.nome for n in analise.a_criar['colaboradores']] == ['Carla Nova']
    assert [n.nome for n in analise.a_criar['tipos']] == ['Home office']
    assert analise.a_criar['situacoes'] == []
    assert analise.decisoes == {'colaboradores': ['carla nova'], 'tipos': ['home office'], 'situacoes': []}


def test_cadastro_marcado_sem_linha_a_importar_nao_e_criado(colaborador):
    analise = analisar([arquivo(('Carla Nova', 'Férias', '01/03/2026', '05/03/2026', 'Em análise'))],
                       {'colaboradores': ['carla nova']})
    assert categorias(analise) == [PENDENTE]
    assert analise.a_criar['colaboradores'] == []


def test_variacoes_de_acento_caixa_e_espaco_resolvem_o_existente(colaborador):
    Colaborador.objects.create(nome='José Conceição')
    analise = analisar([arquivo(
        ('jose  conceicao', 'FERIAS', '01/03/2026', '05/03/2026', 'aprovado'),
        ('JOSÉ CONCEIÇÃO', 'Banco de Horas', '01/04/2026', '05/04/2026', ' PLANEJADO '),
    )])
    assert categorias(analise) == [IMPORTAR, IMPORTAR]
    assert {str(l.colaborador) for l in analise.linhas} == {'José Conceição'}
    assert all(not lista for lista in analise.pendencias.values())


@pytest.mark.parametrize('entidade', ['colaborador', 'tipo', 'situacao'])
def test_cadastro_inativo_e_recusado(colaborador, ferias, aprovado, entidade):
    objeto = {'colaborador': colaborador, 'tipo': ferias, 'situacao': aprovado}[entidade]
    type(objeto).objects.filter(pk=objeto.pk).update(ativo=False)
    [linha] = analisar([arquivo(('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', 'Aprovado'))]).linhas
    assert linha.categoria == INVALIDA
    assert 'está inativo: reative-o' in linha.motivo


def test_situacao_vazia_usa_a_padrao(colaborador, planejado):
    [linha] = analisar([arquivo(('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', ''))]).linhas
    assert linha.situacao == planejado


def test_nome_longo_demais_para_criar(colaborador):
    [linha] = analisar([arquivo(('Ana Souza', 'T' * 61, '01/03/2026', '05/03/2026'))], {'tipos': ['T' * 61]}).linhas
    assert linha.categoria == INVALIDA and 'mais de 60 caracteres' in linha.motivo


# ---------------------------------------------------------------------------
# Linhas inválidas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('inicio, fim, trecho', [
    ('01/03/1999', '05/03/2026', 'entre 2000 e 2100'),
    ('01/03/2026', '05/03/2101', 'entre 2000 e 2100'),
    ('10/03/2026', '05/03/2026', 'anterior à inicial'),
    ('30/02/2026', '05/03/2026', 'inexistente'),
])
def test_linha_invalida(colaborador, inicio, fim, trecho):
    [linha] = analisar([arquivo(('Ana Souza', 'Férias', inicio, fim))]).linhas
    assert linha.categoria == INVALIDA and trecho in linha.motivo


def test_arquivo_recusado_nao_entra_na_analise(colaborador):
    recusado = csv_service.ArquivoLido(nome='x.xlsx', erro='Extensão não aceita')
    analise = analisar([recusado, arquivo(('Ana Souza', 'Férias', '01/03/2026', '05/03/2026'))])
    assert analise.contagens['arquivos_recusados'] == 1 and analise.contagens['registros'] == 1


# ---------------------------------------------------------------------------
# Somente leitura, assinatura e desempenho
# ---------------------------------------------------------------------------
def _totais():
    return [m.objects.count() if m is not Ausencia else Ausencia.todos.count()
            for m in (Ausencia, PeriodoAusencia, Colaborador, TipoAusencia, SituacaoAusencia)]


def test_previa_nao_grava_nada(colaborador, ferias):
    registrar(colaborador, ferias, ('02/03/2026', '06/03/2026'))
    antes = _totais()
    analisar([arquivo(
        ('Ana Souza', 'Férias', '01/06/2026', '05/06/2026', '', 'S9'),
        ('Nova Pessoa', 'Tipo Novo', '01/06/2026', '05/06/2026', 'Situação Nova'),
    )], {'colaboradores': ['nova pessoa'], 'tipos': ['tipo novo'], 'situacoes': ['situacao nova']})
    assert _totais() == antes


def test_assinatura_deterministica_e_sensivel_ao_plano(colaborador, ferias, banco_horas):
    lido = arquivo(('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', '', 'S1'),
                   ('Carla Nova', 'Férias', '01/03/2026', '05/03/2026'))
    base = analisar([lido]).assinatura
    assert analisar([lido]).assinatura == base
    assert analisar([lido], {'colaboradores': ['carla nova']}).assinatura != base
    # O banco mudou: a linha de Ana passa a sobrepor.
    registrar(colaborador, banco_horas, ('05/03/2026', '06/03/2026'))
    assert analisar([lido]).assinatura != base


def test_assinatura_ignora_mudanca_que_nao_altera_o_plano(colaborador, outro_colaborador, ferias):
    lido = arquivo(('Ana Souza', 'Férias', '01/03/2026', '05/03/2026', '', 'S1'))
    base = analisar([lido]).assinatura
    registrar(outro_colaborador, ferias, ('01/03/2026', '05/03/2026'))
    assert analisar([lido]).assinatura == base


def test_numero_de_queries_independe_do_tamanho_do_lote(ferias, gravar_ausencia):
    def consultas(quantos):
        linhas = []
        for i in range(quantos):
            pessoa = Colaborador.objects.create(nome=f'Pessoa {quantos}-{i}')
            gravar_ausencia(pessoa, ferias, ('01/01/2026', '05/01/2026'))
            linhas += [
                (pessoa.nome, 'Férias', '01/01/2026', '05/01/2026'),            # duplicata
                (pessoa.nome, 'Banco de horas', '03/01/2026', '04/01/2026'),    # sobreposição
                (pessoa.nome, 'Férias', '01/03/2026', '05/03/2026', '', f'S{quantos}{i}'),
                (f'Inexistente {i}', 'Férias', '01/03/2026', '05/03/2026'),
            ]
        lido = arquivo(*linhas)
        with CaptureQueriesContext(connection) as contexto:
            analisar([lido], {'colaboradores': [f'inexistente {i}' for i in range(quantos)]})
        return len(contexto.captured_queries)

    assert consultas(2) == consultas(30)
