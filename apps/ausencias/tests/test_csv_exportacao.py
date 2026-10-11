import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.ausencias import ausencias_service, csv_service
from apps.ausencias.ausencias_service import PeriodoInformado
from apps.ausencias.models import Ausencia
from apps.ausencias.tests.conftest import d
from apps.colaboradores.models import Colaborador, Departamento

pytestmark = pytest.mark.django_db

CABECALHO = 'Titulo;Colaborador;TipoEvento;DataInicio;DataFim;QuantidadeDias;Situacao;SolicitacaoID;Observacoes;DataSolicitacao'


def ler(conteudo):
    """Linhas (dicts) de um CSV exportado."""
    assert conteudo.startswith('﻿')
    return list(csv.DictReader(io.StringIO(conteudo[1:], newline=''), delimiter=';'))


def exportar(client, **filtros):
    resposta = client.get(reverse('ausencias:exportar'), filtros)
    assert resposta.status_code == 200
    return resposta


def criar(colaborador, tipo, *periodos, observacoes='', usuario=None, codigo=None):
    return ausencias_service.criar_ausencia(
        colaborador, tipo,
        [PeriodoInformado(d(p[0]), d(p[1]), p[2] if len(p) > 2 else None) for p in periodos],
        observacoes, usuario, codigo=codigo,
    )


@pytest.fixture
def logado(client, usuario_ativo):
    client.force_login(usuario_ativo)
    return client


def test_formato_bom_separador_crlf_e_colunas(logado, colaborador, ferias, aprovado):
    criar(colaborador, ferias, ('02/03/2026', '06/03/2026', aprovado), codigo='SLEG1', observacoes='Viagem')

    resposta = exportar(logado)

    assert resposta['Content-Type'] == 'text/csv; charset=utf-8'
    bruto = resposta.content
    assert bruto.startswith(b'\xef\xbb\xbf')
    texto = bruto.decode('utf-8')
    assert texto.split('\r\n')[0] == '﻿' + CABECALHO
    assert texto.endswith('\r\n') and '\n' not in texto.replace('\r\n', '')
    [linha] = ler(texto)
    assert linha['Titulo'] == 'Ana Souza - Férias'
    assert (linha['Colaborador'], linha['TipoEvento'], linha['Situacao']) == ('Ana Souza', 'Férias', 'Aprovado')
    assert (linha['DataInicio'], linha['DataFim'], linha['QuantidadeDias']) == ('2026-03-02', '2026-03-06', '5')
    assert (linha['SolicitacaoID'], linha['Observacoes']) == ('SLEG1', 'Viagem')


def test_data_solicitacao_em_iso_no_fuso_de_sao_paulo(logado, colaborador, ferias):
    ausencia = criar(colaborador, ferias, ('02/03/2026', '06/03/2026'))
    Ausencia.objects.filter(pk=ausencia.pk).update(criado_em=datetime(2026, 3, 1, 2, 30, tzinfo=ZoneInfo('UTC')))

    [linha] = ler(exportar(logado).content.decode())

    assert linha['DataSolicitacao'] == '2026-02-28T23:30:00-03:00'


def test_nome_do_arquivo_com_data_local(logado, monkeypatch):
    monkeypatch.setattr(csv_service.timezone, 'localdate', lambda: d('11/10/2026'))
    resposta = exportar(logado)
    assert resposta['Content-Disposition'] == 'attachment; filename="periodos-eventos-2026-10-11.csv"'


def test_um_registro_por_periodo_na_ordem_inicio_colaborador_codigo(logado, colaborador, outro_colaborador, ferias):
    criar(outro_colaborador, ferias, ('10/03/2026', '12/03/2026'), codigo='B1')
    criar(colaborador, ferias, ('10/03/2026', '12/03/2026'), ('01/03/2026', '02/03/2026'), codigo='A1')
    criar(colaborador, ferias, ('20/03/2026', '21/03/2026'), codigo='A0')

    linhas = ler(exportar(logado).content.decode())

    assert [(l['DataInicio'], l['Colaborador'], l['SolicitacaoID']) for l in linhas] == [
        ('2026-03-01', 'Ana Souza', 'A1'),
        ('2026-03-10', 'Ana Souza', 'A1'),
        ('2026-03-10', 'Bruno Lima', 'B1'),
        ('2026-03-20', 'Ana Souza', 'A0'),
    ]


