"""Identificação da tentativa de login para o django-axes.

O bloqueio é pelo par e-mail + IP (``AXES_LOCKOUT_PARAMETERS`` no settings).
Estas funções definem o que conta como "o mesmo e-mail" e "o mesmo IP".
"""

import ipaddress

from django.conf import settings
from django.shortcuts import render


def email_da_tentativa(request, credentials):
    """E-mail digitado, normalizado como no cadastro (sem espaços nas pontas,
    em minúsculas): variar a caixa não abre uma nova cota de tentativas.
    """
    if credentials:
        valor = credentials.get('username')
    else:
        valor = getattr(request, 'POST', {}).get('username')
    return (valor or '').strip().lower()


def ip_do_cliente(request):
    """IP real do cliente atrás de ``PROXY_COUNT`` proxies confiáveis.

    Cada proxy ACRESCENTA ao fim do X-Forwarded-For o IP de quem se conectou a
    ele; o cliente pode inventar o começo do cabeçalho, nunca o fim. Por isso
    o IP do cliente é o N-ésimo a partir da DIREITA (N = PROXY_COUNT; no
    Render, 1). Cabeçalho ausente, curto demais ou com valor que não é IP:
    usa REMOTE_ADDR (ex.: runserver local, sem proxy).
    """
    remoto = request.META.get('REMOTE_ADDR', '')
    proxies = settings.PROXY_COUNT
    if proxies <= 0:
        return remoto

    encaminhado = request.META.get('HTTP_X_FORWARDED_FOR', '')
    itens = [item.strip() for item in encaminhado.split(',') if item.strip()]
    if len(itens) < proxies:
        return remoto
    try:
        return str(ipaddress.ip_address(itens[-proxies]))
    except ValueError:
        return remoto


def resposta_bloqueio(request, original_response=None, credentials=None):
    """Página em pt-BR para quem atingiu o limite (HTTP 429)."""
    contexto = {
        'tentativas': settings.AXES_FAILURE_LIMIT,
        'minutos': int(settings.AXES_COOLOFF_TIME.total_seconds() // 60),
    }
    return render(request, 'usuarios/login_bloqueado.html', contexto, status=429)
