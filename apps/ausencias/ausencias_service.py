"""Regras de negócio de ausências.

As views (etapa 5), o admin e a importação de CSV (etapa 6) só traduzem
entrada/saída; toda decisão fica aqui.
"""

import logging
import secrets
from dataclasses import dataclass, replace
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.ausencias.models import Ausencia, PeriodoAusencia, SituacaoAusencia, TipoAusencia
from apps.colaboradores.models import Colaborador

logger = logging.getLogger(__name__)

MAX_PERIODOS = 12
ANO_MINIMO = 2000
ANO_MAXIMO = 2100


@dataclass
class PeriodoInformado:
    """Um período como chega do formulário/importação.

    ``situacao`` ``None`` = a situação padrão. ``id``: o ``PeriodoAusencia``
    que esta linha altera (edição); ``None`` = período novo.
    """
    data_inicio: date | None
    data_fim: date | None
    situacao: SituacaoAusencia | None = None
    id: int | None = None


class ErroValidacaoAusencia(Exception):
    """Envio recusado. Os erros vêm separados para a tela mapear:

    - ``erros_gerais``: do envio todo (ex.: nenhum período, mais de 12);
    - ``erros_por_periodo``: ``{índice na lista enviada: [mensagens]}``;
    - ``erros_campos``: do cabeçalho, ``{'colaborador'|'tipo': [mensagens]}``.
    """

    def __init__(self, erros_gerais=None, erros_por_periodo=None, erros_campos=None):
        self.erros_gerais = list(erros_gerais or [])
        self.erros_por_periodo = {indice: list(msgs) for indice, msgs in (erros_por_periodo or {}).items()}
        self.erros_campos = {campo: list(msgs) for campo, msgs in (erros_campos or {}).items()}
        super().__init__(' '.join(self.mensagens()))

    def mensagens(self):
        """Todas as mensagens numa lista plana (períodos numerados a partir de 1)."""
        resultado = list(self.erros_gerais)
        for campo in self.erros_campos:
            resultado.extend(self.erros_campos[campo])
        for indice in sorted(self.erros_por_periodo):
            resultado.extend(f'Período {indice + 1}: {msg}' for msg in self.erros_por_periodo[indice])
        return resultado


class _Erros:
    """Acumula erros para levantar um único ``ErroValidacaoAusencia``."""

    def __init__(self):
        self.gerais, self.por_periodo, self.campos = [], {}, {}

    def geral(self, mensagem):
        self.gerais.append(mensagem)

    def periodo(self, indice, mensagem):
        self.por_periodo.setdefault(indice, []).append(mensagem)

    def campo(self, nome, mensagem):
        self.campos.setdefault(nome, []).append(mensagem)

    def levantar(self):
        if self.gerais or self.por_periodo or self.campos:
            raise ErroValidacaoAusencia(self.gerais, self.por_periodo, self.campos)


# ---------------------------------------------------------------------------
# Código (SolicitacaoID do CSV)
# ---------------------------------------------------------------------------
# Maiúsculas e dígitos sem os ambíguos 0, O, 1, I e L (31 símbolos).
ALFABETO_CODIGO = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
TAMANHO_CODIGO = 8
TENTATIVAS_CODIGO = 10


def gerar_codigo():
    """Código novo de 8 caracteres (``secrets``), ainda não usado por
    nenhuma ausência, inclusive excluídas. Com 31⁸ combinações a colisão é
    improvável; mesmo assim tenta até ``TENTATIVAS_CODIGO`` vezes e depois
    levanta ``RuntimeError``. A constraint ``unique`` segue como trava final.
    """
    for _ in range(TENTATIVAS_CODIGO):
        codigo = ''.join(secrets.choice(ALFABETO_CODIGO) for _ in range(TAMANHO_CODIGO))
        if not Ausencia.todos.filter(codigo=codigo).exists():
            return codigo
    raise RuntimeError(f'Não foi possível gerar um código de ausência único em {TENTATIVAS_CODIGO} tentativas.')


# ---------------------------------------------------------------------------
# Situação padrão
# ---------------------------------------------------------------------------
def situacao_padrao():
    """A situação marcada como padrão, ou ``None`` se não houver."""
    return SituacaoAusencia.objects.filter(padrao=True).first()


