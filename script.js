/* ════════════════════════════════════════════════
   script.js  —  TELECOLA
════════════════════════════════════════════════ */
let currentScreen       = 'screen-home';
let userTurno           = null;
let pollingTimer        = null;
let notificacionEnviada = false;

const MINS_POR_TURNO = 5;
const MINS_AVISO     = 10;
const TURNOS_AVISO   = Math.ceil(MINS_AVISO / MINS_POR_TURNO);

// ─── SOLO NÚMEROS ────────────────────────────────────────────────────
function aplicarFiltroNumerosInput(el) {
  if (!el) return;
  el.addEventListener('keydown', function(e) {
    const ok = ['Backspace','Delete','ArrowLeft','ArrowRight','Tab','Home','End','Enter'];
    if (ok.includes(e.key) || e.ctrlKey || e.metaKey) return;
    if (!/^\d$/.test(e.key)) e.preventDefault();
  });
  el.addEventListener('input', function() {
    const pos = this.selectionStart;
    const limpio = this.value.replace(/\D/g, '');
    if (this.value !== limpio) {
      this.value = limpio;
      try { this.setSelectionRange(pos - 1, pos - 1); } catch(_) {}
    }
  });
  el.addEventListener('paste', function(e) {
    e.preventDefault();
    const txt = (e.clipboardData || window.clipboardData).getData('text');
    document.execCommand('insertText', false, txt.replace(/\D/g, ''));
  });
}

// ─── SONIDO ──────────────────────────────────────────────────────────
function reproducirSonido(tipo) {
  try {
    const ctx  = new (window.AudioContext || window.webkitAudioContext)();
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    if (tipo === 'alerta') {
      osc.type = 'sine'; osc.frequency.setValueAtTime(880, ctx.currentTime);
      gain.gain.setValueAtTime(0.35, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.18);
      osc.start(ctx.currentTime); osc.stop(ctx.currentTime + 0.18);
      const o2=ctx.createOscillator(),g2=ctx.createGain();
      o2.connect(g2);g2.connect(ctx.destination);
      o2.type='sine';o2.frequency.setValueAtTime(1100,ctx.currentTime+.25);
      g2.gain.setValueAtTime(.35,ctx.currentTime+.25);
      g2.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+.5);
      o2.start(ctx.currentTime+.25);o2.stop(ctx.currentTime+.5);
    } else if (tipo === 'turno') {
      [0,.28,.56].forEach((t,i)=>{
        const o=ctx.createOscillator(),g=ctx.createGain();
        o.connect(g);g.connect(ctx.destination);o.type='sine';
        o.frequency.setValueAtTime([660,880,1100][i],ctx.currentTime+t);
        g.gain.setValueAtTime(.4,ctx.currentTime+t);
        g.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+t+.22);
        o.start(ctx.currentTime+t);o.stop(ctx.currentTime+t+.22);
      });
    } else if (tipo === 'ok') {
      osc.type='sine';osc.frequency.setValueAtTime(660,ctx.currentTime);
      gain.gain.setValueAtTime(.28,ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+.25);
      osc.start(ctx.currentTime);osc.stop(ctx.currentTime+.25);
    }
  } catch(e) {}
}

// ─── NAVEGACIÓN ──────────────────────────────────────────────────────
function goTo(id) {
  if (currentScreen === id) return;
  const prev = document.getElementById(currentScreen);
  if (prev) {
    prev.classList.remove('visible');
    setTimeout(() => { prev.classList.remove('active'); mostrarPantalla(id); }, 300);
  } else { mostrarPantalla(id); }
}

function mostrarPantalla(id) {
  currentScreen = id;
  const next = document.getElementById(id);
  if (next) {
    next.classList.add('active');
    setTimeout(() => next.classList.add('visible'), 50);
    window.scrollTo({ top:0, behavior:'smooth' });
  }
}

// ─── COLA EN VIVO ────────────────────────────────────────────────────
const TIPO_LABEL = { general:'General', mayor:'Adulto mayor', especial:'Cond. especial' };

