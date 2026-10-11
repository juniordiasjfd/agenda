import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_menu_do_gestor_tem_registrar(client, gestor):
    client.force_login(gestor)

    html = client.get(reverse('ausencias:lista')).content.decode()

    assert reverse('ausencias:lista') in html
    assert reverse('ausencias:registrar') in html
    assert reverse('ausencias:lixeira') in html


def test_menu_de_usuario_sem_grupo_nao_tem_registrar(client, usuario_ativo):
    client.force_login(usuario_ativo)

    html = client.get(reverse('ausencias:lista')).content.decode()

    assert reverse('ausencias:lista') in html
    assert reverse('ausencias:registrar') not in html
    assert reverse('ausencias:lixeira') in html
