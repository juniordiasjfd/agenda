from django.contrib import admin

from apps.colaboradores.models import Colaborador, Departamento


class AuditoriaAdminMixin:
    readonly_fields = ('criado_em', 'criado_por', 'atualizado_em', 'atualizado_por')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.criado_por = request.user
        obj.atualizado_por = request.user
        super().save_model(request, obj, form, change)


@admin.register(Departamento)
class DepartamentoAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    list_display = ('nome', 'atualizado_em', 'atualizado_por')
    search_fields = ('nome',)
    fields = ('nome', 'criado_em', 'criado_por', 'atualizado_em', 'atualizado_por')


@admin.register(Colaborador)
class ColaboradorAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    list_display = ('nome', 'departamento', 'ativo', 'usuario')
    list_filter = ('ativo', 'departamento')
    search_fields = ('nome', 'nome_normalizado')
    list_select_related = ('departamento', 'usuario')
    autocomplete_fields = ('usuario',)
    fields = (
        'nome', 'departamento', 'ativo', 'usuario',
        'criado_em', 'criado_por', 'atualizado_em', 'atualizado_por',
    )

    def has_delete_permission(self, request, obj=None):
        # Colaborador nunca é apagado pela interface: desative-o.
        return False
