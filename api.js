/* ════════════════════════════════════════════════
   api.js  —  TELECOLA
════════════════════════════════════════════════ */
// En local usa localhost:8000, en producción usa la misma URL del sitio
const API_BASE_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:8000/api'
  : `${window.location.origin}/api`;

async function apiGetMedicamentos() {
  const res = await fetch(`${API_BASE_URL}/medicamentos`);
  if (!res.ok) throw new Error('No se pudo cargar el catálogo');
  return await res.json();
}

async function apiSolicitarTurno(doc) {
  const res = await fetch(`${API_BASE_URL}/turnos/solicitar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ documento: doc })
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Error en el servidor');
  }
  return await res.json();
}

async function apiGetColaEnVivo() {
  const res = await fetch(`${API_BASE_URL}/admin/turnos`);
  if (!res.ok) return { turnos: [] };
  return { turnos: await res.json() };
}

async function apiGetEstadoTurno(id) {
  const res = await fetch(`${API_BASE_URL}/turnos/estado/${id}`);
  if (!res.ok) throw new Error('Turno no encontrado');
  return await res.json();
}

async function apiConsultarTurnoPorDoc(doc) {
  const res = await fetch(`${API_BASE_URL}/turnos/consultar/${doc}`);
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Error al consultar');
  }
  return await res.json();
}
