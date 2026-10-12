"""CSV de ausências: exportação, leitura, análise (prévia) e aplicação da
importação.

Formato compatível com o fluxo antigo (``legado/referencias/index.html``):
uma linha por período, separador ``;``, UTF-8 com BOM, CRLF. As views só
traduzem requisição/resposta; a regra de sobreposição é a de
``ausencias_service.conflitam`` (uma só para formulário, banco e lote).
"""

import csv
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.ausencias import ausencias_service
from apps.ausencias.ausencias_service import ANO_MAXIMO, ANO_MINIMO
from apps.ausencias.models import ImportacaoCSV, SituacaoAusencia, TipoAusencia
from apps.colaboradores import colaboradores_service
from apps.colaboradores.models import Colaborador
from apps.core.csv_utils import (
    BOM,
    decodificar,
    desfazer_neutralizacao,
    detectar_separador,
    neutralizar_formula,
)
from apps.core.utils import colapsar_espacos, normalizar_nome

logger = logging.getLogger(__name__)

COLUNAS = [
    'Titulo', 'Colaborador', 'TipoEvento', 'DataInicio', 'DataFim',
    'QuantidadeDias', 'Situacao', 'SolicitacaoID', 'Observacoes', 'DataSolicitacao',
]
# Campos de texto livre: os únicos neutralizados contra injeção de fórmula.
COLUNAS_TEXTO = ('Titulo', 'Colaborador', 'TipoEvento', 'Situacao', 'Observacoes')


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

    arquivo.separador = detectar_separador(texto)
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


# ---------------------------------------------------------------------------
# Análise = prévia (somente leitura)
# ---------------------------------------------------------------------------
IMPORTAR = 'importar'
DUPLICATA = 'duplicata'
SOBREPOSICAO = 'sobreposicao'
INVALIDA = 'invalida'
PENDENTE = 'pendente'
CATEGORIAS = (IMPORTAR, DUPLICATA, SOBREPOSICAO, INVALIDA, PENDENTE)
# Categorias que entram no CSV de linhas não importadas (duplicata não é erro).
NAO_IMPORTADAS = (SOBREPOSICAO, INVALIDA, PENDENTE)

ENTIDADES = ('colaboradores', 'tipos', 'situacoes')
ROTULO_ENTIDADE = {'colaboradores': 'colaborador', 'tipos': 'tipo', 'situacoes': 'situação'}
# Tamanho máximo do nome de quem pode ser criado pela importação.
TAMANHO_NOME = {'colaboradores': 150, 'tipos': 60, 'situacoes': 60}


@dataclass(frozen=True)
class NovoCadastro:
    """Colaborador, tipo ou situação que a importação vai criar (marcado
    pelo administrador). Nasce ativo; situação nova conta como ausência."""
    entidade: str
    chave: str
    nome: str
    ativo: bool = True
    conta_como_ausencia: bool = True
    pk = None

    def __str__(self):
        return self.nome


def _referencia(objeto):
    """Identidade estável de um cadastro existente ou a criar (assinatura,
    duplicata e ocupação da agenda)."""
    if isinstance(objeto, NovoCadastro):
        return f'novo:{objeto.entidade}:{objeto.chave}'
    return f'{type(objeto).__name__}:{objeto.pk}'


@dataclass
class LinhaAnalisada:
    """Um registro lido e o que a prévia decidiu sobre ele. Tem
    ``data_inicio``/``data_fim``/``situacao`` para entrar em
    ``ausencias_service.conflitam`` como qualquer período."""
    arquivo: str
    registro: RegistroLido
    categoria: str = ''
    motivo: str = ''
    colaborador: object = None
    tipo: object = None
    situacao: object = None

    @property
    def linha(self):
        return self.registro.linha

    @property
    def data_inicio(self):
        return self.registro.data_inicio

    @property
    def data_fim(self):
        return self.registro.data_fim

    @property
    def dias(self):
        return (self.data_fim - self.data_inicio).days + 1

    @property
    def onde(self):
        return f'{self.arquivo}, linha {self.linha}'

    def para_nao_importada(self):
        """Linha do CSV de não importadas: colunas canônicas com os valores
        lidos, mais motivo, arquivo e linha."""
        return {**self.registro.brutos, 'Motivo': self.motivo, 'Arquivo': self.arquivo, 'Linha': self.linha}