def validar_alteracao_situacao(atual, padrao, ativo):
    """Regras da situação padrão ao salvar uma situação. ``atual`` é a
    situação como está no banco (``None`` se nova); ``padrao``/``ativo`` são
    os valores pretendidos. ``ValidationError`` por campo.

    - a padrão não pode ficar inativa (nem nascer inativa);
    - a padrão não pode perder a flag: outra situação precisa assumir
      (marcar outra como padrão desmarca esta automaticamente).
    """
    erros = {}
    if padrao and not ativo:
        erros['ativo'] = 'A situação padrão não pode ser desativada. Marque outra situação como padrão antes.'
    if atual is not None and atual.padrao and not padrao:
        erros['padrao'] = (
            'Esta é a situação padrão. Para trocar, marque outra situação como '
            'padrão: esta será desmarcada automaticamente.'
        )
    if erros:
        raise ValidationError(erros)


def salvar_situacao(situacao, usuario):
    """Grava a situação com auditoria. Se ela vier marcada como padrão, a
    anterior é desmarcada na mesma transação (antes, por causa da constraint
    de padrão única)."""
    atual = SituacaoAusencia.objects.filter(pk=situacao.pk).first() if situacao.pk else None
    validar_alteracao_situacao(atual, situacao.padrao, situacao.ativo)
    with transaction.atomic():
        if situacao.padrao:
            _desmarcar_padrao(exceto=situacao)
        if situacao.pk is None:
            situacao.criado_por = usuario
        situacao.atualizado_por = usuario
        situacao.save()
    return situacao


def definir_situacao_padrao(situacao, usuario=None):
    """Torna ``situacao`` a padrão (desmarcando a anterior). Situação inativa
    não pode ser padrão (``ValidationError``)."""
    with transaction.atomic():
        situacao = SituacaoAusencia.objects.select_for_update().get(pk=situacao.pk)
        if not situacao.ativo:
            raise ValidationError('Situação inativa não pode ser a padrão. Ative-a antes.')
        if situacao.padrao:
            return situacao
        _desmarcar_padrao(exceto=situacao)
        situacao.padrao = True
        situacao.atualizado_por = usuario
        situacao.save(update_fields=['padrao', 'atualizado_por', 'atualizado_em'])
    logger.info('Situação padrão de ausência agora é "%s".', situacao.nome)
    return situacao


def _desmarcar_padrao(exceto):
    # select_for_update serializa duas trocas simultâneas de padrão.
    anteriores = SituacaoAusencia.objects.select_for_update().filter(padrao=True).exclude(pk=exceto.pk)
    for anterior in anteriores:
        anterior.padrao = False
        anterior.save(update_fields=['padrao', 'atualizado_em'])


# ---------------------------------------------------------------------------
# Sobreposição
# ---------------------------------------------------------------------------
def _fmt(data):
    return f'{data:%d/%m/%Y}'


def _cruzam(inicio_a, fim_a, inicio_b, fim_b):
    """Intervalos com fim INCLUSIVO: compartilhar um único dia já é cruzar;
    terminar dia 10 e começar dia 11 não é."""
    return inicio_a <= fim_b and inicio_b <= fim_a


def _datas_ok(periodo):
    return (
        periodo.data_inicio is not None and periodo.data_fim is not None
        and periodo.data_fim >= periodo.data_inicio
    )


def _conta(periodo):
    """Situação ``None`` conta (é a padrão, a ser resolvida por quem grava)."""
    situacao = getattr(periodo, 'situacao', None)
    return situacao is None or situacao.conta_como_ausencia


@dataclass(frozen=True)
class Conflito:
    """O período ``indice`` (da lista consultada) cruza ``periodo`` (gravado)."""
    indice: int
    periodo: PeriodoAusencia

    @property
    def mensagem(self):
        return (
            f'Sobrepõe {self.periodo.ausencia.tipo} já registrado de '
            f'{_fmt(self.periodo.data_inicio)} a {_fmt(self.periodo.data_fim)}.'
        )


