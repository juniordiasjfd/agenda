"""Ponta a ponta pelas telas: exportar e reimportar (round-trip) e os
arquivos no formato legado (fixtures SINTÉTICAS, sem dados reais)."""

from datetime import date
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ausencias import ausencias_service
from apps.ausencias.ausencias_service import PeriodoInformado
from apps.ausencias.models import Ausencia, ImportacaoCSV, PeriodoAusencia, SituacaoAusencia, TipoAusencia
from apps.colaboradores.models import Colaborador, Departamento

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / 'fixtures'


def importar_pela_tela(client, *enviados, marcar_tudo=False):
    """Envia, (opcionalmente marca todas as pendências), confirma. Devolve
    a ImportacaoCSV e o contexto da prévia confirmada."""
    resposta = client.post(reverse('ausencias:importar'), {'arquivos': list(enviados)})
    assert resposta.status_code == 302, resposta.content.decode()[:500]
    importacao = ImportacaoCSV.objects.get(pk=resposta.url.rstrip('/').split('/')[-1])
    url_previa = reverse('ausencias:importacao_previa', args=[importacao.pk])
    contexto = client.get(url_previa).context
    decisoes = {}
    if marcar_tudo:
        decisoes = {
            pendencia.campo: [p.chave for p in pendencias]
            for pendencias in contexto['analise'].pendencias.values() if pendencias
            for pendencia in pendencias[:1]
        }
        client.post(url_previa, decisoes)
        contexto = client.get(url_previa).context
    analise = contexto['analise']
    if analise.tem_o_que_importar:
        resposta = client.post(
            reverse('ausencias:importacao_confirmar', args=[importacao.pk]),
            {'assinatura': analise.assinatura, **decisoes},
        )
        assert resposta.url == reverse('ausencias:importacao_resultado', args=[importacao.pk])
    importacao.refresh_from_db()
    return importacao, analise


def fotografia():
    """Estado comparável do banco: (colaborador, tipo, código, observações,
    [(início, fim, situação)])."""
    return sorted(
        (
            a.colaborador.nome, a.tipo.nome, a.codigo, a.observacoes,
            tuple((p.data_inicio, p.data_fim, p.situacao.nome) for p in a.periodos.all()),
        )
        for a in Ausencia.objects.select_related('colaborador', 'tipo').prefetch_related('periodos__situacao')
    )


def test_round_trip_exportar_e_importar_em_banco_vazio(admin_client, admin):
    ti = Departamento.objects.create(nome='TI')
    ana = Colaborador.objects.create(nome='Ana  Conceição', departamento=ti)
    bruno = Colaborador.objects.create(nome='Bruno Lima')
    ferias = TipoAusencia.objects.get(nome='Férias')
    curso = TipoAusencia.objects.create(nome='Curso externo', cor='#ff0000', ordem=9)
    em_analise = SituacaoAusencia.objects.create(nome='Em análise', ordem=9)
    cancelado = SituacaoAusencia.objects.get(nome='Cancelado')
    criar = ausencias_service.criar_ausencia
    criar(ana, ferias, [PeriodoInformado(date(2026, 1, 5), date(2026, 1, 16)),
                        PeriodoInformado(date(2026, 7, 6), date(2026, 7, 10), em_analise)],
          'Viagem; "praia"\nsegunda linha', admin, codigo='SMG7X3K2AB')
    criar(ana, curso, [PeriodoInformado(date(2026, 1, 10), date(2026, 1, 12), cancelado)], '=não é fórmula', admin)
    criar(bruno, ferias, [PeriodoInformado(date(2026, 1, 5), date(2026, 1, 16))], '', admin)
    na_lixeira = criar(bruno, curso, [PeriodoInformado(date(2026, 9, 1), date(2026, 9, 2))], '', admin)
    ausencias_service.excluir_ausencia(na_lixeira, admin)
    esperado = fotografia()

    exportado = admin_client.get(reverse('ausencias:exportar')).content

    # Banco "vazio": sem ausências, sem os colaboradores e sem os cadastros criados acima.
    Ausencia.todos.all().delete()
    Colaborador.objects.all().delete()
    curso.delete()
    em_analise.delete()

    importacao, analise = importar_pela_tela(
        admin_client, SimpleUploadedFile('export.csv', exportado), marcar_tudo=True,
    )

    assert analise.contagens['invalida'] == analise.contagens['sobreposicao'] == analise.contagens['pendente'] == 0
    assert fotografia() == esperado
    assert set(Colaborador.objects.values_list('nome', flat=True)) == {'Ana Conceição', 'Bruno Lima'}
    assert SituacaoAusencia.objects.get(nome='Em análise').conta_como_ausencia
    assert not Ausencia.todos.filter(colaborador__nome='Bruno Lima', tipo__nome='Curso externo').exists()

    # Reimportar o mesmo arquivo: tudo duplicata, nada muda.
    _, de_novo = importar_pela_tela(admin_client, SimpleUploadedFile('export.csv', exportado))
    assert de_novo.contagens['duplicata'] == de_novo.contagens['registros'] == 4
    assert fotografia() == esperado