@dataclass
class GrupoImportacao:
    """Uma ausência a criar: linhas com o mesmo (SolicitacaoID, colaborador
    normalizado, tipo normalizado). ``codigo`` ``None`` = gerar um novo."""
    chave: tuple
    solicitacao_id: str
    colaborador: object
    tipo: object
    linhas: list = field(default_factory=list)
    codigo: str | None = None
    avisos: list = field(default_factory=list)
    nao_importadas: int = 0

    @property
    def observacoes(self):
        return next((linha.registro.observacoes for linha in self.linhas if linha.registro.observacoes), '')

    @property
    def parcial(self):
        return self.nao_importadas > 0


@dataclass
class Pendencia:
    """Cadastro que não existe: o administrador decide se a importação cria."""
    entidade: str
    chave: str
    nome: str
    linhas: int = 0
    marcada: bool = False

    @property
    def campo(self):
        return f'criar_{self.entidade}'


@dataclass
class Analise:
    arquivos: list
    decisoes: dict
    linhas: list = field(default_factory=list)
    grupos: list = field(default_factory=list)
    pendencias: dict = field(default_factory=dict)
    a_criar: dict = field(default_factory=dict)
    assinatura: str = ''

    def da_categoria(self, categoria):
        return [linha for linha in self.linhas if linha.categoria == categoria]

    @property
    def contagens(self):
        contagens = {categoria: 0 for categoria in CATEGORIAS}
        for linha in self.linhas:
            contagens[linha.categoria] += 1
        contagens['registros'] = len(self.linhas)
        contagens['ausencias'] = len(self.grupos)
        contagens['arquivos'] = len(self.arquivos)
        contagens['arquivos_recusados'] = sum(1 for arquivo in self.arquivos if arquivo.erro)
        for entidade in ENTIDADES:
            contagens[f'criar_{entidade}'] = len(self.a_criar.get(entidade, []))
        return contagens

    @property
    def tem_o_que_importar(self):
        return bool(self.grupos)

    @property
    def nao_importadas(self):
        return [linha for linha in self.linhas if linha.categoria in NAO_IMPORTADAS]

    def grupos_por_colaborador(self):
        """``[(nome do colaborador, [grupos])]`` em ordem de nome."""
        por_nome = {}
        for grupo in self.grupos:
            por_nome.setdefault(str(grupo.colaborador), []).append(grupo)
        return sorted(por_nome.items(), key=lambda item: normalizar_nome(item[0]))


def decisoes_do_formulario(dados):
    """Decisões vindas da tela (caixas ``criar_colaboradores`` etc.)."""
    return normalizar_decisoes({entidade: dados.getlist(f'criar_{entidade}') for entidade in ENTIDADES})


# Linhas exibidas por categoria na prévia; o resto vai pelo CSV de não importadas.
LIMITE_EXIBICAO = 500


def blocos_da_previa(analise, limite=LIMITE_EXIBICAO):
    """Listas da prévia, cada uma com no máximo ``limite`` linhas:
    ``categorias`` (sobreposições, inválidas, pendentes, duplicatas) e
    ``a_importar`` (``[(colaborador, [grupos])]``, cortado por linhas)."""
    titulos = [
        (SOBREPOSICAO, 'Sobreposições (não importadas)'),
        (INVALIDA, 'Inválidas (não importadas)'),
        (PENDENTE, 'Pendentes de cadastro (não importadas)'),
        (DUPLICATA, 'Duplicatas (ignoradas)'),
    ]
    categorias = []
    for categoria, titulo in titulos:
        linhas = analise.da_categoria(categoria)
        categorias.append({
            'categoria': categoria, 'titulo': titulo, 'total': len(linhas),
            'linhas': linhas[:limite], 'restante': max(len(linhas) - limite, 0),
        })
    a_importar, exibidas = [], 0
    for colaborador, grupos in analise.grupos_por_colaborador():
        if exibidas >= limite:
            break
        a_importar.append((colaborador, grupos))
        exibidas += sum(len(grupo.linhas) for grupo in grupos)
    return {
        'categorias': categorias,
        'a_importar': a_importar,
        'a_importar_restante': max(analise.contagens[IMPORTAR] - exibidas, 0),
    }


