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
import re
from dataclasses import dataclass, field
from datetime import date

from django.conf import settings
from django.utils import timezone

from apps.ausencias.ausencias_service import ANO_MAXIMO, ANO_MINIMO
from apps.core.utils import colapsar_espacos, normalizar_nome

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


# ---------------------------------------------------------------------------
# Leitura (pura: não consulta o banco)
# ---------------------------------------------------------------------------
EXTENSOES_ACEITAS = ('.csv', '.txt')
OBRIGATORIAS = ('Colaborador', 'TipoEvento', 'DataInicio', 'DataFim')

# Cabeçalho normalizado (sem acento, caixa e símbolos) -> coluna canônica.
# Titulo, QuantidadeDias e DataSolicitacao são lidos só para o CSV de linhas
# não importadas: na importação são derivados (criado_em = momento da carga).
ALIASES = {
    'titulo': 'Titulo',
    'colaborador': 'Colaborador',
    'tipoevento': 'TipoEvento',
    'tipo': 'TipoEvento',
    'datainicio': 'DataInicio',
    'inicio': 'DataInicio',
    'datafim': 'DataFim',
    'fim': 'DataFim',
    'quantidadedias': 'QuantidadeDias',
    'situacao': 'Situacao',
    'solicitacaoid': 'SolicitacaoID',
    'observacoes': 'Observacoes',
    'datasolicitacao': 'DataSolicitacao',
}

_RE_DATA_ISO = re.compile(r'(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?')
_RE_DATA_BR = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})(?:\s.*)?')


def limites():
    return {
        'arquivos': settings.CSV_IMPORTACAO_MAX_ARQUIVOS,
        'bytes': settings.CSV_IMPORTACAO_MAX_BYTES,
        'registros': settings.CSV_IMPORTACAO_MAX_REGISTROS,
    }


def normalizar_cabecalho(texto):
    return re.sub(r'[^a-z0-9]', '', normalizar_nome(texto))


def ler_data(texto, rotulo):
    """``(date, None)`` ou ``(None, mensagem)``. Aceita ISO (com sufixo de
    hora) e dd/mm/aaaa (dia e mês com 1 ou 2 dígitos); ano de 2000 a 2100."""
    texto = texto.strip()
    if not texto:
        return None, f'Informe a data de {rotulo}.'
    achado = _RE_DATA_ISO.fullmatch(texto)
    if achado:
        ano, mes, dia = map(int, achado.groups())
    else:
        achado = _RE_DATA_BR.fullmatch(texto)
        if not achado:
            return None, f'Data de {rotulo} inválida: "{texto}" (use AAAA-MM-DD ou DD/MM/AAAA).'
        dia, mes, ano = map(int, achado.groups())
    try:
        data = date(ano, mes, dia)
    except ValueError:
        return None, f'Data de {rotulo} inexistente: "{texto}".'
    if not ANO_MINIMO <= data.year <= ANO_MAXIMO:
        return None, f'Data de {rotulo} fora do intervalo: o ano deve estar entre {ANO_MINIMO} e {ANO_MAXIMO}.'
    return data, None


@dataclass
class RegistroLido:
    """Uma linha de dados do arquivo. ``brutos``: o texto lido em cada
    coluna canônica (sem o apóstrofo da neutralização), base do CSV de não
    importadas; os demais campos são interpretados a partir dele, e
    ``erros`` são os problemas da própria linha (datas, campos vazios)."""
    linha: int
    brutos: dict
    colaborador: str = ''
    tipo: str = ''
    situacao: str = ''
    solicitacao_id: str = ''
    observacoes: str = ''
    data_inicio: date | None = None
    data_fim: date | None = None
    erros: list = field(default_factory=list)

    @classmethod
    def interpretar(cls, linha, brutos):
        registro = cls(
            linha=linha,
            brutos={coluna: brutos.get(coluna, '') for coluna in COLUNAS},
            colaborador=colapsar_espacos(brutos.get('Colaborador')),
            tipo=colapsar_espacos(brutos.get('TipoEvento')),
            situacao=colapsar_espacos(brutos.get('Situacao')),
            solicitacao_id=(brutos.get('SolicitacaoID') or '').strip(),
            observacoes=(brutos.get('Observacoes') or '').strip(),
        )
        if not registro.colaborador:
            registro.erros.append('Colaborador não informado.')
        if not registro.tipo:
            registro.erros.append('Tipo não informado.')
        registro.data_inicio, erro_inicio = ler_data(brutos.get('DataInicio') or '', 'início')
        registro.data_fim, erro_fim = ler_data(brutos.get('DataFim') or '', 'fim')
        registro.erros.extend(erro for erro in (erro_inicio, erro_fim) if erro)
        if registro.data_inicio and registro.data_fim and registro.data_fim < registro.data_inicio:
            registro.erros.append('A data final é anterior à inicial.')
        return registro

    def para_json(self):
        return {'linha': self.linha, 'brutos': self.brutos}

    @classmethod
    def de_json(cls, dados):
        return cls.interpretar(dados['linha'], dados['brutos'])


