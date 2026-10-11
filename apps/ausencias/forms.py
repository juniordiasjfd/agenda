"""Formulários de ausência.

Só traduzem a tela para ``PeriodoInformado`` e os erros do serviço de volta
para campos e linhas: as regras ficam em ``ausencias_service``.
"""

from datetime import datetime

from django import forms

from apps.ausencias import ausencias_service
from apps.ausencias.ausencias_service import ANO_MAXIMO, ANO_MINIMO, MAX_PERIODOS, PeriodoInformado
from apps.core.forms import TablerFormMixin


class CampoData(forms.DateInput):
    """``<input type="date">`` limitado aos anos aceitos pelo serviço."""
    input_type = 'date'

    def __init__(self, attrs=None):
        super().__init__(
            attrs={'min': f'{ANO_MINIMO}-01-01', 'max': f'{ANO_MAXIMO}-12-31', **(attrs or {})},
            format='%Y-%m-%d',
        )


class ColaboradorChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, colaborador):
        return colaborador.nome if colaborador.ativo else f'{colaborador.nome} (inativo)'


class NomeAtivoChoiceField(forms.ModelChoiceField):
    """Tipo/situação: marca o inativo que aparece só por já estar em uso."""

    def label_from_instance(self, objeto):
        return objeto.nome if objeto.ativo else f'{objeto.nome} (inativo)'


