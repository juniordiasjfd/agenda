from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils import timezone

from apps.usuarios.forms import UserAdminChangeForm, UserAdminCreationForm
from apps.usuarios.models import DominioAutocadastro, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm

    list_display = ('email', 'nome', 'is_active', 'is_staff', 'is_superuser', 'aprovado_em', 'last_login')
    list_filter = ('is_active', 'is_staff', 'is_superuser', 'groups')
    search_fields = ('email', 'nome')
    ordering = ('email',)
    readonly_fields = ('last_login', 'date_joined')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Dados pessoais', {'fields': ('nome',)}),
        ('Permissões', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Datas', {'fields': ('aprovado_em', 'last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'nome', 'usable_password', 'password1', 'password2'),
        }),
    )

    def save_model(self, request, obj, form, change):
        # Usuário criado ativo pelo admin já nasce aprovado (mesma regra do
        # UserManager).
        if not change and obj.is_active and obj.aprovado_em is None:
            obj.aprovado_em = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(DominioAutocadastro)
class DominioAutocadastroAdmin(admin.ModelAdmin):
    list_display = ('dominio', 'ativo', 'atualizado_em', 'atualizado_por')
    list_editable = ('ativo',)
    list_filter = ('ativo',)
    search_fields = ('dominio',)
    fields = ('dominio', 'ativo', 'criado_em', 'criado_por', 'atualizado_em', 'atualizado_por')
    readonly_fields = ('criado_em', 'criado_por', 'atualizado_em', 'atualizado_por')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.criado_por = request.user
        obj.atualizado_por = request.user
        super().save_model(request, obj, form, change)
