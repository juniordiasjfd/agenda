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
- ImportacaoCSV (staging da importação; AuditoriaBase, pk UUID): arquivos
  (JSON com as linhas lidas), decisoes (JSON com os cadastros marcados para
  criar), status (pendente, aplicada, cancelada), resumo (JSON: contagens e
  linhas não importadas), aplicada_em. Pendente com mais de 2 h está expirada
  (enviar de novo); cada novo envio apaga as com mais de 24 h; aplicar ou
  cancelar apaga `arquivos`. No admin, somente leitura.

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
- Conflito: mesmo colaborador, intervalos inclusivos que se cruzam
  (inicio_a <= fim_b e inicio_b <= fim_a), independentemente do tipo. Só conta
  quem está em ausência não excluída e situação com conta_como_ausencia=True.
- O serviço de criação/edição/restauração trava a linha do Colaborador
  (select_for_update) dentro de transaction.atomic para serializar registros
  concorrentes do mesmo colaborador. Restaurar da lixeira rechecaga conflito.
- Datas: ano permitido 2000–2100. Máximo de 12 períodos por ausência.
- Ausencia.codigo: até 32 caracteres, único; aceita IDs legados do CSV antigo;
  os novos são gerados com `secrets` (8 caracteres, sem ambíguos 0/O/1/I/L).
- Colaborador inativo não recebe novas ausências. Tipo/situação inativos não
  podem ser escolhidos em novos registros, mas ausências existentes que os
  usam permanecem válidas.
- Tipos e situações são gerenciados no /admin/ do Django (sem telas próprias).
- Trava otimista na edição: token = `atualizado_em` da ausência;
  `atualizar_ausencia(versao=...)` levanta `AusenciaAlterada` se ela mudou; a
  tela mostra mensagem amigável sem perder o que foi digitado.
- Exclusão e lixeira: o admin do Django não exclui ausências;
  `apagar_definitivamente` só para ausência na lixeira, só superuser, digitando
  o código; editar ausência na lixeira é recusado ("restaure antes de
  editar"); restaurar não exige colaborador/tipo/situação ativos, só ausência
  de conflito.
- Situação inativa só vale em período que já a tinha. Período cuja situação
  não conta como ausência não conflita nem com o banco nem com o mesmo envio.
- Listagem: `ausencias_filtradas` é a fonte única dos filtros (listagem e
  exportação). As regras das opções dos selects (`*_para_escolha`) ficam no
  serviço. Linha de período em branco no formulário é erro, não é ignorada.

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
- Exportação usa os mesmos filtros da listagem e exporta TODOS os períodos das
  ausências filtradas (SolicitacaoID íntegro para reimportar).
- Fórmulas: na exportação, campo de texto (Titulo, Colaborador, TipoEvento,
  Situacao, Observacoes) que começa com = + - @ tab ou CR ganha um apóstrofo
  na frente; a importação desfaz exatamente esse prefixo.
- Limites da importação (settings `CSV_IMPORTACAO_*`): 20 arquivos por envio,
  2 MB e 5000 registros por arquivo, extensão .csv ou .txt. Arquivo fora do
  limite é recusado sozinho; os demais seguem.
- Titulo, QuantidadeDias e DataSolicitacao são ignorados na leitura
  (derivados; criado_em = momento da importação).
- Arquivos lidos em ordem alfabética do nome, registros na ordem do arquivo:
  em sobreposição, a linha mais antiga vence.
- Precedência por linha: inválida → resolução de cadastro (nome normalizado;
  situação vazia = padrão) → duplicata → sobreposição (a regra única) →
  limite de 12 períodos por ausência.
- Duplicata compara só com ausências NÃO excluídas (e linhas anteriores do
  lote que serão importadas).
- Colaborador, tipo ou situação existente porém inativo: linha inválida
  (reativar antes de importar).
- Criação de colaborador/tipo/situação só por marcação explícita na prévia
  (padrão: desmarcado) e só se alguma linha a importar usa. Padrões:
  colaborador ativo e sem departamento; tipo ativo, cor neutra, ordem ao
  final; situação ativa, conta como ausência, não padrão, ordem ao final.
- Grupos: (SolicitacaoID, colaborador, tipo) normalizados; linha sem ID =
  uma ausência só dela. ID com colaborador/tipo divergente: o primeiro grupo
  fica com o código, os demais recebem código novo. ID inválido como código
  ou já existente (inclusive lixeira, sem diferença de caixa): código novo,
  com aviso. Grupo parcial importa só as linhas válidas, sinalizado.
- A prévia exibe a assinatura (hash do plano: o que será importado e
  criado). Confirmar trava a importação e os colaboradores envolvidos (ordem
  de id), refaz a análise e só grava se a assinatura bater (senão: "os dados
  mudaram", nada gravado). Tudo numa transação: qualquer erro = rollback
  total, log e "nada foi gravado".
- CSV de linhas não importadas (sobreposição, inválida, pendente; sem
  duplicatas): as colunas canônicas com os valores lidos + Motivo, Arquivo e
  Linha. Disponível na prévia e no resultado; pode ser corrigido e reenviado.

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
- Templates: comentário de várias linhas só com `{% comment %}`; `{# #}`
  apenas numa linha. Há teste que impede reincidência
  (`apps/core/tests/test_templates.py`).
- Front-end: bibliotecas externas (Tabler, HTMX, Alpine, Tom Select) via CDN
  com versão fixa e SRI. Ajustes visuais no CSS do projeto
  (`static/css/agenda.css`), nunca no arquivo do CDN. O Tabler usa
  `--tblr-*`: temas de terceiros baseados em `--bs-*` precisam de override,
  conferido nos temas claro e escuro.
- HTMX é melhoria progressiva: toda tela, filtro e modal funciona por URL
  completa sem JavaScript; as respostas parciais só trocam fragmentos.
- Permissões em `apps/core/permissions.py` (`eh_gestor`, `GestorMixin`,
  `AdministradorMixin`). O controle real é na view (botão escondido é só
  conveniência); testar anônimo, sem grupo, gestor e superuser em todas as
  views.
- Testes nunca dependem do relógio real para ordem ou versão (no Windows duas
  gravações podem ter o mesmo instante): usar tempo controlado.

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
- No Windows, chamar `.venv/Scripts/python` (ex.: `.venv/Scripts/python -m
  pytest`, `.venv/Scripts/python manage.py check`): o `python` do PATH aponta
  para outro venv.