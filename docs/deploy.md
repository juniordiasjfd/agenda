# Deploy da Agenda no Render — runbook

Este é o roteiro para colocar a Agenda no ar e mantê-la. Os comandos com
`python manage.py ...` rodam no **Shell** do web service, no painel do Render
(serviço `agenda` → *Shell*), a menos que o passo diga outra coisa.

## 1. Como está montado

| Peça | Configuração |
|---|---|
| Web service `agenda` | Python nativo (sem Docker), plano **Starter**, região **virginia** |
| Banco `agenda-db` | PostgreSQL 18, plano **basic-256mb**, região **virginia**, sem acesso externo (`ipAllowList: []`) |
| Conexão web → banco | **Internal Database URL** (rede privada, mesma região), injetada em `DATABASE_URL` |
| Build | `./build.sh`: `pip install`, `collectstatic`, `migrate` |
| Start | `gunicorn config.wsgi` (parâmetros em `gunicorn.conf.py`) |
| Healthcheck | `/saude/` = liveness (sem banco, sem host, sem login). `/saude/banco/` = readiness (`SELECT 1`; 503 se o banco cair) |
| HTTPS | O Render redireciona HTTP→HTTPS e encerra o TLS. O Django **não** redireciona (`SECURE_SSL_REDIRECT=False`) e confia no `X-Forwarded-Proto` |
| Deploy automático | Push na `main` → GitHub Actions (CI) → se passar, o Render faz o deploy (`autoDeployTrigger: checksPass`) |
| Estáticos | WhiteNoise, com nomes com hash e compressão |
| Login | django-axes bloqueia o par e-mail + IP após 5 falhas por 15 min, usando o IP real do `X-Forwarded-For` |

Tudo isso está declarado em [`render.yaml`](../render.yaml) (Blueprint).
**Segredos não ficam no repositório**: a `SECRET_KEY` é gerada pelo Render,
a `DATABASE_URL` vem do banco e as credenciais SMTP você digita no painel.

## 2. Variáveis de ambiente

| Variável | Origem | Valor em produção |
|---|---|---|
| `DATABASE_URL` | banco (automático) | Internal Database URL |
| `SECRET_KEY` | gerada pelo Render | — (não trocar sem motivo: derruba as sessões e invalida os links de senha e convite) |
| `RENDER_EXTERNAL_HOSTNAME` | Render (automático) | `agenda-xxxx.onrender.com`; entra sozinho em `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` |
| `DEBUG` | render.yaml | `False` |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | painel | vazias enquanto o domínio for o `.onrender.com` (ver §10) |
| `HSTS_SECONDS` | render.yaml | `300` no início (ver §9) |
| `LOG_LEVEL`, `LOG_LEVEL_DJANGO`, `LOG_LEVEL_ROOT` | render.yaml | `INFO`, `WARNING`, `WARNING` |
| `WEB_CONCURRENCY`, `GUNICORN_TIMEOUT` | render.yaml | `2`, `30` |
| `AXES_FAILURE_LIMIT`, `AXES_COOLOFF_MINUTES` | render.yaml | `5`, `15` |
| `PROXY_COUNT` | render.yaml | `1` (conferir no §5.4) |
| `EMAIL_BACKEND` | render.yaml | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | **painel (secreto)** | dados do provedor SMTP |
| `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL` | render.yaml | `587`, `True`, `False` (ajuste se o provedor usar 465/SSL) |

A lista completa, com comentários, está em [`.env.example`](../.env.example).

## 3. Antes do primeiro deploy

1. O CI precisa estar verde na `main` (aba *Actions* do GitHub).
2. No GitHub (*Settings → Branches*), proteja a `main` exigindo o check
   **CI / testes**. É recomendado, não obrigatório: o Render já espera o CI.
3. Tenha em mãos os dados do SMTP (host, porta, usuário, senha, remetente).
4. Tenha o `legado/referencias/funcionarios.js` local. Ele **não** está no
   Git porque tem dados pessoais.

## 4. Criar os serviços (Blueprint)

1. Render → **New → Blueprint** → conecte o repositório
   `juniordiasjfd/agenda`, branch `main`.
2. O Render lê o `render.yaml` e mostra `agenda-db` e `agenda`. Confira
   **região virginia** nos dois e os planos (Starter e basic-256mb).
3. Preencha as variáveis marcadas como secretas (`EMAIL_HOST`,
   `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`).
4. **Apply**. O banco sobe primeiro e depois roda o build do web
   (`build.sh`, que aplica as migrations no banco vazio).
5. Aguarde o deploy ficar *Live*. O Render só troca para a nova versão
   quando `/saude/` responde 200.

