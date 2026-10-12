from django.http import HttpResponse

CAMINHO_SAUDE = '/saude/'


class SaudeMiddleware:
    """Liveness para o healthcheck do Render: ``/saude/`` responde 200 "ok".

    Fica no topo do MIDDLEWARE e responde antes de tudo: sem validação de host
    (o Render chama pelo IP interno, não pelo hostname público), sem sessão,
    sem login e sem banco. Só diz que o processo está de pé; o banco é
    conferido à parte em ``/saude/banco/`` (readiness).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info == CAMINHO_SAUDE:
            return HttpResponse(
                'ok', content_type='text/plain; charset=utf-8',
                headers={'Cache-Control': 'no-store'},
            )
        return self.get_response(request)
