from django.contrib.auth.backends import AllowAllUsersModelBackend


class EmailBackend(AllowAllUsersModelBackend):
    """Autentica por e-mail e senha.

    ``authenticate()`` devolve também usuários inativos (herdado do
    ``AllowAllUsersModelBackend``), para o ``LoginForm`` distinguir "aguardando
    aprovação" de "desativado" no ``confirm_login_allowed`` — que recusa o
    login. ``get_user()`` volta ao comportamento do ``ModelBackend``: usuário
    desativado depois de entrar perde a sessão na requisição seguinte.
    """

    def get_user(self, user_id):
        user = super().get_user(user_id)
        if user is not None and not user.is_active:
            return None
        return user
