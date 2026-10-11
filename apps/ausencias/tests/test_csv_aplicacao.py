"""Staging (ImportacaoCSV) e aplicação da importação."""

import threading
import time
from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.utils import timezone

from apps.ausencias import ausencias_service, csv_service
from apps.ausencias.ausencias_service import PeriodoInformado
from apps.ausencias.csv_service import DUPLICATA, IMPORTAR
from apps.ausencias.models import Ausencia, ImportacaoCSV, PeriodoAusencia, SituacaoAusencia, TipoAusencia
from apps.colaboradores.models import Colaborador

CABECALHO = 'Colaborador;TipoEvento;DataInicio;DataFim;Situacao;SolicitacaoID;Observacoes'


def enviado(*linhas, nome='a.csv'):
    texto = '\r\n'.join([CABECALHO, *(';'.join((*l, '', '', '')[:7]) for l in linhas)]) + '\r\n'
    return SimpleUploadedFile(nome, ('﻿' + texto).encode())


def importar(admin, *enviados, decisoes=None):
    """Envia, faz a prévia e confirma com a assinatura exibida."""
    importacao = csv_service.criar_importacao(list(enviados), admin)
    previa = csv_service.analisar_importacao(importacao, decisoes)
    return csv_service.aplicar_importacao(importacao, decisoes, previa.assinatura, admin), previa


def _totais():
    return (
        Ausencia.todos.count(), PeriodoAusencia.objects.count(), Colaborador.objects.count(),
        TipoAusencia.objects.count(), SituacaoAusencia.objects.count(),
    )


@pytest.mark.django_db
def test_aplica_exatamente_o_que_a_previa_mostrou(colaborador, ferias, aprovado, admin):
    importacao, previa = importar(admin, enviado(
        ('Ana Souza', 'Férias', '02/03/2026', '06/03/2026', '', 'SLEG1', 'Viagem'),
        ('ana souza', 'ferias', '2026-06-01', '2026-06-05', 'Aprovado', 'SLEG1'),
        ('Ana Souza', 'Banco de horas', '04/03/2026', '04/03/2026', '', 'SLEG2'),  # sobrepõe a 1ª
    ))

    ausencia = Ausencia.objects.get()
    assert (ausencia.codigo, ausencia.colaborador, ausencia.tipo, ausencia.observacoes) == (
        'SLEG1', colaborador, ferias, 'Viagem',
    )
    assert ausencia.criado_por == admin
    assert [(p.data_inicio, p.data_fim, p.situacao.nome) for p in ausencia.periodos.all()] == [
        (date(2026, 3, 2), date(2026, 3, 6), 'Planejado'),
        (date(2026, 6, 1), date(2026, 6, 5), 'Aprovado'),
    ]
    assert importacao.status == ImportacaoCSV.APLICADA and importacao.aplicada_em is not None
    assert importacao.arquivos == []
    assert importacao.resumo['contagens'] == previa.contagens
    assert importacao.resumo['codigos'] == ['SLEG1']
    [nao_importada] = importacao.resumo['nao_importadas']
    assert (nao_importada['Linha'], nao_importada['Arquivo'], nao_importada['TipoEvento']) == (4, 'a.csv', 'Banco de horas')
    assert nao_importada['Motivo'].startswith('Sobrepõe Férias de 02/03/2026 a 06/03/2026')


