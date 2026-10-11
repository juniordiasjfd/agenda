from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.forms.models import BaseInlineFormSet

from apps.ausencias import ausencias_service
from apps.ausencias.models import Ausencia, ImportacaoCSV, PeriodoAusencia, SituacaoAusencia, TipoAusencia
from apps.colaboradores.admin import AuditoriaAdminMixin
from apps.colaboradores.models import Colaborador


@admin.register(TipoAusencia)
class TipoAusenciaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    list_display = ('nome', 'cor', 'ativo', 'ordem')
    list_editable = ('ativo', 'ordem')
    list_filter = ('ativo',)
    search_fields = ('nome',)
    fields = ('nome', 'cor', 'ativo', 'ordem', 'criado_em', 'criado_por', 'atualizado_em', 'atualizado_por')
    # Exclusão: o PROTECT de Ausencia.tipo bloqueia tipos em uso (o admin
    # mostra os registros que impedem). Em uso, desative.


class SituacaoAusenciaAdminForm(forms.ModelForm):
    class Meta:
        model = SituacaoAusencia
        fields = ('nome', 'ativo', 'ordem', 'padrao', 'conta_como_ausencia')

    def clean(self):
        cleaned_data = super().clean()
        atual = SituacaoAusencia.objects.filter(pk=self.instance.pk).first() if self.instance.pk else None
        try:
            ausencias_service.validar_alteracao_situacao(
                atual, cleaned_data.get('padrao', False), cleaned_data.get('ativo', False),
            )
        except ValidationError as erro:
            for campo, mensagens in erro.message_dict.items():
                self.add_error(campo, mensagens)
        return cleaned_data


