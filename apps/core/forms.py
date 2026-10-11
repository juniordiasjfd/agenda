from django import forms


class TablerFormMixin:
    """Aplica as classes CSS do Tabler aos widgets do formulário."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                classe = 'form-check-input'
            elif isinstance(widget, forms.Select):
                classe = 'form-select'
            else:
                classe = 'form-control'
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {classe}".strip()