def periodos_conflitantes(colaborador, periodos, excluir_ausencia=None):
    """Períodos GRAVADOS do ``colaborador`` que cruzam algum de ``periodos``.

    ``periodos``: qualquer objeto com ``data_inicio``, ``data_fim`` e
    ``situacao`` (``PeriodoInformado``, ``PeriodoAusencia``...). Linhas sem
    datas válidas ou cuja situação não conta como ausência são ignoradas.

    Do banco, considera só ausências não excluídas e situações que contam
    como ausência, de qualquer tipo; ``excluir_ausencia`` (a própria, na
    edição/restauração) fica fora. Devolve ``Conflito``s ordenados pelo
    índice e pela data.
    """
    candidatos = [(i, p) for i, p in enumerate(periodos) if _datas_ok(p) and _conta(p)]
    if not candidatos:
        return []
    cruza_algum = Q()
    for _, periodo in candidatos:
        cruza_algum |= Q(data_inicio__lte=periodo.data_fim, data_fim__gte=periodo.data_inicio)
    gravados = (
        PeriodoAusencia.objects
        .filter(cruza_algum)
        .filter(
            ausencia__colaborador=colaborador,
            ausencia__excluido_em__isnull=True,
            situacao__conta_como_ausencia=True,
        )
        .select_related('ausencia__tipo', 'situacao')
        .order_by('data_inicio', 'data_fim', 'pk')
    )
    if excluir_ausencia is not None:
        gravados = gravados.exclude(ausencia_id=excluir_ausencia.pk)
    gravados = list(gravados)
    return [
        Conflito(indice, gravado)
        for indice, periodo in candidatos
        for gravado in gravados
        if _cruzam(periodo.data_inicio, periodo.data_fim, gravado.data_inicio, gravado.data_fim)
    ]


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------
def _resolver_situacoes(periodos, erros):
    """Cópias dos períodos com a situação RECARREGADA do banco (``ativo`` e
    ``conta_como_ausencia`` atuais) e ``None`` trocado pela padrão."""
    situacoes = {s.pk: s for s in SituacaoAusencia.objects.all()}
    padrao = next((s for s in situacoes.values() if s.padrao), None)
    resolvidos = []
    for indice, periodo in enumerate(periodos):
        situacao = periodo.situacao
        if situacao is None:
            if padrao is None:
                erros.periodo(indice, 'Não há situação padrão definida: informe a situação.')
            situacao = padrao
        elif situacao.pk not in situacoes:
            erros.periodo(indice, 'Situação inexistente.')
            situacao = None
        else:
            situacao = situacoes[situacao.pk]
        resolvidos.append(replace(periodo, situacao=situacao))
    return resolvidos


def _validar_periodos(colaborador, periodos, excluir_ausencia, erros):
    """Regras dos períodos, acumulando em ``erros``. ``periodos`` já com as
    situações resolvidas."""
    if not periodos:
        erros.geral('Informe pelo menos um período.')
        return
    if len(periodos) > MAX_PERIODOS:
        erros.geral(f'No máximo {MAX_PERIODOS} períodos por registro (foram {len(periodos)}).')
        return

    validos = []  # índices com datas utilizáveis na checagem de sobreposição
    for indice, periodo in enumerate(periodos):
        mensagens = []
        if periodo.data_inicio is None:
            mensagens.append('Informe a data de início.')
        if periodo.data_fim is None:
            mensagens.append('Informe a data de fim.')
        datas = [data for data in (periodo.data_inicio, periodo.data_fim) if data is not None]
        if any(not ANO_MINIMO <= data.year <= ANO_MAXIMO for data in datas):
            mensagens.append(f'O ano deve estar entre {ANO_MINIMO} e {ANO_MAXIMO}.')
        if len(datas) == 2 and periodo.data_fim < periodo.data_inicio:
            mensagens.append('A data de fim deve ser igual ou posterior à de início.')
        for mensagem in mensagens:
            erros.periodo(indice, mensagem)
        if not mensagens:
            validos.append(indice)

    # Entre os períodos do próprio envio (só os que contam como ausência).
    for posicao, j in enumerate(validos):
        if not _conta(periodos[j]):
            continue
        for i in validos[:posicao]:
            a, b = periodos[i], periodos[j]
            if _conta(a) and _cruzam(a.data_inicio, a.data_fim, b.data_inicio, b.data_fim):
                erros.periodo(j, (
                    f'Sobrepõe o período {i + 1} deste registro '
                    f'({_fmt(a.data_inicio)} a {_fmt(a.data_fim)}).'
                ))

    # Com o que já está gravado.
    if colaborador is not None:
        consultados = [periodos[i] if i in validos else PeriodoInformado(None, None) for i in range(len(periodos))]
        for conflito in periodos_conflitantes(colaborador, consultados, excluir_ausencia):
            erros.periodo(conflito.indice, conflito.mensagem)


def validar_periodos(colaborador, periodos, excluir_ausencia=None):
    """Valida só os períodos (sem o cabeçalho) e levanta
    ``ErroValidacaoAusencia`` se houver erro:

    - de 1 a ``MAX_PERIODOS`` períodos;
    - datas obrigatórias, fim >= início, anos entre 2000 e 2100;
    - sem sobreposição entre os períodos do próprio envio nem com os
      gravados do colaborador (``periodos_conflitantes``), considerando só
      situações que contam como ausência.

    Situação ``None`` = a padrão. Devolve os períodos com a situação resolvida.
    """
    erros = _Erros()
    resolvidos = _resolver_situacoes(periodos, erros)
    _validar_periodos(colaborador, resolvidos, excluir_ausencia, erros)
    erros.levantar()
    return resolvidos


