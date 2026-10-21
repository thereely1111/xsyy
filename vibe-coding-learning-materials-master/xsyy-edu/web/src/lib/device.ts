const DEVICE_ID_KEY = 'xsyy_device_id';

function randomSegment(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function getOrCreateDeviceId(): string {
  const existing = localStorage.getItem(DEVICE_ID_KEY);
  if (existing && existing.length >= 8) {
    return existing;
  }
  const generated = `dev_${Date.now().toString(36)}_${randomSegment()}${randomSegment()}`;
  localStorage.setItem(DEVICE_ID_KEY, generated);
  return generated;
}
