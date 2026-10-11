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
from datetime import date

from django.db.models import Exists, OuterRef, Q
from django.urls import reverse

from apps.ausencias.csv_service import ler_data
from apps.ausencias.models import PeriodoAusencia, TipoAusencia
from apps.colaboradores.colaboradores_service import SEM_DEPARTAMENTO
from apps.colaboradores.models import Colaborador
from apps.core.utils import normalizar_nome

TAMANHO_MAXIMO_BUSCA = 150


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
    - ``avisos``: filtros recusados (e ignorados), para mostrar na tela.
    """
    nome: str = ''
    departamentos: tuple = ()
    ausente: Intervalo | None = None
    presente: Intervalo | None = None
    sem_registros: bool = True
    avisos: list = field(default_factory=list)


def ler_filtros(q='', departamentos=(), ausente_de='', ausente_ate='', presente_de='', presente_ate='',
                sem_registros=None):
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


def montar_painel(filtros, hoje):
    """Pessoas filtradas com TODOS os seus períodos que contam como ausência
    (sem recorte pela janela visível: a navegação é no cliente), e a legenda
    (tipos ativos + tipos presentes nos períodos, mesmo inativos).
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
    return Painel(hoje=hoje, tipos=tipos, pessoas=pessoas, avisos=list(filtros.avisos))


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
    }