function renderTicker(items) {
  if (!items?.length)
    return `<div class="ticker-row" style="justify-content:center;opacity:.5">
      <span style="font-size:.82rem;color:rgba(255,255,255,.5)">💊 Sin turnos activos</span>
    </div>`;
  return items.map(t => `
    <div class="ticker-row ${t.active?'is-active':''}">
      <span class="ticker-num">${t.code}</span>
      <div class="ticker-info">
        <div class="ticker-doc">··· ${t.doc}</div>
        <div class="ticker-sub">${TIPO_LABEL[t.tipo]||'General'}</div>
      </div>
      <span class="ticker-tag ${t.prio?'tag-prio':t.active?'tag-atendiendo':'tag-espera'}">
        ${t.prio?'Prioritario':t.active?'Atendiendo':'Espera'}
      </span>
    </div>`).join('');
}

async function cargarCola() {
  try {
    const data  = await apiGetColaEnVivo();
    const track = document.getElementById('ticker-track');
    if (track) {
      const items = data.turnos.map(t => ({
        code: t.codigo, doc: String(t.documento).slice(-4),
        tipo: t.tipo_usuario||'general',
        prio: ['mayor','especial'].includes(t.tipo_usuario),
        active: t.estado==='atendiendo'
      }));
      track.innerHTML = renderTicker(items) + renderTicker(items);
    }
    const total = data.turnos.length;
    const el = (id,v) => { const e=document.getElementById(id); if(e) e.textContent=v; };
    el('stat-espera', `~${total*5} min`);
    el('stat-cola', total);
    el('stat-actual', total>0 ? data.turnos[0].codigo : '---');
    // Sync mini stats móvil
    el('mob-espera', `~${total*5}m`);
    el('mob-cola', total);
    el('mob-actual', total>0 ? data.turnos[0].codigo : '---');
  } catch (_) {}
}

// ─── SOLICITAR TURNO ─────────────────────────────────────────────────
async function solicitarTurno() {
  const doc = document.getElementById('sol-doc').value.trim();
  if (!doc || doc.length < 5) { showToast('⚠️ Ingresa un documento válido'); return; }
  if (Notification.permission !== 'granted') Notification.requestPermission();

  const btn = document.getElementById('btn-solicitar');
  btn.classList.add('loading');
  try {
    const data = await apiSolicitarTurno(doc);
    userTurno = { id:data.id, codigo:data.codigo_turno, doc, isPrio:data.is_prio, posInicial:null };
    notificacionEnviada = false;

    document.getElementById('t-numero').textContent = data.codigo_turno;
    document.getElementById('t-doc').textContent    = `Doc: •••• ${doc.slice(-4)}`;
    const medEl = document.getElementById('t-med');
    if (medEl && data.medicamento) medEl.textContent = `💊 ${data.medicamento}`;
    document.getElementById('prio-banner').style.display = data.is_prio ? 'flex' : 'none';
    document.getElementById('topbar-my-turn').style.display   = 'flex';
    document.getElementById('topbar-my-turn-val').textContent = data.codigo_turno;
    // Mostrar check animado
    const chk = document.getElementById('turno-check');
    if (chk) { chk.classList.add('visible'); setTimeout(()=>chk.classList.remove('visible'), 3000); }

    iniciarPolling();
    goTo('screen-turno');
    reproducirSonido('ok');
    showToast('✅ Turno registrado — revisa tu correo');
  } catch (err) {
    showToast(`❌ ${err.message}`);
  } finally {
    btn.classList.remove('loading');
  }
}

