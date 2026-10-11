from django import forms

from apps.colaboradores.models import Departamento
from apps.core.forms import TablerFormMixin


class DepartamentoForm(TablerFormMixin, forms.ModelForm):
    """Nome duplicado (sem diferença de maiúsculas) é recusado no
    ``Departamento.clean``, com a mensagem no campo."""

    class Meta:
        model = Departamento
        fields = ['nome']
        widgets = {'nome': forms.TextInput(attrs={'autofocus': True})}
