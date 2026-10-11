"""Telas da importação de CSV: envio, prévia, recálculo, confirmação,
cancelamento e resultado."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.ausencias.models import Ausencia, ImportacaoCSV
from apps.colaboradores.models import Colaborador

pytestmark = pytest.mark.django_db

CABECALHO = 'Colaborador;TipoEvento;DataInicio;DataFim;Situacao;SolicitacaoID;Observacoes'


def arquivo(*linhas, nome='a.csv'):
    texto = '\r\n'.join([CABECALHO, *(';'.join((*l, '', '', '')[:7]) for l in linhas)]) + '\r\n'
    return SimpleUploadedFile(nome, ('﻿' + texto).encode())


def enviar(client, *arquivos):
    return client.post(reverse('ausencias:importar'), {'arquivos': list(arquivos)})


@pytest.fixture
def importacao(admin_client, colaborador, ferias):
    resposta = enviar(admin_client, arquivo(
        ('Ana Souza', 'Férias', '02/03/2026', '06/03/2026', '', 'S1', 'Viagem'),
        ('Carla Nova', 'Férias', '02/03/2026', '06/03/2026'),
    ))
    return ImportacaoCSV.objects.get(pk=resposta.url.rstrip('/').split('/')[-1])


def previa(client, importacao):
    return client.get(reverse('ausencias:importacao_previa', args=[importacao.pk]))


def test_tela_de_envio_explica_a_ordem(admin_client):
    html = admin_client.get(reverse('ausencias:importar')).content.decode()
    assert 'ordem alfabética do nome' in html and 'vale a mais antiga' in html
    assert 'multiple' in html and 'enctype="multipart/form-data"' in html


def test_envio_sem_arquivo(admin_client):
    resposta = admin_client.post(reverse('ausencias:importar'), {})
    assert resposta.status_code == 200
    assert 'Selecione pelo menos um arquivo.' in resposta.content.decode()
    assert not ImportacaoCSV.objects.exists()


def test_envio_redireciona_para_a_previa_prg(admin_client, colaborador, ferias, admin):
    resposta = enviar(admin_client, arquivo(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026')),
                      arquivo(('Ana Souza', 'Férias', '02/04/2026', '06/04/2026'), nome='b.csv'))
    importacao = ImportacaoCSV.objects.get()
    assert resposta.status_code == 302
    assert resposta.url == reverse('ausencias:importacao_previa', args=[importacao.pk])
    assert importacao.criado_por == admin and len(importacao.arquivos) == 2
    assert not Ausencia.objects.exists()


def test_arquivo_vazio_e_extensao_errada_aparecem_na_previa(admin_client, colaborador, ferias):
    enviar(admin_client, SimpleUploadedFile('vazio.csv', b''), SimpleUploadedFile('planilha.xlsx', b'xx'),
           arquivo(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026')))
    html = previa(admin_client, ImportacaoCSV.objects.get()).content.decode()
    assert 'O arquivo está vazio.' in html and 'Extensão não aceita' in html


def test_previa_mostra_arquivos_contagens_e_pendencias(admin_client, importacao):
    resposta = previa(admin_client, importacao)
    html = resposta.content.decode()
    contagens = resposta.context['contagens']
    assert (contagens['importar'], contagens['pendente']) == (1, 1)
    assert 'UTF-8 com BOM' in html and 'a.csv' in html
    assert 'Pendências de cadastro' in html and 'Criar "Carla Nova"' in html
    assert 'name="criar_colaboradores" value="carla nova"' in html
    assert 'checked' not in html.split('Pendências de cadastro')[1].split('</form>')[0]  # desmarcadas
    assert 'Confirmar importação: 1 período em 1 ausência' in html
    assert resposta.context['analise'].assinatura in html


def test_valores_do_arquivo_sao_escapados(admin_client, colaborador, ferias):
    enviar(admin_client, arquivo(('<script>alert(1)</script>', 'Férias', '02/03/2026', '06/03/2026')))
    html = previa(admin_client, ImportacaoCSV.objects.get()).content.decode()
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_recalcular_sem_javascript_guarda_decisoes_e_volta_para_a_previa(admin_client, importacao):
    url = reverse('ausencias:importacao_previa', args=[importacao.pk])
    resposta = admin_client.post(url, {'criar_colaboradores': ['carla nova']})
    assert resposta.status_code == 302 and resposta.url == url
    importacao.refresh_from_db()
    assert importacao.decisoes['colaboradores'] == ['carla nova']
    html = previa(admin_client, importacao).content.decode()
    assert 'Confirmar importação: 2 períodos em 2 ausências, criando 1 colaborador' in html


def test_recalcular_com_htmx_devolve_so_a_previa(admin_client, importacao):
    url = reverse('ausencias:importacao_previa', args=[importacao.pk])
    resposta = admin_client.post(url, {'criar_colaboradores': ['carla nova']}, HTTP_HX_REQUEST='true')
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert '<div id="previa">' in html
    assert '<html' not in html
    assert resposta.context['contagens']['importar'] == 2


def test_confirmar_aplica_e_mostra_o_resultado(admin_client, importacao, admin):
    analise = previa(admin_client, importacao).context['analise']
    resposta = admin_client.post(
        reverse('ausencias:importacao_confirmar', args=[importacao.pk]), {'assinatura': analise.assinatura},
    )
    assert resposta.url == reverse('ausencias:importacao_resultado', args=[importacao.pk])
    assert Ausencia.objects.get().codigo == 'S1'
    resultado = admin_client.get(resposta.url)
    html = resultado.content.decode()
    assert 'Importação concluída: 1 período(s) em 1 ausência(s).' in html
    assert reverse('ausencias:lista') in html
    # Aplicada: a prévia leva ao resultado.
    assert previa(admin_client, importacao).url == resposta.url


def test_confirmar_com_marcacao(admin_client, importacao):
    url_previa = reverse('ausencias:importacao_previa', args=[importacao.pk])
    admin_client.post(url_previa, {'criar_colaboradores': ['carla nova']})
    analise = admin_client.get(url_previa).context['analise']
    admin_client.post(
        reverse('ausencias:importacao_confirmar', args=[importacao.pk]),
        {'assinatura': analise.assinatura, 'criar_colaboradores': ['carla nova']},
    )
    assert Colaborador.objects.filter(nome='Carla Nova', departamento__isnull=True).exists()
    assert Ausencia.objects.count() == 2


def test_confirmar_com_dados_mudados_reexibe_a_previa(admin_client, importacao):
    analise = previa(admin_client, importacao).context['analise']
    # Marcação diferente da prévia exibida (ex.: outra aba): a assinatura não bate.
    resposta = admin_client.post(
        reverse('ausencias:importacao_confirmar', args=[importacao.pk]),
        {'assinatura': analise.assinatura, 'criar_colaboradores': ['carla nova']}, follow=True,
    )
    html = resposta.content.decode()
    assert 'Os dados mudaram desde a prévia e nada foi gravado' in html
    assert 'Confirmar importação: 2 períodos' in html
    assert not Ausencia.objects.exists()


def test_cancelar(admin_client, importacao):
    resposta = admin_client.post(reverse('ausencias:importacao_cancelar', args=[importacao.pk]), follow=True)
    assert 'Importação cancelada. Nada foi gravado.' in resposta.content.decode()
    importacao.refresh_from_db()
    assert importacao.status == ImportacaoCSV.CANCELADA and importacao.arquivos == []
    seguinte = previa(admin_client, importacao)
    assert seguinte.url == reverse('ausencias:importar')


def test_previa_expirada_pede_novo_envio(admin_client, importacao):
    ImportacaoCSV.objects.filter(pk=importacao.pk).update(criado_em=timezone.now() - timedelta(hours=3))
    resposta = previa(admin_client, importacao)
    assert resposta.url == reverse('ausencias:importar')
    html = admin_client.get(resposta.url).content.decode()
    assert 'A prévia expirou' in html and 'Envie os arquivos novamente' in html


def test_resultado_de_importacao_pendente_volta_para_a_previa(admin_client, importacao):
    resposta = admin_client.get(reverse('ausencias:importacao_resultado', args=[importacao.pk]))
    assert resposta.url == reverse('ausencias:importacao_previa', args=[importacao.pk])


def test_nada_a_importar_desabilita_o_botao(admin_client, colaborador, ferias):
    enviar(admin_client, arquivo(('Ninguem', 'Férias', '02/03/2026', '06/03/2026')))
    html = previa(admin_client, ImportacaoCSV.objects.get()).content.decode()
    assert 'disabled' in html.split('id="confirmar-importacao"')[1].split('>')[0]
    assert 'Nada a importar' in html


def test_menu_importar_so_para_o_administrador(client, admin, gestor):
    client.force_login(gestor)
    assert 'Importar CSV' not in client.get(reverse('ausencias:lista')).content.decode()
    client.force_login(admin)
    assert 'Importar CSV' in client.get(reverse('ausencias:lista')).content.decode()
