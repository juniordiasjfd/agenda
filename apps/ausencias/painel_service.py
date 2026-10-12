"""Regras do painel Gantt: quem aparece e com quais períodos.

Fonte única dos filtros do painel (página e endpoint JSON). O JavaScript só
desenha o que vem daqui.

Critério de ausência = o mesmo da sobreposição (``ausencias_service``):
período de ausência NÃO excluída cuja situação conta como ausência
(``conta_como_ausencia``), com intervalos de fim inclusivo (``cruzam``).
Aqui ele é expresso em queryset (``_periodos_que_contam`` e ``_cruzando``);
``test_painel_service`` compara o resultado com as funções puras.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Exists, OuterRef, Q
from django.urls import reverse

from apps.ausencias.csv_service import ler_data
from apps.ausencias.models import PeriodoAusencia, TipoAusencia
from apps.colaboradores.colaboradores_service import SEM_DEPARTAMENTO
from apps.colaboradores.models import Colaborador, Departamento
from apps.core.utils import normalizar_nome

TAMANHO_MAXIMO_BUSCA = 150
HORAS_POR_DIA_UTIL = 8


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Intervalo:
    """Dias de ``de`` a ``ate``, ambos inclusivos (``de <= ate``)."""
    de: date
    ate: date


@dataclass
class FiltrosPainel:
    """Filtros já validados.

    - ``nome``: trecho do nome (comparado sem acento, caixa e espaços duplos);
    - ``departamentos``: ids e/ou ``SEM_DEPARTAMENTO``; vazio = todos
      (inclusive os criados depois). Vários = união;
    - ``ausente``: quem tem algum período cruzando o intervalo;
    - ``presente``: quem NÃO tem nenhum período cruzando o intervalo;
    - ``sem_registros``: incluir quem não tem nenhum período que conte como
      ausência. Desmarcado, só aparece quem tem pelo menos um (mesmo com
      ``presente``, como no legado).
    - ``capacidade``: intervalo para calcular a capacidade disponível das
      pessoas filtradas (não muda quem aparece);
    - ``avisos``: filtros recusados (e ignorados), para mostrar na tela.
    """
    nome: str = ''
    departamentos: tuple = ()
    ausente: Intervalo | None = None
    presente: Intervalo | None = None
    sem_registros: bool = True
    capacidade: Intervalo | None = None
    avisos: list = field(default_factory=list)


def ler_filtros(q='', departamentos=(), ausente_de='', ausente_ate='', presente_de='', presente_ate='',
                sem_registros=None, capacidade_de='', capacidade_ate=''):
    """``FiltrosPainel`` a partir dos textos da querystring. Nada aqui
    levanta erro: valor inválido é ignorado e vira aviso.

    ``sem_registros``: ``'0'`` desmarca; ausente (``None``/vazio) ou qualquer
    outro valor = marcado (o padrão).
    """
    avisos = []
    return FiltrosPainel(
        nome=normalizar_nome((q or '')[:TAMANHO_MAXIMO_BUSCA]),
        departamentos=_ler_departamentos(departamentos, avisos),
        ausente=_ler_intervalo(ausente_de, ausente_ate, 'Ausência em', avisos),
        presente=_ler_intervalo(presente_de, presente_ate, 'Presença em', avisos),
        sem_registros=(sem_registros or '').strip() != '0',
        capacidade=_ler_intervalo(capacidade_de, capacidade_ate, 'Capacidade em', avisos),
        avisos=avisos,
    )


def _ler_departamentos(valores, avisos):
    escolhidos = []
    for valor in valores:
        valor = (valor or '').strip()
        if valor == SEM_DEPARTAMENTO:
            escolhido = SEM_DEPARTAMENTO
        elif valor.isdigit() and int(valor) > 0:
            escolhido = int(valor)
        else:
            if valor:
                avisos.append(f'Departamento inválido ignorado: "{valor[:30]}".')
            continue
        if escolhido not in escolhidos:
            escolhidos.append(escolhido)
    return tuple(escolhidos)


def _ler_intervalo(texto_de, texto_ate, rotulo, avisos):
    """Intervalo inclusivo. Só uma data = aquele dia; datas invertidas são
    trocadas (como no legado). Data inválida ou fora de 2000–2100: o filtro
    inteiro é ignorado, com aviso."""
    textos = [(texto or '').strip() for texto in (texto_de, texto_ate)]
    if not any(textos):
        return None
    datas = []
    for texto, ponta in zip(textos, ('de', 'até')):
        if not texto:
            continue
        data, erro = ler_data(texto, f'"{rotulo}" ({ponta})')
        if erro:
            avisos.append(f'{erro} O filtro "{rotulo}" foi ignorado.')
            return None
        datas.append(data)
    return Intervalo(min(datas), max(datas))


# ---------------------------------------------------------------------------
# Opções do formulário de filtros
# ---------------------------------------------------------------------------
def departamentos_para_escolha():
    """Todos os departamentos, por nome ("Sem departamento" vai no fim, na
    tela)."""
    return Departamento.objects.all()


def rotulo_departamentos(escolhidos, departamentos):
    """Resumo do botão da multisseleção: "Todos", o nome do único escolhido
    ("Sem departamento" inclusive) ou "N departamentos". ``escolhidos``: os
    de ``FiltrosPainel.departamentos``; ids sem departamento existente não
    contam. O painel.js repete este texto ao marcar/desmarcar."""
    nomes = {d.pk: d.nome for d in departamentos}
    validos = [valor for valor in escolhidos if valor == SEM_DEPARTAMENTO or valor in nomes]
    if not validos:
        return 'Todos'
    if len(validos) == 1:
        return 'Sem departamento' if validos[0] == SEM_DEPARTAMENTO else nomes[validos[0]]
    return f'{len(validos)} departamentos'


# ---------------------------------------------------------------------------
# Critério de ausência em queryset
# ---------------------------------------------------------------------------
def _periodos_que_contam():
    """Períodos de ausências não excluídas cuja situação conta como
    ausência: ``conta_como_ausencia`` em SQL (no banco a situação nunca é
    nula)."""
    return PeriodoAusencia.objects.filter(ausencia__excluido_em__isnull=True, situacao__conta_como_ausencia=True)


def _cruzando(periodos, intervalo):
    """``cruzam(p.data_inicio, p.data_fim, intervalo.de, intervalo.ate)`` em
    SQL: início <= fim do outro e fim >= início do outro (fim inclusivo)."""
    return periodos.filter(data_inicio__lte=intervalo.ate, data_fim__gte=intervalo.de)


def colaboradores_filtrados(filtros):
    """Colaboradores ATIVOS que atendem aos filtros, com departamento, em
    ordem de nome (sem acento/caixa). Uma query."""
    colaboradores = Colaborador.objects.filter(ativo=True)
    if filtros.nome:
        colaboradores = colaboradores.filter(nome_normalizado__contains=filtros.nome)
    if filtros.departamentos:
        ids = [valor for valor in filtros.departamentos if valor != SEM_DEPARTAMENTO]
        escolha = Q(departamento_id__in=ids)
        if SEM_DEPARTAMENTO in filtros.departamentos:
            escolha |= Q(departamento__isnull=True)
        colaboradores = colaboradores.filter(escolha)

    do_colaborador = _periodos_que_contam().filter(ausencia__colaborador=OuterRef('pk'))
    if filtros.ausente is not None:
        colaboradores = colaboradores.filter(Exists(_cruzando(do_colaborador, filtros.ausente)))
    if filtros.presente is not None:
        colaboradores = colaboradores.filter(~Exists(_cruzando(do_colaborador, filtros.presente)))
    if not filtros.sem_registros:
        colaboradores = colaboradores.filter(Exists(do_colaborador))
    return colaboradores.select_related('departamento').order_by('nome_normalizado', 'pk')


# ---------------------------------------------------------------------------
# Capacidade
# ---------------------------------------------------------------------------
def dias_uteis(de, ate):
    """Dias de segunda a sexta de ``de`` a ``ate`` (inclusivos); 0 se
    ``ate < de``. Feriados não são descontados."""
    if ate < de:
        return 0
    semanas, resto = divmod((ate - de).days + 1, 7)
    return semanas * 5 + sum(1 for i in range(resto) if (de + timedelta(days=i)).weekday() < 5)


def dias_uteis_ausente(periodos, intervalo):
    """Dias úteis do ``intervalo`` cobertos por algum dos ``periodos``
    (objetos com ``inicio`` e ``fim`` inclusivos). Dia coberto por mais de um
    período conta uma vez só."""
    recortes = sorted(
        (max(p.inicio, intervalo.de), min(p.fim, intervalo.ate))
        for p in periodos
        if p.inicio <= intervalo.ate and p.fim >= intervalo.de
    )
    uteis = 0
    atual = None
    for inicio, fim in recortes:
        if atual and inicio <= atual[1] + timedelta(days=1):
            atual = (atual[0], max(atual[1], fim))
            continue
        if atual:
            uteis += dias_uteis(*atual)
        atual = (inicio, fim)
    if atual:
        uteis += dias_uteis(*atual)
    return uteis


@dataclass(frozen=True)
class Capacidade:
    """Capacidade das pessoas do painel no intervalo: cada pessoa vale
    ``HORAS_POR_DIA_UTIL`` horas por dia útil; dia útil com ausência que
    conta não está disponível. ``percentual`` é ``None`` sem horas totais."""
    intervalo: Intervalo
    pessoas: int
    dias_uteis: int
    total_horas: int
    disponivel_horas: int

    @property
    def percentual(self):
        if not self.total_horas:
            return None
        return self.disponivel_horas * 100 / self.total_horas

    @property
    def texto(self):
        """Ex.: "Capacidade disponível: 240 / 360 horas (66,7%)"."""
        percentual = '—' if self.percentual is None else f'{_numero(self.percentual, 1)}%'
        return (f'Capacidade disponível: {_numero(self.disponivel_horas)} / {_numero(self.total_horas)} horas '
                f'({percentual})')

    @property
    def detalhe(self):
        pessoas = '1 colaborador' if self.pessoas == 1 else f'{_numero(self.pessoas)} colaboradores'
        dias = '1 dia útil' if self.dias_uteis == 1 else f'{_numero(self.dias_uteis)} dias úteis'
        return (f'De {self.intervalo.de:%d/%m/%Y} a {self.intervalo.ate:%d/%m/%Y}: {pessoas} × {dias} × '
                f'{HORAS_POR_DIA_UTIL} h (segunda a sexta; feriados não descontados).')


def _numero(valor, casas=0):
    """Número em pt-BR (milhar com ponto, decimal com vírgula); sem casas
    decimais quando o valor arredondado é inteiro."""
    valor = round(valor, casas)
    if valor == int(valor):
        casas = 0
    return f'{valor:,.{casas}f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def calcular_capacidade(pessoas, intervalo):
    """``Capacidade`` das ``pessoas`` (``PessoaPainel`` com os períodos que
    contam como ausência) no ``intervalo``. Sem queries."""
    uteis = dias_uteis(intervalo.de, intervalo.ate)
    total = len(pessoas) * uteis * HORAS_POR_DIA_UTIL
    ausente = sum(dias_uteis_ausente(pessoa.periodos, intervalo) for pessoa in pessoas) * HORAS_POR_DIA_UTIL
    return Capacidade(intervalo, len(pessoas), uteis, total, total - ausente)


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TipoPainel:
    id: int
    nome: str
    cor: str


@dataclass(frozen=True)
class PeriodoPainel:
    inicio: date
    fim: date
    dias: int
    tipo_id: int
    situacao: str
    ausencia_id: int


@dataclass
class PessoaPainel:
    id: int
    nome: str
    departamento: str | None
    periodos: list = field(default_factory=list)


@dataclass
class Painel:
    hoje: date
    tipos: list
    pessoas: list
    avisos: list
    capacidade: Capacidade | None = None


def montar_painel(filtros, hoje):
    """Pessoas filtradas com TODOS os seus períodos que contam como ausência
    (sem recorte pela janela visível: a navegação é no cliente), e a legenda
    (tipos ativos + tipos presentes nos períodos, mesmo inativos). Com o
    filtro ``capacidade``, calcula a capacidade das pessoas filtradas.
    Três queries, independentemente do volume."""
    # Ordem em Python: a collation do banco pode ignorar espaços ("ana b" x
    # "anab"); nome_normalizado já está sem acento e em minúsculas.
    colaboradores = sorted(colaboradores_filtrados(filtros), key=lambda c: (c.nome_normalizado, c.pk))
    pessoas = [
        PessoaPainel(c.pk, c.nome, c.departamento.nome if c.departamento_id else None)
        for c in colaboradores
    ]
    por_id = {pessoa.id: pessoa for pessoa in pessoas}

    periodos = (
        _periodos_que_contam()
        .filter(ausencia__colaborador_id__in=list(por_id))
        .select_related('ausencia', 'situacao')
        .order_by('data_inicio', 'data_fim', 'pk')
    ) if por_id else []
    tipos_presentes = set()
    for periodo in periodos:
        tipos_presentes.add(periodo.ausencia.tipo_id)
        por_id[periodo.ausencia.colaborador_id].periodos.append(PeriodoPainel(
            inicio=periodo.data_inicio,
            fim=periodo.data_fim,
            dias=periodo.dias,
            tipo_id=periodo.ausencia.tipo_id,
            situacao=periodo.situacao.nome,
            ausencia_id=periodo.ausencia_id,
        ))

    tipos = [
        TipoPainel(tipo.pk, tipo.nome, tipo.cor)
        for tipo in TipoAusencia.objects.filter(Q(ativo=True) | Q(pk__in=tipos_presentes)).order_by('ordem', 'nome')
    ]
    capacidade = calcular_capacidade(pessoas, filtros.capacidade) if filtros.capacidade else None
    return Painel(hoje=hoje, tipos=tipos, pessoas=pessoas, avisos=list(filtros.avisos), capacidade=capacidade)


def capacidade_para_json(capacidade):
    """Capacidade do endpoint (``None`` sem o filtro). ``texto`` e
    ``detalhe`` já vêm formatados: o painel.js só os mostra."""
    if capacidade is None:
        return None
    return {
        'de': capacidade.intervalo.de.isoformat(),
        'ate': capacidade.intervalo.ate.isoformat(),
        'pessoas': capacidade.pessoas,
        'dias_uteis': capacidade.dias_uteis,
        'total_horas': capacidade.total_horas,
        'disponivel_horas': capacidade.disponivel_horas,
        'percentual': None if capacidade.percentual is None else round(capacidade.percentual, 1),
        'texto': capacidade.texto,
        'detalhe': capacidade.detalhe,
    }


def painel_para_json(painel):
    """Dicionário do endpoint ``painel/dados/`` (datas ISO). Observações e
    outros campos que o desenho não usa ficam de fora."""
    return {
        'hoje': painel.hoje.isoformat(),
        'tipos': [{'id': t.id, 'nome': t.nome, 'cor': t.cor} for t in painel.tipos],
        'pessoas': [
            {
                'id': pessoa.id,
                'nome': pessoa.nome,
                'departamento': pessoa.departamento,
                'periodos': [
                    {
                        'inicio': p.inicio.isoformat(),
                        'fim': p.fim.isoformat(),
                        'dias': p.dias,
                        'tipo_id': p.tipo_id,
                        'situacao': p.situacao,
                        'url': reverse('ausencias:detalhe', args=[p.ausencia_id]),
                    }
                    for p in pessoa.periodos
                ],
            }
            for pessoa in painel.pessoas
        ],
        'avisos': painel.avisos,
        'capacidade': capacidade_para_json(painel.capacidade),
    }
