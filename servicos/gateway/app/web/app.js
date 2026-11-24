// Tela do HelpDesk TI (servida pelo API Gateway).
// Todo texto vindo da API passa por esc() antes de entrar no HTML, bloqueando XSS.
"use strict";
const API = "";
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (s) => new Date(s).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const ROTULO = { aberto: "aberto", em_atendimento: "em atendimento", resolvido: "resolvido", fechado: "fechado" };
const NOMES_SERVICOS = { usuarios: "Usuários", inventario: "Inventário", chamados: "Chamados", notificacoes: "Notificações" };

let token = null;
let eu = null;
let usuarios = [];
let ativosLista = [];
let chamadosLista = [];
let chamadoModalId = null;
let timerNotificacoes = null;
let elementoFocoAnterior = null;

try { token = sessionStorage.getItem("token"); } catch (e) { token = null; }

async function req(metodo, caminho, corpo) {
  const cab = { "Content-Type": "application/json" };
  if (token) cab.Authorization = "Bearer " + token;
  const r = await fetch(API + caminho, { method: metodo, headers: cab, body: corpo ? JSON.stringify(corpo) : undefined });
  const dados = await r.json().catch(() => ({}));
  if (r.status === 401 && caminho !== "/auth/login") {
    sair();
    throw new Error("Sessão expirada. Entre novamente.");
  }
  if (!r.ok) {
    throw new Error(typeof dados.detail === "string" ? dados.detail : "Dados inválidos (" + r.status + ").");
  }
  return dados;
}

function guardarToken(t) {
  token = t;
  try { t ? sessionStorage.setItem("token", t) : sessionStorage.removeItem("token"); } catch (e) {}
}

function cancelarTimerNotificacoes() {
  if (timerNotificacoes !== null) {
    clearTimeout(timerNotificacoes);
    timerNotificacoes = null;
  }
}

function sair() {
  cancelarTimerNotificacoes();
  chamadoModalId = null;
  if ($("modal-chamado").open) $("modal-chamado").close();
  guardarToken(null);
  eu = null;
  usuarios = [];
  ativosLista = [];
  chamadosLista = [];
  mostrar(false);
}

function mostrar(logado) {
  $("tela-login").hidden = logado;
  $("tela-sistema").hidden = !logado;
  $("barra").hidden = !logado;
}

const nome = (id) => (usuarios.find((u) => u.id === id) || {}).nome || "Usuário #" + id;
const equipe = () => eu && (eu.perfil === "tecnico" || eu.perfil === "admin");

function renderizarSaude(saude) {
  const resumo = $("saude-resumo");
  const cont = $("saude-servicos");
  if (!saude || !saude.servicos) {
    resumo.textContent = "Gateway sem resposta";
    cont.innerHTML = `<span class="svc-chip svc-offline">Gateway · offline</span>`;
    return;
  }
  resumo.textContent = saude.status === "ok" ? "Todos os serviços operacionais" : "Operação degradada (serviço fora do ar)";
  const itens = [
    `<span class="svc-chip svc-ok">Gateway · ok</span>`,
    ...Object.entries(saude.servicos).map(([chave, info]) => {
      const st = info.status || "offline";
      const cls = st === "ok" ? "svc-ok" : st === "degradado" ? "svc-degradado" : "svc-offline";
      const lat = typeof info.latencia_ms === "number" ? ` (${Math.round(info.latencia_ms)} ms)` : "";
      return `<span class="svc-chip ${cls}">${esc(NOMES_SERVICOS[chave] || chave)} · ${esc(st)}${esc(lat)}</span>`;
    }),
  ];
  cont.innerHTML = itens.join("");
}

function renderizarAvisos(avisos) {
  $("avisos").innerHTML = avisos.slice().reverse().slice(0, 6).map((a) =>
    `<div class="aviso"><b>${esc(a.tipo)}</b><br>${esc(a.mensagem)}<small>${esc(fmt(a.criada_em))}</small></div>`
  ).join("") || "<small>Nenhuma notificação.</small>";
}

function agendarRefreshNotificacoes() {
  cancelarTimerNotificacoes();
  timerNotificacoes = setTimeout(async () => {
    timerNotificacoes = null;
    if (!token) return;
    try {
      const avisos = await req("GET", "/notificacoes");
      if (token) renderizarAvisos(avisos);
    } catch (e) {}
  }, 450);
}

