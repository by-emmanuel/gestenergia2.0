/* Grafico de consumo real x previsto do painel (issue #20).
 *
 * Chart.js servido pelo proprio sistema, de app/static/vendor/. Nenhuma
 * biblioteca de CDN: a maquina do laboratorio pode estar sem internet.
 *
 * As escolhas visuais seguem as especificacoes de marca adotadas no projeto:
 *   - linha de 2px, ponto de 8px com anel de 2px na cor da superficie;
 *   - grade em fio solido e recessivo (tracejado leria como projecao ou limite);
 *   - um unico eixo Y: as duas series sao kWh, e dois eixos distorceriam a leitura;
 *   - crosshair vertical com um tooltip que lista as DUAS series no mesmo instante,
 *     para o leitor nao precisar acertar a linha com o mouse;
 *   - a linha do previsto e tracejada, o que distingue as series por forma e nao
 *     so por cor;
 *   - spanGaps desligado: onde nao houve previsao a linha CORTA. Ligar os pontos
 *     inventaria continuidade que o dado nao tem.
 */

(function () {
  "use strict";

  const elemento = document.getElementById("grafico-consumo");
  const fonteDeDados = document.getElementById("dados-do-grafico");
  if (!elemento || !fonteDeDados || typeof Chart === "undefined") {
    return;
  }

  const dados = JSON.parse(fonteDeDados.textContent);
  const script = document.currentScript || document.querySelector("script[data-cor-real]");
  const corReal = script.dataset.corReal;
  const corPrevisto = script.dataset.corPrevisto;

  // Tons de apresentacao, um passo acima da superficie: a grade e os eixos nao
  // competem com o dado.
  const SUPERFICIE = "#ffffff";
  const FIO_DA_GRADE = "#e1e0d9";
  const TINTA_FRACA = "#898781";
  const TINTA = "#52606d";

  /* Crosshair: uma linha vertical no instante apontado. O leitor mira numa data,
   * nunca numa linha de 2px. */
  const crosshair = {
    id: "crosshair",
    afterDatasetsDraw(grafico) {
      const ativos = grafico.tooltip?.getActiveElements?.() || [];
      if (!ativos.length) {
        return;
      }
      const x = ativos[0].element.x;
      const { top, bottom } = grafico.chartArea;
      const pincel = grafico.ctx;
      pincel.save();
      pincel.beginPath();
      pincel.moveTo(x, top);
      pincel.lineTo(x, bottom);
      pincel.lineWidth = 1;
      pincel.strokeStyle = TINTA_FRACA;
      pincel.stroke();
      pincel.restore();
    },
  };

  const comVirgula = (valor) =>
    valor === null || valor === undefined ? "sem previsão" : valor.toFixed(3).replace(".", ",");

  new Chart(elemento, {
    type: "line",
    data: {
      labels: dados.rotulos,
      datasets: [
        {
          label: "Consumo real",
          data: dados.real,
          borderColor: corReal,
          backgroundColor: corReal,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBorderWidth: 2,
          pointHoverBorderColor: SUPERFICIE,
          tension: 0,
        },
        {
          label: "Consumo previsto",
          data: dados.previsto,
          borderColor: corPrevisto,
          backgroundColor: corPrevisto,
          borderWidth: 2,
          borderDash: [6, 4],
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBorderWidth: 2,
          pointHoverBorderColor: SUPERFICIE,
          tension: 0,
          // Onde nao houve previsao, a linha corta.
          spanGaps: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      // O ponteiro so precisa estar no mesmo instante, nao sobre a linha.
      interaction: { mode: "index", intersect: false },
      plugins: {
        // A legenda em HTML ja esta no template, com texto: identidade nunca so
        // por cor, e sem depender de JavaScript para existir.
        legend: { display: false },
        tooltip: {
          backgroundColor: "#1f2933",
          padding: 10,
          displayColors: true,
          // Valor primeiro, nome depois: quem olha o tooltip ja sabe a serie e
          // quer o numero.
          callbacks: {
            label: (contexto) => `${comVirgula(contexto.parsed.y)} kWh — ${contexto.dataset.label}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: TINTA_FRACA, maxRotation: 0, autoSkipPadding: 24 },
          border: { color: FIO_DA_GRADE },
        },
        y: {
          title: { display: true, text: "kWh", color: TINTA },
          beginAtZero: true,
          grid: { color: FIO_DA_GRADE, drawTicks: false },
          ticks: { color: TINTA_FRACA, padding: 8 },
          border: { display: false },
        },
      },
    },
    plugins: [crosshair],
  });
})();
