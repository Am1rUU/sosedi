/*
  Листание фото.

  1. Галерея на странице объявления ([data-gallery]): фото лежат в ряд,
     листаются пальцем вбок (прокрутка со «щелчком» — CSS scroll-snap),
     на компьютере — стрелками. Счётчик «2 / 5» обновляется сам.

  2. Фото в карточке ленты ([data-photo-stack]): движение вбок там занято
     свайпом «нравится / пропустить», поэтому фото листаются касанием —
     по правой половине вперёд, по левой назад (как в Tinder).

  Обработчики висят на document, поэтому работают и после того,
  как HTMX подставил новую карточку.
*/
(function () {
  "use strict";

  // --- Галерея на странице объявления ---------------------------------------

  function galleryParts(gallery) {
    return {
      track: gallery.querySelector(".gallery-track"),
      counter: gallery.querySelector(".gallery-current"),
      prev: gallery.querySelector(".gallery-nav.prev"),
      next: gallery.querySelector(".gallery-nav.next"),
    };
  }

  function currentIndex(track) {
    return Math.round(track.scrollLeft / track.clientWidth);
  }

  function updateGallery(gallery) {
    var p = galleryParts(gallery);
    if (!p.track) return;
    var total = p.track.children.length;
    var index = currentIndex(p.track);
    if (p.counter) p.counter.textContent = String(index + 1);
    if (p.prev) p.prev.disabled = index <= 0;
    if (p.next) p.next.disabled = index >= total - 1;
  }

  function goTo(gallery, index) {
    var track = galleryParts(gallery).track;
    var total = track.children.length;
    index = Math.max(0, Math.min(total - 1, index));
    track.scrollTo({ left: index * track.clientWidth, behavior: "smooth" });
  }

  document.addEventListener("click", function (event) {
    var nav = event.target.closest(".gallery-nav");
    if (!nav) return;
    var gallery = nav.closest("[data-gallery]");
    var track = galleryParts(gallery).track;
    goTo(gallery, currentIndex(track) + (nav.classList.contains("next") ? 1 : -1));
  });

  // Событие scroll не всплывает, поэтому ловим его на этапе погружения
  document.addEventListener("scroll", function (event) {
    var track = event.target;
    if (!track.classList || !track.classList.contains("gallery-track")) return;
    updateGallery(track.closest("[data-gallery]"));
  }, true);

  document.addEventListener("keydown", function (event) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    var gallery = event.target.closest && event.target.closest("[data-gallery]");
    if (!gallery) return;
    event.preventDefault();
    var track = galleryParts(gallery).track;
    goTo(gallery, currentIndex(track) + (event.key === "ArrowRight" ? 1 : -1));
  });

  function initGalleries(root) {
    (root || document).querySelectorAll("[data-gallery]").forEach(updateGallery);
  }
  document.addEventListener("DOMContentLoaded", function () { initGalleries(); });
  window.addEventListener("resize", function () { initGalleries(); });

  // --- Фото в карточке ленты ----------------------------------------------------

  function showPhoto(stack, index) {
    var photos = stack.querySelectorAll(".stack-photo");
    var bars = stack.querySelectorAll(".stack-bar");
    if (!photos.length) return;
    index = (index + photos.length) % photos.length;
    photos.forEach(function (img, i) { img.classList.toggle("active", i === index); });
    bars.forEach(function (bar, i) { bar.classList.toggle("active", i === index); });
    stack.dataset.index = String(index);
  }

  document.addEventListener("click", function (event) {
    var stack = event.target.closest("[data-photo-stack]");
    if (!stack || event.target.closest("a, button")) return;
    var card = stack.closest("[data-swipe-card]");
    if (card && (card.dataset.justDragged || card.dataset.decided)) return;
    var rect = stack.getBoundingClientRect();
    var forward = event.clientX - rect.left > rect.width / 2;
    showPhoto(stack, Number(stack.dataset.index || 0) + (forward ? 1 : -1));
  });
})();
