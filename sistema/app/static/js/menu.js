// Barra de navegacao animada.
//
// 1. Entrada: a barra desce e os itens aparecem em sequencia, so na primeira
//    pagina da sessao do navegador (nas seguintes, aparece direto).
// 2. Indicador: a pilula branca desliza ate o item sob o mouse (ou com foco
//    do teclado) e volta para a pagina atual ao sair do menu.
//
// Sem JavaScript, o menu continua funcionando: o item atual ja vem com a
// pilula pelo CSS (.ativo).
(function () {
  "use strict";

  var topo = document.querySelector(".topo");
  var menu = document.querySelector(".menu");
  if (!topo) return;

  // --- 1. Entrada ---------------------------------------------------------
  try {
    if (!sessionStorage.getItem("ge-menu-visto")) {
      topo.classList.add("topo-entrada");
      sessionStorage.setItem("ge-menu-visto", "1");
    }
  } catch (e) {
    // sessionStorage bloqueado: segue sem a animacao de entrada.
  }

  // --- 2. Indicador deslizante -------------------------------------------
  // Visitante nao tem menu (so o logo e os botoes de acesso).
  if (!menu) return;
  var links = Array.prototype.slice.call(menu.querySelectorAll("a"));
  if (!links.length) return;

  var indicador = document.createElement("span");
  indicador.className = "menu-indicador";
  indicador.setAttribute("aria-hidden", "true");
  menu.insertBefore(indicador, menu.firstChild);

  var ativo = menu.querySelector("a.ativo");
  var atual = null;

  function moverPara(link, semTransicao) {
    if (atual) atual.classList.remove("sob-indicador");
    atual = link;

    if (!link) {
      indicador.style.opacity = "0";
      return;
    }
    if (semTransicao) indicador.classList.add("sem-transicao");
    indicador.style.width = link.offsetWidth + "px";
    indicador.style.height = link.offsetHeight + "px";
    indicador.style.transform = "translate(" + link.offsetLeft + "px, " + link.offsetTop + "px)";
    indicador.style.opacity = "1";
    link.classList.add("sob-indicador");
    if (semTransicao) {
      // Forca o layout antes de religar a transicao.
      void indicador.offsetWidth;
      indicador.classList.remove("sem-transicao");
    }
  }

  menu.classList.add("menu-com-indicador");
  moverPara(ativo, true);

  links.forEach(function (link) {
    link.addEventListener("mouseenter", function () { moverPara(link); });
    link.addEventListener("focus", function () { moverPara(link); });
  });
  menu.addEventListener("mouseleave", function () { moverPara(ativo); });
  menu.addEventListener("focusout", function (evento) {
    if (!menu.contains(evento.relatedTarget)) moverPara(ativo);
  });

  // O menu quebra de linha no celular: reposiciona ao mudar o tamanho e
  // quando as fontes terminam de carregar.
  window.addEventListener("resize", function () { moverPara(atual, true); });

  // Logo apos o login os itens chegam abrindo espaco (.topo-revelar) e os
  // vizinhos se deslocam: a pilula acompanha quadro a quadro ate acabar.
  if (topo.classList.contains("topo-revelar") && window.requestAnimationFrame) {
    var fim = performance.now() + 1500;
    (function acompanhar() {
      if (atual) moverPara(atual, true);
      if (performance.now() < fim) requestAnimationFrame(acompanhar);
    })();
  }
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () { moverPara(atual, true); });
  }
})();