async function carregar() {
  $("erro").textContent = "";
  eu = await req("GET", "/auth/eu");
  $("quem").textContent = eu.nome + " (" + eu.perfil + ")";
  $("box-ativo").hidden = !equipe();
  $("box-usuario").hidden = eu.perfil !== "admin";

  const avisosDeFalha = [];
  const tentar = (caminho, padrao) => req("GET", caminho).catch((e) => { avisosDeFalha.push(e.message); return padrao; });
  const [saude, lista, ativos, chamados, painel, avisos] = await Promise.all([
    req("GET", "/saude").catch(() => null),
    tentar("/usuarios", []),
    tentar("/ativos", null),
    tentar("/chamados", []),
    tentar("/chamados/painel", { total: 0, por_status: {}, atrasados: 0 }),
    tentar("/notificacoes", []),
  ]);

  usuarios = lista;
  if (ativos !== null) ativosLista = ativos;
  chamadosLista = chamados;

  renderizarSaude(saude);
  const ps = painel.por_status || {};
  $("kpis").innerHTML = [
    ["Total", painel.total],
    ["Abertos", ps.aberto || 0],
    ["Em atendimento", ps.em_atendimento || 0],
    ["Resolvidos", (ps.resolvido || 0) + (ps.fechado || 0)],
    ["Atrasados", painel.atrasados],
  ].map(([t, v]) => `<div class="kpi"><small>${esc(t)}</small><b>${esc(v)}</b></div>`).join("");

  const tecnicos = usuarios.filter((u) => u.perfil === "tecnico");
  $("lista").innerHTML = chamados.map((c) => `<tr>
    <td>${esc(c.id)}</td>
    <td><b>${esc(c.titulo)}</b><br><small>${esc(nome(c.solicitante_id))}</small></td>
    <td class="p-${esc(c.prioridade)}">${esc(c.prioridade)}</td>
    <td><span class="pill s-${esc(c.status)}">${esc(ROTULO[c.status] || c.status)}</span></td>
    <td>${c.tecnico_id ? esc(nome(c.tecnico_id)) : "—"}</td>
    <td>${esc(fmt(c.prazo_sla))}</td>
    <td><div class="acoes">${acoes(c, tecnicos)}</div></td>
  </tr>`).join("") || `<tr><td colspan="7"><small>Nenhum chamado.</small></td></tr>`;

  renderizarAvisos(avisos);
  $("erro").textContent = [...new Set(avisosDeFalha)].join(" ");
  if (ativos !== null || $("ativo").options.length === 0) {
    const selecionado = $("ativo").value;
    $("ativo").innerHTML = `<option value="">Nenhum</option>` + ativosLista.map((a) =>
      `<option value="${esc(a.id)}">${esc(a.patrimonio)} · ${esc(a.descricao)}</option>`
    ).join("");
    if (selecionado) $("ativo").value = selecionado;
  }

  if (chamadoModalId !== null && $("modal-chamado").open) {
    renderizarModal(chamadoModalId);
  }
}

function acoes(c, tecnicos) {
  const botao = (acaoNome, texto, extra = "") =>
    `<button type="button" data-acao="${acaoNome}" data-id="${esc(c.id)}" ${extra}>${esc(texto)}</button>`;
  const partes = [botao("ver", "Detalhes", 'class="sec"')];
  if (equipe() && c.status === "aberto") {
    partes.push(
      `<select id="t${esc(c.id)}" aria-label="Técnico">${tecnicos.map((t) => `<option value="${esc(t.id)}">${esc(t.nome)}</option>`).join("")}</select>` +
      botao("atribuir", "Atribuir")
    );
  } else if (equipe() && c.status === "em_atendimento") {
    partes.push(botao("resolvido", "Resolver"));
  } else if (c.status === "resolvido" && (equipe() || c.solicitante_id === eu.id)) {
    partes.push(botao("fechado", "Fechar") + botao("em_atendimento", "Reabrir", 'class="sec"'));
  }
  return partes.join("");
}

