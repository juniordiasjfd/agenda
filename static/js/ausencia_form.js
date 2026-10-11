/* Tela de registro/edição de ausência.
 *
 * Só comportamento de tela: linhas do formset (adicionar/remover), dias e
 * aviso de período no passado. Validação e conflitos ficam no servidor.
 */
document.addEventListener('alpine:init', function () {
  // Lista de períodos. Linha nova = cópia do empty_form (<template x-ref="modelo">)
  // com o próximo índice; remover marca o DELETE e esconde a linha (o
  // formset continua com os índices contínuos).
  Alpine.data('periodosForm', function (maximo) {
    return {
      maximo: maximo,
      ativas: 0,

      init: function () {
        this.renumerar();
      },

      linhas: function () {
        return Array.prototype.slice.call(this.$refs.lista.querySelectorAll(':scope > .periodo'));
      },

      adicionar: function () {
        if (this.ativas >= this.maximo) return;
        var total = this.$root.querySelector('input[name$="-TOTAL_FORMS"]');
        var indice = Number(total.value);
        var html = this.$refs.modelo.innerHTML.replace(/__prefix__/g, String(indice));
        this.$refs.lista.insertAdjacentHTML('beforeend', html);
        total.value = indice + 1;
        this.renumerar();
        var nova = this.$refs.lista.lastElementChild;
        this.$nextTick(function () {
          var campo = nova.querySelector('input[type="date"]');
          if (campo) campo.focus();
        });
      },

      remover: function (botao) {
        var linha = botao.closest('.periodo');
        var marcador = linha.querySelector('input[name$="-DELETE"]');
        if (marcador) marcador.checked = true;
        linha.hidden = true;
        this.renumerar();
      },

      // Numera as linhas visíveis como o servidor numera os períodos.
      renumerar: function () {
        var numero = 0;
        this.linhas().forEach(function (linha) {
          if (linha.hidden) return;
          numero += 1;
          linha.querySelector('.periodo-numero').textContent = numero;
        });
        this.ativas = numero;
      },
    };
  });

  // Uma linha: dias corridos (fim inclusivo) e aviso de início antes de
  // hoje. Lê os próprios campos, então funciona também depois de o servidor
  // devolver a tela com erros.
  Alpine.data('linhaPeriodo', function () {
    return {
      dias: 0,
      passado: false,

      init: function () {
        this.atualizar();
      },

      valor: function (campo) {
        var entrada = this.$root.querySelector('input[name$="-' + campo + '"]');
        return entrada ? entrada.value : '';
      },

      atualizar: function () {
        var inicio = this.valor('data_inicio');
        var fim = this.valor('data_fim');
        var referencia = this.$root.closest('[data-hoje]');
        var hoje = referencia ? referencia.dataset.hoje : '';
        // Datas ISO (aaaa-mm-dd) comparam como texto.
        this.passado = Boolean(inicio && hoje && inicio < hoje);
        this.dias = (inicio && fim && fim >= inicio)
          ? Math.round((Date.parse(fim) - Date.parse(inicio)) / 864e5) + 1
          : 0;
      },

      get textoDias() {
        if (!this.dias) return '';
        return this.dias === 1 ? '1 dia' : this.dias + ' dias';
      },
    };
  });
});

// Busca do colaborador sem considerar acentos (Tom Select).
document.addEventListener('DOMContentLoaded', function () {
  var campo = document.getElementById('id_colaborador');
  if (!campo || typeof TomSelect === 'undefined') return;
  new TomSelect(campo, {
    create: false,
    maxOptions: null,
    allowEmptyOption: false,
    placeholder: 'Digite para buscar...',
    diacritics: true,
  });
});