class CabecalhoAusenciaForm(TablerFormMixin, forms.Form):
    """Colaborador, tipo e observações. ``ausencia`` (edição) mantém nas
    opções o colaborador e o tipo atuais, mesmo se inativos.

    Na edição há também ``versao`` (oculto): o ``atualizado_em`` de quando a
    tela foi aberta. Se a ausência mudou desde então, o envio é recusado
    (trava otimista) sem perder o que foi digitado; o serviço repete a
    verificação com a ausência travada.
    """
    colaborador = ColaboradorChoiceField(queryset=None, label='Colaborador', empty_label='Selecione...')
    tipo = NomeAtivoChoiceField(queryset=None, label='Tipo', empty_label='Selecione...')
    observacoes = forms.CharField(label='Observações', required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, ausencia=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ausencia = ausencia
        self.fields['colaborador'].queryset = ausencias_service.colaboradores_para_escolha(ausencia)
        self.fields['tipo'].queryset = ausencias_service.tipos_para_escolha(ausencia)
        if ausencia is not None:
            self.fields['versao'] = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean(self):
        dados = super().clean()
        if self.ausencia is not None:
            try:
                dados['versao'] = datetime.fromisoformat(dados.get('versao') or '')
            except ValueError:
                dados['versao'] = None
            if dados['versao'] != self.ausencia.atualizado_em:
                self.add_error(None, ausencias_service.MENSAGEM_ALTERADA_POR_OUTRO)
        return dados


class PeriodoForm(TablerFormMixin, forms.Form):
    """Uma linha de período. Tudo opcional aqui: datas faltando, fim antes do
    início, ano fora do limite e sobreposição são mensagens do serviço."""
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    data_inicio = forms.DateField(label='Início', required=False, widget=CampoData())
    data_fim = forms.DateField(label='Fim', required=False, widget=CampoData())
    situacao = NomeAtivoChoiceField(queryset=None, label='Situação', required=False, empty_label=None)

    def __init__(self, *args, situacoes=None, situacao_padrao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['situacao'].queryset = situacoes
        if situacao_padrao is not None:
            self.fields['situacao'].initial = situacao_padrao.pk

    def tem_erro_de_campo(self):
        return any(self.has_error(nome) for nome in self.fields)


class BasePeriodoFormSet(forms.BaseFormSet):
    """Períodos de um envio. ``cabecalho`` é o ``CabecalhoAusenciaForm`` do
    mesmo envio; ``ausencia`` a registrada, na edição.

    O ``clean`` monta ``periodos_informados`` (linhas não removidas, na
    ordem da tela) e chama ``validar_ausencia``. Os índices dos erros do
    serviço são dessa lista, não do formset: ``linhas_enviadas[i]`` é o
    formulário do período ``i``.
    """
    default_error_messages = {
        'too_many_forms': f'No máximo {MAX_PERIODOS} períodos por registro.',
    }

    def __init__(self, *args, cabecalho=None, ausencia=None, **kwargs):
        self.cabecalho = cabecalho
        self.ausencia = ausencia
        self.periodos_informados = []
        self.linhas_enviadas = []
        super().__init__(*args, **kwargs)

    def removida(self, form):
        return self.can_delete and self.is_bound and self._should_delete_form(form)

    def linhas(self):
        """``(form, número exibido ou None se removida)`` para o template:
        as linhas não removidas são numeradas como o serviço as numera."""
        numero = 0
        for form in self.forms:
            if self.removida(form):
                yield form, None
            else:
                numero += 1
                yield form, numero

    def clean(self):
        super().clean()
        self.periodos_informados, self.linhas_enviadas = [], []
        for form in self.forms:
            if self.removida(form):
                continue
            dados = getattr(form, 'cleaned_data', {})
            self.periodos_informados.append(PeriodoInformado(
                data_inicio=dados.get('data_inicio'),
                data_fim=dados.get('data_fim'),
                situacao=dados.get('situacao'),
                id=dados.get('id'),
            ))
            self.linhas_enviadas.append(form)

        self.cabecalho.is_valid()
        dados_cabecalho = self.cabecalho.cleaned_data
        try:
            ausencias_service.validar_ausencia(
                dados_cabecalho.get('colaborador'),
                dados_cabecalho.get('tipo'),
                self.periodos_informados,
                ausencia=self.ausencia,
            )
        except ausencias_service.ErroValidacaoAusencia as erro:
            self.aplicar_erros(erro)

    def aplicar_erros(self, erro):
        """Distribui um ``ErroValidacaoAusencia``: cabeçalho nos campos,
        períodos nas linhas (pelo índice da lista enviada), gerais no topo
        dos períodos. Campo/linha que já tem erro do próprio formulário
        (ex.: campo vazio, data ilegível) não recebe a mensagem repetida do
        serviço."""
        for campo, mensagens in erro.erros_campos.items():
            if campo in self.cabecalho.fields and not self.cabecalho.has_error(campo):
                for mensagem in mensagens:
                    self.cabecalho.add_error(campo, mensagem)
        for indice, mensagens in erro.erros_por_periodo.items():
            form = self.linhas_enviadas[indice]
            if form.tem_erro_de_campo():
                continue
            for mensagem in mensagens:
                form.add_error(None, mensagem)
        self.non_form_errors().extend(erro.erros_gerais)


PeriodoFormSet = forms.formset_factory(
    PeriodoForm,
    formset=BasePeriodoFormSet,
    extra=0,
    can_delete=True,
    max_num=MAX_PERIODOS,
    validate_max=True,
)


def montar_formularios(data=None, ausencia=None, usuario=None):
    """Cabeçalho e formset de períodos, para o registro (``ausencia`` None)
    ou a edição. Sem ``data``, vêm preenchidos com a ausência (edição) ou
    com uma linha vazia e o colaborador vinculado ao usuário (registro)."""
    if ausencia is not None:
        inicial_cabecalho = {
            'colaborador': ausencia.colaborador_id,
            'tipo': ausencia.tipo_id,
            'observacoes': ausencia.observacoes,
            'versao': ausencia.atualizado_em.isoformat(),
        }
        inicial_periodos = [
            {'id': p.pk, 'data_inicio': p.data_inicio, 'data_fim': p.data_fim, 'situacao': p.situacao_id}
            for p in ausencia.periodos.all()
        ]
    else:
        vinculado = ausencias_service.colaborador_do_usuario(usuario) if usuario is not None else None
        inicial_cabecalho = {'colaborador': vinculado.pk} if vinculado else {}
        inicial_periodos = [{}]

    cabecalho = CabecalhoAusenciaForm(data, ausencia=ausencia, initial=inicial_cabecalho)
    periodos = PeriodoFormSet(
        data,
        prefix='periodos',
        # Com POST, o que vale é o enviado (as linhas podem ter mudado de posição).
        initial=inicial_periodos if data is None else None,
        cabecalho=cabecalho,
        ausencia=ausencia,
        form_kwargs={
            'situacoes': ausencias_service.situacoes_para_escolha(ausencia),
            'situacao_padrao': ausencias_service.situacao_padrao(),
        },
    )
    return cabecalho, periodos
