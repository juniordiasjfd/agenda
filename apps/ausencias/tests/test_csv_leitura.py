"""Leitura do CSV: função pura, sem banco (nenhum teste aqui usa ``db``)."""

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.ausencias import csv_service
from apps.ausencias.csv_service import ler_arquivos, ler_conteudo, ler_data

CABECALHO = 'Titulo;Colaborador;TipoEvento;DataInicio;DataFim;QuantidadeDias;Situacao;SolicitacaoID;Observacoes;DataSolicitacao'


def montar(*linhas, cabecalho=CABECALHO, sep=';', bom=True, codificacao='utf-8', fim='\r\n'):
    texto = fim.join([cabecalho.replace(';', sep), *linhas]) + fim
    return (('﻿' if bom else '') + texto).encode(codificacao)


LINHA = 'Ana Souza - Férias;Ana Souza;Férias;2026-03-02;2026-03-06;5;Planejado;SABC123;Viagem;2026-01-10T09:00:00.000Z'


def test_formato_legado_com_bom_e_ponto_e_virgula():
    arquivo = ler_conteudo('a.csv', montar(LINHA))

    assert (arquivo.erro, arquivo.codificacao, arquivo.separador) == ('', 'UTF-8 com BOM', ';')
    [registro] = arquivo.registros
    assert registro.linha == 2
    assert (registro.colaborador, registro.tipo, registro.situacao) == ('Ana Souza', 'Férias', 'Planejado')
    assert (registro.data_inicio, registro.data_fim) == (date(2026, 3, 2), date(2026, 3, 6))
    assert (registro.solicitacao_id, registro.observacoes, registro.erros) == ('SABC123', 'Viagem', [])
    assert registro.brutos['Titulo'] == 'Ana Souza - Férias'
    assert registro.brutos['DataSolicitacao'] == '2026-01-10T09:00:00.000Z'


def test_virgula_sem_bom_em_windows_1252_com_datas_brasileiras():
    conteudo = montar(
        'José Conceição,Férias,2/3/2026,06/03/2026',
        cabecalho='Colaborador,Tipo,Inicio,Fim', sep=',', bom=False, codificacao='cp1252',
    )

    arquivo = ler_conteudo('b.csv', conteudo)

    assert (arquivo.erro, arquivo.codificacao, arquivo.separador) == ('', 'Windows-1252', ',')
    [registro] = arquivo.registros
    assert (registro.colaborador, registro.tipo) == ('José Conceição', 'Férias')
    assert (registro.data_inicio, registro.data_fim) == (date(2026, 3, 2), date(2026, 3, 6))


def test_utf8_sem_bom():
    arquivo = ler_conteudo('a.csv', montar(LINHA, bom=False))
    assert arquivo.codificacao == 'UTF-8' and arquivo.registros[0].tipo == 'Férias'


def test_codificacao_irreconhecivel_recusa_o_arquivo():
    # 0x81 não existe em Windows-1252 e a sequência não é UTF-8 válida.
    arquivo = ler_conteudo('x.csv', CABECALHO.encode() + b'\r\nAna;\x81\xff;2026-01-01;2026-01-01\r\n')
    assert 'Codificação não reconhecida' in arquivo.erro and arquivo.registros == []


def test_campo_entre_aspas_com_separador_aspas_e_quebra_de_linha():
    linha = 'T;Ana Souza;Férias;2026-03-02;2026-03-06;5;;S1;"Volta dia 10; levar ""note""\nsegunda linha";'
    arquivo = ler_conteudo('a.csv', montar(linha, LINHA.replace('SABC123', 'S2')))

    primeiro, segundo = arquivo.registros
    assert primeiro.observacoes == 'Volta dia 10; levar "note"\nsegunda linha'
    # A quebra dentro das aspas não conta como registro novo.
    assert (primeiro.linha, segundo.linha) == (2, 3)


@pytest.mark.parametrize('cabecalho', [
    'colaborador;tipo evento;data início;data fim',
    'COLABORADOR;Tipo;Início;FIM',
    ' Colaborador ;Tipo-Evento;Data_Inicio;Data.Fim',
])
def test_cabecalhos_sem_acento_caixa_simbolos_e_aliases(cabecalho):
    arquivo = ler_conteudo('a.csv', montar('Ana;Férias;2026-03-02;2026-03-06', cabecalho=cabecalho))
    assert arquivo.erro == ''
    assert arquivo.registros[0].tipo == 'Férias'


def test_colunas_obrigatorias_faltando():
    arquivo = ler_conteudo('a.csv', montar('Ana;2026-03-02', cabecalho='Colaborador;DataInicio'))
    assert arquivo.erro == 'Faltam as colunas obrigatórias: TipoEvento, DataFim.'


def test_colunas_extras_sao_ignoradas_e_ordem_livre():
    arquivo = ler_conteudo('a.csv', montar(
        'x;2026-03-06;Férias;Ana;Motivo qualquer;2026-03-01',
        cabecalho='Extra;DataFim;TipoEvento;Colaborador;Motivo;DataInicio',
    ))
    [registro] = arquivo.registros
    assert (registro.colaborador, registro.data_fim, registro.erros) == ('Ana', date(2026, 3, 6), [])


@pytest.mark.parametrize('conteudo', [b'', b'\xef\xbb\xbf', b'  \r\n\r\n'])
def test_arquivo_vazio(conteudo):
    assert ler_conteudo('a.csv', conteudo).erro == 'O arquivo está vazio.'


def test_so_cabecalho_nao_tem_dados():
    assert ler_conteudo('a.csv', montar()).erro == 'O arquivo não tem linhas de dados.'


