// ==========================================
// ATROPBOT — app.js (Lógica Blindada V4)
// ==========================================

function toast(msg, tipo = "ok") {
  const wrap = document.getElementById("toast-wrap");
  if(!wrap) return;
  const el = document.createElement("div");
  el.className = `toast ${tipo}`;

  const texto = document.createElement("span");
  texto.className = "toast-texto";
  texto.textContent = msg;
  el.appendChild(texto);

  const btnFechar = document.createElement("button");
  btnFechar.className = "toast-fechar";
  btnFechar.textContent = "✕";
  btnFechar.addEventListener("click", () => el.remove());
  el.appendChild(btnFechar);

  wrap.appendChild(el);

  // Mensagens de erro ficam bem mais tempo na tela (10s) — e o usuário
  // ainda pode fechar antes ou depois clicando no X. Mensagens de
  // sucesso/aviso continuam rápidas, para não acumular.
  const duracao = tipo === "erro" ? 10000 : 4200;
  const timeoutId = setTimeout(() => el.remove(), duracao);

  // Passar o mouse por cima pausa o desaparecimento — evita perder a
  // mensagem se você for ler bem no instante em que ela ia fechar.
  el.addEventListener("mouseenter", () => clearTimeout(timeoutId));
}

async function api(metodo, url, corpo) {
  const opts = { method: metodo, headers: {} };
  if (corpo !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(corpo);
  }
  const resp = await fetch(url, opts);
  let dados = null;
  try { dados = await resp.json(); } catch (_) { }
  if (!resp.ok) {
    const msg = (dados && dados.erro) ? dados.erro : `Erro ${resp.status}`;
    throw new Error(msg);
  }
  return dados;
}

// ===================== NAVEGAÇÃO DE ABAS =====================
function configurarAbas() {
  const botoes = document.querySelectorAll(".nav-item");
  botoes.forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      botoes.forEach(b => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      
      document.querySelectorAll(".aba").forEach(a => a.hidden = true);
      
      const alvo = document.getElementById(`aba-${btn.dataset.aba}`);
      if(alvo) alvo.hidden = false;
    });
  });
}

// ===================== AUTOCOMPLETE GENÉRICO =====================
function ligarAutocomplete(input, fonte, onEscolher) {
  if(!input) return;
  const wrap = document.createElement("div");
  wrap.className = "autocomplete-wrap";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  const lista = document.createElement("div");
  lista.className = "autocomplete-lista";
  lista.style.display = "none";
  wrap.appendChild(lista);

  let itens = [];
  let ativo = -1;
  let debounceId = null;

  async function buscar(texto) {
    try {
      if (typeof fonte === "function") {
        itens = await fonte(texto);
      } else {
        const params = new URLSearchParams({ tabela: fonte.tabela, coluna: fonte.coluna, texto });
        itens = await api("GET", `/api/sugestoes?${params.toString()}`);
      }
    } catch (e) { itens = []; }
    renderizar();
  }

  function renderizar() {
    ativo = -1;
    lista.innerHTML = "";
    if (itens.length === 0) { lista.style.display = "none"; return; }
    itens.forEach((valor, i) => {
      const item = document.createElement("div");
      item.className = "item";
      item.textContent = valor;
      item.addEventListener("mousedown", (e) => { e.preventDefault(); escolher(valor); });
      lista.appendChild(item);
    });
    lista.style.display = "block";
  }

  function escolher(valor) {
    input.value = valor;
    lista.style.display = "none";
    if (onEscolher) onEscolher(valor);
  }

  function fecharLista() { lista.style.display = "none"; }

  input.addEventListener("input", () => {
    clearTimeout(debounceId);
    debounceId = setTimeout(() => buscar(input.value.trim()), 120);
  });

  input.addEventListener("focus", () => buscar(input.value.trim()));

  input.addEventListener("keydown", (e) => {
    if (lista.style.display === "none") return;
    const opcoes = lista.querySelectorAll(".item");
    if (e.key === "ArrowDown") {
      e.preventDefault(); ativo = Math.min(ativo + 1, opcoes.length - 1); atualizarAtivo(opcoes);
    } else if (e.key === "ArrowUp") {
      e.preventDefault(); ativo = Math.max(ativo - 1, 0); atualizarAtivo(opcoes);
    } else if (e.key === "Enter") {
      if (ativo >= 0 && opcoes[ativo]) { e.preventDefault(); escolher(opcoes[ativo].textContent); }
    } else if (e.key === "Escape") { fecharLista(); }
  });

  function atualizarAtivo(opcoes) {
    opcoes.forEach((el, i) => el.classList.toggle("is-ativo", i === ativo));
    if (ativo >= 0) opcoes[ativo].scrollIntoView({ block: "nearest" });
  }

  document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) fecharLista(); });
  return { recarregar: () => buscar(input.value.trim()) };
}

