from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.core.permissions import GestorMixin


class AusenciasView(LoginRequiredMixin, TemplateView):
    template_name = 'ausencias/em_construcao.html'
    extra_context = {'active_nav': 'ausencias', 'titulo': 'Ausências'}


class AusenciaCriarView(GestorMixin, TemplateView):
    template_name = 'ausencias/em_construcao.html'
    extra_context = {'active_nav': 'registrar', 'titulo': 'Registrar ausência'}


class LixeiraView(LoginRequiredMixin, TemplateView):
    template_name = 'ausencias/em_construcao.html'
    extra_context = {'active_nav': 'lixeira', 'titulo': 'Lixeira'}
