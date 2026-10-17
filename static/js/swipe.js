/*
  Свайп карточек пальцем (и мышью на компьютере).

  Как работает: карточку с атрибутом data-swipe-card можно тянуть влево-вправо.
  Если отпустить дальше порога — карточка улетает, и мы «нажимаем» кнопку
  «Нравится» или «Пропустить» внутри неё. Дальше всё как при обычном нажатии:
  HTMX отправляет форму и подставляет следующую карточку.

  На компьютере работают ещё и стрелки: → нравится, ← пропустить.
  Обработчики навешаны на document один раз, поэтому продолжают работать
  после того, как HTMX подменил карточку.
*/
(function () {
  "use strict";

  var THRESHOLD = 110; // на сколько пикселей нужно сдвинуть, чтобы засчитать свайп
  var drag = null;

  function cardFrom(target) {
    return target.closest ? target.closest("[data-swipe-card]") : null;
  }

  // Кнопки решения лежат в той же форме, что и карточка (под ней)
  function button(card, decision) {
    var form = card.closest("form");
    return form ? form.querySelector('button[name="decision"][value="' + decision + '"]') : null;
  }

  function setStamp(card, dx) {
    var like = card.querySelector(".stamp-like");
    var pass = card.querySelector(".stamp-pass");
    var strength = Math.min(Math.abs(dx) / THRESHOLD, 1);
    if (like) like.style.opacity = dx > 0 ? strength : 0;
    if (pass) pass.style.opacity = dx < 0 ? strength : 0;
  }

  // Улёт карточки и отправка решения
  function decide(card, decision) {
    if (!card || card.dataset.decided) return;
    var btn = button(card, decision);
    if (!btn) return;
    card.dataset.decided = "1";
    card.style.transform = "";
    card.classList.remove("dragging");
    card.classList.add(decision === "like" ? "fly-right" : "fly-left");
    // Даём анимации начаться, затем отправляем форму через настоящую кнопку
    window.setTimeout(function () { btn.click(); }, 120);
  }

  document.addEventListener("pointerdown", function (event) {
    var card = cardFrom(event.target);
    // Ссылки и кнопки внутри карточки должны нажиматься как обычно
    if (!card || card.dataset.decided || event.target.closest("a, button")) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    drag = { card: card, startX: event.clientX, startY: event.clientY, dx: 0, active: false, id: event.pointerId };
  });

  document.addEventListener("pointermove", function (event) {
    if (!drag || event.pointerId !== drag.id) return;
    var dx = event.clientX - drag.startX;
    var dy = event.clientY - drag.startY;
    // Начинаем тянуть, только если движение в основном горизонтальное (иначе это прокрутка)
    if (!drag.active) {
      if (Math.abs(dx) < 8 || Math.abs(dx) < Math.abs(dy)) return;
      drag.active = true;
      drag.card.classList.add("dragging");
      try { drag.card.setPointerCapture(event.pointerId); } catch (e) { /* не критично */ }
    }
    drag.dx = dx;
    drag.card.style.transform = "translateX(" + dx + "px) rotate(" + dx / 18 + "deg)";
    setStamp(drag.card, dx);
  });

  function endDrag() {
    if (!drag) return;
    var card = drag.card;
    var dx = drag.dx;
    var wasActive = drag.active;
    drag = null;
    if (!wasActive) return;
    if (dx > THRESHOLD) return decide(card, "like");
    if (dx < -THRESHOLD) return decide(card, "pass");
    // Не дотянули — карточка плавно возвращается на место
    card.classList.remove("dragging");
    card.style.transform = "";
    setStamp(card, 0);
  }

  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);

  // Нажатие кнопок тоже запускает анимацию улёта. Первый клик перехватываем,
  // проигрываем анимацию, а повторный (программный) клик уже отправляет форму.
  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-swipe-action]");
    if (!btn || !btn.form) return;
    var card = btn.form.querySelector("[data-swipe-card]");
    if (!card || card.dataset.decided) return;
    event.preventDefault();
    decide(card, btn.value);
  }, true);

  // Стрелки на клавиатуре — только когда фокус не в поле ввода
  document.addEventListener("keydown", function (event) {
    if (event.target.closest("input, textarea, select, [contenteditable]")) return;
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    var card = document.querySelector("[data-swipe-card]:not([data-decided])");
    if (!card) return;
    event.preventDefault();
    decide(card, event.key === "ArrowRight" ? "like" : "pass");
  });
})();