def test_linhas_vazias_descartadas_mas_contam_na_numeracao():
    arquivo = ler_conteudo('a.csv', montar(LINHA, ';;;;;;;;;', '', LINHA))
    assert [r.linha for r in arquivo.registros] == [2, 5]


def test_espacos_internos_colapsados():
    arquivo = ler_conteudo('a.csv', montar('T;  Helena  Teixeira   Exemplo ; Banco   de horas ;2026-03-02;2026-03-06;5; Aprovado ;S1;  obs  ;'))
    registro = arquivo.registros[0]
    assert (registro.colaborador, registro.tipo, registro.situacao, registro.observacoes) == (
        'Helena Teixeira Exemplo', 'Banco de horas', 'Aprovado', 'obs',
    )


def test_desfaz_neutralizacao_de_formula_nos_campos_de_texto():
    arquivo = ler_conteudo('a.csv', montar("'=T;'-Ana;'+Férias;2026-03-02;2026-03-06;5;'@Sit;S1;'=1+1;'=x"))
    registro = arquivo.registros[0]
    assert (registro.colaborador, registro.tipo, registro.situacao, registro.observacoes) == ('-Ana', '+Férias', '@Sit', '=1+1')
    assert registro.brutos['Titulo'] == '=T'
    # DataSolicitacao não é campo de texto neutralizado: fica como veio.
    assert registro.brutos['DataSolicitacao'] == "'=x"


@pytest.mark.parametrize('texto, esperado', [
    ('2026-03-02', date(2026, 3, 2)),
    ('2026-03-02T00:00:00.000Z', date(2026, 3, 2)),
    ('2026-03-02 10:00', date(2026, 3, 2)),
    ('02/03/2026', date(2026, 3, 2)),
    ('2/3/2026', date(2026, 3, 2)),
    (' 2/3/2026 ', date(2026, 3, 2)),
    ('2000-01-01', date(2000, 1, 1)),
    ('31/12/2100', date(2100, 12, 31)),
])
def test_datas_aceitas(texto, esperado):
    assert ler_data(texto, 'início') == (esperado, None)


@pytest.mark.parametrize('texto, trecho', [
    ('', 'Informe a data de início'),
    ('31/02/2026', 'inexistente'),
    ('2026-13-01', 'inexistente'),
    ('03-02-2026', 'inválida'),
    ('2026/03/02', 'inválida'),
    ('ontem', 'inválida'),
    ('31/12/1999', 'entre 2000 e 2100'),
    ('2101-01-01', 'entre 2000 e 2100'),
])
def test_datas_recusadas(texto, trecho):
    data, erro = ler_data(texto, 'início')
    assert data is None and trecho in erro


def test_erros_da_linha():
    arquivo = ler_conteudo('a.csv', montar(';;;2026-03-10;2026-03-01;;;;;', 'T;Ana;Férias;xx;;;;;;'))
    vazia, datas = arquivo.registros
    assert vazia.erros == ['Colaborador não informado.', 'Tipo não informado.', 'A data final é anterior à inicial.']
    assert datas.erros[0].startswith('Data de início inválida') and datas.erros[1] == 'Informe a data de fim.'


def test_ida_e_volta_pelo_json():
    arquivo = ler_conteudo('a.csv', montar(LINHA))
    assert csv_service.ArquivoLido.de_json(arquivo.para_json()) == arquivo


# ---------------------------------------------------------------------------
# Limites e ordem dos arquivos
# ---------------------------------------------------------------------------
def enviado(nome, conteudo=None):
    return SimpleUploadedFile(nome, montar(LINHA) if conteudo is None else conteudo)


def test_ordem_alfabetica_pelo_nome():
    lidos = ler_arquivos([enviado('b.csv'), enviado('A2.csv'), enviado('a1.csv')])
    assert [a.nome for a in lidos] == ['a1.csv', 'A2.csv', 'b.csv']


def test_extensao_nao_aceita_so_esse_e_recusado():
    lidos = ler_arquivos([enviado('dados.xlsx'), enviado('dados.TXT')])
    assert lidos[0].erro == '' and lidos[0].nome == 'dados.TXT'
    assert 'Extensão não aceita' in lidos[1].erro


def test_tamanho_maximo(settings):
    settings.CSV_IMPORTACAO_MAX_BYTES = 100
    pequeno = b'Colaborador;Tipo;Inicio;Fim\r\nAna;Ferias;2026-03-02;2026-03-06\r\n'
    lidos = ler_arquivos([enviado('a.csv', b'x' * 101), enviado('b.csv', pequeno)])
    assert lidos[0].erro == f'Arquivo maior que {100 / 1048576:g} MB.'
    assert lidos[1].erro == ''


def test_quantidade_maxima_de_arquivos(settings):
    settings.CSV_IMPORTACAO_MAX_ARQUIVOS = 2
    lidos = ler_arquivos([enviado('c.csv'), enviado('a.csv'), enviado('b.csv')])
    assert [(a.nome, bool(a.erro)) for a in lidos] == [('a.csv', False), ('b.csv', False), ('c.csv', True)]
    assert 'no máximo 2 arquivos' in lidos[2].erro


def test_limite_de_registros(settings):
    settings.CSV_IMPORTACAO_MAX_REGISTROS = 2
    no_limite = ler_arquivos([enviado('a.csv', montar(LINHA, LINHA))])[0]
    acima = ler_arquivos([enviado('b.csv', montar(LINHA, LINHA, '', LINHA))])[0]
    assert no_limite.erro == '' and len(no_limite.registros) == 2
    assert acima.erro == 'O arquivo tem mais de 2 registros: divida-o em arquivos menores.'
    assert acima.registros == []


def test_padroes_dos_limites():
    assert csv_service.limites() == {'arquivos': 20, 'bytes': 2 * 1024 * 1024, 'registros': 5000}
