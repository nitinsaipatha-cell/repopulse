import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

class ResizeObserverStub {
  constructor(callback) { this.callback = callback; }
  observe(target) { this.callback([{ target, contentRect: { width: 640, height: 300 } }]); }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub;
afterEach(() => cleanup());