function renderizarModal(id) {
  const c = chamadosLista.find((item) => item.id === id);
  if (!c) {
    $("modal-chamado").close();
    return;
  }
  chamadoModalId = id;
  $("modal-titulo").textContent = `Chamado #${c.id} · ${c.titulo}`;
  const ativoObj = ativosLista.find((a) => a.id === c.ativo_id);
  const textoAtivo = c.ativo_id ? (ativoObj ? `${ativoObj.patrimonio} · ${ativoObj.descricao}` : `Ativo #${c.ativo_id}`) : "Nenhum";
  const comentariosHtml = (c.comentarios || []).map((cm) =>
    `<div class="comentario-item"><b>${esc(nome(cm.autor_id))}</b>: ${esc(cm.texto)}<small>${esc(fmt(cm.criado_em))}</small></div>`
  ).join("") || "<small>Nenhum comentário ainda.</small>";

  $("modal-corpo").innerHTML = `
    <div class="meta-chamado">
      <div><b>Solicitante:</b> ${esc(nome(c.solicitante_id))} · <b>Status:</b> ${esc(ROTULO[c.status] || c.status)} · <b>Prioridade:</b> ${esc(c.prioridade)}</div>
      <div><b>Equipamento:</b> ${esc(textoAtivo)} · <b>Prazo SLA:</b> ${esc(fmt(c.prazo_sla))}</div>
      <div><b>Descrição:</b> ${esc(c.descricao)}</div>
    </div>
    <h3>Comentários</h3>
    <div class="comentarios-lista">${comentariosHtml}</div>
  `;
  const fechado = c.status === "fechado";
  $("texto-comentario").disabled = fechado;
  $("btn-comentar").disabled = fechado;
  $("erro-modal").textContent = fechado ? "Chamados fechados não recebem comentários." : "";
}

async function acao(f, atualizaNotificacoes = false) {
  try {
    await f();
    await carregar();
    if (atualizaNotificacoes) agendarRefreshNotificacoes();
  } catch (e) {
    $("erro").textContent = e.message;
  }
}

$("lista").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-acao]");
  if (!b) return;
  const id = Number(b.dataset.id);
  const tipoAcao = b.dataset.acao;
  if (tipoAcao === "ver") {
    elementoFocoAnterior = b;
    renderizarModal(id);
    $("modal-chamado").showModal();
    return;
  }
  if (tipoAcao === "atribuir") {
    acao(() => req("PATCH", `/chamados/${id}/atribuir`, { tecnico_id: Number($("t" + id).value) }), true);
  } else {
    acao(() => req("PATCH", `/chamados/${id}/status`, { status: tipoAcao }), tipoAcao === "resolvido");
  }
});

$("fechar-modal").addEventListener("click", () => $("modal-chamado").close());
$("modal-chamado").addEventListener("close", () => {
  chamadoModalId = null;
  if (elementoFocoAnterior && typeof elementoFocoAnterior.focus === "function") {
    elementoFocoAnterior.focus();
  }
});

$("form-comentario").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (chamadoModalId === null) return;
  $("erro-modal").textContent = "";
  try {
    await req("POST", `/chamados/${chamadoModalId}/comentarios`, { texto: $("texto-comentario").value });
    $("texto-comentario").value = "";
    await carregar();
  } catch (err) {
    $("erro-modal").textContent = err.message;
  }
});

$("novo").addEventListener("submit", (e) => {
  e.preventDefault();
  acao(() => req("POST", "/chamados", {
    titulo: $("titulo").value,
    descricao: $("descricao").value,
    prioridade: $("prioridade").value,
    ativo_id: $("ativo").value ? Number($("ativo").value) : null,
  }), true);
});

$("form-ativo").addEventListener("submit", (e) => {
  e.preventDefault();
  acao(async () => {
    await req("POST", "/ativos", {
      patrimonio: $("ativo-pat").value,
      tipo: $("ativo-tipo").value,
      descricao: $("ativo-desc").value,
      setor: $("ativo-setor").value,
    });
    $("form-ativo").reset();
  });
});

$("form-usuario").addEventListener("submit", (e) => {
  e.preventDefault();
  acao(async () => {
    await req("POST", "/usuarios", {
      nome: $("usu-nome").value,
      email: $("usu-email").value,
      perfil: $("usu-perfil").value,
      senha: $("usu-senha").value,
    });
    $("form-usuario").reset();
  });
});

$("tela-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("erro-login").textContent = "";
  try {
    const r = await req("POST", "/auth/login", { email: $("email").value, senha: $("senha").value });
    guardarToken(r.access_token);
    $("senha").value = "";
    mostrar(true);
    await carregar();
  } catch (err) {
    $("erro-login").textContent = err.message;
  }
});

$("atualizar").addEventListener("click", () => { carregar().catch((e) => { $("erro").textContent = e.message; }); });
$("sair").addEventListener("click", sair);

if (token) {
  mostrar(true);
  carregar().catch((e) => { $("erro").textContent = e.message; });
} else {
  mostrar(false);
}
