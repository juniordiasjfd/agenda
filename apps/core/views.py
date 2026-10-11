from django.views.generic import RedirectView


class HomeView(RedirectView):
    """A página inicial é o painel de ausências (que exige login)."""
    pattern_name = 'painel:painel'
