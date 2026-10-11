from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView

from apps.usuarios import usuarios_service
from apps.usuarios.forms import AutocadastroForm, LoginForm


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = 'usuarios/login.html'
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        # O link "Criar conta" só aparece com o autocadastro habilitado.
        kwargs['autocadastro_habilitado'] = usuarios_service.autocadastro_habilitado()
        return super().get_context_data(**kwargs)


# ---------------------------------------------------------------------------
# Autocadastro (público)
# ---------------------------------------------------------------------------
class CadastroView(FormView):
    form_class = AutocadastroForm
    template_name = 'usuarios/cadastro.html'
    success_url = reverse_lazy('usuarios:cadastro_recebido')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('core:home')
        if not usuarios_service.autocadastro_habilitado():
            return render(request, 'usuarios/cadastro_desabilitado.html')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # Mesmo redirecionamento com ou sem e-mail já cadastrado.
        usuarios_service.registrar_autocadastro(
            nome=form.cleaned_data['nome'],
            email=form.cleaned_data['email'],
            senha=form.cleaned_data['password1'],
        )
        return super().form_valid(form)


class CadastroRecebidoView(TemplateView):
    template_name = 'usuarios/cadastro_recebido.html'