// ===================== BLOCO: CONFIGURAÇÕES =====================
const veiculoEdicao = { placaOriginal: null };

async function carregarVeiculos() {
  const lista = await api("GET", "/api/veiculos");
  const tbody = document.querySelector("#tabela-veiculos tbody");
  if(!tbody) return;
  tbody.innerHTML = "";
  if (lista.length === 0) {
    tbody.innerHTML = `<tr class="tabela-vazia"><td colspan="4">Nenhum veículo cadastrado.</td></tr>`;
    return;
  }
  lista.forEach(v => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="check-veiculo" value="${v.placa}"></td>
      <td>${v.placa}</td>
      <td style="font-family:var(--font-sans)">${v.motorista || ""}</td>
      <td>${v.cpf}</td>`;
    tr.addEventListener("click", (e) => {
      if (e.target.tagName === "INPUT") return;
      iniciarEdicaoVeiculo(v);
    });
    tbody.appendChild(tr);
  });
}

function iniciarEdicaoVeiculo(v) {
  veiculoEdicao.placaOriginal = v.placa;
  document.getElementById("veiculo-placa").value = v.placa;
  document.getElementById("veiculo-motorista").value = v.motorista || "";
  document.getElementById("veiculo-cpf").value = v.cpf;
  document.getElementById("btn-salvar-veiculo").textContent = "Salvar Edição";
  document.getElementById("btn-cancelar-edicao-veiculo").hidden = false;
}

function cancelarEdicaoVeiculo() {
  veiculoEdicao.placaOriginal = null;
  const f = document.getElementById("form-veiculo");
  if(f) f.reset();
  document.getElementById("btn-salvar-veiculo").textContent = "Salvar Veículo";
  document.getElementById("btn-cancelar-edicao-veiculo").hidden = true;
}

function configurarVeiculos() {
  const form = document.getElementById("form-veiculo");
  if(!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const placa = document.getElementById("veiculo-placa").value.trim().toUpperCase();
    const motorista = document.getElementById("veiculo-motorista").value.trim().toUpperCase();
    const cpf = document.getElementById("veiculo-cpf").value.trim();
    try {
      await api("POST", "/api/veiculos", { placa, motorista, cpf, placa_original: veiculoEdicao.placaOriginal || "" });
      toast(veiculoEdicao.placaOriginal ? `Veículo ${placa} atualizado!` : `Veículo ${placa} salvo!`);
      cancelarEdicaoVeiculo();
      carregarVeiculos();
    } catch (err) { toast(err.message, "erro"); }
  });

  document.getElementById("btn-cancelar-edicao-veiculo").addEventListener("click", cancelarEdicaoVeiculo);

  document.getElementById("check-todos-veiculos").addEventListener("change", (e) => {
    document.querySelectorAll(".check-veiculo").forEach(c => c.checked = e.target.checked);
  });

  document.getElementById("btn-excluir-veiculos").addEventListener("click", async () => {
    const placas = [...document.querySelectorAll(".check-veiculo:checked")].map(c => c.value);
    if (placas.length === 0) { toast("Selecione ao menos um veículo.", "aviso"); return; }
    if (!confirm(`Excluir ${placas.length} veículo(s)?`)) return;
    await api("POST", "/api/veiculos/excluir", { placas });
    toast("Veículo(s) excluído(s).");
    carregarVeiculos();
  });

  document.getElementById("input-csv").addEventListener("change", async (e) => {
    const arquivo = e.target.files[0];
    if (!arquivo) return;
    const formData = new FormData();
    formData.append("arquivo", arquivo);
    try {
      const resp = await fetch("/api/veiculos/importar_csv", { method: "POST", body: formData });
      const dados = await resp.json();
      if (!resp.ok) throw new Error(dados.erro || "Erro ao importar.");
      toast(`${dados.importados} veículo(s) importado(s)!`);
      carregarVeiculos();
    } catch (err) { toast(err.message, "erro"); }
    e.target.value = "";
  });
}

async function carregarVinculos() {
  const lista = await api("GET", "/api/vinculos");
  const tbody = document.querySelector("#tabela-vinculos tbody");
  if(!tbody) return;
  tbody.innerHTML = "";
  if (lista.length === 0) {
    tbody.innerHTML = `<tr class="tabela-vazia"><td colspan="3">Nenhum vínculo.</td></tr>`;
    return;
  }
  lista.forEach(v => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="check-vinculo" data-fazenda="${v.fazenda}" data-contrato="${v.contrato}"></td>
      <td>${v.fazenda}</td><td>${v.contrato}</td>`;
    tbody.appendChild(tr);
  });
}