def validar_ausencia(colaborador, tipo, periodos, ausencia=None):
    """Valida um envio completo (cabeçalho + períodos). ``ausencia`` é o
    registro gravado, na edição (``None`` = registro novo).

    Além de ``validar_periodos``:
    - colaborador inativo não recebe ausência nova nem pode ser escolhido na
      edição; continuar com o mesmo (que ficou inativo) é permitido;
    - tipo inativo, idem;
    - situação inativa só é aceita num período já existente que a mantém;
    - ``PeriodoInformado.id`` precisa ser um período desta ausência.

    Levanta ``ErroValidacaoAusencia`` com todos os erros encontrados.
    Devolve os períodos com a situação resolvida.
    """
    erros = _Erros()
    if colaborador is None:
        erros.campo('colaborador', 'Informe o colaborador.')
    elif not colaborador.ativo and (ausencia is None or colaborador.pk != ausencia.colaborador_id):
        erros.campo('colaborador', 'Colaborador inativo não pode receber ausências.')
    if tipo is None:
        erros.campo('tipo', 'Informe o tipo de ausência.')
    elif not tipo.ativo and (ausencia is None or tipo.pk != ausencia.tipo_id):
        erros.campo('tipo', f'O tipo "{tipo}" está inativo.')

    existentes = {p.pk: p for p in ausencia.periodos.all()} if ausencia is not None else {}
    resolvidos = _resolver_situacoes(periodos, erros)
    vistos = set()
    for indice, periodo in enumerate(resolvidos):
        anterior = existentes.get(periodo.id)
        if periodo.id is not None:
            if anterior is None:
                erros.periodo(indice, 'Este período não pertence a este registro.')
            elif periodo.id in vistos:
                erros.periodo(indice, 'Período repetido no envio.')
            vistos.add(periodo.id)
        situacao = periodo.situacao
        mantida = anterior is not None and situacao is not None and anterior.situacao_id == situacao.pk
        if situacao is not None and not situacao.ativo and not mantida:
            erros.periodo(indice, f'A situação "{situacao}" está inativa.')

    _validar_periodos(colaborador, resolvidos, ausencia, erros)
    erros.levantar()
    return resolvidos


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------
# Ordem das travas, sempre a mesma para não haver deadlock: primeiro a linha
# da Ausencia (edição/exclusão/restauração), depois os Colaboradores, por pk.
# Travar o colaborador serializa os envios dele: a checagem de sobreposição
# só lê o banco depois que o envio concorrente gravou (READ COMMITTED).
def _travar_colaboradores(*ids):
    """``{pk: Colaborador}`` recarregados e travados (``select_for_update``)."""
    ids = {pk for pk in ids if pk is not None}
    return {c.pk: c for c in Colaborador.objects.select_for_update().filter(pk__in=ids).order_by('pk')}


def _travar_ausencia(ausencia):
    return Ausencia.todos.select_for_update().get(pk=ausencia.pk)


def _recarregar_tipo(tipo):
    return TipoAusencia.objects.filter(pk=tipo.pk).first() if tipo is not None else None


def _criar_periodo(ausencia, periodo, usuario):
    return PeriodoAusencia.objects.create(
        ausencia=ausencia,
        data_inicio=periodo.data_inicio,
        data_fim=periodo.data_fim,
        situacao=periodo.situacao,
        criado_por=usuario,
        atualizado_por=usuario,
    )


def criar_ausencia(colaborador, tipo, periodos, observacoes, usuario):
    """Registra uma ausência com seus períodos (``PeriodoInformado``, sem
    ``id``). Valida tudo (``validar_ausencia``) com o colaborador travado e
    grava numa transação: ou entra tudo, ou nada. Levanta
    ``ErroValidacaoAusencia``. Devolve a ``Ausencia`` criada.
    """
    pk_colaborador = colaborador.pk if colaborador is not None else None
    with transaction.atomic():
        colaborador = _travar_colaboradores(pk_colaborador).get(pk_colaborador)
        tipo = _recarregar_tipo(tipo)
        resolvidos = validar_ausencia(colaborador, tipo, periodos)
        ausencia = Ausencia.objects.create(
            colaborador=colaborador,
            tipo=tipo,
            observacoes=(observacoes or '').strip(),
            codigo=gerar_codigo(),
            criado_por=usuario,
            atualizado_por=usuario,
        )
        for periodo in resolvidos:
            _criar_periodo(ausencia, periodo, usuario)
    logger.info('Ausência %s registrada (%s, %d período(s)).', ausencia.codigo, ausencia.titulo, len(resolvidos))
    return ausencia


