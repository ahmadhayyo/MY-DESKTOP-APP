/* ============================================================================
 * HAYO — Workspace picker button in the message composer.
 *
 * Injects a "📁+" button next to Chainlit's attach button. Clicking it sends
 * the `/workspace` command, which opens a native Windows folder picker on the
 * backend so the user can choose EXACTLY the project folder the agent works in.
 * ==========================================================================*/
(function () {
  "use strict";

  var BTN_ID = "hayo-workspace-btn";

  // Fire a message into Chainlit's React-controlled textarea and submit it.
  function sendCommand(text) {
    var ta = document.getElementById("chat-input");
    if (!ta) return;

    // React tracks the value via its own setter — bypass it so state updates.
    var proto = window.HTMLTextAreaElement && window.HTMLTextAreaElement.prototype;
    var setter = proto && Object.getOwnPropertyDescriptor(proto, "value");
    if (setter && setter.set) {
      setter.set.call(ta, text);
    } else {
      ta.value = text;
    }
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    ta.focus();

    // Give React a tick to enable the submit button, then send.
    setTimeout(function () {
      var submit = document.getElementById("chat-submit");
      if (submit && !submit.disabled) {
        submit.click();
      } else {
        ta.dispatchEvent(
          new KeyboardEvent("keydown", {
            key: "Enter",
            code: "Enter",
            keyCode: 13,
            which: 13,
            bubbles: true,
          })
        );
      }
    }, 80);
  }

  function makeButton(template) {
    var btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.type = "button";
    btn.title = "اختيار مجلد العمل — Select working folder";
    btn.setAttribute("aria-label", "Select working folder");
    // Inherit Chainlit's button styling for a native look.
    if (template && template.className) {
      btn.className = template.className;
    }
    btn.style.cursor = "pointer";
    // Folder-with-plus icon (inherits currentColor).
    btn.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" ' +
      'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>' +
      '<line x1="12" y1="10" x2="12" y2="16"/>' +
      '<line x1="9" y1="13" x2="15" y2="13"/>' +
      "</svg>";
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      sendCommand("/workspace");
    });
    return btn;
  }

  function inject() {
    if (document.getElementById(BTN_ID)) return; // already injected
    var anchor = document.getElementById("upload-button");
    if (!anchor || !anchor.parentNode) return;
    var btn = makeButton(anchor);
    // Place it right before the attach button so it sits in the toolbar.
    anchor.parentNode.insertBefore(btn, anchor);
  }

  // The composer mounts/re-mounts as the SPA navigates — keep re-checking.
  var observer = new MutationObserver(function () {
    inject();
  });

  function start() {
    inject();
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

/* ============================================================================
 * HAYO — Animated welcome / splash screen with a "ابدأ" (Start) button.
 * Shows once per page load; the Start button fades it out to reveal the chat.
 * ==========================================================================*/
(function () {
  "use strict";
  if (window.__hayoSplashDone) return;
  window.__hayoSplashDone = true;
  // Show once per browser session (survives refresh + login route change),
  // reappears when the user opens the app fresh in a new session.
  try {
    if (sessionStorage.getItem("hayoSplashSeen") === "1") return;
    sessionStorage.setItem("hayoSplashSeen", "1");
  } catch (e) {}

  var FEATURES = [
    ["🧠", "تحليل عميق وتخطيط ذكي"],
    ["🛠️", "أكثر من 265 أداة تنفيذية"],
    ["👁️", "رؤية حقيقية — يرى الشاشة والصور"],
    ["🌐", "تحكّم كامل بالمتصفح والويب"],
    ["🏗️", "بناء مشاريع وتطبيقات EXE"],
    ["📱", "تحكّم بمحاكي وأجهزة أندرويد"],
    ["💻", "جلسة طرفية دائمة"],
    ["🧩", "مهارات جاهزة ووكلاء فرعيون"],
    ["💬", "وضعا السؤال (Ask) والوكيل (Agent)"],
    ["🔓", "يعمل بحرية حتى إنجاز المهمة"]
  ];

  function build() {
    if (document.getElementById("hayo-splash")) return;

    var s = document.createElement("div");
    s.id = "hayo-splash";

    var feats = FEATURES.map(function (f, i) {
      return '<div class="hayo-feat" style="animation-delay:' + (0.35 + i * 0.06) +
        's"><span>' + f[0] + "</span><div>" + f[1] + "</div></div>";
    }).join("");

    s.innerHTML =
      '<div class="hayo-orbit"></div><div class="hayo-orbit two"></div>' +
      '<img class="hayo-logo" src="/public/logo_dark.png" alt="HAYO" />' +
      "<h1>HAYO AI AGENT</h1>" +
      '<div class="hayo-tag">وكيلك الذكي الخارق — يفكّر، يخطّط، ينفّذ، ويتحقّق</div>' +
      '<div class="hayo-feats">' + feats + "</div>" +
      '<button class="hayo-start" id="hayo-start-btn">ابدأ ▸</button>';

    document.body.appendChild(s);

    document.getElementById("hayo-start-btn").addEventListener("click", function () {
      s.classList.add("hayo-hide");
      setTimeout(function () { if (s && s.parentNode) s.parentNode.removeChild(s); }, 550);
    });
  }

  function ready() {
    if (document.body) { build(); }
    else { setTimeout(ready, 60); }
  }
  ready();
})();