function configurarVinculos() {
  const form = document.getElementById("form-vinculo");
  if(!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fazenda = document.getElementById("vinculo-fazenda").value.trim().toUpperCase();
    const contrato = document.getElementById("vinculo-contrato").value.trim().toUpperCase();
    if (!fazenda || !contrato) { toast("Preencha a Fazenda e o Contrato.", "aviso"); return; }
    try {
      await api("POST", "/api/vinculos", { fazenda, contrato });
      toast(`Vínculo ${fazenda} → ${contrato} salvo!`);
      document.getElementById("vinculo-fazenda").value = "";
      document.getElementById("vinculo-contrato").value = "";
      carregarVinculos();
    } catch (err) { toast(err.message, "erro"); }
  });

  document.getElementById("check-todos-vinculos").addEventListener("change", (e) => {
    document.querySelectorAll(".check-vinculo").forEach(c => c.checked = e.target.checked);
  });

  document.getElementById("btn-excluir-vinculos").addEventListener("click", async () => {
    const pares = [...document.querySelectorAll(".check-vinculo:checked")].map(c => ({ fazenda: c.dataset.fazenda, contrato: c.dataset.contrato }));
    if (pares.length === 0) { toast("Selecione ao menos um vínculo.", "aviso"); return; }
    await api("POST", "/api/vinculos/excluir", { pares });
    toast("Vínculo(s) removido(s).");
    carregarVinculos();
  });
}

async function carregarCredenciaisTrizy() {
  const elEmail = document.getElementById("trizy-email");
  if(!elEmail) return;
  const { email, senha } = await api("GET", "/api/credenciais_trizy");
  elEmail.value = email;
  document.getElementById("trizy-senha").value = senha;
}

function configurarTrizy() {
  const form = document.getElementById("form-trizy");
  if(!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("trizy-email").value.trim();
    const senha = document.getElementById("trizy-senha").value.trim();
    await api("POST", "/api/credenciais_trizy", { email, senha });
    toast("Credenciais salvas!");
  });

  document.getElementById("btn-olho-senha").addEventListener("click", () => {
    const campo = document.getElementById("trizy-senha");
    const btn = document.getElementById("btn-olho-senha");
    if (campo.type === "password") { campo.type = "text"; btn.textContent = "🙈"; }
    else { campo.type = "password"; btn.textContent = "👁"; }
  });
}

// ===================== HISTÓRICO DE EVENTOS DO TRIZY =====================
function escapeHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto;
  return div.innerHTML;
}