@admin.register(SituacaoAusencia)
class SituacaoAusenciaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    form = SituacaoAusenciaAdminForm
    list_display = ('nome', 'ativo', 'ordem', 'padrao', 'conta_como_ausencia')
    list_filter = ('ativo', 'conta_como_ausencia')
    search_fields = ('nome',)
    fields = (
        'nome', 'ativo', 'ordem', 'padrao', 'conta_como_ausencia',
        'criado_em', 'criado_por', 'atualizado_em', 'atualizado_por',
    )
    actions = ['marcar_como_padrao']

    def save_model(self, request, obj, form, change):
        # Pelo serviço: marcar como padrão desmarca a anterior.
        ausencias_service.salvar_situacao(obj, request.user)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.padrao:
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        # Sem exclusão em massa: ela não passa pelo has_delete_permission(obj)
        # e apagaria a situação padrão.
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    @admin.action(description='Definir como situação padrão')
    def marcar_como_padrao(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Selecione exatamente uma situação.', messages.ERROR)
            return
        try:
            situacao = ausencias_service.definir_situacao_padrao(queryset.get(), request.user)
        except ValidationError as erro:
            self.message_user(request, ' '.join(erro.messages), messages.ERROR)
            return
        self.message_user(request, f'"{situacao.nome}" agora é a situação padrão.')


class PeriodoInlineFormSet(BaseInlineFormSet):
    """Valida o envio pelo serviço (mesmas regras da tela): sobreposição,
    limites, inativos. O admin já roda numa transação; o colaborador é
    travado como no serviço."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        ausencia = self.instance
        if ausencia.colaborador_id is None or ausencia.tipo_id is None:
            return  # o formulário do cabeçalho já tem erro
        formularios, periodos = [], []
        for form in self.forms:
            if self._should_delete_form(form) or (form.instance.pk is None and not form.has_changed()):
                continue
            formularios.append(form)
            periodos.append(ausencias_service.PeriodoInformado(
                form.cleaned_data.get('data_inicio'),
                form.cleaned_data.get('data_fim'),
                form.cleaned_data.get('situacao'),
                id=form.instance.pk,
            ))
        gravada = Ausencia.todos.filter(pk=ausencia.pk).first() if ausencia.pk else None
        colaborador = Colaborador.objects.select_for_update().get(pk=ausencia.colaborador_id)
        try:
            ausencias_service.validar_ausencia(colaborador, ausencia.tipo, periodos, ausencia=gravada)
        except ausencias_service.ErroValidacaoAusencia as erro:
            for indice, mensagens in erro.erros_por_periodo.items():
                formularios[indice].add_error(None, mensagens)
            gerais = erro.erros_gerais + [msg for msgs in erro.erros_campos.values() for msg in msgs]
            if gerais:
                raise ValidationError(gerais)


class PeriodoAusenciaInline(admin.TabularInline):
    model = PeriodoAusencia
    extra = 0
    min_num = 1
    max_num = ausencias_service.MAX_PERIODOS
    fields = ('data_inicio', 'data_fim', 'situacao', 'dias')
    readonly_fields = ('dias',)
    formset = PeriodoInlineFormSet

    @admin.display(description='Dias')
    def dias(self, obj):
        return obj.dias if obj.pk else '—'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'situacao':
            kwargs['initial'] = ausencias_service.situacao_padrao()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ExcluidaFilter(admin.SimpleListFilter):
    title = 'exclusão'
    parameter_name = 'excluida'

    def lookups(self, request, model_admin):
        return [('nao', 'Ativas'), ('sim', 'Na lixeira')]

    def queryset(self, request, queryset):
        if self.value() == 'nao':
            return queryset.filter(excluido_em__isnull=True)
        if self.value() == 'sim':
            return queryset.filter(excluido_em__isnull=False)
        return queryset


@admin.register(Ausencia)
class AusenciaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    list_display = ('codigo', 'colaborador', 'tipo', 'total_periodos', 'excluido_em', 'atualizado_em')
    list_filter = (ExcluidaFilter, 'tipo', 'colaborador__departamento')
    search_fields = ('codigo', 'colaborador__nome', 'colaborador__nome_normalizado', 'observacoes')
    list_select_related = ('colaborador', 'tipo')
    autocomplete_fields = ('colaborador',)
    inlines = [PeriodoAusenciaInline]
    readonly_fields = (
        'codigo', 'excluido_em', 'excluido_por',
        'criado_em', 'criado_por', 'atualizado_em', 'atualizado_por',
    )
    fields = (
        'codigo', 'colaborador', 'tipo', 'observacoes', 'excluido_em', 'excluido_por',
        'criado_em', 'criado_por', 'atualizado_em', 'atualizado_por',
    )

    def get_queryset(self, request):
        # Inclui as excluídas (na lixeira), para consulta e auditoria.
        return Ausencia.todos.select_related('colaborador', 'tipo').annotate(_total_periodos=Count('periodos'))

    @admin.display(description='Períodos', ordering='_total_periodos')
    def total_periodos(self, obj):
        return obj._total_periodos

    def has_delete_permission(self, request, obj=None):
        # Exclusão é lógica, pelo serviço (lixeira na etapa 5); o admin do
        # Django não apaga ausências, nem uma a uma nem em massa.
        return False

    def save_model(self, request, obj, form, change):
        if not obj.codigo:
            obj.codigo = ausencias_service.gerar_codigo()
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        periodos = formset.save(commit=False)
        for periodo in formset.deleted_objects:
            periodo.delete()
        for periodo in periodos:
            if periodo.pk is None:
                periodo.criado_por = request.user
            periodo.atualizado_por = request.user
            periodo.save()
        formset.save_m2m()


@admin.register(ImportacaoCSV)
class ImportacaoCSVAdmin(admin.ModelAdmin):
    """Só consulta: a importação é feita pela tela "Importar CSV"."""
    list_display = ('criado_em', 'status', 'criado_por', 'aplicada_em')
    list_filter = ('status',)
    fields = ('id', 'status', 'criado_em', 'criado_por', 'aplicada_em', 'decisoes', 'resumo')
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
