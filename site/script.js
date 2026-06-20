/* ============ Skvortsov ADV — script ============ */
(function () {
  "use strict";

  /* -------------------------------------------------------------
   * НАСТРОЙКА ПРИЁМА ЗАЯВОК
   * Вставьте URL вебхука n8n (или другого backend), который шлёт
   * заявку в Telegram и на Email. Шаблон воркфлоу — site/n8n_lead_webhook.json.
   * Пока поле пустое — форма отправляет заявку через почтовый клиент (mailto)
   * и предлагает написать в Telegram, чтобы ни один лид не потерялся.
   * ----------------------------------------------------------- */
  var LEAD_WEBHOOK_URL = ""; // напр. "https://n8n.ваш-домен.ru/webhook/lead"
  var CONTACT_EMAIL = "sunpavel@gmail.com";
  var TELEGRAM_USER = "skvortsov_adv";

  document.addEventListener("DOMContentLoaded", function () {
    initYear();
    initMobileNav();
    initLeadForm();
  });

  function initYear() {
    var y = document.getElementById("year");
    if (y) y.textContent = String(new Date().getFullYear());
  }

  function initMobileNav() {
    var toggle = document.querySelector(".nav-toggle");
    var menu = document.getElementById("mobile-nav");
    if (!toggle || !menu) return;

    function setOpen(open) {
      toggle.setAttribute("aria-expanded", String(open));
      menu.hidden = !open;
    }
    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a")) setOpen(false);
    });
  }

  function initLeadForm() {
    var form = document.getElementById("lead-form");
    if (!form) return;
    var status = document.getElementById("form-status");

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      status.className = "form-status";
      status.textContent = "";

      var data = {
        name: form.name.value.trim(),
        phone: form.phone.value.trim(),
        email: form.email.value.trim(),
        task: form.task.value.trim(),
        page: location.href,
        ts: new Date().toISOString()
      };

      if (!data.name || !data.phone) {
        setStatus("err", "Заполните имя и телефон.");
        return;
      }

      var btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      var prev = btn.textContent;
      btn.textContent = "Отправляем…";

      function done(ok, msg) {
        btn.disabled = false;
        btn.textContent = prev;
        setStatus(ok ? "ok" : "err", msg);
        if (ok) form.reset();
      }

      if (LEAD_WEBHOOK_URL) {
        fetch(LEAD_WEBHOOK_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data)
        })
          .then(function (r) {
            if (!r.ok) throw new Error("bad status " + r.status);
            done(true, "Спасибо! Заявка отправлена — отвечу в течение рабочего дня.");
          })
          .catch(function () {
            fallback(data);
            done(true, "Открываю почту для отправки заявки. Если не получилось — напишите в Telegram @" + TELEGRAM_USER + ".");
          });
      } else {
        fallback(data);
        done(true, "Открываю почтовый клиент. Можно также написать в Telegram @" + TELEGRAM_USER + ".");
      }
    });

    function setStatus(kind, msg) {
      status.className = "form-status " + kind;
      status.textContent = msg;
    }

    function fallback(data) {
      var subject = "Заявка с сайта — " + data.name;
      var body =
        "Имя: " + data.name + "\n" +
        "Телефон: " + data.phone + "\n" +
        "Email: " + (data.email || "—") + "\n" +
        "Задача: " + (data.task || "—") + "\n" +
        "Страница: " + data.page;
      var href = "mailto:" + CONTACT_EMAIL +
        "?subject=" + encodeURIComponent(subject) +
        "&body=" + encodeURIComponent(body);
      window.location.href = href;
    }
  }
})();