def normalizar_decisoes(decisoes):
    """``{'colaboradores'|'tipos'|'situacoes': [chaves normalizadas]}``,
    sem repetição e em ordem (o que fica guardado na ImportacaoCSV)."""
    decisoes = decisoes or {}
    return {
        entidade: sorted({normalizar_nome(nome) for nome in decisoes.get(entidade, []) if normalizar_nome(nome)})
        for entidade in ENTIDADES
    }


def _por_nome_normalizado(objetos):
    """``{nome normalizado: objeto}``. Se dois nomes só diferem em acento
    (a constraint do banco só ignora caixa), vale o ativo de menor pk."""
    mapa = {}
    for objeto in sorted(objetos, key=lambda o: (not o.ativo, o.pk)):
        mapa.setdefault(normalizar_nome(objeto.nome), objeto)
    return mapa


class _Cadastros:
    """Colaboradores, tipos e situações em memória (uma query cada) e a
    resolução de nomes, criando ``NovoCadastro`` para os marcados."""

    def __init__(self, registros, decisoes):
        chaves = {normalizar_nome(registro.colaborador) for registro in registros}
        self.existentes = {
            'colaboradores': {c.nome_normalizado: c for c in Colaborador.objects.filter(nome_normalizado__in=chaves)},
            'tipos': _por_nome_normalizado(TipoAusencia.objects.all()),
            'situacoes': _por_nome_normalizado(SituacaoAusencia.objects.all()),
        }
        self.padrao = next((s for s in self.existentes['situacoes'].values() if s.padrao), None)
        self.decisoes = decisoes
        self.pendencias = {entidade: {} for entidade in ENTIDADES}
        self.novos = {entidade: {} for entidade in ENTIDADES}

    def resolver(self, entidade, nome):
        """``(objeto, problema)``. ``objeto``: existente ativo ou
        ``NovoCadastro`` marcado; ``problema``: ``('invalida', msg)`` ou
        ``('pendente', msg)``."""
        rotulo = ROTULO_ENTIDADE[entidade]
        chave = normalizar_nome(nome)
        existente = self.existentes[entidade].get(chave)
        if existente is not None:
            if not existente.ativo:
                onde = 'no cadastro de colaboradores' if entidade == 'colaboradores' else 'no /admin/'
                return None, (INVALIDA, f'O {rotulo} "{existente.nome}" está inativo: reative-o {onde} para importar.')
            return existente, None
        if len(nome) > TAMANHO_NOME[entidade]:
            return None, (INVALIDA, f'Nome de {rotulo} com mais de {TAMANHO_NOME[entidade]} caracteres.')
        pendencia = self.pendencias[entidade].setdefault(
            chave, Pendencia(entidade, chave, nome, marcada=chave in self.decisoes[entidade]),
        )
        pendencia.linhas += 1
        if pendencia.marcada:
            return self.novos[entidade].setdefault(chave, NovoCadastro(entidade, chave, pendencia.nome)), None
        return None, (PENDENTE, f'{rotulo.capitalize()} "{pendencia.nome}" não cadastrado.')

    def resolver_situacao(self, nome):
        if nome:
            return self.resolver('situacoes', nome)
        if self.padrao is None:
            return None, (INVALIDA, 'Situação não informada e não há situação padrão definida.')
        return self.padrao, None


def _mensagem_lote(anterior):
    return (
        f'Sobrepõe {anterior.tipo} de {anterior.data_inicio:%d/%m/%Y} a {anterior.data_fim:%d/%m/%Y} '
        f'({anterior.onde}).'
    )


