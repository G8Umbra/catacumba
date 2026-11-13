// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
(() => {
  const MODOS = {
    work: { etiqueta: "FOCUS", segundos: 25 * 60 },
    short: { etiqueta: "BREAK", segundos: 5 * 60 },
    long: { etiqueta: "LONG BREAK", segundos: 15 * 60 },
  };

  let modo = "work";
  let segundosTotales = MODOS.work.segundos;
  let segundosRestantes = segundosTotales;
  let sesionesCompletadas = 0;
  let terminaEn = 0;
  let intervalo = null;

  const reloj = document.querySelector("#pomodoro-reloj");
  const barra = document.querySelector("#pomodoro-progreso");
  const etiqueta = document.querySelector("#pomodoro-modo");
  const sesion = document.querySelector("#pomodoro-sesion");
  const aviso = document.querySelector("#pomodoro-aviso");
  const botonToggle = document.querySelector("#pomodoro-toggle");

  function dibujar() {
    const minutos = Math.floor(segundosRestantes / 60);
    const segundos = segundosRestantes % 60;
    reloj.textContent = `${String(minutos).padStart(2, "0")}:${String(segundos).padStart(2, "0")}`;
    barra.max = segundosTotales;
    barra.value = segundosRestantes;
    etiqueta.textContent = MODOS[modo].etiqueta;
    const numeroSesion = Math.min(sesionesCompletadas + (modo === "work" ? 1 : 0), 4) || 1;
    sesion.textContent = `Session ${numeroSesion}/4`;
    for (const boton of document.querySelectorAll("[data-pomodoro-mode]")) {
      boton.setAttribute("aria-pressed", String(boton.dataset.pomodoroMode === modo));
    }
  }

  function detener() {
    if (intervalo !== null) window.clearInterval(intervalo);
    intervalo = null;
    terminaEn = 0;
  }

  function tono() {
    try {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) return;
      const contexto = new Audio();
      const oscilador = contexto.createOscillator();
      const volumen = contexto.createGain();
      oscilador.type = "sine";
      oscilador.frequency.value = 587.33;
      volumen.gain.setValueAtTime(0.12, contexto.currentTime);
      volumen.gain.exponentialRampToValueAtTime(0.001, contexto.currentTime + 0.35);
      oscilador.connect(volumen);
      volumen.connect(contexto.destination);
      oscilador.start();
      oscilador.stop(contexto.currentTime + 0.35);
      oscilador.addEventListener("ended", () => contexto.close(), { once: true });
    } catch { /* El sonido depende de los permisos del navegador. */ }
  }

  function cambiarModo(nuevoModo, mensaje) {
    detener();
    modo = nuevoModo;
    segundosTotales = MODOS[modo].segundos;
    segundosRestantes = segundosTotales;
    botonToggle.textContent = "Start";
    botonToggle.classList.add("primario");
    aviso.textContent = mensaje;
    dibujar();
  }

  function completar() {
    detener();
    tono();
    if (modo === "work") {
      sesionesCompletadas++;
      if (sesionesCompletadas % 4 === 0) {
        cambiarModo("long", "Block finished. Take a long break.");
      } else {
        cambiarModo("short", "Block finished. Take a break.");
      }
    } else {
      if (modo === "long") sesionesCompletadas = 0;
      cambiarModo("work", "Break finished. Ready for another block.");
    }
  }

  function actualizar() {
    segundosRestantes = Math.max(0, Math.ceil((terminaEn - Date.now()) / 1000));
    dibujar();
    if (segundosRestantes === 0) completar();
  }

  function alternar() {
    if (intervalo !== null) {
      segundosRestantes = Math.max(0, Math.ceil((terminaEn - Date.now()) / 1000));
      detener();
      botonToggle.textContent = "Resume";
      aviso.textContent = "Timer paused.";
      dibujar();
      return;
    }
    terminaEn = Date.now() + segundosRestantes * 1000;
    botonToggle.textContent = "Pause";
    botonToggle.classList.remove("primario");
    aviso.textContent = "Timer running.";
    actualizar();
    if (segundosRestantes > 0) intervalo = window.setInterval(actualizar, 250);
  }

  function reiniciar() {
    detener();
    segundosRestantes = segundosTotales;
    botonToggle.textContent = "Start";
    botonToggle.classList.add("primario");
    aviso.textContent = "Timer reset.";
    dibujar();
  }

  document.querySelector("#pomodoro-toggle").addEventListener("click", alternar);
  document.querySelector("#pomodoro-reset").addEventListener("click", reiniciar);
  for (const boton of document.querySelectorAll("[data-pomodoro-mode]")) {
    boton.addEventListener("click", () => cambiarModo(boton.dataset.pomodoroMode, "Timer ready."));
  }
  window.addEventListener("pagehide", detener, { once: true });
  dibujar();
})();