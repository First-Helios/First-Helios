/**
 * SpiritPool — Consent State Management
 *
 * Centralised helpers for checking and managing user consent.
 * Used by popup, options, and content scripts.
 */

const Consent = {
  /**
   * Check if the user has granted consent.
   * @returns {Promise<boolean>}
   */
  async isGranted() {
    const { consent } = await browser.storage.local.get("consent");
    return consent && consent.given === true;
  },

  /**
   * Grant consent (called from the first-run modal or options page).
   * @returns {Promise<void>}
   */
  async grant() {
    return browser.runtime.sendMessage({ type: "spiritpool:grantConsent" });
  },

  /**
   * Revoke consent (clears all collected data).
   * @returns {Promise<void>}
   */
  async revoke() {
    return browser.runtime.sendMessage({ type: "spiritpool:revokeConsent" });
  },

  /**
   * Get full consent object.
   * @returns {Promise<{given: boolean, timestamp: string|null, version: number}>}
   */
  async get() {
    const { consent } = await browser.storage.local.get("consent");
    return consent || { given: false, timestamp: null, version: 1 };
  },
};

// Export for use in modules / content scripts
if (typeof globalThis !== "undefined") {
  globalThis.SpiritPoolConsent = Consent;
}