function formatarHoraEvento(timestampSegundos) {
  const d = new Date(timestampSegundos * 1000);
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function carregarEventosTrizy() {
  const lista = document.getElementById("eventos-trizy-lista");
  if (!lista) return;
  const tipo = document.getElementById("filtro-tipo-evento")?.value || "";

  try {
    const params = tipo ? `?tipo=${encodeURIComponent(tipo)}` : "";
    const eventos = await api("GET", `/api/eventos_trizy${params}`);

    if (eventos.length === 0) {
      lista.innerHTML = `<p class="dica-texto">Nenhum evento registrado ainda. Eles aparecem aqui automaticamente conforme o ATROPBOT roda e encontra avisos na tela do Trizy.</p>`;
      return;
    }

    lista.innerHTML = eventos.map(ev => {
      const thumb = ev.screenshot
        ? `<img class="evento-trizy-thumb" src="/screenshots/${encodeURIComponent(ev.screenshot)}" data-full="/screenshots/${encodeURIComponent(ev.screenshot)}" alt="screenshot">`
        : `<div class="evento-trizy-thumb"></div>`;
      const placaTexto = ev.placa ? ` · ${escapeHtml(ev.placa)}` : "";
      return `
        <div class="evento-trizy-item">
          ${thumb}
          <div class="evento-trizy-corpo">
            <div class="evento-trizy-topo">
              <span class="evento-trizy-tag ${ev.tipo}">${ev.tipo}</span>
              <span class="evento-trizy-meta">${formatarHoraEvento(ev.hora)}${placaTexto}</span>
            </div>
            <div class="evento-trizy-texto">${escapeHtml(ev.texto)}</div>
          </div>
        </div>`;
    }).join("");

    lista.querySelectorAll(".evento-trizy-thumb[data-full]").forEach(img => {
      img.addEventListener("click", () => abrirLightbox(img.dataset.full));
    });
  } catch (err) {
    lista.innerHTML = `<p class="dica-texto">Não foi possível carregar o histórico agora.</p>`;
  }
}

function abrirLightbox(urlImagem) {
  const overlay = document.createElement("div");
  overlay.className = "lightbox-overlay";
  overlay.innerHTML = `<img src="${urlImagem}" alt="screenshot ampliado">`;
  overlay.addEventListener("click", () => overlay.remove());
  document.body.appendChild(overlay);
}

function configurarEventosTrizy() {
  const filtro = document.getElementById("filtro-tipo-evento");
  if (filtro) filtro.addEventListener("change", carregarEventosTrizy);

  const btnAtualizar = document.getElementById("btn-atualizar-eventos");
  if (btnAtualizar) btnAtualizar.addEventListener("click", carregarEventosTrizy);
}

function configurarNavegadorManual() {
  const btnNavManual = document.getElementById("btn-abrir-nav-manual");
  if(btnNavManual) {
    btnNavManual.addEventListener("click", async () => {
      try {
        await api("POST", "/api/navegador/abrir_manual");
        toast("Navegador manual aberto.");
      } catch(err) { toast(err.message, "erro"); }
    });
  }

  const btnForcarFechar = document.getElementById("btn-forcar-fechar-nav");
  if(btnForcarFechar) {
    btnForcarFechar.addEventListener("click", async () => {
      if (!confirm("Isso vai zerar o estado do navegador no ATROPBOT, mesmo que ele esteja respondendo normalmente. Use só se o app estiver 'travado' dizendo que o navegador está aberto quando na verdade já foi fechado.\n\nContinuar?")) return;
      try {
        await api("POST", "/api/navegador/forcar_fechamento");
        toast("Navegador desconectado. Estado zerado.");
        atualizarEstadoRobo();
      } catch(err) { toast(err.message, "erro"); }
    });
  }
}

// ===================== BLOCO: OPERAÇÃO =====================
// Converte o valor do <input type="date"> (aaaa-mm-dd) para dd/mm/aaaa,
// que é o formato que o Trizy espera. Vazio vira "".
function dataParaBR(valorISO) {
  if (!valorISO) return "";
  const partes = valorISO.split("-");
  if (partes.length !== 3) return valorISO;
  return `${partes[2]}/${partes[1]}/${partes[0]}`;
}

function lerLote() {
  const cT = document.getElementById("lote-terminal-input");
  const cD = document.getElementById("lote-data-input");
  return {
    terminal: cT ? cT.value.trim().toUpperCase() : "",
    fazenda: document.getElementById("lote-fazenda-input") ? document.getElementById("lote-fazenda-input").value.trim().toUpperCase() : "",
    contrato: document.getElementById("lote-contrato-input") ? document.getElementById("lote-contrato-input").value.trim().toUpperCase() : "",
    data_cota: cD ? dataParaBR(cD.value.trim()) : "",
  };
}

function atualizarBadgeLote() {
  const { terminal, fazenda, contrato, data_cota } = lerLote();
  const lbTerm = document.getElementById("lote-terminal");
  if(lbTerm) {
      lbTerm.textContent = terminal || "—";
      document.getElementById("lote-fazenda").textContent = fazenda || "—";
      document.getElementById("lote-contrato").textContent = contrato || "—";
      const lbData = document.getElementById("lote-data");
      if (lbData) lbData.textContent = data_cota || "—";
  }
}

async function preencherContratoDaFazenda(fazenda) {
  if (!fazenda) return;
  try {
    const contratos = await api("GET", `/api/contratos_da_fazenda?fazenda=${encodeURIComponent(fazenda)}`);
    if (contratos.length > 0) {
      const cmp = document.getElementById("lote-contrato-input");
      if(cmp) {
          cmp.value = contratos[0];
          atualizarBadgeLote();
      }
    }
  } catch (_) { }
}

function configurarLote() {
  const campoTerminal = document.getElementById("lote-terminal-input");
  const campoFazenda = document.getElementById("lote-fazenda-input");
  const campoContrato = document.getElementById("lote-contrato-input");
  const campoData = document.getElementById("lote-data-input");

  if(!campoTerminal) return;

  campoTerminal.addEventListener("change", atualizarBadgeLote);
  if (campoData) campoData.addEventListener("change", atualizarBadgeLote);

  ligarAutocomplete(campoFazenda, { tabela: "fazendas", coluna: "nome" }, (valor) => {
    atualizarBadgeLote();
    preencherContratoDaFazenda(valor);
  });

  campoContrato.addEventListener("input", atualizarBadgeLote);

  document.getElementById("btn-limpar-lote").addEventListener("click", async () => {
    if (!confirm("Isso vai esvaziar a fila atual, limpar o log e o Lote atual. Continuar?")) return;
    try {
      await api("POST", "/api/fila/limpar");
      campoTerminal.value = "";
      campoFazenda.value = "";
      campoContrato.value = "";
      if (campoData) campoData.value = "";
      atualizarBadgeLote();
      const lg = document.getElementById("log-geral");
      if(lg) lg.textContent = "";
      ultimoLogId = 0;
      carregarFila();
      toast("Sessão limpa.");
    } catch (err) { toast(err.message, "erro"); }
  });
}

let ultimoLogId = 0;

const STATUS_LABEL = {
  "Aguardando...": "aguardando", "Processando...": "processando", "Sucesso": "sucesso",
  "Erro": "erro", "Erro Composição": "erro-composicao", "Sem CTR": "sem-ctr", "Erro Data": "erro"
};

function classeStatus(status) {
  if (status.includes("CTR Inválido")) return "ctr-invalido";
  return STATUS_LABEL[status] || "aguardando";
}

async function carregarFila() {
  const lista = await api("GET", "/api/fila");
  const tbody = document.querySelector("#tabela-fila tbody");
  if(!tbody) return;

  // MEMÓRIA DO CHECKBOX: Salva todos os id's marcados antes de limpar o HTML
  const marcados = new Set([...document.querySelectorAll(".check-fila:checked")].map(c => c.value));

  tbody.innerHTML = "";
  if (lista.length === 0) {
    tbody.innerHTML = `<tr class="tabela-vazia"><td colspan="8">Fila vazia — adicione veículos acima.</td></tr>`;
    return;
  }

  let ultimoIndiceLote = null;
  const NUM_CORES_LOTE = 4; // ciclo de 4 cores — dá pra distinguir lotes vizinhos sem exagerar

  lista.forEach(item => {
    // Quando o lote muda (Terminal/Fazenda/Contrato diferente do item
    // anterior), insere uma linha separadora — fica claro onde o robô
    // vai trocar de Terminal/CTR durante a execução.
    if (ultimoIndiceLote !== null && item.indice_lote !== ultimoIndiceLote) {
      const trSep = document.createElement("tr");
      trSep.className = "fila-separador-lote";
      trSep.innerHTML = `<td colspan="8"><span class="separador-lote-texto">▾ Troca de lote: ${item.terminal} · ${item.fazenda} · CTR ${item.contrato}</span></td>`;
      tbody.appendChild(trSep);
    }
    ultimoIndiceLote = item.indice_lote;

    const tr = document.createElement("tr");
    tr.dataset.id = item.id;
    tr.classList.add(`lote-cor-${item.indice_lote % NUM_CORES_LOTE}`);

    // Verifica se esse item estava na lista de marcados
    const isChecked = marcados.has(item.id.toString()) ? "checked" : "";

    tr.innerHTML = `
      <td><input type="checkbox" class="check-fila" value="${item.id}" ${isChecked}></td>
      <td>${item.terminal}</td><td>${item.fazenda}</td><td>${item.contrato}</td>
      <td>${item.data_cota || "—"}</td>
      <td>${item.placa}</td><td>${item.cpf}</td>
      <td><span class="status-pill ${classeStatus(item.status)}">${item.status}</span></td>`;
    tr.addEventListener("dblclick", () => abrirLogItem(item.id, item.placa));
    tr.addEventListener("contextmenu", (e) => { e.preventDefault(); menuContexto(e, item); });
    tbody.appendChild(tr);
  });
}

function atualizarLinhaStatus(itemId, status) {
  const tr = document.querySelector(`#tabela-fila tr[data-id="${itemId}"]`);
  if (!tr) return;
  const pill = tr.querySelector(".status-pill");
  if (pill) {
    pill.textContent = status;
    pill.className = `status-pill ${classeStatus(status)}`;
  }
}

function reprocessarItem(itemId) {
  const chk = document.getElementById("chk-modo-guiado");
  const modoGuiado = chk ? chk.checked : false;
  api("POST", "/api/robo/reprocessar_item", { id: itemId, modo_guiado: modoGuiado })
    .then(() => toast("Reprocessando item..."))
    .catch(err => toast(err.message, "erro"));
}

function menuContexto(e, item) {
  const acao = prompt(`Veículo ${item.placa} — digite:\n1 = Reprocessar\n2 = Ver log\n3 = Remover`, "2");
  if (acao === "1") reprocessarItem(item.id);
  else if (acao === "2") abrirLogItem(item.id, item.placa);
  else if (acao === "3") removerItens([item.id]);
}

function configurarFilaUI() {
  const chkTodos = document.getElementById("check-todos-fila");
  if(!chkTodos) return;
  
  chkTodos.addEventListener("change", (e) => {
    document.querySelectorAll(".check-fila").forEach(c => c.checked = e.target.checked);
  });

  document.getElementById("btn-remover-selecionados").addEventListener("click", () => {
    const ids = [...document.querySelectorAll(".check-fila:checked")].map(c => parseInt(c.value));
    if (ids.length === 0) { toast("Selecione ao menos um item.", "aviso"); return; }
    removerItens(ids);
  });

  document.getElementById("btn-fechar-log-item").addEventListener("click", () => {
    document.getElementById("modal-log-item").hidden = true;
  });
}

async function removerItens(ids) {
  try {
    await api("POST", "/api/fila/remover", { ids });
    toast("Item(ns) removido(s).");
    carregarFila();
  } catch (err) { toast(err.message, "erro"); }
}

async function abrirLogItem(itemId, placa) {
  document.getElementById("modal-log-item-placa").textContent = placa;
  const linhas = await api("GET", `/api/fila/log/${itemId}`);
  const area = document.getElementById("modal-log-item-conteudo");
  if(!area) return;
  area.textContent = linhas.map(l => l.mensagem).join("\n") || "(sem logs ainda)";
  document.getElementById("modal-log-item").hidden = false;
  area.scrollTop = area.scrollHeight;
}

function configurarAdicionarFila() {
  const campoPlaca = document.getElementById("fila-placa-input");
  const campoCpf = document.getElementById("fila-cpf-input");
  const formFila = document.getElementById("form-veiculo-fila");

  if(!campoPlaca || !campoCpf || !formFila) return;

  async function puxarCpf(placaEscolhida) {
    if (!placaEscolhida) return;
    try {
      const res = await api("GET", `/api/cpf_por_placa?placa=${encodeURIComponent(placaEscolhida)}`);
      if (res && res.cpf) campoCpf.value = res.cpf;
    } catch (_) { }
  }

  // Preenche pelo clique na lista do Autocomplete
  ligarAutocomplete(campoPlaca, { tabela: "veiculos", coluna: "placa" }, puxarCpf);

  // Preenche super rápido quando ele perde o foco (o cara aperta TAB)
  campoPlaca.addEventListener("blur", () => {
      puxarCpf(campoPlaca.value.trim().toUpperCase());
  });

  formFila.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { terminal, fazenda, contrato, data_cota } = lerLote();
    const placa = campoPlaca.value.trim().toUpperCase();
    const cpf = campoCpf.value.trim();

    try {
      await api("POST", "/api/fila", { terminal, fazenda, contrato, placa, cpf, data_cota });
      toast(`${placa} adicionado!`);
      campoPlaca.value = "";
      campoCpf.value = "";
      campoPlaca.focus();
      carregarFila();
    } catch (err) { toast(err.message, "erro"); }
  });
}