> Se o nome `agenda` já estiver em uso no `onrender.com`, o Render
> acrescenta um sufixo (ex.: `agenda-ab12.onrender.com`). Nada a ajustar:
> o hostname vem de `RENDER_EXTERNAL_HOSTNAME`.

## 5. Primeiro deploy: verificações

### 5.1 Saúde
```
https://<host>/saude/        → ok
https://<host>/saude/banco/  → ok
http://<host>/               → redireciona para https (feito pelo Render)
```

### 5.2 Configuração
No Shell:
```bash
python manage.py check --deploy --fail-level WARNING
python manage.py showmigrations | grep '\[ \]' || echo "todas aplicadas"
```

### 5.3 E-mail
```bash
python manage.py testar_email voce@scriba.com.br
```
O comando mostra a configuração em uso (sem a senha) e, se falhar, o
**erro real** do SMTP. No uso normal da aplicação o envio nunca derruba a
tela: a falha só aparece no log como `Falha ao enviar e-mail`.

### 5.4 IP real atrás do proxy (django-axes)
1. Descubra o seu IP público (ex.: pesquisar "meu ip").
2. Faça **um** login com senha errada.
3. Em `/admin/` → *Axes* → *Tentativas de acesso*, confira o **IP** da
   tentativa:
   - é o seu IP → `PROXY_COUNT=1` está certo;
   - é um IP interno (10.x, 172.16–31.x) ou de proxy → aumente
     `PROXY_COUNT` para 2 no painel e repita o teste.
4. Faça login com a senha certa (zera a contagem).

Se o IP estiver errado, todo mundo atrás do mesmo proxy divide a mesma cota
de tentativas, e um usuário pode bloquear o outro.

## 6. Carga inicial (produção começa vazia)

### 6.1 Administrador
```bash
python manage.py createsuperuser
```
Use o seu e-mail `@scriba.com.br` e uma senha forte (os validadores do
Django valem aqui).

### 6.2 Colaboradores
O `funcionarios.js` não está no servidor. Cole o arquivo pelo Shell num
arquivo temporário:
```bash
cat > /tmp/funcionarios.js <<'FIM'
(cole aqui o conteúdo inteiro do legado/referencias/funcionarios.js)
FIM
python manage.py carregar_colaboradores /tmp/funcionarios.js --dry-run
python manage.py carregar_colaboradores /tmp/funcionarios.js
rm /tmp/funcionarios.js
```
O comando é idempotente: rodar de novo não duplica ninguém. O `/tmp` do
Render é apagado a cada deploy ou reinício.

### 6.3 Departamentos e vínculos
Pela interface (admin): cadastre os departamentos, atribua-os aos
colaboradores e vincule usuários quando fizer sentido.

### 6.4 Reimportar os CSVs antigos
Logado como administrador: **Ausências → Importar CSV**.
1. Envie os arquivos (até 20 por vez, 2 MB e 5000 linhas cada).
2. Leia a **prévia**: duplicatas são ignoradas, sobreposições e linhas
   inválidas não entram, e colaboradores, tipos ou situações inexistentes
   aparecem com a opção de criar (desmarcada por padrão).
3. Marque o que deve ser criado e confirme. Tudo é gravado numa transação:
   ou entra tudo do plano, ou nada.
4. Baixe o **CSV de linhas não importadas**, corrija e reenvie.
5. Confira o painel e a listagem.

## 7. Deploys do dia a dia

- Push (ou merge) na `main` → CI → deploy automático.
- As **migrations rodam no build**, antes da versão nova entrar no ar. Por
  alguns instantes o código **antigo** roda com o banco **já migrado**.
  Toda migration precisa ser compatível com o código anterior. Por exemplo,
  para remover uma coluna: primeiro um deploy que pare de usá-la, depois
  outro que a remova.
- Se o build falhar (testes, collectstatic, migrate), a versão anterior
  continua no ar.
- Deploy manual: painel → *Manual Deploy → Deploy latest commit*.

## 8. Rollback

1. Painel do `agenda` → *Events* → escolha o deploy bom anterior →
   **Rollback**. O Render volta o código **sem rodar build**, portanto sem
   desfazer migrations.
2. Se a versão ruim aplicou uma migration incompatível com o código
   antigo, escolha uma das saídas:
   - corrigir para a frente: um commit novo que conserte, que é o caminho
     preferido;
   - ou, no Shell, reverter a migration (`python manage.py migrate <app>
     <migration_anterior>`) **antes** do rollback, se ela for reversível e
     sem perda de dados.
3. Perda ou corrupção de dados: veja §9.
4. Durante um rollback, desligue o auto-deploy (*Settings → Auto-Deploy*)
   para um push não desfazê-lo. Lembre de religar depois.

## 9. Backup e restauração do banco

O plano pago do Postgres no Render inclui:
- **PITR (Point-in-Time Recovery)**: restaura o banco para qualquer instante
  dentro da janela do plano (confira em *agenda-db → Recovery*);
