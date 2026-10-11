# Agenda — Scriba

Sistema interno para registrar e visualizar ausências (férias, banco de horas,
licença, etc.) dos colaboradores. Substitui um fluxo antigo baseado em HTML
offline + CSV por e-mail. Os arquivos do fluxo antigo estão em `legado/` e são
a referência das regras de negócio (validações, CSV, Gantt). Exemplos das
convenções de código da Scriba (AuditoriaBase, *_service.py, bloco de e-mail
do settings) estão em `legado/referencias/`: reproduza esses padrões.

## Stack
- Python + Django, PostgreSQL. Usar as mesmas versões dos demais projetos
  Scriba (fixar em requirements): [legado\referencias\requirements_example.txt].
- Frontend: Tabler UI + HTMX + Alpine.js, ícones Font Awesome. Sem SPA.
- Testes: pytest-django.
- Hospedagem: Render (Web Service pago + Postgres pago com backup). Estáticos
  via WhiteNoise. Config por variáveis de ambiente (python-dotenv em dev,
  dj-database-url).
- E-mail: SMTP configurado só por variáveis de ambiente, copiando o bloco de
  `legado/referencias/email_settings.py` (EMAIL_BACKEND, HOST, PORT, USER,
  PASSWORD, USE_TLS, USE_SSL, DEFAULT_FROM_EMAIL, EMAIL_TIMEOUT=10). Em dev o
  padrão é o backend de console. DEFAULT_FROM_EMAIL padrão:
  "Agenda <nao-responder@agenda.local>". Envio nunca pode quebrar o fluxo:
  capturar exceção, registrar em log e seguir.
- Idioma pt-BR, fuso America/Sao_Paulo, interface 100% em português.

## Estrutura
- `config/` — settings, urls, wsgi.
- `apps/core/` — AuditoriaBase, SoftDeleteMixin, home, utilitários.
- `apps/usuarios/` — User customizado, Convite, DominioAutocadastro, cadastro,
  aprovação, login.
- `apps/colaboradores/` — Departamento, Colaborador, comando de carga inicial.
- `apps/ausencias/` — TipoAusencia, SituacaoAusencia, Ausencia,
  PeriodoAusencia, forms, services, views, CSV, painel, lixeira.
- Regra de negócio em `*_service.py` (`ausencias_service.py`, `csv_service.py`,
  `painel_service.py`, `usuarios_service.py`). Views finas; nada de regra de
  negócio em views ou templates.

## Usuários e acesso
- `AUTH_USER_MODEL` customizado, definido ANTES da primeira migration. Login
  por e-mail (único, normalizado em minúsculas, sem username).
- Perfis: Administrador = superuser. Gestor = Group "Gestor". Todo usuário
  autenticado vê tudo; todo gestor cria, edita, exclui e restaura qualquer
  ausência. Só o administrador gerencia usuários, colaboradores,
  departamentos, tipos, situações, domínios de autocadastro e importa CSV.
- Autocadastro: permitido só para e-mails cujo domínio (comparação por
  IGUALDADE exata, em minúsculas) esteja em DominioAutocadastro ativo. Sem
  domínio ativo, o autocadastro fica desligado. DominioAutocadastro: dominio
  (único), ativo; editável pelo admin.py. A data migration cria
  `scriba.com.br` ativo.
- O autocadastro cria User com is_active=False e aprovado_em nulo, sem grupo.
  Tela "Cadastros pendentes" para o admin aprovar (is_active=True, aprovado_em,
  grupo Gestor, e opcionalmente vincular a um Colaborador) ou rejeitar
  (exclui). Aviso de pendências no menu do admin e e-mail para os superusers
  ativos com e-mail. Resposta do cadastro neutra para e-mail já existente (sem
  revelar quem tem conta).