// ===================== OPERAÇÃO: CONTROLE DO ROBÔ =====================
function definirStatusVisual(estado) {
  const dot = document.getElementById("status-dot");
  const texto = document.getElementById("status-texto");
  if(!dot || !texto) return;

  const btnPausar = document.getElementById("btn-pausar");
  const btnIniciar = document.getElementById("btn-iniciar");

  dot.className = "status-dot";
  if (estado.rodando) {
    if (estado.status === "rodando") { dot.classList.add("rodando"); texto.textContent = "Rodando"; }
    else if (estado.status.startsWith("pausado")) { dot.classList.add("pausado"); texto.textContent = "Pausado"; }
    else if (estado.status === "aguardando_login") { dot.classList.add("pausado"); texto.textContent = "Aguardando login"; }
    else if (estado.status === "aguardando_guiado") { dot.classList.add("pausado"); texto.textContent = "Aguardando (Guiado)"; }
    else { texto.textContent = "Rodando"; }
  } else {
    texto.textContent = "Parado";
  }

  if(btnPausar && btnIniciar) {
      btnPausar.hidden = !estado.rodando;
      btnIniciar.disabled = estado.rodando;
      btnIniciar.textContent = estado.rodando ? "▶ Em execução..." : "▶ Iniciar ATROPBOT";
      btnPausar.textContent = estado.status === "pausado_manual" ? "▶ Retomar" : "⏸ Pausar";
  }

  const elLog = document.getElementById("modal-log-item");
  const logItemAberto = elLog && !elLog.hidden;

  const modalCtr = document.getElementById("modal-ctr");
  if(modalCtr) {
      modalCtr.hidden = logItemAberto || estado.status !== "pausado_ctr";
      if (!logItemAberto && estado.status === "pausado_ctr") {
        const ctx = estado.contexto || {};
        document.getElementById("modal-ctr-texto").textContent =
          `O CTR ${ctx.contrato || "?"} (Fazenda ${ctx.fazenda || "?"}, Terminal ${ctx.terminal || "?"}) não foi aceito pelo painel.`;
      }
  }

  const modalNav = document.getElementById("modal-navegador");
  if(modalNav) modalNav.hidden = logItemAberto || estado.status !== "pausado_navegador";

  const modalErroTrizy = document.getElementById("modal-erro-trizy");
  if(modalErroTrizy) {
      modalErroTrizy.hidden = logItemAberto || estado.status !== "pausado_erro_trizy";
      if (!logItemAberto && estado.status === "pausado_erro_trizy") {
        const ctx = estado.contexto || {};
        document.getElementById("modal-erro-trizy-texto").textContent =
          ctx.mensagem || "O Trizy exibiu um aviso de erro na tela.";
      }
  }

  const modalCheck = document.getElementById("modal-checkpoint");
  if(modalCheck) {
      modalCheck.hidden = logItemAberto || estado.status !== "aguardando_guiado";
      if (!logItemAberto && estado.status === "aguardando_guiado") {
        const ctx = estado.contexto || {};
        document.getElementById("modal-checkpoint-etapa").textContent = ctx.nome_etapa || "";
      }
  }
}