- **Exports lógicos**: arquivos de backup que podem ser baixados (em
  *agenda-db → Recovery/Exports*).

### Restaurar (incidente)
1. *agenda-db → Recovery → Point-in-time recovery*: escolha o instante
   **anterior** ao problema. O Render cria um **banco novo** com os dados
   daquele momento; o original continua intacto.
2. Confira o banco novo (veja "Testar uma restauração" abaixo).
3. No web `agenda` → *Environment*, troque `DATABASE_URL` pela **Internal
   Database URL** do banco novo e salve. Isso faz um novo deploy, e o build
   roda `migrate` (sem efeito se o banco já estiver em dia).
4. Teste o sistema e só então apague ou renomeie o banco antigo. Se usou o
   Blueprint, atualize o `render.yaml` (`fromDatabase.name`) para o novo
   nome, ou o próximo sync do Blueprint pode religar o banco antigo.

### Testar uma restauração (a cada 3 meses, ou após mudanças grandes)
1. Crie um PITR de "agora" num banco novo (não ligue ao web).
2. No Shell do `agenda`, aponte só o comando para o banco restaurado:
   ```bash
   DATABASE_URL='<Internal URL do banco restaurado>' python manage.py shell -c "
   from apps.ausencias.models import Ausencia, PeriodoAusencia
   from apps.colaboradores.models import Colaborador
   from apps.usuarios.models import User
   print('usuarios', User.objects.count())
   print('colaboradores', Colaborador.objects.count())
   print('ausencias', Ausencia.todos.count(), 'periodos', PeriodoAusencia.objects.count())"
   ```
3. Compare com os mesmos números no banco de produção (rode sem a
   variável).
4. Registre data, instante restaurado e resultado. Depois **apague** o banco
   de teste, que é cobrado.

## 10. Domínio próprio (futuro)

1. Painel do `agenda` → *Settings → Custom Domains* → adicione, por
   exemplo, `agenda.scriba.com.br`.
2. No DNS da Scriba, crie o **CNAME** `agenda` → `<host>.onrender.com`. O
   Render emite o certificado sozinho.
3. Em *Environment*:
   ```
   ALLOWED_HOSTS=agenda.scriba.com.br
   CSRF_TRUSTED_ORIGINS=https://agenda.scriba.com.br
   ```
   O `.onrender.com` continua aceito via `RENDER_EXTERNAL_HOSTNAME`.
4. Atualize os links de e-mail: eles usam o host da requisição, então nada
   muda se os usuários acessarem pelo domínio novo.
5. Depois de algumas semanas estável no HTTPS, suba `HSTS_SECONDS` para
   `31536000` (1 ano). Só então avalie `includeSubDomains`/`preload`, que
   hoje estão desligados e com os avisos silenciados porque `onrender.com`
   não é nosso.

## 11. Operação

- **Logs**: painel → *Logs*. A aplicação escreve no stdout; erro 500 aparece
  com traceback (`django.request`). Para investigar, suba `LOG_LEVEL` para
  `DEBUG` temporariamente.
- **Desbloquear um login** antes dos 15 min: `/admin/` → *Axes* → apague a
  tentativa, ou no Shell:
  ```bash
  python manage.py axes_reset_username fulano@scriba.com.br
  ```
- **Limite do axes**: o bloqueio é por e-mail + IP. Um ataque que troca de
  IP a cada tentativa não é contido por ele; nesse caso a defesa são as
  senhas fortes (validadores do Django). Se aparecerem muitas tentativas
  no admin do Axes, avalie bloqueio por IP no Render.
- **Python**: a versão vem de `.python-version`, usada pelo Render e pelo
  CI.

## 12. Problemas comuns

| Sintoma | Causa provável |
|---|---|
| Build falha em `collectstatic` com `ImproperlyConfigured` | variável obrigatória ausente (`SECRET_KEY`, `DATABASE_URL`) |
| Build falha em `migrate` sem conectar ao banco | `DATABASE_URL` não é a Internal URL ou o banco está em outra região. Alternativa: mover o `migrate` do `build.sh` para um `preDeployCommand` |
| Deploy não fica *Live* (healthcheck) | o gunicorn não sobe: veja o log de start (import errado, variável faltando) |
| 400 Bad Request no navegador | host fora de `ALLOWED_HOSTS` (domínio próprio sem a variável) |
| 403 CSRF ao enviar formulário | origem fora de `CSRF_TRUSTED_ORIGINS` (domínio próprio sem a variável) |
| E-mails não chegam | `python manage.py testar_email ...` e procure `Falha ao enviar e-mail` no log |
| Todos bloqueados juntos no login | `PROXY_COUNT` errado (§5.4) |
