import { useEffect, useState } from 'react'
import { api, statusOf } from './api.js'
import MapView from './MapView.jsx'

const LIVE_POLL_MS = 3000
const SPEEDS = [{ label: 'Slow', ms: 3000 }, { label: 'Normal', ms: 1500 }, { label: 'Fast', ms: 500 }]

const load = (k, d) => { try { return localStorage.getItem(k) ?? d } catch { return d } }
const save = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }

function ago(iso, now) {
  const s = Math.max(0, Math.round((now - new Date(iso)) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return new Date(iso).toLocaleString()
}
const time = iso => new Date(iso).toLocaleTimeString()

function Login({ onLogin }) {
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async e => {
    e.preventDefault()
    setBusy(true); setError(null)
    try { onLogin((await api('login', { method: 'POST', body: form })).user) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  return (
    <main className="login">
      <form onSubmit={submit} className="card">
        <h1>Herd Watch</h1>
        <p className="muted">GPS geo-fencing for livestock</p>
        <label>Username<input autoFocus autoComplete="username" value={form.username}
          onChange={e => setForm({ ...form, username: e.target.value })} required /></label>
        <label>Password<input type="password" autoComplete="current-password" value={form.password}
          onChange={e => setForm({ ...form, password: e.target.value })} required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </main>
  )
}

function SimPanel({ running, setRunning, speed, setSpeed, onReset, step }) {
  return (
    <section className="panel sim">
      <div className="panel-head">
        <h2>Simulation</h2>
        <span className={'pill ' + (running ? 'pill-on' : '')}>{running ? 'Running' : 'Paused'}</span>
      </div>
      <p className="muted">Three virtual cows around a 50 m test fence. Readings go through the same
        geo-fence and alert logic as real station data, but are kept separate from it.</p>
      <div className="row">
        <button className="primary" onClick={() => setRunning(!running)}>{running ? 'Pause' : 'Start'}</button>
        <div className="seg" role="group" aria-label="Simulation speed">
          {SPEEDS.map(s => (
            <button key={s.ms} aria-pressed={speed === s.ms} onClick={() => setSpeed(s.ms)}>{s.label}</button>
          ))}
        </div>
        <button onClick={onReset}>Reset</button>
      </div>
      <p className="muted small">Step {step ?? '–'}</p>
    </section>
  )
}

function LivePanel({ animals, now }) {
  const last = animals.map(a => a.reading?.at).filter(Boolean).sort().at(-1)
  const healthy = last && now - new Date(last) < 60_000
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Station</h2>
        <span className={'pill ' + (healthy ? 'pill-on' : last ? 'pill-warn' : '')}>
          {healthy ? 'Receiving' : last ? 'Silent' : 'No data'}</span>
      </div>
      <p className="muted">{last ? `Last packet ${ago(last, now)}` : 'Waiting for the monitoring station to upload readings.'}</p>
      {!animals.length && (
        <p className="muted">No animals registered. Add a fence and animals (tag = cattle unit ID)
          in <a href="/admin/" target="_blank" rel="noreferrer">Admin</a>.</p>
      )}
    </section>
  )
}

// A circle fence becomes an editable 24-corner polygon.
const M_PER_DEG = 111_195
const circlePoints = (f, n = 24) => Array.from({ length: n }, (_, i) => {
  const a = (i / n) * 2 * Math.PI
  return [f.lat + (f.radius_m * Math.cos(a)) / M_PER_DEG,
    f.lon + (f.radius_m * Math.sin(a)) / (M_PER_DEG * Math.cos((f.lat * Math.PI) / 180))]
})

function FencePanel({ fences, mode, edit, setEdit, draft, onSaved }) {
  const [name, setName] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null)

  const start = f => {
    setError(null); setConfirmDelete(null)
    setName(f ? f.name : '')
    setEdit(f ? { id: f.id, points: f.polygon ?? circlePoints(f) } : {})
  }
  const run = async fn => {
    setBusy(true); setError(null)
    try { await fn(); onSaved() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const save = () => run(async () => {
    const body = { name: name.trim(), polygon: draft }
    await (edit.id ? api(`fences/${edit.id}`, { method: 'PATCH', body }) : api('fences', { method: 'POST', body }))
    setEdit(null)
  })
  const remove = f => confirmDelete === f.id
    ? run(() => api(`fences/${f.id}`, { method: 'DELETE' })).then(() => setConfirmDelete(null))
    : setConfirmDelete(f.id)

  if (edit) {
    const ready = draft?.length >= 3 && name.trim()
    return (
      <section className="panel editing">
        <h2>{edit.id ? 'Edit boundary' : 'Draw a new fence'}</h2>
        <p className="muted">{edit.id || draft
          ? 'Drag corners to reshape. Drag a small middle point to add a corner, right-click a corner to remove it.'
          : 'Click on the map to place each corner. Click the first corner again to close the shape.'}</p>
        <label>Name<input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. North pasture" /></label>
        <p className="muted small">{draft ? `${draft.length} corners` : 'No shape yet'}</p>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="row">
          <button className="primary" disabled={!ready || busy} onClick={save}>{busy ? 'Saving…' : 'Save fence'}</button>
          <button onClick={() => setEdit(null)}>Cancel</button>
        </div>
      </section>
    )
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Fences</h2>
        {mode === 'live' && <button onClick={() => start(null)}>+ Draw fence</button>}
      </div>
      {!fences.length && <p className="muted">No fences yet. Draw one around the pasture.</p>}
      <ul className="list">
        {fences.map(f => (
          <li key={f.id} className="fence">
            <span className="grow">
              <strong>{f.name}</strong>
              <span className="muted small block">
                {f.polygon ? `${f.polygon.length}-corner boundary` : `${Math.round(f.radius_m)} m circle`}
                {` · ${f.animals} animal${f.animals === 1 ? '' : 's'}`}
              </span>
            </span>
            <button onClick={() => start(f)}>Edit</button>
            <button className={confirmDelete === f.id ? 'danger' : ''} onClick={() => remove(f)}
              onBlur={() => setConfirmDelete(null)}>{confirmDelete === f.id ? 'Confirm' : 'Delete'}</button>
          </li>
        ))}
      </ul>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  )
}

const STATUS_LABEL = { in: 'Inside', out: 'Outside', stale: 'No signal', none: 'No data' }

export default function App() {
  const [user, setUser] = useState(undefined) // undefined = checking session
  const [mode, setModeState] = useState(() => load('mode', 'live'))
  const [running, setRunning] = useState(false)
  const [speed, setSpeed] = useState(1500)
  const [animals, setAnimals] = useState([])
  const [alerts, setAlerts] = useState([])
  const [selected, setSelected] = useState(null)
  const [track, setTrack] = useState([])
  const [focus, setFocus] = useState(null)
  const [error, setError] = useState(null)
  const [now, setNow] = useState(() => Date.now())
  const [refreshKey, setRefreshKey] = useState(0)
  const [fences, setFences] = useState([])
  const [edit, setEdit] = useState(null) // null | {} (drawing) | { id, points } (reshaping)
  const [draft, setDraft] = useState(null)

  useEffect(() => { api('me').then(d => setUser(d.user)).catch(() => setUser(null)) }, [])

  const setMode = m => {
    save('mode', m); setModeState(m)
    setAnimals([]); setAlerts([]); setSelected(null); setTrack([]); setRunning(false); setFences([]); setEditing(null)
  }

  // One polling loop: in running simulation it advances a step first, then refreshes.
  useEffect(() => {
    if (!user) return
    let stop = false, timer
    const loop = async () => {
      try {
        if (mode === 'sim' && running) await api('sim/tick', { method: 'POST' })
        const q = '?mode=' + mode
        const [l, al, fe] = await Promise.all([api('latest' + q), api('alerts' + q), api('fences' + q)])
        const t = selected ? await api(`track/${encodeURIComponent(selected)}?hours=6`) : null
        if (stop) return
        setAnimals(l.animals); setAlerts(al.alerts); setFences(fe.fences); setTrack(t ? t.points : []); setError(null); setNow(Date.now())
      } catch (e) {
        if (e.status === 401) return setUser(null)
        if (!stop) setError(e.message)
      }
      if (!stop) timer = setTimeout(loop, mode === 'sim' && running ? speed : LIVE_POLL_MS)
    }
    loop()
    return () => { stop = true; clearTimeout(timer) }
  }, [user, mode, running, speed, selected, refreshKey])

  const select = tag => {
    setSelected(tag === selected ? null : tag)
    const a = animals.find(x => x.tag === tag)
    if (a?.reading && tag !== selected) setFocus({ lat: a.reading.lat, lon: a.reading.lon })
  }

  const resetSim = async () => {
    setRunning(false)
    try { await api('sim/reset', { method: 'POST' }) } catch (e) { setError(e.message) }
    setTrack([]); setRefreshKey(k => k + 1)
  }

  const setEditing = e => { setEdit(e); setDraft(null) }

  const moveAnimal = async (tag, fence) => {
    try { await api(`animals/${encodeURIComponent(tag)}`, { method: 'PATCH', body: { fence: +fence } }) }
    catch (e) { setError(e.message) }
    setRefreshKey(k => k + 1)
  }

  const logout = async () => { await api('logout', { method: 'POST' }).catch(() => {}); setUser(null) }

  if (user === undefined) return <main className="login"><p className="muted">Loading…</p></main>
  if (!user) return <Login onLogin={setUser} />

  const outside = animals.filter(a => a.alert)
  const simStep = animals.find(a => a.reading)?.reading.seq
  const fenceById = Object.fromEntries(fences.map(f => [f.id, f]))
  const selectedAnimal = animals.find(a => a.tag === selected)

  return (
    <div className="app">
      <header>
        <strong className="brand">Herd Watch</strong>
        <div className="seg mode" role="group" aria-label="Data source">
          <button aria-pressed={mode === 'live'} onClick={() => setMode('live')}>Live data</button>
          <button aria-pressed={mode === 'sim'} onClick={() => setMode('sim')}>Simulation</button>
        </div>
        <nav>
          <a href="/admin/" target="_blank" rel="noreferrer">Admin</a>
          <span className="muted">{user}</span>
          <button className="link" onClick={logout}>Sign out</button>
        </nav>
      </header>

      <MapView animals={animals} fences={fences} track={track} focus={focus} selected={selected}
        onSelect={select} fitKey={mode} now={now} edit={edit} onDraft={setDraft} />

      <aside>
        {mode === 'sim'
          ? <SimPanel running={running} setRunning={setRunning} speed={speed} setSpeed={setSpeed}
              onReset={resetSim} step={simStep} />
          : <LivePanel animals={animals} now={now} />}

        {error && <p className="error" role="alert">Connection problem: {error}</p>}

        <FencePanel fences={fences} mode={mode} edit={edit} setEdit={setEditing} draft={draft}
          onSaved={() => setRefreshKey(k => k + 1)} />

        {outside.length > 0 && (
          <div className="banner" role="status">
            {outside.length === 1 ? `${outside[0].name} is` : `${outside.length} animals are`} outside the fence
          </div>
        )}

        <section className="panel">
          <h2>Animals</h2>
          {!animals.length && <p className="muted">{mode === 'sim' ? 'Press Start to create the virtual herd.' : 'None yet.'}</p>}
          <ul className="list">
            {animals.map(a => {
              const s = statusOf(a, now)
              return (
                <li key={a.tag}>
                  <button className={'animal' + (a.tag === selected ? ' selected' : '') + (a.alert ? ' alerting' : '')}
                    onClick={() => select(a.tag)} aria-pressed={a.tag === selected}>
                    <span className={'dot ' + s} aria-hidden="true" />
                    <span className="grow">
                      <strong>{a.name}</strong> <span className="muted small">{a.tag}</span>
                      <span className="muted small block">
                        {a.reading
                          ? `${STATUS_LABEL[s]} · ${a.reading.distance_m} m from ${fenceById[a.fence.id]?.polygon ? 'edge' : 'center'} · ${a.reading.sats ?? '?'} sats · ${ago(a.reading.at, now)}`
                          : 'No readings yet'}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
          {selectedAnimal && mode === 'live' && (
            <label className="small">Fence for {selectedAnimal.name}
              <select value={selectedAnimal.fence.id} onChange={e => moveAnimal(selectedAnimal.tag, e.target.value)}>
                {fences.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </label>
          )}
          {selected && <p className="muted small">Blue line: {selected}'s last 6 hours. Click again to hide.</p>}
        </section>

        <section className="panel">
          <h2>Alerts</h2>
          {!alerts.length && <p className="muted">No breaches recorded.</p>}
          <ul className="list">
            {alerts.slice(0, 30).map(x => (
              <li key={x.id}>
                <button className={'alert' + (x.ended_at ? '' : ' open')} onClick={() => setFocus({ lat: x.lat, lon: x.lon })}>
                  <strong>{x.name}</strong> {x.ended_at ? 'returned' : 'is OUTSIDE'}
                  <span className="muted small block">
                    Left {time(x.started_at)}{x.ended_at && ` · back ${time(x.ended_at)}`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </aside>
    </div>
  )
}
