import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.usuarios.models import User

pytestmark = pytest.mark.django_db


def test_create_user(senha):
    user = User.objects.create_user('fulano@scriba.com.br', senha, nome='Fulano de Tal')

    assert user.email == 'fulano@scriba.com.br'
    assert user.check_password(senha)
    assert user.password != senha
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser
    assert user.aprovado_em is not None  # ativo = aprovado
    assert user.date_joined is not None


def test_create_user_inativo_fica_sem_aprovacao(senha):
    user = User.objects.create_user('novo@scriba.com.br', senha, nome='Novo', is_active=False)

    assert not user.is_active
    assert user.aprovado_em is None
    assert user.aguardando_aprovacao


def test_create_user_exige_email(senha):
    with pytest.raises(ValueError):
        User.objects.create_user('', senha, nome='Sem e-mail')
    with pytest.raises(ValueError):
        User.objects.create_user('   ', senha, nome='Só espaços')


def test_create_superuser(senha):
    admin = User.objects.create_superuser('admin@scriba.com.br', senha, nome='Admin')

    assert admin.is_staff
    assert admin.is_superuser
    assert admin.is_active
    assert admin.aprovado_em is not None


@pytest.mark.parametrize('campo', ['is_staff', 'is_superuser', 'is_active'])
def test_create_superuser_recusa_flag_falsa(senha, campo):
    with pytest.raises(ValueError):
        User.objects.create_superuser('admin@scriba.com.br', senha, nome='Admin', **{campo: False})


def test_email_normalizado_em_minusculas(senha):
    user = User.objects.create_user('  Fulano.Tal@Scriba.COM.BR ', senha, nome='Fulano')

    user.refresh_from_db()
    assert user.email == 'fulano.tal@scriba.com.br'


def test_email_normalizado_no_save(usuario_ativo):
    usuario_ativo.email = 'Outro@Scriba.com.br'
    usuario_ativo.save()

    usuario_ativo.refresh_from_db()
    assert usuario_ativo.email == 'outro@scriba.com.br'


def test_email_duplicado_com_caixa_diferente_rejeitado(senha):
    User.objects.create_user('fulano@scriba.com.br', senha, nome='Fulano')

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user('FULANO@Scriba.com.br', senha, nome='Outro Fulano')

    assert User.objects.count() == 1


def test_constraint_no_banco_barra_caixa_diferente(senha):
    """Mesmo gravando sem passar pela normalização (update direto), o banco
    recusa o mesmo e-mail com caixa diferente."""
    User.objects.create_user('fulano@scriba.com.br', senha, nome='Fulano')
    outro = User.objects.create_user('outro@scriba.com.br', senha, nome='Outro')

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=outro.pk).update(email='Fulano@Scriba.com.br')


def test_full_clean_rejeita_email_duplicado_com_caixa_diferente(senha):
    User.objects.create_user('fulano@scriba.com.br', senha, nome='Fulano')
    novo = User(email='Fulano@SCRIBA.com.br', nome='Outro')
    novo.set_password(senha)

    with pytest.raises(ValidationError):
        novo.full_clean()


def test_get_by_natural_key_ignora_caixa(usuario_ativo):
    assert User.objects.get_by_natural_key('ATIVO@Scriba.com.br') == usuario_ativo