def atualizar_ausencia(ausencia, colaborador, tipo, periodos, observacoes, usuario):
    """Substitui o envio inteiro: cabeçalho e períodos.

    Reconciliação pelos ``PeriodoInformado.id``: com id, o período existente
    é alterado (e só ganha ``atualizado_por`` se algo mudou); sem id, é
    criado; os existentes que não vierem na lista são apagados. Situação
    ``None`` = a padrão. Ausência na lixeira não é editável (restaure antes).
    Levanta ``ErroValidacaoAusencia``. Devolve a ``Ausencia`` atualizada
    (instância nova, recarregada do banco).
    """
    with transaction.atomic():
        gravada = _travar_ausencia(ausencia)
        if gravada.esta_excluido:
            raise ErroValidacaoAusencia(['Este registro está na lixeira: restaure-o antes de editar.'])
        pk_colaborador = colaborador.pk if colaborador is not None else None
        colaborador = _travar_colaboradores(gravada.colaborador_id, pk_colaborador).get(pk_colaborador)
        tipo = _recarregar_tipo(tipo)
        resolvidos = validar_ausencia(colaborador, tipo, periodos, ausencia=gravada)

        existentes = {p.pk: p for p in gravada.periodos.all()}
        for periodo in resolvidos:
            if periodo.id is None:
                _criar_periodo(gravada, periodo, usuario)
                continue
            atual = existentes.pop(periodo.id)
            novo = (periodo.data_inicio, periodo.data_fim, periodo.situacao.pk)
            if (atual.data_inicio, atual.data_fim, atual.situacao_id) != novo:
                atual.data_inicio, atual.data_fim, atual.situacao = periodo.data_inicio, periodo.data_fim, periodo.situacao
                atual.atualizado_por = usuario
                atual.save()
        if existentes:
            PeriodoAusencia.objects.filter(pk__in=existentes).delete()

        gravada.colaborador = colaborador
        gravada.tipo = tipo
        gravada.observacoes = (observacoes or '').strip()
        gravada.atualizado_por = usuario
        gravada.save()
    logger.info('Ausência %s atualizada (%s, %d período(s)).', gravada.codigo, gravada.titulo, len(resolvidos))
    return gravada


def excluir_ausencia(ausencia, usuario):
    """Exclusão lógica (vai para a lixeira). Idempotente: se já estiver
    excluída, nada muda (mantém quando e quem excluiu primeiro)."""
    with transaction.atomic():
        gravada = _travar_ausencia(ausencia)
        if not gravada.esta_excluido:
            gravada.excluir(usuario)
            logger.info('Ausência %s excluída (lixeira).', gravada.codigo)
    return gravada


def restaurar_ausencia(ausencia, usuario):
    """Tira da lixeira, se os períodos ainda não conflitarem com o que foi
    registrado depois da exclusão; senão levanta ``ErroValidacaoAusencia``
    (conflitos por período, na ordem de ``ausencia.periodos``) e a ausência
    continua excluída. Idempotente se já estiver ativa.

    Colaborador, tipo ou situação que ficaram inativos não impedem: a
    ausência volta como era.
    """
    with transaction.atomic():
        gravada = _travar_ausencia(ausencia)
        if not gravada.esta_excluido:
            return gravada
        colaborador = _travar_colaboradores(gravada.colaborador_id)[gravada.colaborador_id]
        periodos = list(gravada.periodos.select_related('situacao'))
        erros = _Erros()
        for conflito in periodos_conflitantes(colaborador, periodos, excluir_ausencia=gravada):
            erros.periodo(conflito.indice, conflito.mensagem)
        if erros.por_periodo:
            erros.geral('Não é possível restaurar: há ausências registradas no mesmo período.')
        erros.levantar()
        gravada.restaurar()
        gravada.atualizado_por = usuario
        gravada.save(update_fields=['atualizado_por', 'atualizado_em'])
    logger.info('Ausência %s restaurada.', gravada.codigo)
    return gravada


def apagar_definitivamente(ausencia):
    """Apaga do banco a ausência e seus períodos. Só para o administrador (a
    checagem de perfil fica na view, etapa 5) e só para registro que já está
    na lixeira (``ErroValidacaoAusencia`` se não estiver). Devolve o código."""
    with transaction.atomic():
        gravada = _travar_ausencia(ausencia)
        if not gravada.esta_excluido:
            raise ErroValidacaoAusencia(['Só é possível apagar definitivamente um registro que está na lixeira.'])
        codigo = gravada.codigo
        gravada.delete()
    logger.info('Ausência %s apagada definitivamente.', codigo)
    return codigo