def test_fixture_legada_utf8_bom_ponto_e_virgula(admin_client):
    for nome in ('Fulana de Teste Sintética', 'Beltrano Exemplo', 'Ciclano Fictício'):
        Colaborador.objects.create(nome=nome)
    conteudo = (FIXTURES / 'legado_sintetico.csv').read_bytes()
    assert conteudo.startswith(b'\xef\xbb\xbf') and b'\r\n' in conteudo

    importacao, analise = importar_pela_tela(admin_client, SimpleUploadedFile('legado_sintetico.csv', conteudo))

    assert [a.codificacao for a in analise.arquivos] == ['UTF-8 com BOM']
    assert analise.contagens['importar'] == 4 and analise.contagens['ausencias'] == 3
    assert importacao.resumo['nao_importadas'] == []
    fulana = Ausencia.objects.get(codigo='SMG7X3K2AB')
    assert fulana.colaborador.nome == 'Fulana de Teste Sintética'  # o espaço duplo do arquivo não duplica o cadastro
    assert [(p.data_inicio, p.data_fim) for p in fulana.periodos.all()] == [
        (date(2026, 1, 5), date(2026, 1, 16)), (date(2026, 7, 6), date(2026, 7, 10)),
    ]
    assert Ausencia.objects.get(codigo='SMH01ZQ9CD').observacoes == 'Consulta; retorno à tarde'
    assert Ausencia.objects.get(codigo='SMJ88KLM1E').observacoes == 'Licença médica\nretorno previsto em abril'


def test_fixtures_legadas_juntas_em_ordem_alfabetica(admin_client):
    for nome in ('Fulana de Teste Sintética', 'Beltrano Exemplo', 'Ciclano Fictício'):
        Colaborador.objects.create(nome=nome)
    enviados = [
        SimpleUploadedFile(nome, (FIXTURES / nome).read_bytes())
        for nome in ('legado_windows1252.csv', 'legado_sintetico.csv')
    ]

    _, analise = importar_pela_tela(admin_client, *enviados)

    assert [(a.nome, a.codificacao, a.separador) for a in analise.arquivos] == [
        ('legado_sintetico.csv', 'UTF-8 com BOM', ';'), ('legado_windows1252.csv', 'Windows-1252', ','),
    ]
    por_linha = {(l.arquivo, l.linha): l for l in analise.linhas}
    # Mesma linha nos dois arquivos: o segundo (alfabético) vira duplicata.
    assert por_linha[('legado_windows1252.csv', 2)].categoria == 'duplicata'
    # Beltrano já tem Banco de horas em 13/02 (primeiro arquivo); Férias em março entra.
    assert por_linha[('legado_windows1252.csv', 3)].categoria == 'importar'
    # Ciclano: Licença 02-31/03 no primeiro arquivo; "Outro" 10-12/03 sobrepõe.
    assert por_linha[('legado_windows1252.csv', 4)].categoria == 'sobreposicao'
    assert Ausencia.objects.get(codigo='SMQ55RSTUV').observacoes == 'Observação com vírgula, e acento'
    assert PeriodoAusencia.objects.count() == 5