@pytest.mark.django_db
def test_codigo_gerado_quando_o_id_nao_serve(colaborador, ferias, admin):
    importar(admin, enviado(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026', '', 'ID INVÁLIDO')))
    assert len(Ausencia.objects.get().codigo) == ausencias_service.TAMANHO_CODIGO


@pytest.mark.django_db
def test_sem_marcacao_nada_e_criado(admin):
    antes = _totais()
    importacao = csv_service.criar_importacao([enviado(('Nova Pessoa', 'Tipo Novo', '02/03/2026', '06/03/2026'))], admin)
    previa = csv_service.analisar_importacao(importacao)
    assert not previa.tem_o_que_importar
    with pytest.raises(csv_service.ImportacaoIndisponivel):
        csv_service.aplicar_importacao(importacao, None, previa.assinatura, admin)
    assert _totais() == antes


@pytest.mark.django_db
def test_cria_os_cadastros_marcados_com_os_padroes(admin, ferias):
    TipoAusencia.objects.filter(pk=ferias.pk).update(ordem=40)
    decisoes = {'colaboradores': ['nova pessoa'], 'tipos': ['tipo novo'], 'situacoes': ['em analise']}

    importar(admin, enviado(('Nova  Pessoa', 'Tipo   Novo', '02/03/2026', '06/03/2026', 'Em análise')),
             decisoes=decisoes)

    colaborador = Colaborador.objects.get(nome='Nova Pessoa')
    assert (colaborador.ativo, colaborador.departamento, colaborador.criado_por) == (True, None, admin)
    tipo = TipoAusencia.objects.get(nome='Tipo Novo')
    assert (tipo.ativo, tipo.cor, tipo.ordem, tipo.criado_por) == (True, csv_service.COR_TIPO_NOVO, 41, admin)
    situacao = SituacaoAusencia.objects.get(nome='Em análise')
    maior = max(s.ordem for s in SituacaoAusencia.objects.exclude(pk=situacao.pk))
    assert (situacao.ativo, situacao.conta_como_ausencia, situacao.padrao, situacao.ordem) == (True, True, False, maior + 1)
    assert SituacaoAusencia.objects.get(padrao=True).nome == 'Planejado'
    periodo = PeriodoAusencia.objects.get()
    assert (periodo.ausencia.colaborador, periodo.ausencia.tipo, periodo.situacao) == (colaborador, tipo, situacao)


@pytest.mark.django_db
def test_assinatura_divergente_nao_grava(colaborador, ferias, banco_horas, admin):
    importacao = csv_service.criar_importacao([enviado(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026'))], admin)
    previa = csv_service.analisar_importacao(importacao)
    # Alguém registra no mesmo período entre a prévia e a confirmação.
    ausencias_service.criar_ausencia(colaborador, banco_horas, [PeriodoInformado(date(2026, 3, 5), date(2026, 3, 5))], '', admin)
    antes = _totais()

    with pytest.raises(csv_service.PreviaDesatualizada) as erro:
        csv_service.aplicar_importacao(importacao, None, previa.assinatura, admin)

    assert _totais() == antes
    assert erro.value.analise.contagens[IMPORTAR] == 0
    importacao.refresh_from_db()
    assert importacao.status == ImportacaoCSV.PENDENTE and importacao.arquivos


@pytest.mark.django_db
def test_decisoes_diferentes_das_da_previa_nao_gravam(admin, ferias):
    importacao = csv_service.criar_importacao([enviado(('Nova Pessoa', 'Férias', '02/03/2026', '06/03/2026'))], admin)
    previa = csv_service.analisar_importacao(importacao, {})
    with pytest.raises(csv_service.PreviaDesatualizada):
        csv_service.aplicar_importacao(importacao, {'colaboradores': ['nova pessoa']}, previa.assinatura, admin)
    assert not Colaborador.objects.filter(nome='Nova Pessoa').exists()


@pytest.mark.django_db
def test_falha_no_meio_desfaz_tudo(monkeypatch, admin, ferias, caplog):
    decisoes = {'colaboradores': ['nova pessoa', 'outra pessoa'], 'tipos': ['tipo novo']}
    importacao = csv_service.criar_importacao([enviado(
        ('Nova Pessoa', 'Tipo Novo', '02/03/2026', '06/03/2026'),
        ('Outra Pessoa', 'Férias', '02/03/2026', '06/03/2026'),
    )], admin)
    previa = csv_service.analisar_importacao(importacao, decisoes)
    antes = _totais()
    original = ausencias_service.criar_ausencia
    chamadas = []

    def falha_na_segunda(*args, **kwargs):
        chamadas.append(1)
        if len(chamadas) == 2:
            raise ausencias_service.ErroValidacaoAusencia(['divergência simulada'])
        return original(*args, **kwargs)

    monkeypatch.setattr(ausencias_service, 'criar_ausencia', falha_na_segunda)

    with pytest.raises(csv_service.FalhaImportacao, match='nada foi gravado'):
        csv_service.aplicar_importacao(importacao, decisoes, previa.assinatura, admin)

    assert _totais() == antes
    assert 'nada foi gravado' in caplog.text
    importacao.refresh_from_db()
    assert importacao.status == ImportacaoCSV.PENDENTE and importacao.arquivos


@pytest.mark.django_db
def test_previa_expirada(admin, colaborador, ferias):
    importacao = csv_service.criar_importacao([enviado(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026'))], admin)
    previa = csv_service.analisar_importacao(importacao)
    ImportacaoCSV.objects.filter(pk=importacao.pk).update(criado_em=timezone.now() - timedelta(hours=2, minutes=1))
    importacao.refresh_from_db()
    assert importacao.expirada
    with pytest.raises(csv_service.ImportacaoIndisponivel, match='expirou'):
        csv_service.aplicar_importacao(importacao, None, previa.assinatura, admin)
    assert not Ausencia.objects.exists()


@pytest.mark.django_db
def test_nao_aplica_duas_vezes(admin, colaborador, ferias):
    importacao, previa = importar(admin, enviado(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026')))
    with pytest.raises(csv_service.ImportacaoIndisponivel, match='já foi aplicada'):
        csv_service.aplicar_importacao(importacao, None, previa.assinatura, admin)
    assert Ausencia.objects.count() == 1


@pytest.mark.django_db
def test_reenviar_o_mesmo_arquivo_resulta_tudo_duplicata(admin, colaborador, outro_colaborador, ferias):
    linhas = [
        ('Ana Souza', 'Férias', '02/03/2026', '06/03/2026', '', 'S1'),
        ('Ana Souza', 'Férias', '02/06/2026', '06/06/2026', 'Aprovado', 'S1'),
        ('Bruno Lima', 'Banco de horas', '02/03/2026', '02/03/2026'),
    ]
    importar(admin, enviado(*linhas))
    antes = _totais()

    importacao = csv_service.criar_importacao([enviado(*linhas)], admin)
    previa = csv_service.analisar_importacao(importacao)

    assert [linha.categoria for linha in previa.linhas] == [DUPLICATA] * 3
    assert not previa.tem_o_que_importar
    assert _totais() == antes


@pytest.mark.django_db
def test_cancelar_apaga_as_linhas_lidas(admin):
    importacao = csv_service.criar_importacao([enviado(('Ana', 'Férias', '02/03/2026', '06/03/2026'))], admin)
    csv_service.cancelar_importacao(importacao, admin)
    importacao.refresh_from_db()
    assert (importacao.status, importacao.arquivos) == (ImportacaoCSV.CANCELADA, [])
    with pytest.raises(csv_service.ImportacaoIndisponivel, match='cancelada'):
        csv_service.aplicar_importacao(importacao, None, '', admin)


@pytest.mark.django_db
def test_novo_envio_apaga_importacoes_com_mais_de_24_horas(admin):
    velha = csv_service.criar_importacao([enviado(('Ana', 'Férias', '02/03/2026', '06/03/2026'))], admin)
    recente = csv_service.criar_importacao([enviado(('Ana', 'Férias', '02/03/2026', '06/03/2026'))], admin)
    ImportacaoCSV.objects.filter(pk=velha.pk).update(criado_em=timezone.now() - timedelta(hours=24, minutes=1))
    ImportacaoCSV.objects.filter(pk=recente.pk).update(criado_em=timezone.now() - timedelta(hours=23))

    csv_service.criar_importacao([enviado(('Ana', 'Férias', '02/03/2026', '06/03/2026'))], admin)

    assert not ImportacaoCSV.objects.filter(pk=velha.pk).exists()
    assert ImportacaoCSV.objects.filter(pk=recente.pk).exists()


@pytest.mark.django_db
def test_decisoes_guardadas(admin):
    importacao = csv_service.criar_importacao([enviado(('Ana', 'Férias', '02/03/2026', '06/03/2026'))], admin)
    csv_service.salvar_decisoes(importacao, {'colaboradores': ['ANA', 'ana '], 'tipos': []}, admin)
    importacao.refresh_from_db()
    assert importacao.decisoes == {'colaboradores': ['ana'], 'tipos': [], 'situacoes': []}
    assert csv_service.analisar_importacao(importacao).a_criar['colaboradores'][0].nome == 'Ana'


# ---------------------------------------------------------------------------
# Concorrência: colaborador travado por outro registro durante a confirmação
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_confirmacao_espera_o_registro_concorrente_e_detecta_a_mudanca(admin):
    colaborador = Colaborador.objects.create(nome='Ana Souza')
    ferias = TipoAusencia.objects.get(nome='Férias')
    importacao = csv_service.criar_importacao([enviado(('Ana Souza', 'Férias', '02/03/2026', '06/03/2026'))], admin)
    previa = csv_service.analisar_importacao(importacao)
    travou = threading.Event()

    def registro_concorrente():
        try:
            with transaction.atomic():
                ausencias_service.travar_colaboradores(colaborador.pk)
                travou.set()
                time.sleep(0.5)  # a confirmação chega enquanto a trava está com este registro
                ausencias_service.criar_ausencia(
                    colaborador, ferias, [PeriodoInformado(date(2026, 3, 6), date(2026, 3, 8))], '', None,
                )
        finally:
            connection.close()

    thread = threading.Thread(target=registro_concorrente)
    thread.start()
    assert travou.wait(timeout=5)
    # Sem a trava, a análise não veria o registro concorrente e gravaria.
    with pytest.raises(csv_service.PreviaDesatualizada):
        csv_service.aplicar_importacao(importacao, None, previa.assinatura, admin)
    thread.join(timeout=10)

    assert Ausencia.objects.count() == 1  # só a do registro concorrente
