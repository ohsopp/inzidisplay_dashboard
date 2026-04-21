// 배포: same-origin + vercel.json 이 /api/* 를 원격 Gunicorn으로 프록시.
// VITE_API_BASE_URL 로 직접 백엔드에 붙이면 HTTPS 권장(혼합 콘텐츠 방지).

const PRODUCTION_API_URL = String(import.meta.env.VITE_API_BASE_URL || '')
  .trim()
  .replace(/\/$/, '')

export const API_URL = import.meta.env.DEV
  ? `http://${window.location.hostname}:6005`
  : PRODUCTION_API_URL

export function getApiToken() {
  const envToken = (import.meta.env.VITE_API_TOKEN || '').trim()
  if (envToken) return envToken
  if (typeof window === 'undefined') return ''
  try {
    const q = new URLSearchParams(window.location.search)
    const queryToken = (q.get('token') || q.get('api_token') || '').trim()
    if (queryToken) {
      window.localStorage.setItem('api_token', queryToken)
      return queryToken
    }
    return (window.localStorage.getItem('api_token') || '').trim()
  } catch {
    return ''
  }
}

export function buildApiUrl(path) {
  return `${API_URL}${path}`
}

export function buildEventsUrl() {
  const token = getApiToken()
  const base = buildApiUrl('/api/events')
  if (!token) return base
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}token=${encodeURIComponent(token)}`
}

export async function apiFetch(path, options = {}) {
  const token = getApiToken()
  const mergedHeaders = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  }
  return fetch(buildApiUrl(path), { ...options, headers: mergedHeaders })
}