def test_respeita_filtros_e_exporta_todos_os_periodos_da_ausencia(logado, colaborador, outro_colaborador, ferias):
    ti = Departamento.objects.create(nome='TI')
    Colaborador.objects.filter(pk=colaborador.pk).update(departamento=ti)
    criar(colaborador, ferias, ('02/03/2026', '06/03/2026'), ('01/06/2026', '05/06/2026'), codigo='A1')
    criar(colaborador, ferias, ('01/09/2026', '05/09/2026'), codigo='A2')
    criar(outro_colaborador, ferias, ('02/03/2026', '06/03/2026'), codigo='B1')

    linhas = ler(exportar(logado, departamento=ti.pk, de='2026-03-01', ate='2026-03-31').content.decode())

    # A1 cruza março; o período de junho vai junto para o código continuar íntegro.
    assert [(l['SolicitacaoID'], l['DataInicio']) for l in linhas] == [('A1', '2026-03-02'), ('A1', '2026-06-01')]


def test_filtro_por_nome(logado, colaborador, outro_colaborador, ferias):
    criar(colaborador, ferias, ('02/03/2026', '06/03/2026'))
    criar(outro_colaborador, ferias, ('02/03/2026', '06/03/2026'))
    assert {l['Colaborador'] for l in ler(exportar(logado, nome='bruno').content.decode())} == {'Bruno Lima'}


def test_ignora_excluidas(logado, colaborador, ferias, admin):
    ausencia = criar(colaborador, ferias, ('02/03/2026', '06/03/2026'))
    criar(colaborador, ferias, ('02/04/2026', '06/04/2026'), codigo='FICA')
    ausencias_service.excluir_ausencia(ausencia, admin)

    assert [l['SolicitacaoID'] for l in ler(exportar(logado).content.decode())] == ['FICA']


def test_sem_registros_so_cabecalho(logado):
    assert exportar(logado).content.decode() == '﻿' + CABECALHO + '\r\n'


def test_observacoes_com_separador_aspas_e_quebra_de_linha(logado, colaborador, ferias):
    texto = 'Volta dia 10; levar "notebook"\nsegunda linha'
    criar(colaborador, ferias, ('02/03/2026', '06/03/2026'), observacoes=texto)

    conteudo = exportar(logado).content.decode()

    assert '"Volta dia 10; levar ""notebook""\nsegunda linha"' in conteudo
    assert ler(conteudo)[0]['Observacoes'] == texto


@pytest.mark.parametrize('valor', ['=SOMA(A1)', '+55 11', '-x', '@cmd', '\tdentro'])
def test_neutraliza_formula_nos_campos_de_texto(logado, colaborador, ferias, valor):
    criar(colaborador, ferias, ('02/03/2026', '06/03/2026'), observacoes='x' + valor)
    ausencia = Ausencia.objects.get()
    Ausencia.objects.filter(pk=ausencia.pk).update(observacoes=valor)
    Colaborador.objects.filter(pk=colaborador.pk).update(nome='=' + colaborador.nome)

    [linha] = ler(exportar(logado).content.decode())

    assert linha['Observacoes'] == "'" + valor
    assert linha['Colaborador'] == "'=Ana Souza"
    assert linha['Titulo'] == "'=Ana Souza - Férias"
    assert csv_service.desfazer_neutralizacao(linha['Observacoes']) == valor


def test_nao_neutraliza_texto_comum_nem_apostrofo_comum():
    assert csv_service.neutralizar_formula('Ana') == 'Ana'
    assert csv_service.desfazer_neutralizacao("'Ana") == "'Ana"
    assert csv_service.desfazer_neutralizacao("'=1") == '=1'
    assert csv_service.desfazer_neutralizacao("''=1") == "''=1"


def test_numero_de_queries_constante(logado, ferias):
    def consultas(quantas):
        for _ in range(quantas):
            colaborador = Colaborador.objects.create(nome=f'Pessoa {Colaborador.objects.count()}')
            criar(colaborador, ferias, ('02/03/2026', '06/03/2026'), ('01/04/2026', '02/04/2026'))
        with CaptureQueriesContext(connection) as contexto:
            exportar(logado)
        return len(contexto.captured_queries)

    poucas = consultas(1)
    muitas = consultas(15)
    assert poucas == muitas


def test_botao_exportar_na_listagem_preserva_filtros(logado):
    resposta = logado.get(reverse('ausencias:lista'), {'nome': 'ana', 'page': '1'})
    html = resposta.content.decode()
    assert 'href="/ausencias/exportar/?nome=ana' in html
    assert 'page=1' not in html.split('id="exportar-csv"')[0].rsplit('<a', 1)[1]


def test_anonimo_vai_para_o_login(client):
    resposta = client.get(reverse('ausencias:exportar'))
    assert resposta.status_code == 302 and reverse('usuarios:login') in resposta['Location']
