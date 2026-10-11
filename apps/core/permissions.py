"""Perfis e mixins de permissão para class-based views.

    AdministradorMixin -> só superuser.
    GestorMixin        -> gestor (grupo "Gestor") ou superuser.

Comportamento herdado do ``AccessMixin`` do Django: anônimo vai para o login
(com ``next``); autenticado sem permissão recebe 403.
"""

from django.contrib.auth.mixins import UserPassesTestMixin

NOME_GRUPO_GESTOR = 'Gestor'


def eh_gestor(user):
    """Gestor (grupo "Gestor") ou administrador (superuser), ativo.

    O resultado fica guardado no próprio objeto: menu, botões e a view
    consultam várias vezes na mesma requisição com uma única query.
    """
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if not hasattr(user, '_eh_gestor'):
        user._eh_gestor = user.groups.filter(name=NOME_GRUPO_GESTOR).exists()
    return user._eh_gestor


class AdministradorMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


class GestorMixin(UserPassesTestMixin):
    def test_func(self):
        return eh_gestor(self.request.user)
