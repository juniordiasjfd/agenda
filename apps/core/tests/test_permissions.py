import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.views import View

from apps.core.permissions import AdministradorMixin
from apps.usuarios.models import User

pytestmark = pytest.mark.django_db


class ViewDeAdmin(AdministradorMixin, View):
    def get(self, request):
        return HttpResponse('ok')


def _get(user):
    request = RequestFactory().get('/restrita/')
    request.user = user
    return ViewDeAdmin.as_view()(request)


def test_anonimo_vai_para_o_login():
    response = _get(AnonymousUser())

    assert response.status_code == 302
    assert response.url == '/entrar/?next=/restrita/'


def test_usuario_comum_recebe_403(usuario_ativo):
    with pytest.raises(PermissionDenied):
        _get(usuario_ativo)


def test_superuser_passa(senha):
    admin = User.objects.create_superuser('admin@scriba.com.br', senha, nome='Admin')

    assert _get(admin).status_code == 200
