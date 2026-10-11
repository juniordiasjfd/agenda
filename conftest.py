import pytest
from django.utils import timezone

from apps.usuarios.models import User

SENHA = 'Agenda-Teste-2026!'


@pytest.fixture(autouse=True)
def _hasher_rapido(settings):
    """MD5 só nos testes: o PBKDF2 padrão deixaria a suíte lenta."""
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


@pytest.fixture
def senha():
    return SENHA


@pytest.fixture
def usuario_ativo(db):
    return User.objects.create_user('ativo@scriba.com.br', SENHA, nome='Usuária Ativa')


@pytest.fixture
def usuario_pendente(db):
    """Autocadastro ainda não aprovado: inativo e sem aprovado_em."""
    return User.objects.create_user('pendente@scriba.com.br', SENHA, nome='Pendente', is_active=False)


@pytest.fixture
def usuario_desativado(db):
    """Já foi aprovado e depois desativado pelo administrador."""
    return User.objects.create_user(
        'desativado@scriba.com.br', SENHA, nome='Desativado',
        is_active=False, aprovado_em=timezone.now(),
    )
