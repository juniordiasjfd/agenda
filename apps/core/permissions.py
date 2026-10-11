"""Mixins de permissão para class-based views.

    AdministradorMixin -> só superuser.

Comportamento herdado do ``AccessMixin`` do Django: anônimo vai para o login
(com ``next``); autenticado sem permissão recebe 403.
"""

from django.contrib.auth.mixins import UserPassesTestMixin


class AdministradorMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser
