import pytest
from django.contrib.auth.models import Group

pytestmark = pytest.mark.django_db


def test_grupo_gestor_existe_apos_migrations():
    assert Group.objects.filter(name='Gestor').exists()
