import csv
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ausencias import ausencias_service, csv_service
from apps.ausencias.ausencias_service import PeriodoInformado
from apps.ausencias.models import ImportacaoCSV
from apps.ausencias.tests.conftest import d

pytestmark = pytest.mark.django_db

CABECALHO = 'Titulo;Colaborador;TipoEvento;DataInicio;DataFim;QuantidadeDias;Situacao;SolicitacaoID;Observacoes;DataSolicitacao'


def arquivo(*linhas, nome='lote.csv'):
    texto = '\r\n'.join([CABECALHO, *linhas]) + '\r\n'
    return SimpleUploadedFile(nome, ('﻿' + texto).encode())


LINHAS = [
    'Ana Souza - Férias;Ana Souza;Férias;2026-03-02;2026-03-06;5;Planejado;S1;ok;2026-01-01T10:00:00Z',      # importa
    'Ana Souza - Férias;Ana Souza;Férias;2026-03-02;2026-03-06;5;Planejado;S1;dup;',                         # duplicata
    'X;Ana Souza;Férias;31/02/2026;2026-03-06;;;S2;"data; ruim";',                                           # inválida
    'X;Carla Nova;Férias;2026-05-04;2026-05-05;;;S3;"=1+1";',                                                # pendente
    'X;Ana Souza;Banco de horas;2026-03-04;2026-03-04;1;;S4;;',                                              # sobreposição
]


def ler(resposta):
    texto = resposta.content.decode('utf-8')
    assert texto.startswith('﻿')
    return list(csv.DictReader(io.StringIO(texto[1:], newline=''), delimiter=';'))


@pytest.fixture
def importacao(admin_client, colaborador, ferias):
    resposta = admin_client.post(reverse('ausencias:importar'), {'arquivos': [arquivo(*LINHAS)]})
    return ImportacaoCSV.objects.get(pk=resposta.url.rstrip('/').split('/')[-1])


def baixar(client, importacao):
    resposta = client.get(reverse('ausencias:importacao_nao_importadas', args=[importacao.pk]))
    assert resposta.status_code == 200
    assert resposta['Content-Type'] == 'text/csv; charset=utf-8'
    assert resposta['Content-Disposition'].startswith('attachment; filename="nao-importadas-')
    return resposta


def test_da_previa_com_valores_lidos_motivo_arquivo_e_linha(admin_client, importacao):
    linhas = ler(baixar(admin_client, importacao))

    assert list(linhas[0]) == [*csv_service.COLUNAS, 'Motivo', 'Arquivo', 'Linha']
    assert [(l['Linha'], l['Arquivo']) for l in linhas] == [('4', 'lote.csv'), ('5', 'lote.csv'), ('6', 'lote.csv')]
    invalida, pendente, sobreposicao = linhas
    assert invalida['DataInicio'] == '31/02/2026' and invalida['Observacoes'] == 'data; ruim'
    assert 'inexistente' in invalida['Motivo']
    assert pendente['Motivo'] == 'Colaborador "Carla Nova" não cadastrado.'
    assert pendente['Observacoes'] == "'=1+1"  # neutralizado de novo na saída
    assert sobreposicao['Motivo'].startswith('Sobrepõe Férias de 02/03/2026 a 06/03/2026')


def test_reflete_as_decisoes_atuais(admin_client, importacao):
    admin_client.post(reverse('ausencias:importacao_previa', args=[importacao.pk]), {'criar_colaboradores': ['carla nova']})
    assert [l['Linha'] for l in ler(baixar(admin_client, importacao))] == ['4', '6']


def test_do_resultado_depois_de_aplicada(admin_client, importacao):
    analise = admin_client.get(reverse('ausencias:importacao_previa', args=[importacao.pk])).context['analise']
    admin_client.post(reverse('ausencias:importacao_confirmar', args=[importacao.pk]), {'assinatura': analise.assinatura})
    importacao.refresh_from_db()
    assert importacao.arquivos == []

    assert [l['Linha'] for l in ler(baixar(admin_client, importacao))] == ['4', '5', '6']
    html = admin_client.get(reverse('ausencias:importacao_resultado', args=[importacao.pk])).content.decode()
    assert 'id="baixar-nao-importadas"' in html


def test_link_na_previa(admin_client, importacao):
    html = admin_client.get(reverse('ausencias:importacao_previa', args=[importacao.pk])).content.decode()
    assert 'Baixar linhas não importadas (3)' in html


def test_pode_ser_corrigido_e_reimportado(admin_client, importacao, admin):
    conteudo = baixar(admin_client, importacao).content
    # Corrige a data inválida no próprio arquivo; as colunas extras são ignoradas na leitura.
    corrigido = conteudo.decode('utf-8').replace('31/02/2026', '2026-03-01').encode('utf-8')

    lido = csv_service.ler_conteudo('corrigido.csv', corrigido)
    analise = csv_service.analisar([lido], {'colaboradores': ['carla nova']})

    assert lido.erro == ''
    assert [l.categoria for l in analise.linhas] == [csv_service.IMPORTAR, csv_service.IMPORTAR, csv_service.SOBREPOSICAO]
    assert analise.linhas[1].registro.observacoes == '=1+1'


def test_importacao_cancelada_nao_tem_download(admin_client, importacao):
    admin_client.post(reverse('ausencias:importacao_cancelar', args=[importacao.pk]))
    resposta = admin_client.get(reverse('ausencias:importacao_nao_importadas', args=[importacao.pk]))
    assert resposta.status_code == 302 and resposta.url == reverse('ausencias:importar')


def test_sem_linhas_nao_importadas(admin_client, colaborador, ferias, admin):
    ausencias_service.criar_ausencia(colaborador, ferias, [PeriodoInformado(d('02/03/2026'), d('06/03/2026'))], '', admin)
    resposta = admin_client.post(reverse('ausencias:importar'), {'arquivos': [arquivo(LINHAS[0])]})
    importacao = ImportacaoCSV.objects.get(pk=resposta.url.rstrip('/').split('/')[-1])
    assert ler(baixar(admin_client, importacao)) == []