// ─── CONSULTAR TURNO ─────────────────────────────────────────────────
async function consultarTurno() {
  const doc = document.getElementById('con-doc').value.trim();
  if (!doc || doc.length < 5) { showToast('⚠️ Ingresa un documento válido'); return; }

  const btn = document.querySelector('#screen-consultar .btn-submit');
  btn.classList.add('loading');
  try {
    const data = await apiConsultarTurnoPorDoc(doc);
    document.getElementById('consulta-box').style.display = 'block';
    document.getElementById('con-num').textContent  = data.codigo;
    document.getElementById('con-med').textContent  = data.medicamento;
    document.getElementById('con-pos').textContent  = data.estado==='atendiendo'?'Ventanilla':`#${data.posicion}`;
    document.getElementById('con-esp').textContent  = data.estado==='atendiendo'?'¡Ahora!':`~${data.posicion*5} min`;
    document.getElementById('con-est').textContent  = data.estado==='en_espera'?'En espera':'En atención';
    userTurno = { id:data.id, codigo:data.codigo, doc };
    document.getElementById('topbar-my-turn').style.display   = 'flex';
    document.getElementById('topbar-my-turn-val').textContent = data.codigo;
    iniciarPolling();
  } catch (err) {
    document.getElementById('consulta-box').style.display = 'none';
    showToast(`❌ ${err.message}`);
  } finally { btn.classList.remove('loading'); }
}

// ─── POLLING ─────────────────────────────────────────────────────────
function iniciarPolling() {
  if (pollingTimer) clearInterval(pollingTimer);
  pollingTimer = setInterval(async () => {
    if (!userTurno) return;
    try {
      const e = await apiGetEstadoTurno(userTurno.id);
      // Guardar posición inicial para calcular progreso real
      if (userTurno.posInicial === null && e.posicion > 0) userTurno.posInicial = e.posicion;
      const set = (id,v) => { const el=document.getElementById(id); if(el) el.textContent=v; };
      set('t-pos',    e.posicion||'0');
      set('t-esp',    e.estado==='atendiendo'?'¡Ahora!':`~${e.posicion * MINS_POR_TURNO} min`);
      set('t-actual', e.estado==='atendiendo'?'¡Es tu turno!':'En espera');

      // Actualizar barra de progreso
      const fill = document.getElementById('progress-fill');
      const ptxt = document.getElementById('progress-txt');
      if (fill && ptxt) {
        if (e.estado === 'atendiendo') {
          fill.style.width = '100%';
          fill.classList.add('atendiendo');
          ptxt.textContent = '¡Es tu turno!';
        } else {
          fill.classList.remove('atendiendo');
          const pct = userTurno.posInicial
            ? Math.max(5, Math.round((1 - e.posicion / userTurno.posInicial) * 100))
            : Math.max(5, 100 - (e.posicion * 15));
          fill.style.width = Math.min(100, pct) + '%';
          ptxt.textContent = `Posición #${e.posicion} · ~${e.posicion * MINS_POR_TURNO} min`;
        }
      }

      // Aviso ~10 minutos antes
      if (e.posicion > 0 && e.posicion <= TURNOS_AVISO && !notificacionEnviada && e.estado==='en_espera') {
        notificacionEnviada = true;
        if (Notification.permission==='granted')
          new Notification('⏰ Prepárate', { body:`Tu turno ${e.codigo} está a ${e.posicion} turno(s). Ve acercándote.` });
        reproducirSonido('alerta');
        showToast(`🔔 Faltan ~${e.posicion * MINS_POR_TURNO} min — ve acercándote`);
      }
      if (e.estado==='atendiendo') {
        clearInterval(pollingTimer);
        set('t-pos','Ventanilla'); set('t-esp','¡Ahora!'); set('t-actual','¡Es tu turno!');
        reproducirSonido('turno');
        showToast('📢 ¡Pasa a ventanilla ahora!');
        if (Notification.permission==='granted')
          new Notification('📢 ¡Es tu turno!', { body:`${e.codigo} — acércate a la ventanilla.` });
      }
    } catch (_) {}
  }, 5000);
}

// ─── TOAST ───────────────────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3200);
}

// ─── INIT ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  cargarCola();
  setInterval(cargarCola, 8000);
  ['sol-doc', 'con-doc'].forEach(id => aplicarFiltroNumerosInput(document.getElementById(id)));
});
