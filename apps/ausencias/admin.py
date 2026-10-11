from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from apps.ausencias import ausencias_service
from apps.ausencias.models import SituacaoAusencia, TipoAusencia
from apps.colaboradores.admin import AuditoriaAdminMixin


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