async function atualizarEstadoRobo() {
  try {
    const estado = await api("GET", "/api/robo/estado");
    definirStatusVisual(estado);
  } catch (_) { }
}

function configurarControleRobo() {
  const btnIni = document.getElementById("btn-iniciar");
  if(!btnIni) return;

  btnIni.addEventListener("click", async () => {
    const chk = document.getElementById("chk-modo-guiado");
    const modoGuiado = chk ? chk.checked : false;
    try { await api("POST", "/api/robo/iniciar", { modo_guiado: modoGuiado }); } 
    catch (err) { toast(err.message, "erro"); }
  });

  document.getElementById("btn-pausar").addEventListener("click", async () => {
    const indoRetomar = document.getElementById("btn-pausar").textContent.includes("Retomar");
    try {
      if (indoRetomar) await api("POST", "/api/robo/retomar");
      else await api("POST", "/api/robo/pausar");
    } catch (err) { toast(err.message, "erro"); }
  });

  document.getElementById("btn-reprocessar-erros").addEventListener("click", async () => {
    const chk = document.getElementById("chk-modo-guiado");
    const modoGuiado = chk ? chk.checked : false;
    try {
      const r = await api("POST", "/api/robo/reprocessar_erros", { modo_guiado: modoGuiado });
      toast(`Reprocessando ${r.quantidade} item(ns) com erro...`);
    } catch (err) { toast(err.message, "erro"); }
  });

  document.getElementById("btn-reorganizar-fila").addEventListener("click", async () => {
    try {
      await api("POST", "/api/fila/reorganizar");
      toast("Fila reorganizada — veículos do mesmo Terminal/Fazenda/Contrato agora estão agrupados.");
      carregarFila();
    } catch (err) { toast(err.message, "erro"); }
  });

  document.getElementById("btn-ctr-tentar").addEventListener("click", () =>
    api("POST", "/api/robo/resolver_ctr", { pular_lote: false }).catch(err => toast(err.message, "erro")));
  document.getElementById("btn-ctr-pular").addEventListener("click", () =>
    api("POST", "/api/robo/resolver_ctr", { pular_lote: true }).catch(err => toast(err.message, "erro")));

  document.getElementById("btn-nav-reabrir").addEventListener("click", async () => {
    try { await api("POST", "/api/robo/resolver_navegador_fechado", { cancelar: false }); } 
    catch (err) { toast(err.message, "erro"); }
  });
  document.getElementById("btn-nav-cancelar").addEventListener("click", () =>
    api("POST", "/api/robo/resolver_navegador_fechado", { cancelar: true }).catch(err => toast(err.message, "erro")));

  document.getElementById("btn-erro-trizy-tentar").addEventListener("click", () =>
    api("POST", "/api/robo/resolver_erro_trizy", { cancelar: false }).catch(err => toast(err.message, "erro")));
  document.getElementById("btn-erro-trizy-cancelar").addEventListener("click", () =>
    api("POST", "/api/robo/resolver_erro_trizy", { cancelar: true }).catch(err => toast(err.message, "erro")));

  document.getElementById("btn-checkpoint-continuar").addEventListener("click", () =>
    api("POST", "/api/robo/continuar_checkpoint").catch(err => toast(err.message, "erro")));

  const chkGuiado = document.getElementById("chk-modo-guiado");
  if(chkGuiado) {
      chkGuiado.addEventListener("change", (e) => {
        api("POST", "/api/robo/modo_guiado", { ativo: e.target.checked }).catch(() => {});
      });
  }
}