- Convite (admin): model Convite (token UUID, e-mail, colaborador opcional,
  expira_em, usado_em, criado_por). O admin copia o link e/ou envia por e-mail.
  Aceitar o convite cria o usuário com is_active=True, aprovado_em preenchido e
  grupo Gestor, já vinculado ao colaborador do convite, se houver.
- Login: usar AllowAllUsersModelBackend e mensagens distintas para "aguardando
  aprovação" (is_active=False e aprovado_em nulo) e "usuário desativado".
- Vínculo usuário↔colaborador: Colaborador.usuario (OneToOne, nulo). Só o
  admin vincula (na aprovação, no convite ou na edição do colaborador).
  Quando houver vínculo, o formulário de registro pré-seleciona esse
  colaborador. O vínculo é opcional.
- Validadores de senha do Django ativos.

## Modelos
- Departamento: nome (único).
- Colaborador: nome (único, espaços normalizados), departamento (FK, NULO
  permitido), ativo, usuario (OneToOne nulo). Nunca apagar colaborador com
  ausências: usar `ativo`. Inativo some do formulário e do painel; o histórico
  permanece no banco.
- TipoAusencia: nome (único), cor (hex), ativo, ordem. Carga inicial: Férias,
  Banco de horas, Licença, Outro. Tipo em uso não pode ser apagado, só
  inativado.
- SituacaoAusencia: nome (único), ativo, ordem, padrao (bool),
  conta_como_ausencia (bool). Carga inicial: Planejado (padrão), Aprovado,
  Realizado, Cancelado (conta_como_ausencia=False). Se desmarcada, a situação
  some do Gantt e não gera conflito de sobreposição.
- Ausencia (cabeçalho): colaborador (FK PROTECT), tipo (FK PROTECT),
  observacoes, codigo (curto, único; é o SolicitacaoID do CSV).
  Exclusão lógica: excluido_em, excluido_por. Manager padrão oculta as
  excluídas; `todos` as inclui.
- PeriodoAusencia: ausencia (FK CASCADE), data_inicio, data_fim (DateField, fim
  INCLUSIVO), situacao (FK PROTECT, padrão = a marcada como padrao).
  CheckConstraint: data_fim >= data_inicio. `dias` é propriedade calculada.
- Auditoria: AuditoriaBase (criado_em/por, atualizado_em/por) em todos os
  models de domínio. Sem histórico completo de alterações.

## Regras de negócio
- Sobreposição de períodos do mesmo colaborador é evitada na camada de
  aplicação (clean do formset + service), NÃO por constraint no banco. Uma
  única função de verificação, usada por formulário, view e importação.
- A checagem considera: períodos do mesmo envio (formset), períodos já
  gravados do colaborador e, na edição, EXCLUI os períodos da própria
  ausência. Ignora ausências excluídas e situações com
  conta_como_ausencia=False.
- Registro e edição usam a mesma tela: cabeçalho (colaborador, tipo,
  observações) + inline formset de períodos (máx. 12), linhas adicionadas por
  HTMX/Alpine, dias calculados na tela. Editar altera o envio inteiro. Salvar
  em transaction.atomic.
- Período no passado: permitido, com aviso visual (não bloqueia).
- Exclusão: lógica. Tela de lixeira; qualquer gestor restaura, só o admin
  apaga de vez.
- Comparação de nomes (busca e importação): ignorar acento, caixa e espaços
  duplos (ver `norm()` em `legado/index.html`).

## CSV (compatível com os arquivos já existentes)
- Colunas: Titulo;Colaborador;TipoEvento;DataInicio;DataFim;QuantidadeDias;
  Situacao;SolicitacaoID;Observacoes;DataSolicitacao. Uma linha por período.
- Exportação: separador `;`, UTF-8 com BOM, uma linha por PeriodoAusencia;
  Titulo = "Colaborador - Tipo"; SolicitacaoID = Ausencia.codigo. Respeita os
  filtros da tela; ignora ausências excluídas.
