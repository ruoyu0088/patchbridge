import { getLocale, t } from './i18n.js';

export class ApiError extends Error {
  constructor(code, message, details, status) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.details = details;
    this.status = status;
  }
}

async function request(path, options = {}) {
  const init = {
    ...options,
    // 每个请求都带上当前语言，后端据此本地化错误信息、诊断文本和提示词。
    headers: { 'Accept-Language': getLocale(), ...(options.headers || {}) },
  };
  if (init.body && typeof init.body !== 'string') {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(init.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    throw new ApiError('network_error', t('无法连接 PatchBridge 后端'), null, 0);
  }
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    const text = await response.text();
    if (!response.ok) {
      throw new ApiError('http_error', text || `HTTP ${response.status}`, null, response.status);
    }
    return text;
  }
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    const error = payload.error || {};
    throw new ApiError(
      error.code || 'api_error',
      error.message || t('请求失败'),
      error.details || null,
      response.status,
    );
  }
  return payload.data;
}

export const api = {
  get: (path) => request(path),
  text: (path) => request(path, { headers: { Accept: 'text/plain' } }),
  post: (path, body = {}) => request(path, { method: 'POST', body }),
  put: (path, body = {}) => request(path, { method: 'PUT', body }),
  delete: (path) => request(path, { method: 'DELETE' }),
  downloadUrl: (path) => path,
};
