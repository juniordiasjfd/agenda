"""CSV de ausências: exportação, leitura, análise (prévia) e aplicação da
importação.

Formato compatível com o fluxo antigo (``legado/referencias/index.html``):
uma linha por período, separador ``;``, UTF-8 com BOM, CRLF. As views só
traduzem requisição/resposta; a regra de sobreposição é a de
``ausencias_service.conflitam`` (uma só para formulário, banco e lote).
"""

import csv
import io
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

COLUNAS = [
    'Titulo', 'Colaborador', 'TipoEvento', 'DataInicio', 'DataFim',
    'QuantidadeDias', 'Situacao', 'SolicitacaoID', 'Observacoes', 'DataSolicitacao',
]
# Campos de texto livre: os únicos neutralizados contra injeção de fórmula.
COLUNAS_TEXTO = ('Titulo', 'Colaborador', 'TipoEvento', 'Situacao', 'Observacoes')
BOM = '﻿'


# ---------------------------------------------------------------------------
# Injeção de fórmula (planilhas executam célula que começa com = + - @...)
# ---------------------------------------------------------------------------
_INICIO_DE_FORMULA = ('=', '+', '-', '@', '\t', '\r')


def neutralizar_formula(valor):
    """Prefixa com apóstrofo o texto que uma planilha leria como fórmula."""
    return f"'{valor}" if valor.startswith(_INICIO_DE_FORMULA) else valor


def desfazer_neutralizacao(valor):
    """Inverso exato de ``neutralizar_formula``: tira o apóstrofo só quando
    ele vem seguido de um dos caracteres neutralizados."""
    if len(valor) >= 2 and valor[0] == "'" and valor[1] in _INICIO_DE_FORMULA:
        return valor[1:]
    return valor


def escrever_csv(linhas, colunas=COLUNAS):
    """Texto CSV (com BOM, ``;``, CRLF, aspas só quando necessário) de
    ``linhas`` (dicts por nome de coluna; ausente = vazio). Os campos de
    ``COLUNAS_TEXTO`` são neutralizados contra fórmula."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=';', quotechar='"', lineterminator='\r\n', quoting=csv.QUOTE_MINIMAL)
    escritor.writerow(colunas)
    for linha in linhas:
        valores = []
        for coluna in colunas:
            valor = '' if linha.get(coluna) is None else str(linha.get(coluna))
            valores.append(neutralizar_formula(valor) if coluna in COLUNAS_TEXTO else valor)
        escritor.writerow(valores)
    return BOM + saida.getvalue()


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def nome_arquivo_exportacao(hoje=None):
    hoje = hoje or timezone.localdate()
    return f'periodos-eventos-{hoje:%Y-%m-%d}.csv'


def linhas_exportacao(ausencias):
    """Uma linha por período de cada ausência (todos os períodos, para o
    SolicitacaoID continuar íntegro na reimportação), ordenadas por início,
    colaborador e código. ``ausencias`` como as de
    ``ausencias_service.ausencias_filtradas`` (relacionados já carregados)."""
    pares = [(periodo, ausencia) for ausencia in ausencias for periodo in ausencia.periodos.all()]
    pares.sort(key=lambda par: (par[0].data_inicio, par[1].colaborador.nome_normalizado, par[1].codigo, par[0].data_fim))
    return [
        {
            'Titulo': ausencia.titulo,
            'Colaborador': ausencia.colaborador.nome,
            'TipoEvento': ausencia.tipo.nome,
            'DataInicio': periodo.data_inicio.isoformat(),
            'DataFim': periodo.data_fim.isoformat(),
            'QuantidadeDias': periodo.dias,
            'Situacao': periodo.situacao.nome,
            'SolicitacaoID': ausencia.codigo,
            'Observacoes': ausencia.observacoes,
            'DataSolicitacao': timezone.localtime(ausencia.criado_em).isoformat(timespec='seconds'),
        }
        for periodo, ausencia in pares
    ]


def exportar_csv(ausencias):
    """Texto do CSV de exportação (ver ``linhas_exportacao``)."""
    return escrever_csv(linhas_exportacao(ausencias))
