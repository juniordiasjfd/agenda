from django import forms

from apps.colaboradores import colaboradores_service
from apps.colaboradores.models import Colaborador, Departamento
from apps.core.forms import TablerFormMixin


class DepartamentoForm(TablerFormMixin, forms.ModelForm):
    """Nome duplicado (sem diferença de maiúsculas) é recusado no
    ``Departamento.clean``, com a mensagem no campo."""

    class Meta:
        model = Departamento
        fields = ['nome']
        widgets = {'nome': forms.TextInput(attrs={'autofocus': True})}


class UsuarioChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, usuario):
        return f'{usuario.nome} ({usuario.email})' if usuario.nome else usuario.email


class ColaboradorForm(TablerFormMixin, forms.ModelForm):
    """Nome duplicado (mesmo ``nome_normalizado``) é recusado no
    ``Colaborador.clean``. O usuário vinculado só pode ser um usuário ativo
    ainda sem colaborador (ou o já vinculado, na edição)."""

    class Meta:
        model = Colaborador
        fields = ['nome', 'departamento', 'ativo', 'usuario']
        field_classes = {'usuario': UsuarioChoiceField}
        widgets = {'nome': forms.TextInput(attrs={'autofocus': True})}
        help_texts = {
            'ativo': 'Inativo some do formulário de ausências e do painel; o histórico permanece.',
            'usuario': 'Opcional. Só aparecem usuários ativos que ainda não têm colaborador.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['departamento'].empty_label = 'Sem departamento'
        self.fields['usuario'].empty_label = 'Nenhum'
        self.fields['usuario'].queryset = colaboradores_service.usuarios_vinculaveis(self.instance.usuario)


class FiltroColaboradoresForm(TablerFormMixin, forms.Form):
    """Filtros da lista (GET). Valor inválido cai no padrão."""
    SITUACOES = [
        (colaboradores_service.SITUACAO_ATIVOS, 'Ativos'),
        (colaboradores_service.SITUACAO_INATIVOS, 'Inativos'),
        (colaboradores_service.SITUACAO_TODOS, 'Todos'),
    ]

    busca = forms.CharField(
        label='Nome', required=False, max_length=150,
        widget=forms.TextInput(attrs={'placeholder': 'Buscar por nome', 'type': 'search'}),
    )
    departamento = forms.ChoiceField(label='Departamento', required=False)
    situacao = forms.ChoiceField(label='Situação', required=False, choices=SITUACOES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['departamento'].choices = [
            ('', 'Todos'),
            (colaboradores_service.SEM_DEPARTAMENTO, 'Sem departamento'),
            *((str(d.pk), d.nome) for d in Departamento.objects.all()),
        ]

    def filtros(self):
        """Valores para ``colaboradores_service.filtrar_colaboradores``."""
        dados = self.cleaned_data if self.is_valid() else {}
        return {
            'busca': dados.get('busca', ''),
            'departamento': dados.get('departamento', ''),
            'situacao': dados.get('situacao') or colaboradores_service.SITUACAO_ATIVOS,
        }