// ===================== OPERAÇÃO: LOG E SSE =====================
function anexarLinhaLog(mensagem) {
  const area = document.getElementById("log-geral");
  if(!area) return;
  area.textContent += (area.textContent ? "\n" : "") + mensagem;
  area.scrollTop = area.scrollHeight;
}

function conectarSSE() {
  const fonte = new EventSource("/api/eventos");
  fonte.onmessage = (e) => {
    let evento;
    try { evento = JSON.parse(e.data); } catch (_) { return; }

    if (evento.tipo === "log_geral") {
      anexarLinhaLog(evento.mensagem);
      ultimoLogId = Math.max(ultimoLogId, evento.id || ultimoLogId);
    } else if (evento.tipo === "status_item") {
      atualizarLinhaStatus(evento.item_id, evento.status);
    } else if (evento.tipo === "finalizado" || evento.tipo === "checkpoint") {
      atualizarEstadoRobo();
    } else if (evento.tipo === "evento_trizy") {
      // Algo novo foi capturado na tela do Trizy — atualiza a lista no
      // Histórico de Eventos automaticamente, sem precisar clicar em
      // "Atualizar" (só recarrega se a aba Configurações estiver visível,
      // para não gastar requisição à toa enquanto está na Operação).
      const abaConfig = document.getElementById("aba-configuracoes");
      if (abaConfig && !abaConfig.hidden) carregarEventosTrizy();
    }
  };
  fonte.onerror = () => { };
}

