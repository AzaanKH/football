// Vitest setup: DOM matchers (toBeInTheDocument, toHaveTextContent, ...)
import '@testing-library/jest-dom/vitest';

// jsdom lacks a few browser APIs used by cmdk / Radix popovers and selects
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
Element.prototype.scrollIntoView = function scrollIntoView() {};
Element.prototype.hasPointerCapture = function hasPointerCapture() { return false; };
Element.prototype.releasePointerCapture = function releasePointerCapture() {};
