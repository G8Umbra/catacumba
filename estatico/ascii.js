// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
(() => {
  // The banner font below was authored from scratch for this project: every glyph is a short list of strokes on a
  // 5 x 5 grid (no table or font from elsewhere was used or copied).
  // Strokes: ["H", row, col0, col1] horizontal, ["V", col, row0, row1] vertical, ["D", row0, col0, row1, col1] diagonal,
  // ["P", row, col] single block.
  const TRAZOS = {
    A: [["V", 0, 1, 4], ["V", 4, 1, 4], ["H", 0, 1, 3], ["H", 2, 0, 4]],
    B: [["V", 0, 0, 4], ["H", 0, 0, 3], ["H", 2, 0, 3], ["H", 4, 0, 3], ["P", 1, 4], ["P", 3, 4]],
    C: [["V", 0, 1, 3], ["H", 0, 1, 4], ["H", 4, 1, 4]],
    D: [["V", 0, 0, 4], ["H", 0, 0, 3], ["H", 4, 0, 3], ["V", 4, 1, 3]],
    E: [["V", 0, 0, 4], ["H", 0, 0, 4], ["H", 2, 0, 3], ["H", 4, 0, 4]],
    F: [["V", 0, 0, 4], ["H", 0, 0, 4], ["H", 2, 0, 3]],
    G: [["V", 0, 1, 3], ["H", 0, 1, 4], ["H", 4, 1, 4], ["V", 4, 2, 3], ["H", 2, 2, 4]],
    H: [["V", 0, 0, 4], ["V", 4, 0, 4], ["H", 2, 0, 4]],
    I: [["H", 0, 1, 3], ["H", 4, 1, 3], ["V", 2, 0, 4]],
    J: [["V", 4, 0, 3], ["H", 4, 0, 3], ["P", 3, 0]],
    K: [["V", 0, 0, 4], ["H", 2, 0, 2], ["D", 2, 2, 0, 4], ["D", 2, 2, 4, 4]],
    L: [["V", 0, 0, 4], ["H", 4, 0, 4]],
    M: [["V", 0, 0, 4], ["V", 4, 0, 4], ["D", 0, 0, 2, 2], ["D", 0, 4, 2, 2]],
    N: [["V", 0, 0, 4], ["V", 4, 0, 4], ["D", 0, 0, 4, 4]],
    O: [["V", 0, 1, 3], ["V", 4, 1, 3], ["H", 0, 1, 3], ["H", 4, 1, 3]],
    P: [["V", 0, 0, 4], ["H", 0, 0, 3], ["H", 2, 0, 3], ["P", 1, 4]],
    Q: [["V", 0, 1, 3], ["V", 4, 1, 3], ["H", 0, 1, 3], ["H", 4, 1, 3], ["D", 3, 3, 4, 4]],
    R: [["V", 0, 0, 4], ["H", 0, 0, 3], ["H", 2, 0, 3], ["P", 1, 4], ["D", 2, 2, 4, 4]],
    S: [["H", 0, 1, 4], ["P", 1, 0], ["H", 2, 1, 3], ["P", 3, 4], ["H", 4, 0, 3]],
    T: [["H", 0, 0, 4], ["V", 2, 0, 4]],
    U: [["V", 0, 0, 3], ["V", 4, 0, 3], ["H", 4, 1, 3]],
    V: [["V", 0, 0, 2], ["V", 4, 0, 2], ["D", 2, 0, 4, 2], ["D", 2, 4, 4, 2]],
    W: [["V", 0, 0, 3], ["V", 4, 0, 3], ["P", 4, 1], ["P", 4, 3], ["V", 2, 1, 3]],
    X: [["D", 0, 0, 4, 4], ["D", 0, 4, 4, 0]],
    Y: [["D", 0, 0, 2, 2], ["D", 0, 4, 2, 2], ["V", 2, 2, 4]],
    Z: [["H", 0, 0, 4], ["H", 4, 0, 4], ["D", 0, 4, 4, 0]],
    "0": [["V", 0, 1, 3], ["V", 4, 1, 3], ["H", 0, 1, 3], ["H", 4, 1, 3], ["P", 2, 2]],
    "1": [["P", 1, 1], ["V", 2, 0, 4], ["H", 4, 1, 3]],
    "2": [["H", 0, 1, 3], ["P", 1, 0], ["P", 1, 4], ["P", 2, 3], ["P", 3, 2], ["H", 4, 0, 4]],
    "3": [["H", 0, 0, 3], ["P", 1, 4], ["H", 2, 1, 3], ["P", 3, 4], ["H", 4, 0, 3]],
    "4": [["V", 3, 0, 4], ["D", 0, 3, 3, 0], ["H", 3, 0, 4]],
    "5": [["H", 0, 0, 4], ["P", 1, 0], ["H", 2, 0, 3], ["P", 3, 4], ["H", 4, 0, 3]],
    "6": [["H", 0, 1, 4], ["V", 0, 1, 4], ["H", 2, 1, 3], ["P", 3, 4], ["H", 4, 1, 3]],
    "7": [["H", 0, 0, 4], ["D", 1, 4, 4, 1]],
    "8": [["V", 0, 1, 3], ["V", 4, 1, 3], ["H", 0, 1, 3], ["H", 4, 1, 3], ["H", 2, 1, 3]],
    "9": [["H", 0, 1, 3], ["V", 0, 1, 2], ["V", 4, 1, 3], ["H", 2, 1, 3], ["H", 4, 1, 3]],
    " ": [],
    "-": [["H", 2, 1, 3]],
    _: [["H", 4, 0, 4]],
    "/": [["D", 0, 4, 4, 0]],
    "?": [["H", 0, 1, 3], ["P", 1, 4], ["P", 2, 3], ["P", 3, 2], ["P", 4, 2]],
    "!": [["V", 2, 0, 2], ["P", 4, 2]],
    ".": [["P", 4, 2]],
    ":": [["P", 1, 2], ["P", 3, 2]],
    "+": [["H", 2, 1, 3], ["V", 2, 1, 3]],
    "=": [["H", 1, 1, 3], ["H", 3, 1, 3]],
    "(": [["V", 1, 1, 3], ["P", 0, 2], ["P", 4, 2]],
    ")": [["V", 3, 1, 3], ["P", 0, 2], ["P", 4, 2]],
    "'": [["V", 2, 0, 1]],
  };

  function dibujar(trazos) {
    const rejilla = Array.from({ length: 5 }, () => Array(5).fill(" "));
    const poner = (fila, col) => { rejilla[fila][col] = "#"; };
    for (const [tipo, a, b, c, d] of trazos) {
      if (tipo === "H") for (let col = b; col <= c; col++) poner(a, col);
      else if (tipo === "V") for (let fila = b; fila <= c; fila++) poner(fila, a);
      else if (tipo === "P") poner(a, b);
      else if (tipo === "D") {
        const pasos = Math.max(Math.abs(c - a), Math.abs(d - b));
        for (let i = 0; i <= pasos; i++) poner(Math.round(a + ((c - a) * i) / pasos), Math.round(b + ((d - b) * i) / pasos));
      }
    }
    return rejilla.map((fila) => fila.join(""));
  }

  const fuente = Object.fromEntries(Object.entries(TRAZOS).map(([caracter, trazos]) => [caracter, dibujar(trazos)]));
  if (typeof module !== "undefined" && module.exports) {   // lets the test suite check the font under Node
    module.exports = { fuente };
    return;
  }

  const entrada = document.querySelector("#ascii-texto");
  const salida = document.querySelector("#ascii-output");
  const aviso = document.querySelector("#ascii-aviso");

  function generar() {
    const texto = entrada.value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
    const lineas = Array.from({ length: 5 }, () => "");
    for (const caracter of texto) {
      const glifo = fuente[caracter] || fuente["?"];
      for (let fila = 0; fila < lineas.length; fila++) lineas[fila] += glifo[fila] + " ";
    }
    salida.textContent = lineas.join("\n");
    aviso.textContent = "";
  }

  async function copiar() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(salida.textContent);
      } else {
        const campo = document.createElement("textarea");
        campo.value = salida.textContent;
        campo.setAttribute("readonly", "");
        campo.style.position = "fixed";
        campo.style.opacity = "0";
        document.body.append(campo);
        campo.select();
        const copiado = document.execCommand("copy");
        campo.remove();
        if (!copiado) throw new Error("Could not copy");
      }
      aviso.textContent = "Result copied.";
    } catch {
      aviso.textContent = "Could not copy the result.";
    }
  }

  entrada.addEventListener("input", generar);
  document.querySelector("#ascii-copiar").addEventListener("click", copiar);
  for (const boton of document.querySelectorAll("[data-ascii-preset]")) {
    boton.addEventListener("click", () => {
      entrada.value = boton.dataset.asciiPreset;
      generar();
      entrada.focus();
    });
  }
  generar();
})();