- Importação (somente administrador, vários arquivos de uma vez): detectar `;`
  ou `,`; tentar UTF-8 e cair para Windows-1252; datas ISO ou dd/mm/aaaa;
  agrupar linhas pelo SolicitacaoID em uma Ausencia com vários períodos
  (se colaborador/tipo divergirem no mesmo ID, tratar como grupos separados).
- Sempre com etapa de PRÉVIA antes de gravar. Na prévia:
  - duplicata exata (colaborador, tipo, início, fim): ignorar;
  - sobreposição (com o banco ou com linhas anteriores do próprio lote): NÃO
    importar a linha e reportar;
  - colaborador inexistente: reportar e oferecer criar (departamento nulo);
  - tipo ou situação inexistente: reportar e oferecer criar.
- Migração dos CSVs antigos: feita pela própria tela de importação.

## Painel Gantt
- Reaproveitar o JS de `legado/Painel de ausências.html` (escalas diária,
  semanal e mensal; lanes para sobreposição; tela cheia) como arquivo
  estático. Não reescrever a lógica de desenho sem necessidade.
- Remover do legado: localStorage, seed embutido, carga de CSV, "Baixar
  painel HTML" e as cores fixas c0..c3 (a cor vem de TipoAusencia.cor; a
  legenda vem dos tipos ativos).
- Dados via endpoint JSON com filtros na querystring; filtragem no servidor
  (`painel_service.py`): nome, departamento (inclui "Sem departamento"),
  "ausência em" [de, até], "presença em" [de, até] (= nenhuma ausência no
  período), incluir colaboradores sem registros. Só colaboradores ativos e só
  situações que contam como ausência. Situação aparece no tooltip.

## senha
- Redefinição de senha: fluxo padrão do Django (solicitar, e-mail enviado,
  link com token, definir nova senha, concluído), com templates e e-mail em
  pt-BR. Resposta SEMPRE neutra (não revela se o e-mail existe). Usuário
  inativo/pendente não recebe e-mail (comportamento padrão do Django).
  Validade do link: 24 h (PASSWORD_RESET_TIMEOUT). Há também "Alterar senha"
  para usuário logado.

## Convenções
- Testes obrigatórios para: sobreposição (inclusive edição), importação CSV,
  filtros do painel, fluxo de cadastro/aprovação/convite (incluindo domínio
  não permitido e autocadastro desligado), exclusão lógica.
- Migrations versionadas; nunca editar migration já aplicada em produção.
  Cargas iniciais (tipos, situações, grupo Gestor, domínio scriba.com.br) via
  data migration.
- Segredos só em variáveis de ambiente; nunca commitar `.env`.
- Commits pequenos, um por etapa, mensagens em português.
- Antes de qualquer etapa grande, apresentar um plano e aguardar aprovação.

## Deploy (Render)
- gunicorn, `build.sh` (install, collectstatic, migrate), DATABASE_URL,
  SECRET_KEY, DEBUG, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS e as variáveis de
  e-mail.

## Etapas
1. Projeto base, settings (incl. e-mail), User customizado (e-mail), login,
   grupos, core.
2. Cadastro, domínios de autocadastro, aprovação e convite de usuários
   (SEM vínculo com Colaborador; o campo Convite.colaborador e a escolha de
   vínculo na aprovação entram na etapa 3).
3. Departamento, Colaborador (+ vínculo usuário↔colaborador na aprovação,
   no convite e na edição do colaborador), comando `carregar_colaboradores`.
4. Tipos, situações, Ausencia/Periodo, serviço de sobreposição e testes.
5. Registro/edição (formset), listagem com filtros, exclusão lógica e lixeira.
6. Import/export CSV com prévia.
7. Endpoint JSON e painel Gantt.
8. Deploy no Render.

## Comandos úteis
- `python manage.py carregar_colaboradores legado/referencias/funcionarios.js` (`--dry-run` para simular)
- `pytest`