import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.views import View

from apps.core.permissions import AdministradorMixin, GestorMixin, eh_gestor
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


# ---------------------------------------------------------------------------
# GestorMixin / eh_gestor
# ---------------------------------------------------------------------------
class ViewDeGestor(GestorMixin, View):
    def get(self, request):
        return HttpResponse('ok')


def _get_gestor(user):
    request = RequestFactory().get('/gestao/')
    request.user = user
    return ViewDeGestor.as_view()(request)


def test_gestor_mixin_anonimo_vai_para_o_login():
    response = _get_gestor(AnonymousUser())

    assert response.status_code == 302
    assert response.url == '/entrar/?next=/gestao/'


def test_gestor_mixin_usuario_sem_grupo_recebe_403(usuario_ativo):
    with pytest.raises(PermissionDenied):
        _get_gestor(usuario_ativo)


def test_gestor_mixin_gestor_e_superuser_passam(gestor, admin):
    assert _get_gestor(gestor).status_code == 200
    assert _get_gestor(admin).status_code == 200


def test_eh_gestor(usuario_ativo, gestor, admin):
    assert eh_gestor(AnonymousUser()) is False
    assert eh_gestor(usuario_ativo) is False
    assert eh_gestor(gestor) is True
    assert eh_gestor(admin) is True
    assert gestor.eh_gestor is True


def test_eh_gestor_inativo_nao_e_gestor(gestor):
    gestor.is_active = False

    assert eh_gestor(gestor) is False


def test_eh_gestor_consulta_o_grupo_uma_vez(gestor, django_assert_num_queries):
    with django_assert_num_queries(1):
        assert eh_gestor(gestor)
        assert eh_gestor(gestor)
