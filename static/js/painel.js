/* Painel de ausências (Gantt).
 *
 * Adaptado de legado/referencias/Painel de ausências.html: escalas diária,
 * semanal e mensal, navegação, faixas (lanes) para períodos sobrepostos,
 * cabeçalho em dois níveis, coluna de nomes fixa, fins de semana, destaque
 * do dia atual e tela cheia.
 *
 * Este arquivo SÓ DESENHA. Quem aparece e quais períodos contam como
 * ausência é decidido no servidor (painel_service.py); os dados vêm de
 * painel/dados/ com a mesma querystring do formulário de filtros. "Hoje"
 * também vem do servidor (America/Sao_Paulo), não do relógio do navegador.
 *
 * Segurança: todo texto vindo do servidor (nomes, departamento, tipo,
 * situação) entra por textContent/atributos do DOM, nunca por innerHTML. A
 * cor do tipo é validada (#RRGGBB) e a URL do detalhe precisa ser relativa.
 *
 * localStorage: só a preferência de escala (Diário/Semanal/Mensal).
 */
(function () {
  'use strict';

  var formulario = document.getElementById('painel-filtros');
  var palco = document.getElementById('painel-palco');
  if (!formulario || !palco || !window.fetch) return;

  // -------------------------------------------------------------------------
  // Constantes do desenho (as do legado)
  // -------------------------------------------------------------------------
  var MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro',
    'Outubro', 'Novembro', 'Dezembro'];
  var MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  var DIAS_SEMANA = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'];
  var DIA_MS = 864e5;
  var QUANTAS_COLUNAS = { dia: 30, sem: 26, mes: 12 };
  var LARGURA_COLUNA = { dia: 30, sem: 46, mes: 70 };
  var ALTURA_FAIXA = 18;
  var MARGEM_VERTICAL = 6;
  var ALTURA_MINIMA_LINHA = 36;  // nome + departamento em duas linhas
  var COR_NEUTRA = '#6c7a91';
  var RE_COR = /^#[0-9a-fA-F]{6}$/;
  var ESPERA_DIGITACAO_MS = 300;
  var CHAVE_ESCALA = 'agenda-painel-escala';
  var CAMPOS_DE_DATA = ['ausente_de', 'ausente_ate', 'presente_de', 'presente_ate', 'capacidade_de',
    'capacidade_ate'];

  var urlDados = formulario.getAttribute('data-url-dados');

  // Elementos da página (todos dentro do palco, exceto os avisos).
  function parte(seletor) { return palco.querySelector(seletor); }
  var el = {
    gantt: parte('[data-gantt]'),
    rolagem: parte('[data-rolagem]'),
    vazio: parte('[data-vazio]'),
    contador: parte('[data-contador]'),
    carregando: parte('[data-carregando]'),
    erro: parte('[data-erro]'),
    legenda: parte('[data-legenda]'),
    intervalo: parte('[data-intervalo]'),
    telaCheia: parte('[data-tela-cheia]'),
    avisos: document.getElementById('painel-avisos'),
    capacidade: document.getElementById('painel-capacidade'),
  };

  var estado = {
    escala: 'dia',
    deslocamento: 0,  // quantas "telas" para trás (-) ou para frente (+) de hoje
    dados: null,      // último JSON recebido
    hojeMs: null,     // "hoje" do servidor, em ms UTC
    tipos: {},        // id -> {nome, cor}
  };

  // -------------------------------------------------------------------------
  // Utilitários
  // -------------------------------------------------------------------------
  // Datas em ms UTC (meia-noite): sem fuso nem horário de verão no meio.
  function isoParaMs(iso) {
    var p = String(iso).split('-');
    return Date.UTC(+p[0], +p[1] - 1, +p[2]);
  }

  function doisDigitos(n) { return (n < 10 ? '0' : '') + n; }

  function msParaBr(ms, comAno) {
    var d = new Date(ms);
    return doisDigitos(d.getUTCDate()) + '/' + doisDigitos(d.getUTCMonth() + 1) + (comAno ? '/' + d.getUTCFullYear() : '');
  }

  function isoParaBr(iso) { return msParaBr(isoParaMs(iso), true); }

  // Cria um elemento com classe e texto (sempre textContent).
  function criar(tag, classe, texto) {
    var no = document.createElement(tag);
    if (classe) no.className = classe;
    if (texto != null) no.textContent = texto;
    return no;
  }

  function corSegura(cor) { return RE_COR.test(cor || '') ? cor : COR_NEUTRA; }

  // Só caminho relativo ao site ("/ausencias/12/"): nada de javascript: etc.
  function urlSegura(url) { return /^\/(?!\/)/.test(url || '') ? url : null; }

  function plural(n, singular, plural_) { return n + ' ' + (n === 1 ? singular : plural_); }

  // -------------------------------------------------------------------------
  // Preferência de escala (único uso de localStorage)
  // -------------------------------------------------------------------------
  function lerEscalaSalva() {
    try {
      var escala = window.localStorage.getItem(CHAVE_ESCALA);
      if (QUANTAS_COLUNAS[escala]) estado.escala = escala;
    } catch (e) { /* armazenamento indisponível: fica a padrão */ }
  }

  function salvarEscala() {
    try { window.localStorage.setItem(CHAVE_ESCALA, estado.escala); } catch (e) { /* ignora */ }
  }

  // -------------------------------------------------------------------------
  // Filtros -> querystring
  // -------------------------------------------------------------------------
  // Monta a querystring só com o que está preenchido. "Todos os
  // departamentos" = nenhum parâmetro; "sem registros" só vai quando
  // desmarcado (sem_registros=0), pois marcado é o padrão.
  function parametrosDosFiltros() {
    var parametros = new URLSearchParams();
    var q = formulario.elements.q.value.trim();
    if (q) parametros.append('q', q);
    formulario.querySelectorAll('input[name="departamento"]:checked').forEach(function (caixa) {
      parametros.append('departamento', caixa.value);
    });
    CAMPOS_DE_DATA.forEach(function (nome) {
      var valor = formulario.elements[nome].value;
      if (valor) parametros.append(nome, valor);
    });
    var semRegistros = formulario.querySelector('input[type="checkbox"][name="sem_registros"]');
    if (semRegistros && !semRegistros.checked) parametros.append('sem_registros', '0');
    return parametros.toString();
  }

  // -------------------------------------------------------------------------
  // Busca dos dados (descarta respostas fora de ordem)
  // -------------------------------------------------------------------------
  var numeroRequisicao = 0;
  var controleAtual = null;

  function carregar() {
    var querystring = parametrosDosFiltros();
    // URL compartilhável sem recarregar a página.
    window.history.replaceState(null, '', window.location.pathname + (querystring ? '?' + querystring : ''));

    if (controleAtual && window.AbortController) controleAtual.abort();
    controleAtual = window.AbortController ? new AbortController() : null;
    var numero = ++numeroRequisicao;
    mostrarCarregando(true);

    fetch(urlDados + (querystring ? '?' + querystring : ''), {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
      cache: 'no-store',
      signal: controleAtual ? controleAtual.signal : undefined,
    })
      .then(function (resposta) {
        var tipo = resposta.headers.get('Content-Type') || '';
        // Sessão expirada: o fetch segue o redirecionamento e recebe o HTML do login.
        if (!resposta.ok || tipo.indexOf('application/json') !== 0) {
          throw new Error(resposta.redirected ? 'sessao' : 'http');
        }
        return resposta.json();
      })
      .then(function (dados) {
        if (numero !== numeroRequisicao) return;  // chegou outra mais nova
        receberDados(dados);
        mostrarCarregando(false);
      })
      .catch(function (erro) {
        if (erro && erro.name === 'AbortError') return;
        if (numero !== numeroRequisicao) return;
        mostrarCarregando(false);
        mostrarErro(erro && erro.message === 'sessao'
          ? 'Sua sessão expirou. Recarregue a página para entrar de novo.'
          : 'Não foi possível carregar o painel. Tente novamente em instantes.');
      });
  }

  // Espera o usuário parar de digitar/alterar antes de buscar.
  var temporizador = null;
  function carregarEmInstantes() {
    window.clearTimeout(temporizador);
    temporizador = window.setTimeout(carregar, ESPERA_DIGITACAO_MS);
  }

  function receberDados(dados) {
    estado.dados = dados;
    estado.hojeMs = isoParaMs(dados.hoje);
    estado.tipos = {};
    (dados.tipos || []).forEach(function (tipo) {
      estado.tipos[tipo.id] = { nome: tipo.nome, cor: corSegura(tipo.cor) };
    });
    mostrarErro('');
    mostrarAvisos(dados.avisos || []);
    mostrarCapacidade(dados.capacidade);
    desenharLegenda(dados.tipos || []);
    desenhar();
  }

  // -------------------------------------------------------------------------
  // Mensagens
  // -------------------------------------------------------------------------
  function mostrarCarregando(sim) { el.carregando.classList.toggle('d-none', !sim); }

  function mostrarErro(texto) {
    el.erro.textContent = texto;
    el.erro.classList.toggle('d-none', !texto);
  }

  function mostrarAvisos(avisos) {
    el.avisos.replaceChildren();
    avisos.forEach(function (aviso) { el.avisos.appendChild(criar('div', 'alert alert-warning', aviso)); });
  }

  // A capacidade vem calculada e formatada do servidor; aqui só aparece.
  function mostrarCapacidade(capacidade) {
    if (!el.capacidade) return;
    el.capacidade.querySelector('[data-capacidade-texto]').textContent = capacidade ? capacidade.texto : '';
    el.capacidade.querySelector('[data-capacidade-detalhe]').textContent = capacidade ? capacidade.detalhe : '';
    el.capacidade.classList.toggle('d-none', !capacidade);
  }

  function desenharLegenda(tipos) {
    el.legenda.replaceChildren();
    tipos.forEach(function (tipo) {
      var item = criar('span');
      var quadrado = criar('i');
      quadrado.style.setProperty('--cor-tipo', corSegura(tipo.cor));
      quadrado.setAttribute('aria-hidden', 'true');
      item.appendChild(quadrado);
      item.appendChild(document.createTextNode(tipo.nome));
      el.legenda.appendChild(item);
    });
  }

  // -------------------------------------------------------------------------
  // Colunas da escala atual: [{a, b}] em ms, b exclusivo
  // -------------------------------------------------------------------------
  function colunas() {
    var hoje = estado.hojeMs, n = QUANTAS_COLUNAS[estado.escala], lista = [], i, a;
    if (estado.escala === 'dia') {
      var inicioDia = hoje + estado.deslocamento * n * DIA_MS;
      for (i = 0; i < n; i++) { a = inicioDia + i * DIA_MS; lista.push({ a: a, b: a + DIA_MS }); }
    } else if (estado.escala === 'sem') {
      var diaDaSemana = (new Date(hoje).getUTCDay() + 6) % 7;  // segunda = 0
      var inicioSemana = hoje - diaDaSemana * DIA_MS + estado.deslocamento * n * 7 * DIA_MS;
      for (i = 0; i < n; i++) { a = inicioSemana + i * 7 * DIA_MS; lista.push({ a: a, b: a + 7 * DIA_MS }); }
    } else {
      var d = new Date(hoje), mesAbsoluto = d.getUTCFullYear() * 12 + d.getUTCMonth() + estado.deslocamento * n;
      for (i = 0; i < n; i++) {
        var ano = Math.floor((mesAbsoluto + i) / 12), mes = (mesAbsoluto + i) % 12;
        lista.push({ a: Date.UTC(ano, mes, 1), b: Date.UTC(ano, mes + 1, 1) });
      }
    }
    return lista;
  }

  function ehHoje(coluna) { return estado.hojeMs >= coluna.a && estado.hojeMs < coluna.b; }

  function ehFimDeSemana(coluna) {
    if (estado.escala !== 'dia') return false;
    var dia = new Date(coluna.a).getUTCDay();
    return dia === 0 || dia === 6;
  }

  function classesDaColuna(coluna) {
    return (ehFimDeSemana(coluna) ? ' fim-de-semana' : '') + (ehHoje(coluna) ? ' hoje' : '');
  }

  // -------------------------------------------------------------------------
  // Cabeçalho em dois níveis: mês/ano agrupado em cima, dias/semanas/meses embaixo
  // -------------------------------------------------------------------------
  function cabecalho(cols) {
    var thead = criar('thead');
    var linhaGrupos = criar('tr');
    var linhaColunas = criar('tr');

    var nome = criar('th', 'painel-col-nome', 'Colaborador');
    nome.rowSpan = 2;
    nome.scope = 'col';
    linhaGrupos.appendChild(nome);

    var grupos = [], ultimo = null;
    cols.forEach(function (coluna) {
      var d = new Date(coluna.a), chave, rotulo;
      if (estado.escala === 'mes') { chave = String(d.getUTCFullYear()); rotulo = chave; }
      else { chave = d.getUTCFullYear() + '-' + d.getUTCMonth(); rotulo = MESES[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); }
      if (ultimo && ultimo.chave === chave) ultimo.n++;
      else { ultimo = { chave: chave, rotulo: rotulo, n: 1 }; grupos.push(ultimo); }
    });
    grupos.forEach(function (grupo) {
      var th = criar('th', null, grupo.rotulo);
      th.colSpan = grupo.n;
      th.scope = 'colgroup';
      linhaGrupos.appendChild(th);
    });

    cols.forEach(function (coluna) {
      var d = new Date(coluna.a), th = criar('th', classesDaColuna(coluna).trim() || null);
      th.scope = 'col';
      if (estado.escala === 'dia') {
        th.appendChild(criar('span', 'painel-dia-semana', DIAS_SEMANA[d.getUTCDay()]));
        th.appendChild(criar('span', 'painel-dia-numero', String(d.getUTCDate())));
        th.title = msParaBr(coluna.a, true);
      } else if (estado.escala === 'sem') {
        th.appendChild(criar('span', 'painel-dia-semana', 'sem.'));
        th.appendChild(criar('span', 'painel-dia-numero', msParaBr(coluna.a)));
        th.title = 'Semana de ' + msParaBr(coluna.a, true) + ' a ' + msParaBr(coluna.b - DIA_MS, true);
      } else {
        th.appendChild(criar('span', 'painel-dia-numero', MESES_CURTOS[d.getUTCMonth()]));
        th.title = MESES[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
      }
      linhaColunas.appendChild(th);
    });

    thead.appendChild(linhaGrupos);
    thead.appendChild(linhaColunas);
    return thead;
  }

  // -------------------------------------------------------------------------
  // Linha de uma pessoa
  // -------------------------------------------------------------------------
  // Faixas (lanes): cada período vai na primeira faixa livre, para que
  // períodos sobrepostos não fiquem um em cima do outro.
  function distribuirEmFaixas(periodos) {
    var ordenados = periodos.slice().sort(function (x, y) {
      return x.inicio < y.inicio ? -1 : x.inicio > y.inicio ? 1 : x.fim < y.fim ? -1 : x.fim > y.fim ? 1 : 0;
    });
    var fimDaFaixa = [], faixas = 1;
    var itens = ordenados.map(function (periodo) {
      var faixa = 0;
      while (fimDaFaixa[faixa] !== undefined && fimDaFaixa[faixa] >= periodo.inicio) faixa++;
      fimDaFaixa[faixa] = periodo.fim;
      if (faixa + 1 > faixas) faixas = faixa + 1;
      return { periodo: periodo, faixa: faixa, a: isoParaMs(periodo.inicio), b: isoParaMs(periodo.fim) + DIA_MS };
    });
    return { itens: itens, faixas: faixas };
  }

  function descricaoDoPeriodo(pessoa, periodo) {
    var tipo = estado.tipos[periodo.tipo_id];
    var nomeTipo = tipo ? tipo.nome : 'Ausência';
    return {
      titulo: nomeTipo + '\nSituação: ' + periodo.situacao + '\n' + isoParaBr(periodo.inicio) + ' a '
        + isoParaBr(periodo.fim) + ' · ' + plural(periodo.dias, 'dia', 'dias'),
      rotulo: pessoa.nome + ': ' + nomeTipo + ', ' + periodo.situacao + ', de ' + isoParaBr(periodo.inicio) + ' a '
        + isoParaBr(periodo.fim) + ', ' + plural(periodo.dias, 'dia', 'dias') + '. Abrir detalhe.',
      cor: tipo ? tipo.cor : COR_NEUTRA,
    };
  }

  // Barra (pedaço do período dentro de uma coluna). É um link para o
  // detalhe: clique, Enter e "abrir em nova aba" funcionam sozinhos. Só o
  // primeiro pedaço de cada período entra na ordem do Tab.
  function barra(item, coluna, descricao, primeiroPedaco) {
    var url = urlSegura(item.periodo.url);
    var no = criar(url ? 'a' : 'span', 'painel-barra');
    var inicio = Math.max(item.a, coluna.a), fim = Math.min(item.b, coluna.b), largura = coluna.b - coluna.a;
    if (item.a >= coluna.a) no.classList.add('borda-esquerda');
    if (item.b <= coluna.b) no.classList.add('borda-direita');
    no.style.left = ((inicio - coluna.a) / largura * 100).toFixed(2) + '%';
    no.style.width = ((fim - inicio) / largura * 100).toFixed(2) + '%';
    no.style.top = (MARGEM_VERTICAL + item.faixa * ALTURA_FAIXA) + 'px';
    no.style.height = (ALTURA_FAIXA - 2) + 'px';
    no.style.setProperty('--cor-tipo', descricao.cor);
    no.title = descricao.titulo;
    if (url) no.href = url;
    if (primeiroPedaco) {
      no.setAttribute('aria-label', descricao.rotulo);
    } else {
      no.setAttribute('aria-hidden', 'true');
      no.tabIndex = -1;
    }
    return no;
  }

  function linhaDaPessoa(pessoa, cols) {
    var distribuicao = distribuirEmFaixas(pessoa.periodos || []);
    var tr = criar('tr');
    tr.style.height = Math.max(distribuicao.faixas * ALTURA_FAIXA + MARGEM_VERTICAL * 2, ALTURA_MINIMA_LINHA) + 'px';

    var nome = criar('th', 'painel-nome', pessoa.nome);
    nome.scope = 'row';
    nome.title = pessoa.departamento ? pessoa.nome + ' (' + pessoa.departamento + ')' : pessoa.nome;
    if (pessoa.departamento) nome.appendChild(criar('small', null, pessoa.departamento));
    tr.appendChild(nome);

    var celulas = cols.map(function (coluna) {
      var td = criar('td', classesDaColuna(coluna).trim() || null);
      tr.appendChild(td);
      return td;
    });

    distribuicao.itens.forEach(function (item) {
      var descricao = descricaoDoPeriodo(pessoa, item.periodo);
      var primeiro = true;
      cols.forEach(function (coluna, i) {
        if (item.a >= coluna.b || item.b <= coluna.a) return;
        celulas[i].appendChild(barra(item, coluna, descricao, primeiro));
        primeiro = false;
      });
    });
    return tr;
  }

  // -------------------------------------------------------------------------
  // Desenho completo
  // -------------------------------------------------------------------------
  function atualizarBotoesDeEscala() {
    palco.querySelectorAll('[data-escala]').forEach(function (botao) {
      var ativo = botao.getAttribute('data-escala') === estado.escala;
      botao.setAttribute('aria-pressed', String(ativo));
      botao.classList.toggle('active', ativo);
    });
  }

  function desenhar() {
    atualizarBotoesDeEscala();
    if (!estado.dados) return;

    var pessoas = estado.dados.pessoas || [];
    var cols = colunas();
    var largura = LARGURA_COLUNA[estado.escala];

    el.contador.textContent = 'Mostrando ' + plural(pessoas.length, 'colaborador', 'colaboradores');
    el.intervalo.textContent = msParaBr(cols[0].a, true) + ' – ' + msParaBr(cols[cols.length - 1].b - DIA_MS, true);

    var colgroup = criar('colgroup');
    var colNome = criar('col');
    colNome.style.width = 'var(--painel-nome)';
    colgroup.appendChild(colNome);
    // Colunas de período sem largura própria: com table-layout fixed, dividem
    // igualmente o que sobra da coluna do nome. A tabela ocupa toda a largura
    // do contêiner e só fica mais larga (com rolagem) quando as colunas
    // ficariam menores que a largura mínima da escala.
    cols.forEach(function () { colgroup.appendChild(criar('col')); });

    var tbody = criar('tbody');
    pessoas.forEach(function (pessoa) { tbody.appendChild(linhaDaPessoa(pessoa, cols)); });

    el.gantt.style.width = 'max(100%, calc(var(--painel-nome) + ' + (cols.length * largura) + 'px))';
    el.gantt.replaceChildren(colgroup, cabecalho(cols), tbody);
    el.vazio.classList.toggle('d-none', pessoas.length > 0);
    el.rolagem.scrollLeft = 0;
  }

  // -------------------------------------------------------------------------
  // Escala e navegação
  // -------------------------------------------------------------------------
  function iniciarEscalaENavegacao() {
    palco.querySelectorAll('[data-escala]').forEach(function (botao) {
      botao.addEventListener('click', function () {
        estado.escala = botao.getAttribute('data-escala');
        estado.deslocamento = 0;
        salvarEscala();
        desenhar();
      });
    });
    palco.querySelectorAll('[data-navegar]').forEach(function (botao) {
      botao.addEventListener('click', function () {
        var passo = Number(botao.getAttribute('data-navegar'));
        estado.deslocamento = passo === 0 ? 0 : estado.deslocamento + passo;
        desenhar();
      });
    });
  }

  // -------------------------------------------------------------------------
  // Tela cheia: modo de página inteira; usa também a do navegador quando
  // permitida. Esc sai nos dois casos.
  // -------------------------------------------------------------------------
  var telaCheia = false, telaCheiaNativa = false;

  function definirTelaCheia(ligar) {
    telaCheia = ligar;
    palco.classList.toggle('tela-cheia', ligar);
    document.body.classList.toggle('painel-em-tela-cheia', ligar);
    el.telaCheia.setAttribute('aria-pressed', String(ligar));
    el.telaCheia.querySelector('span').textContent = ligar ? 'Sair da tela cheia' : 'Tela cheia';
    var icone = el.telaCheia.querySelector('i');
    icone.classList.toggle('fa-expand', !ligar);
    icone.classList.toggle('fa-compress', ligar);
    if (ligar) {
      try {
        var promessa = palco.requestFullscreen && palco.requestFullscreen();
        if (promessa && promessa.then) {
          promessa.then(function () { telaCheiaNativa = true; }, function () { telaCheiaNativa = false; });
        }
      } catch (e) { telaCheiaNativa = false; }
    } else if (document.fullscreenElement) {
      try { document.exitFullscreen(); } catch (e) { /* ignora */ }
      telaCheiaNativa = false;
    }
  }

  function iniciarTelaCheia() {
    el.telaCheia.addEventListener('click', function () { definirTelaCheia(!telaCheia); });
    // Esc na tela cheia do navegador: ele sai sozinho e avisa aqui.
    document.addEventListener('fullscreenchange', function () {
      if (!document.fullscreenElement && telaCheiaNativa && telaCheia) {
        telaCheiaNativa = false;
        definirTelaCheia(false);
      }
    });
    document.addEventListener('keydown', function (evento) {
      if (evento.key === 'Escape' && telaCheia && !telaCheiaNativa) definirTelaCheia(false);
    });
  }

  // -------------------------------------------------------------------------
  // Multisseleção de departamentos
  // -------------------------------------------------------------------------
  var caixaDepartamentos = document.getElementById('filtro-departamentos');

  function departamentosMarcados() {
    return Array.prototype.slice.call(caixaDepartamentos.querySelectorAll('input[name="departamento"]:checked'));
  }

  // Mesmo texto de painel_service.rotulo_departamentos.
  function atualizarResumoDepartamentos() {
    var marcados = departamentosMarcados();
    var texto = marcados.length === 0 ? 'Todos'
      : marcados.length === 1 ? marcados[0].getAttribute('data-nome')
        : marcados.length + ' departamentos';
    caixaDepartamentos.querySelector('[data-resumo]').textContent = texto;
  }

  function iniciarDepartamentos() {
    if (!caixaDepartamentos) return;
    var todos = caixaDepartamentos.querySelector('[data-todos]');

    caixaDepartamentos.addEventListener('change', function (evento) {
      if (evento.target === todos) {
        // Marcar "Todos" limpa os demais; não dá para desmarcá-lo sozinho.
        if (todos.checked) departamentosMarcados().forEach(function (caixa) { caixa.checked = false; });
        else if (departamentosMarcados().length === 0) todos.checked = true;
      } else {
        // Desmarcar tudo volta a "Todos".
        todos.checked = departamentosMarcados().length === 0;
      }
      atualizarResumoDepartamentos();
    });

    // Fecha ao clicar fora ou no Esc (dentro dele, continua aberto).
    document.addEventListener('click', function (evento) {
      if (caixaDepartamentos.open && !caixaDepartamentos.contains(evento.target)) caixaDepartamentos.open = false;
    });
    caixaDepartamentos.addEventListener('keydown', function (evento) {
      if (evento.key === 'Escape' && caixaDepartamentos.open) {
        evento.stopPropagation();
        caixaDepartamentos.open = false;
        caixaDepartamentos.querySelector('summary').focus();
      }
    });
  }

  // -------------------------------------------------------------------------
  // Formulário de filtros
  // -------------------------------------------------------------------------
  function limparFiltros() {
    formulario.elements.q.value = '';
    CAMPOS_DE_DATA.forEach(function (nome) {
      formulario.elements[nome].value = '';
    });
    formulario.querySelectorAll('input[name="departamento"]').forEach(function (caixa) { caixa.checked = false; });
    var todos = formulario.querySelector('[data-todos]');
    if (todos) todos.checked = true;
    var semRegistros = formulario.querySelector('input[type="checkbox"][name="sem_registros"]');
    if (semRegistros) semRegistros.checked = true;
    if (caixaDepartamentos) atualizarResumoDepartamentos();
  }

  function iniciarFiltros() {
    formulario.addEventListener('input', carregarEmInstantes);
    formulario.addEventListener('change', carregarEmInstantes);
    // "Aplicar" busca na hora, sem recarregar a página.
    formulario.addEventListener('submit', function (evento) {
      evento.preventDefault();
      window.clearTimeout(temporizador);
      carregar();
    });
    var limpar = formulario.querySelector('[data-limpar]');
    if (limpar) {
      limpar.addEventListener('click', function (evento) {
        evento.preventDefault();
        limparFiltros();
        window.clearTimeout(temporizador);
        carregar();
      });
    }
  }

  // -------------------------------------------------------------------------
  // Início
  // -------------------------------------------------------------------------
  lerEscalaSalva();
  iniciarEscalaENavegacao();
  iniciarTelaCheia();
  iniciarDepartamentos();
  iniciarFiltros();
  palco.hidden = false;
  atualizarBotoesDeEscala();
  carregar();
})();