async function pollLogReforco() {
  try {
    const novas = await api("GET", `/api/log_geral?desde_id=${ultimoLogId}`);
    novas.forEach(l => { anexarLinhaLog(l.mensagem); ultimoLogId = l.id; });
  } catch (_) { }
}

async function carregarLogGeralInicial() {
  const linhas = await api("GET", `/api/log_geral?desde_id=0`);
  const area = document.getElementById("log-geral");
  if(!area) return;
  area.textContent = linhas.map(l => l.mensagem).join("\n");
  linhas.forEach(l => { ultimoLogId = Math.max(ultimoLogId, l.id); });
  area.scrollTop = area.scrollHeight;
}

function iniciarLoopsDeAtualizacao() {
  setInterval(atualizarEstadoRobo, 1500);
  setInterval(carregarFila, 2500);
  setInterval(pollLogReforco, 3000);
}

// ===================== INICIALIZAÇÃO BLINDADA =====================
document.addEventListener("DOMContentLoaded", async () => {
  
  // Tudo inicializa com "Fail Safes" para não estourar erro se a UI não existir na tela.
  configurarAbas();
  configurarLote();
  configurarFilaUI();
  configurarAdicionarFila();
  configurarControleRobo();
  configurarVeiculos();
  configurarVinculos();
  configurarTrizy();
  configurarNavegadorManual();
  configurarEventosTrizy();

  await Promise.all([
    carregarFila(),
    carregarLogGeralInicial(),
    carregarVeiculos(),
    carregarVinculos(),
    carregarCredenciaisTrizy(),
    atualizarEstadoRobo(),
    carregarEventosTrizy(),
  ]);
  
  atualizarBadgeLote();
  conectarSSE();
  iniciarLoopsDeAtualizacao();
});