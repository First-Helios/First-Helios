/**
 * SpiritPool — API Client
 *
 * Handles communication between content scripts and the background worker.
 * Also provides the future backend POST client.
 */

const SpiritPoolAPI = {
  /**
   * Send a signal from a content script to the background worker.
   * @param {string} domain - e.g. "indeed.com"
   * @param {object} signal - structured signal object from Parser.buildSignal()
   * @returns {Promise<{ok: boolean, queued?: number, reason?: string}>}
   */
  async sendSignal(domain, signal) {
    try {
      return await browser.runtime.sendMessage({
        type: "spiritpool:signal",
        domain,
        signal,
      });
    } catch (err) {
      console.warn("[SpiritPool] Failed to send signal:", err);
      return { ok: false, reason: err.message };
    }
  },

  /**
   * Get extension status (consent, stats, per-domain queue sizes).
   * @returns {Promise<object>}
   */
  async getStatus() {
    try {
      return await browser.runtime.sendMessage({
        type: "spiritpool:getStatus",
      });
    } catch (err) {
      console.warn("[SpiritPool] Failed to get status:", err);
      return null;
    }
  },

  /**
   * Toggle a site on/off.
   * @param {string} domain
   * @param {boolean} enabled
   */
  async toggleSite(domain, enabled) {
    return browser.runtime.sendMessage({
      type: "spiritpool:toggleSite",
      domain,
      enabled,
    });
  },

  /**
   * Get cached signals for a specific domain.
   * @param {string} domain
   * @returns {Promise<{signals: Array, lastUpdate: string|null}>}
   */
  async getDomainCache(domain) {
    return browser.runtime.sendMessage({
      type: "spiritpool:getDomainCache",
      domain,
    });
  },

  /**
   * Clear cached signals for a domain.
   * @param {string} domain
   */
  async clearDomainCache(domain) {
    return browser.runtime.sendMessage({
      type: "spiritpool:clearDomainCache",
      domain,
    });
  },
};

if (typeof globalThis !== "undefined") {
  globalThis.SpiritPoolAPI = SpiritPoolAPI;
}