def _assinatura(grupos, a_criar):
    """Hash determinístico do plano: o que será criado e o que será
    importado (código mantido ou "gerar", cadastros, datas, situações e
    observações)."""
    plano = {
        'criar': {entidade: [novo.nome for novo in a_criar[entidade]] for entidade in ENTIDADES},
        'grupos': [
            [
                grupo.codigo or '', _referencia(grupo.colaborador), _referencia(grupo.tipo), grupo.observacoes,
                [[l.data_inicio.isoformat(), l.data_fim.isoformat(), _referencia(l.situacao)] for l in grupo.linhas],
            ]
            for grupo in grupos
        ],
    }
    texto = json.dumps(plano, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def analisar(arquivos, decisoes=None):
    """Classifica cada linha dos ``arquivos`` (``ArquivoLido``, já em ordem
    alfabética) SEM gravar nada. Precedência, linha a linha (arquivos na
    ordem, registros na ordem do arquivo; a linha mais antiga vence):

    1. inválida: problemas da própria linha (vazio, data, fim < início);
    2. cadastro: colaborador, tipo e situação pelo nome normalizado
       (situação vazia = padrão). Inativo = inválida; inexistente não
       marcado = pendente; marcado = será criado;
    3. duplicata exata (colaborador, tipo, início, fim) de ausência não
       excluída do banco ou de linha anterior a importar: ignorada;
    4. sobreposição (``ausencias_service.conflitam``) com o banco ou com
       linha anterior a importar: não importa;
    5. mais de ``MAX_PERIODOS`` no mesmo grupo: inválida.

    Agrupa por (SolicitacaoID, colaborador, tipo) e decide os códigos.
    Consultas ao banco em número fixo, independentemente do tamanho do lote.
    """
    decisoes = normalizar_decisoes(decisoes)
    analise = Analise(arquivos=arquivos, decisoes=decisoes)
    registros = [(arquivo.nome, registro) for arquivo in arquivos if not arquivo.erro for registro in arquivo.registros]
    cadastros = _Cadastros([registro for _, registro in registros], decisoes)

    colaboradores_ids = [c.pk for c in cadastros.existentes['colaboradores'].values()]
    duplicatas = set()   # (colaborador, tipo, início, fim) já no banco ou aceitos
    ocupados = {}        # colaborador -> períodos que contam (banco e aceitos)
    for periodo in ausencias_service.periodos_gravados(colaboradores_ids):
        colaborador = f'Colaborador:{periodo.ausencia.colaborador_id}'
        duplicatas.add((colaborador, f'TipoAusencia:{periodo.ausencia.tipo_id}', periodo.data_inicio, periodo.data_fim))
        if ausencias_service.conta_como_ausencia(periodo):
            ocupados.setdefault(colaborador, []).append(periodo)

    grupos = {}
    nao_importadas_por_chave = {}
    for nome_arquivo, registro in registros:
        linha = LinhaAnalisada(nome_arquivo, registro)
        analise.linhas.append(linha)
        chave_grupo = (
            registro.solicitacao_id or f'sem-id:{nome_arquivo}:{registro.linha}',
            normalizar_nome(registro.colaborador), normalizar_nome(registro.tipo),
        )
        _classificar(linha, cadastros, duplicatas, ocupados, grupos, chave_grupo)
        if linha.categoria != IMPORTAR:
            nao_importadas_por_chave[chave_grupo] = nao_importadas_por_chave.get(chave_grupo, 0) + 1

    analise.grupos = list(grupos.values())
    for grupo in analise.grupos:
        grupo.nao_importadas = nao_importadas_por_chave.get(grupo.chave, 0)
        if grupo.parcial:
            grupo.avisos.append(
                f'Importação parcial: {grupo.nao_importadas} linha(s) com o mesmo SolicitacaoID ficam de fora.'
            )
    _definir_codigos(analise.grupos)

    analise.pendencias = {
        entidade: list(cadastros.pendencias[entidade].values()) for entidade in ENTIDADES
    }
    # Só é criado o cadastro marcado que alguma linha a importar usa.
    usados = {
        _referencia(objeto)
        for grupo in analise.grupos
        for objeto in (grupo.colaborador, grupo.tipo, *(linha.situacao for linha in grupo.linhas))
    }
    analise.a_criar = {
        entidade: [novo for novo in cadastros.novos[entidade].values() if _referencia(novo) in usados]
        for entidade in ENTIDADES
    }
    analise.assinatura = _assinatura(analise.grupos, analise.a_criar)
    return analise


def _classificar(linha, cadastros, duplicatas, ocupados, grupos, chave_grupo):
    registro = linha.registro
    # 1. Problemas da própria linha.
    if registro.erros:
        linha.categoria, linha.motivo = INVALIDA, ' '.join(registro.erros)
        return

    # 2. Cadastros.
    linha.colaborador, problema_colaborador = cadastros.resolver('colaboradores', registro.colaborador)
    linha.tipo, problema_tipo = cadastros.resolver('tipos', registro.tipo)
    linha.situacao, problema_situacao = cadastros.resolver_situacao(registro.situacao)
    problemas = [p for p in (problema_colaborador, problema_tipo, problema_situacao) if p]
    if problemas:
        invalidos = [msg for categoria, msg in problemas if categoria == INVALIDA]
        if invalidos:
            linha.categoria, linha.motivo = INVALIDA, ' '.join(invalidos)
        else:
            linha.categoria, linha.motivo = PENDENTE, ' '.join(msg for _, msg in problemas)
        return

    # 3. Duplicata exata.
    colaborador = _referencia(linha.colaborador)
    chave_duplicata = (colaborador, _referencia(linha.tipo), linha.data_inicio, linha.data_fim)
    if chave_duplicata in duplicatas:
        linha.categoria, linha.motivo = DUPLICATA, 'Período já registrado (ignorado).'
        return

    # 4. Sobreposição: a regra única do serviço, contra o banco e o lote.
    for ocupado in ocupados.get(colaborador, []):
        if ausencias_service.conflitam(linha, ocupado):
            if isinstance(ocupado, LinhaAnalisada):
                linha.motivo = _mensagem_lote(ocupado)
            else:
                linha.motivo = ausencias_service.Conflito(0, ocupado).mensagem
            linha.categoria = SOBREPOSICAO
            return

    # 5. Limite de períodos por ausência.
    grupo = grupos.get(chave_grupo)
    if grupo is not None and len(grupo.linhas) >= ausencias_service.MAX_PERIODOS:
        linha.categoria = INVALIDA
        linha.motivo = (
            f'Excede {ausencias_service.MAX_PERIODOS} períodos na mesma ausência '
            f'(SolicitacaoID {registro.solicitacao_id}).'
        )
        return

    linha.categoria = IMPORTAR
    if grupo is None:
        grupo = grupos[chave_grupo] = GrupoImportacao(
            chave_grupo, registro.solicitacao_id, linha.colaborador, linha.tipo,
        )
    grupo.linhas.append(linha)
    duplicatas.add(chave_duplicata)
    if ausencias_service.conta_como_ausencia(linha):
        ocupados.setdefault(colaborador, []).append(linha)


def _definir_codigos(grupos):
    """SolicitacaoID vira o código se for válido e livre (no banco,
    inclusive lixeira, e entre os grupos do lote; o primeiro grupo fica com
    ele). Senão, o grupo recebe código novo na gravação, com aviso."""
    em_uso = ausencias_service.codigos_em_uso([g.solicitacao_id for g in grupos])
    usados_no_lote = set()
    for grupo in grupos:
        sid = grupo.solicitacao_id
        if not sid:
            continue
        problema = ausencias_service.problema_no_codigo(sid)
        if problema:
            grupo.avisos.append(f'SolicitacaoID "{sid}" não serve como código ({problema}): será gerado um novo.')
        elif sid.upper() in em_uso:
            grupo.avisos.append(f'O código {sid} já existe no sistema (inclusive lixeira): será gerado um novo.')
        elif sid.upper() in usados_no_lote:
            grupo.avisos.append(
                f'O SolicitacaoID {sid} aparece com outro colaborador ou tipo: este grupo recebe um código novo.'
            )
        else:
            grupo.codigo = sid
            usados_no_lote.add(sid.upper())


# ---------------------------------------------------------------------------
# Staging (ImportacaoCSV) e aplicação
# ---------------------------------------------------------------------------
# Cor de tipo criado pela importação; o administrador ajusta no /admin/.
COR_TIPO_NOVO = '#868e96'


class ImportacaoIndisponivel(Exception):
    """A importação não pode mais ser confirmada (aplicada, cancelada,
    expirada ou sem nada a importar). A mensagem vai para a tela."""


class PreviaDesatualizada(Exception):
    """A análise refeita na confirmação difere da prévia exibida: nada foi
    gravado. ``analise`` é a nova prévia."""

    def __init__(self, analise):
        super().__init__('Os dados mudaram desde a prévia: confira a nova prévia antes de confirmar.')
        self.analise = analise


class FalhaImportacao(Exception):
    """Erro inesperado na gravação: a transação foi desfeita inteira."""


def apagar_importacoes_antigas():
    """Remove as importações (de qualquer situação) com mais de
    ``ImportacaoCSV.RETENCAO``. Chamado a cada novo envio."""
    limite = timezone.now() - ImportacaoCSV.RETENCAO
    apagadas, _ = ImportacaoCSV.objects.filter(criado_em__lt=limite).delete()
    return apagadas


def criar_importacao(enviados, usuario):
    """Lê os arquivos enviados e guarda o resultado para a prévia."""
    apagar_importacoes_antigas()
    lidos = ler_arquivos(enviados)
    importacao = ImportacaoCSV.objects.create(
        arquivos=[arquivo.para_json() for arquivo in lidos], criado_por=usuario, atualizado_por=usuario,
    )
    logger.info(
        'Importação %s recebida: %d arquivo(s), %d registro(s).',
        importacao.pk, len(lidos), sum(len(arquivo.registros) for arquivo in lidos),
    )
    return importacao


def arquivos_da_importacao(importacao):
    return [ArquivoLido.de_json(dados) for dados in importacao.arquivos]


def analisar_importacao(importacao, decisoes=None):
    """Prévia com as ``decisoes`` informadas ou, sem elas, as guardadas."""
    return analisar(arquivos_da_importacao(importacao), importacao.decisoes if decisoes is None else decisoes)


def salvar_decisoes(importacao, decisoes, usuario):
    importacao.decisoes = normalizar_decisoes(decisoes)
    importacao.atualizado_por = usuario
    importacao.save(update_fields=['decisoes', 'atualizado_por', 'atualizado_em'])
    return importacao


def cancelar_importacao(importacao, usuario):
    """Descarta a importação pendente; as linhas lidas são apagadas já."""
    if importacao.status != ImportacaoCSV.PENDENTE:
        return importacao
    importacao.status = ImportacaoCSV.CANCELADA
    importacao.arquivos = []
    importacao.atualizado_por = usuario
    importacao.save(update_fields=['status', 'arquivos', 'atualizado_por', 'atualizado_em'])
    logger.info('Importação %s cancelada.', importacao.pk)
    return importacao


def verificar_disponivel(importacao):
    """``ImportacaoIndisponivel`` se a importação não está mais pendente."""
    if importacao.status == ImportacaoCSV.APLICADA:
        raise ImportacaoIndisponivel('Esta importação já foi aplicada.')
    if importacao.status == ImportacaoCSV.CANCELADA:
        raise ImportacaoIndisponivel('Esta importação foi cancelada. Envie os arquivos novamente.')
    if importacao.expirada:
        raise ImportacaoIndisponivel('A prévia expirou (mais de 2 horas). Envie os arquivos novamente.')


def _criar_cadastros(a_criar, usuario):
    """Cria os cadastros marcados. Devolve ``{referência: objeto criado}``."""
    criados = {}
    for novo in a_criar['colaboradores']:
        colaborador = Colaborador(nome=novo.nome, ativo=True, departamento=None)
        criados[_referencia(novo)] = colaboradores_service.salvar_colaborador(colaborador, usuario)
    ordem = (TipoAusencia.objects.aggregate(maior=Max('ordem'))['maior'] or 0)
    for novo in a_criar['tipos']:
        ordem += 1
        tipo = TipoAusencia(nome=novo.nome, cor=COR_TIPO_NOVO, ativo=True, ordem=ordem,
                            criado_por=usuario, atualizado_por=usuario)
        tipo.save()
        criados[_referencia(novo)] = tipo
    ordem = (SituacaoAusencia.objects.aggregate(maior=Max('ordem'))['maior'] or 0)
    for novo in a_criar['situacoes']:
        ordem += 1
        situacao = SituacaoAusencia(nome=novo.nome, ativo=True, ordem=ordem, padrao=False, conta_como_ausencia=True)
        criados[_referencia(novo)] = ausencias_service.salvar_situacao(situacao, usuario)
    return criados


def resumo_da_analise(analise, codigos=()):
    """O que fica guardado depois de aplicar (as linhas lidas são apagadas)."""
    return {
        'contagens': analise.contagens,
        'arquivos': [
            {'nome': a.nome, 'codificacao': a.codificacao, 'separador': a.separador,
             'registros': len(a.registros), 'erro': a.erro}
            for a in analise.arquivos
        ],
        'criados': {entidade: [novo.nome for novo in analise.a_criar[entidade]] for entidade in ENTIDADES},
        'codigos': list(codigos),
        'nao_importadas': [linha.para_nao_importada() for linha in analise.nao_importadas],
    }


def aplicar_importacao(importacao, decisoes, assinatura, usuario):
    """Grava a importação exatamente como a prévia mostrou, numa única
    transação:

    1. trava a importação e os colaboradores envolvidos (ordem de pk);
    2. refaz a análise com as ``decisoes`` enviadas;
    3. se a assinatura diferir da exibida (``assinatura``), não grava nada
       e levanta ``PreviaDesatualizada`` com a prévia nova;
    4. cria os cadastros marcados e cada ausência por
       ``ausencias_service.criar_ausencia`` (com o código decidido).

    Qualquer erro desfaz tudo (``FalhaImportacao``, registrado no log).
    Devolve a ``ImportacaoCSV`` aplicada, com o ``resumo``.
    """
    try:
        with transaction.atomic():
            importacao = ImportacaoCSV.objects.select_for_update().get(pk=importacao.pk)
            verificar_disponivel(importacao)
            arquivos = arquivos_da_importacao(importacao)
            nomes = {normalizar_nome(r.colaborador) for arquivo in arquivos for r in arquivo.registros}
            ausencias_service.travar_colaboradores(
                *Colaborador.objects.filter(nome_normalizado__in=nomes).values_list('pk', flat=True)
            )
            analise = analisar(arquivos, decisoes)
            if analise.assinatura != assinatura:
                raise PreviaDesatualizada(analise)
            if not analise.tem_o_que_importar:
                raise ImportacaoIndisponivel('Não há linhas a importar.')

            criados = _criar_cadastros(analise.a_criar, usuario)

            def real(objeto):
                return criados[_referencia(objeto)] if isinstance(objeto, NovoCadastro) else objeto

            codigos = []
            for grupo in analise.grupos:
                periodos = [
                    ausencias_service.PeriodoInformado(linha.data_inicio, linha.data_fim, real(linha.situacao))
                    for linha in grupo.linhas
                ]
                ausencia = ausencias_service.criar_ausencia(
                    real(grupo.colaborador), real(grupo.tipo), periodos, grupo.observacoes, usuario,
                    codigo=grupo.codigo,
                )
                codigos.append(ausencia.codigo)

            importacao.status = ImportacaoCSV.APLICADA
            importacao.aplicada_em = timezone.now()
            importacao.decisoes = analise.decisoes
            importacao.resumo = resumo_da_analise(analise, codigos)
            importacao.arquivos = []
            importacao.atualizado_por = usuario
            importacao.save()
    except (PreviaDesatualizada, ImportacaoIndisponivel):
        raise
    except Exception as erro:
        logger.exception('Falha ao aplicar a importação %s: nada foi gravado.', importacao.pk)
        raise FalhaImportacao('Erro ao gravar a importação: nada foi gravado.') from erro

    contagens = importacao.resumo['contagens']
    logger.info(
        'Importação %s aplicada: %d período(s) em %d ausência(s); %d duplicata(s), %d sobreposição(ões), '
        '%d inválida(s), %d pendente(s); criados %d colaborador(es), %d tipo(s), %d situação(ões).',
        importacao.pk, contagens[IMPORTAR], contagens['ausencias'], contagens[DUPLICATA],
        contagens[SOBREPOSICAO], contagens[INVALIDA], contagens[PENDENTE],
        contagens['criar_colaboradores'], contagens['criar_tipos'], contagens['criar_situacoes'],
    )
    return importacao


# ---------------------------------------------------------------------------
# CSV de linhas não importadas
# ---------------------------------------------------------------------------
COLUNAS_NAO_IMPORTADAS = [*COLUNAS, 'Motivo', 'Arquivo', 'Linha']


def csv_nao_importadas(linhas):
    """``linhas``: dicts de ``LinhaAnalisada.para_nao_importada`` (ou do
    ``resumo``). Mesmo formato da exportação, com Motivo, Arquivo e Linha
    no fim (ignoradas na reimportação)."""
    return escrever_csv(linhas, COLUNAS_NAO_IMPORTADAS)


def nome_arquivo_nao_importadas(importacao):
    return f'nao-importadas-{timezone.localtime(importacao.criado_em):%Y-%m-%d-%H%M}.csv'
