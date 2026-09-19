(function () {
  "use strict";

  function relativeLuminance(value) {
    const match = /^#([0-9a-f]{6})$/i.exec(String(value || ""));
    if (!match) return null;
    const channels = [0, 2, 4].map(offset => {
      const channel = parseInt(match[1].slice(offset, offset + 2), 16) / 255;
      return channel <= .04045
        ? channel / 12.92
        : Math.pow((channel + .055) / 1.055, 2.4);
    });
    return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
  }

  function tone(tokens) {
    const ink = relativeLuminance(tokens && tokens.ink);
    const panel = relativeLuminance(tokens && tokens.panel);
    if (ink === null || panel === null) return "dark";
    const inkOnWhite = 1.05 / (ink + .05);
    return panel > ink && inkOnWhite >= 4.5 ? "light" : "dark";
  }

  function apply(tokens, root) {
    root = root || document.documentElement;
    const value = tone(tokens);
    root.dataset.themeTone = value;
    root.style.colorScheme = value;
    root.style.setProperty(
      "--composer-bg",
      value === "light" ? "#ffffff" : "color-mix(in srgb,var(--bg) 82%,#080604)"
    );
    return value;
  }

  window.JNSQThemeSurface = Object.freeze({apply, relativeLuminance, tone});
})();
