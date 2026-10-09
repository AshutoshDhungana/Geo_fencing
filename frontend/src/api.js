const csrf = () => document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] ?? ''

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch('/api/' + path, {
    method,
    credentials: 'same-origin',
    headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
    body: body && JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(data.error || `Request failed (${res.status})`), { status: res.status })
  return data
}

// in | out | stale (no packet for 60 s) | none
export const statusOf = (a, now) => {
  const r = a.reading
  if (!r) return 'none'
  if (now - new Date(r.at) > 60_000) return 'stale'
  return r.inside ? 'in' : 'out'
}
