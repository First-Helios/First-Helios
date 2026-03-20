/**
 * SpiritPool — Element Highlight Utility
 *
 * Adds a subtle blue glow to DOM elements the extension has captured.
 * The tint naturally decays over 10 seconds, or fades immediately on hover.
 *
 * Usage (from any content script):
 *   spiritpoolHighlight(element);
 *
 * Loaded before each content script via manifest.json ordering.
 */

const spiritpoolHighlight = (() => {
  const HIGHLIGHT_CLASS = "spiritpool-hl";
  const FADE_CLASS = "spiritpool-hl-fade";
  const DECAY_MS = 3000; // natural colour-fade duration
  const TAPER_MS = 300; // final taper for outline-width & border-radius
  let styleInjected = false;

  function injectStyle() {
    if (styleInjected) return;
    styleInjected = true;

    const style = document.createElement("style");
    style.textContent = `
      .${HIGHLIGHT_CLASS} {
        background-color: rgba(100, 170, 240, 0.07) !important;
        outline: 1px solid rgba(100, 170, 240, 0.15);
        outline-offset: -1px;
        border-radius: 4px;
        transition: background-color ${DECAY_MS}ms ease-out,
                    outline-color ${DECAY_MS}ms ease-out,
                    outline-width ${TAPER_MS}ms ease-out,
                    border-radius ${TAPER_MS}ms ease-out;
      }
      .${HIGHLIGHT_CLASS}.${FADE_CLASS} {
        background-color: transparent !important;
        outline-color: transparent;
        transition: background-color 0.5s ease-out,
                    outline-color 0.5s ease-out,
                    outline-width ${TAPER_MS}ms ease-out,
                    border-radius ${TAPER_MS}ms ease-out;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  /* Strip every highlight artefact from the element */
  function cleanup(el) {
    el.classList.remove(HIGHLIGHT_CLASS, FADE_CLASS);
    for (const p of [
      "background-color",
      "outline-color",
      "outline-width",
      "border-radius",
    ]) {
      el.style.removeProperty(p);
    }
  }

  /* Taper outline-width & border-radius to 0, then clean up */
  function taperAndCleanup(el) {
    el.style.outlineWidth = "0";
    el.style.borderRadius = "0";
    setTimeout(() => cleanup(el), TAPER_MS + 50);
  }

  /**
   * Highlight an element with a subtle blue glow.
   * Naturally decays over DECAY_MS, then tapers remaining
   * properties to 0 so nothing pops on removal.
   * Hover accelerates the whole sequence.
   *
   * @param {Element} el — the DOM element to highlight
   */
  function highlight(el) {
    if (!el || !(el instanceof Element)) return;
    if (el.classList.contains(HIGHLIGHT_CLASS)) return;

    injectStyle();
    el.classList.add(HIGHLIGHT_CLASS);

    // Force paint of initial highlight, then kick off colour decay
    requestAnimationFrame(() => {
      el.style.backgroundColor = "transparent";
      el.style.outlineColor = "transparent";
    });

    // After colours have faded, taper outline-width & border-radius to 0
    const decayTimer = setTimeout(() => taperAndCleanup(el), DECAY_MS + 50);

    // Hover accelerates the fade
    el.addEventListener(
      "mouseenter",
      () => {
        clearTimeout(decayTimer);
        el.classList.add(FADE_CLASS);
        el.style.backgroundColor = "transparent";
        el.style.outlineColor = "transparent";
        // After the fast colour fade, taper remaining props
        setTimeout(() => taperAndCleanup(el), 500);
      },
      { once: true }
    );
  }

  return highlight;
})();