@dataclass
class ArquivoLido:
    """Resultado da leitura de um arquivo. ``erro`` preenchido = arquivo
    recusado inteiro (os demais do envio seguem)."""
    nome: str
    codificacao: str = ''
    separador: str = ''
    registros: list = field(default_factory=list)
    erro: str = ''

    def para_json(self):
        return {
            'nome': self.nome, 'codificacao': self.codificacao, 'separador': self.separador,
            'erro': self.erro, 'registros': [registro.para_json() for registro in self.registros],
        }

    @classmethod
    def de_json(cls, dados):
        return cls(
            nome=dados['nome'], codificacao=dados['codificacao'], separador=dados['separador'],
            erro=dados['erro'], registros=[RegistroLido.de_json(r) for r in dados['registros']],
        )


def decodificar(conteudo):
    """``(texto, codificação)``: UTF-8 (com ou sem BOM) e, se não for,
    Windows-1252. ``(None, '')`` se nenhuma das duas servir."""
    try:
        texto = conteudo.decode('utf-8')
    except UnicodeDecodeError:
        pass
    else:
        if texto.startswith(BOM):
            return texto[1:], 'UTF-8 com BOM'
        return texto, 'UTF-8'
    try:
        return conteudo.decode('cp1252'), 'Windows-1252'
    except UnicodeDecodeError:
        return None, ''


def ler_conteudo(nome, conteudo, max_registros=None):
    """Lê um arquivo já carregado (``bytes``). Separador ``;`` ou ``,``
    detectado pelo cabeçalho (o mais frequente; empate = ``;``), aspas no
    padrão CSV (campo com separador ou quebra de linha). O número da linha é
    a posição do registro no arquivo, com o cabeçalho = 1. Registros
    totalmente vazios são descartados (mas contam na numeração)."""
    max_registros = max_registros or limites()['registros']
    arquivo = ArquivoLido(nome=nome)
    texto, arquivo.codificacao = decodificar(conteudo)
    if texto is None:
        arquivo.erro = 'Codificação não reconhecida: salve o arquivo em UTF-8 ou Windows-1252.'
        return arquivo
    if not texto.strip():
        arquivo.erro = 'O arquivo está vazio.'
        return arquivo

    primeira_linha = texto.splitlines()[0]
    arquivo.separador = ';' if primeira_linha.count(';') >= primeira_linha.count(',') else ','
    try:
        tabela = list(csv.reader(io.StringIO(texto, newline=''), delimiter=arquivo.separador, quotechar='"'))
    except csv.Error as erro:
        arquivo.erro = f'O arquivo não é um CSV válido ({erro}).'
        return arquivo

    indices = {}
    for indice, titulo in enumerate(tabela[0]):
        coluna = ALIASES.get(normalizar_cabecalho(titulo))
        if coluna and coluna not in indices:
            indices[coluna] = indice
    faltando = [coluna for coluna in OBRIGATORIAS if coluna not in indices]
    if faltando:
        arquivo.erro = f'Faltam as colunas obrigatórias: {", ".join(faltando)}.'
        return arquivo

    for posicao, valores in enumerate(tabela[1:], start=2):
        if not any(valor.strip() for valor in valores):
            continue
        if len(arquivo.registros) == max_registros:
            arquivo.registros = []
            arquivo.erro = f'O arquivo tem mais de {max_registros} registros: divida-o em arquivos menores.'
            return arquivo
        brutos = {}
        for coluna, indice in indices.items():
            valor = valores[indice] if indice < len(valores) else ''
            brutos[coluna] = desfazer_neutralizacao(valor) if coluna in COLUNAS_TEXTO else valor
        arquivo.registros.append(RegistroLido.interpretar(posicao, brutos))
    if not arquivo.registros:
        arquivo.erro = 'O arquivo não tem linhas de dados.'
    return arquivo


def ler_arquivos(enviados):
    """Lê os arquivos de um envio (objetos com ``name``, ``size`` e
    ``read()``, como os ``UploadedFile`` do Django) em ORDEM ALFABÉTICA do
    nome, que é a ordem da análise (a linha mais antiga vence). Cada arquivo
    fora dos limites (quantidade, extensão, tamanho, registros) volta com
    ``erro`` e sem registros; os demais seguem."""
    limite = limites()
    resultado = []
    for posicao, enviado in enumerate(sorted(enviados, key=lambda a: (a.name.lower(), a.name))):
        nome = enviado.name
        if posicao >= limite['arquivos']:
            erro = f'Ignorado: no máximo {limite["arquivos"]} arquivos por envio.'
        elif not nome.lower().endswith(EXTENSOES_ACEITAS):
            erro = 'Extensão não aceita: envie arquivos .csv ou .txt.'
        elif enviado.size > limite['bytes']:
            erro = f'Arquivo maior que {limite["bytes"] / (1024 * 1024):g} MB.'
        else:
            resultado.append(ler_conteudo(nome, enviado.read(), limite['registros']))
            continue
        resultado.append(ArquivoLido(nome=nome, erro=erro))
    return resultado
