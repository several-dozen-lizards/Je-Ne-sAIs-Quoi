/* Shared exact-color editor for JNSQ's native color swatches. */
(() => {
  const HEX = /^#?[0-9a-f]{6}$/i;

  function normalize(value) {
    const text = String(value || "").trim();
    return HEX.test(text) ? `#${text.replace(/^#/, "").toLowerCase()}` : null;
  }

  function labelFor(input) {
    const label = input.closest("label");
    const text = label?.innerText?.replace(/#[0-9a-f]{6}/ig, "").trim();
    return `${text || input.title || "color"} hex code`;
  }

  function syncOne(input) {
    const field = input.parentElement?.querySelector(":scope > .jnsq-hex-code");
    if (field && document.activeElement !== field)
      field.value = String(input.value || "#000000").toUpperCase();
  }

  function wireOne(input) {
    if (input.dataset.hexWired === "true") return;
    input.dataset.hexWired = "true";
    input.classList.add("jnsq-color-swatch");
    const wrap = document.createElement("span");
    wrap.className = "jnsq-color-control";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const field = document.createElement("input");
    field.type = "text";
    field.className = "jnsq-hex-code";
    field.maxLength = 7;
    field.spellcheck = false;
    field.autocomplete = "off";
    field.inputMode = "text";
    field.setAttribute("aria-label", labelFor(input));
    field.title = "Enter an exact color as #RRGGBB";
    wrap.appendChild(field);
    syncOne(input);
    input.addEventListener("input", () => syncOne(input));
    input.addEventListener("change", () => syncOne(input));
    field.addEventListener("input", () => {
      const value = normalize(field.value);
      field.setAttribute("aria-invalid", String(!value));
      if (!value) return;
      field.value = value.toUpperCase();
      if (input.value.toLowerCase() === value) return;
      input.value = value;
      input.dispatchEvent(new Event("input", {bubbles: true}));
      input.dispatchEvent(new Event("change", {bubbles: true}));
    });
    field.addEventListener("blur", () => {
      if (!normalize(field.value)) syncOne(input);
      field.setAttribute("aria-invalid", "false");
    });
  }

  function wire(root = document) {
    if (root.matches?.('input[type="color"]')) wireOne(root);
    root.querySelectorAll?.('input[type="color"]').forEach(wireOne);
  }

  function sync(root = document) {
    wire(root);
    root.querySelectorAll?.('input[type="color"][data-hex-wired="true"]')
      .forEach(syncOne);
  }

  if (!document.getElementById("jnsq-hex-color-style")) {
    const style = document.createElement("style");
    style.id = "jnsq-hex-color-style";
    style.textContent = `
      .jnsq-color-control{display:grid;grid-template-columns:44px minmax(78px,1fr);
        gap:6px;align-items:center;width:100%}
      .jnsq-color-control>.jnsq-color-swatch{width:44px!important;min-width:44px;
        height:34px!important;padding:2px!important}
      .jnsq-color-control>.jnsq-hex-code{width:100%;min-width:0;
        font-family:var(--font-mono,Consolas,monospace);font-size:.78rem;
        letter-spacing:.03em;text-transform:uppercase}
      .jnsq-color-control>.jnsq-hex-code[aria-invalid="true"]{
        border-color:var(--warn,var(--danger,#d97b6c));
        box-shadow:0 0 0 1px color-mix(in srgb,var(--warn,var(--danger,#d97b6c)) 35%,transparent)}
    `;
    document.head.appendChild(style);
  }
  window.JNSQHexColors = Object.freeze({wire, sync});
  const start = () => {
    wire();
    new MutationObserver(records => {
      for (const record of records)
        for (const node of record.addedNodes)
          if (node.nodeType === 1) wire(node);
    }).observe(document.documentElement, {childList: true, subtree: true});
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", start, {once: true});
  else start();
  addEventListener("jnsq-theme-applied", () => sync());
})();
