const KANBAN_COLUMNS = [
  { key: "qualified", label: "Cualificados (IA)", stages: ["new", "qualifying", "qualified"] },
  { key: "contacted", label: "Contactados", stages: ["contacted"] },
  { key: "meeting_scheduled", label: "Demo Agendada", stages: ["meeting_scheduled"] },
  { key: "proposal_sent", label: "Propuesta Enviada", stages: ["proposal_sent"] },
  { key: "nurture", label: "Nurturing (Fríos)", stages: ["nurture"] },
  { key: "closed", label: "Cerrados / Descartados", stages: ["won", "lost"] },
];

const SOURCE_LABELS = {
  website_form: "Formulario Web",
  typeform_webhook: "Typeform Webhook",
  meta_ads_webhook: "Meta Ads Webhook",
  linkedin_ads_webhook: "LinkedIn Ads",
  hubspot_webhook: "HubSpot Webhook",
  csv_import: "Importación CSV",
  api_direct: "API Directa",
};

const STAGE_LABELS = {
  new: "Nuevo",
  qualifying: "Cualificando",
  qualified: "Cualificado",
  contacted: "Contactado",
  meeting_scheduled: "Demo Agendada",
  proposal_sent: "Propuesta Enviada",
  won: "Ganado (Won)",
  lost: "Descartado (Lost)",
  nurture: "Nurturing",
};

let allLeadsCache = [];

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatUsd(amount) {
  if (amount === null || amount === undefined || Number.isNaN(Number(amount))) {
    return "Por definir";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Number(amount));
}

function showToast(message) {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

// Fallback for <dialog closedby="any"> per modern-web-guidance `light-dismiss-a-dialog`
function setupDialogLightDismissFallbacks() {
  if (!("closedBy" in HTMLDialogElement.prototype)) {
    for (const dialog of document.querySelectorAll('dialog[closedby="any"]')) {
      dialog.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const isDialogContent =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;
        if (isDialogContent) return;
        dialog.close();
      });
    }
  }
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.detail || `Error HTTP ${res.status}`);
  }
  return res.json();
}

async function refreshWorkspace() {
  const search = document.getElementById("filter-search").value.trim();
  const tier = document.getElementById("filter-tier").value;
  const source = document.getElementById("filter-source").value;

  const params = new URLSearchParams({ limit: "100" });
  if (search) params.set("search", search);
  if (tier) params.set("tier", tier);
  if (source) params.set("source", source);

  const [health, stats, leadsResp, tasks, webhooks] = await Promise.all([
    fetchJson("/health"),
    fetchJson("/api/v1/leads/stats"),
    fetchJson(`/api/v1/leads?${params.toString()}`),
    fetchJson("/api/v1/automation/tasks?limit=40"),
    fetchJson("/api/v1/webhooks/logs?limit=30"),
  ]);

  document.getElementById("ai-engine-label").textContent =
    health.ai_mode === "gemini-live" ? "Gemini 3.8 Flash Live" : "Motor BANT IA Activo";

  document.getElementById("kpi-pipeline-usd").textContent = formatUsd(stats.total_estimated_pipeline_usd);
  document.getElementById("kpi-total-leads").textContent = `${stats.total_leads} leads registrados en CRM`;
  document.getElementById("kpi-avg-score").innerHTML = `${stats.average_bant_score}<small>/100</small>`;
  document.getElementById("kpi-hot-count").textContent = String(stats.hot_leads_count);
  document.getElementById("kpi-ready-rate").textContent = `${stats.conversion_ready_rate}%`;

  allLeadsCache = leadsResp.items || [];
  renderKanban(allLeadsCache);
  renderTable(allLeadsCache);
  renderAutomationAndWebhooks(tasks, webhooks);
}

function renderKanban(leads) {
  const board = document.getElementById("kanban-board");
  board.innerHTML = KANBAN_COLUMNS.map((col) => {
    const colLeads = leads.filter((l) => col.stages.includes(l.stage));
    const cardsHtml = colLeads.length
      ? colLeads
          .map(
            (lead) => `
          <article class="lead-card" data-lead-id="${lead.id}">
            <div class="lead-card-top">
              <div>
                <div class="lead-card-name">${escapeHtml(lead.full_name)}</div>
                <div class="lead-card-company">${escapeHtml(lead.company_name || "Sin empresa")} &middot; ${escapeHtml(lead.job_title || "Rol N/A")}</div>
              </div>
              <span class="tier-badge tier-${escapeHtml(lead.qualification_tier)}">
                ${lead.bant_total_score} pts
              </span>
            </div>
            <div class="lead-card-need">${escapeHtml(lead.primary_need || lead.ai_summary || "Sin descripción")}</div>
            <div class="lead-card-meta">
              <span class="mono">${formatUsd(lead.estimated_budget_usd)}</span>
              <span>${escapeHtml(SOURCE_LABELS[lead.source] || lead.source)}</span>
            </div>
          </article>
        `
          )
          .join("")
      : `<div style="padding:18px 10px;text-align:center;color:var(--text-muted);font-size:12px;">Sin leads en esta etapa</div>`;

    return `
      <div class="kanban-col">
        <div class="kanban-col-header">
          <span class="kanban-col-title">${escapeHtml(col.label)}</span>
          <span class="kanban-col-count">${colLeads.length}</span>
        </div>
        <div class="kanban-cards">${cardsHtml}</div>
      </div>
    `;
  }).join("");

  for (const card of board.querySelectorAll(".lead-card")) {
    card.addEventListener("click", () => openLeadInspector(Number(card.dataset.leadId)));
  }
}

function renderTable(leads) {
  const tbody = document.getElementById("leads-table-body");
  if (!leads.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:24px;">No se encontraron leads con los filtros seleccionados.</td></tr>`;
    return;
  }

  tbody.innerHTML = leads
    .map(
      (lead) => `
      <tr>
        <th>
          <div style="font-weight:700;color:var(--text-primary);">${escapeHtml(lead.full_name)}</div>
          <div style="font-size:12px;color:var(--text-muted);">${escapeHtml(lead.company_name || "Sin empresa")} &middot; ${escapeHtml(lead.email)}</div>
        </th>
        <td class="mono" style="font-weight:700;color:var(--text-primary);">${lead.bant_total_score} / 100</td>
        <td><span class="tier-badge tier-${escapeHtml(lead.qualification_tier)}">${escapeHtml(lead.qualification_tier)}</span></td>
        <td class="mono">${formatUsd(lead.estimated_budget_usd)}</td>
        <td>${escapeHtml(STAGE_LABELS[lead.stage] || lead.stage)}</td>
        <td>${escapeHtml(SOURCE_LABELS[lead.source] || lead.source)}</td>
        <td style="font-size:12.5px;">${escapeHtml(lead.suggested_owner || "Pendiente")}</td>
        <td>
          <button type="button" class="btn btn-secondary btn-sm btn-inspect-row" data-lead-id="${lead.id}">
            Inspeccionar IA
          </button>
        </td>
      </tr>
    `
    )
    .join("");

  for (const btn of tbody.querySelectorAll(".btn-inspect-row")) {
    btn.addEventListener("click", () => openLeadInspector(Number(btn.dataset.leadId)));
  }
}

function renderAutomationAndWebhooks(tasks, webhooks) {
  const taskContainer = document.getElementById("global-tasks-list");
  const leadMap = new Map(allLeadsCache.map((l) => [l.id, l]));

  if (!tasks.length) {
    taskContainer.innerHTML = `<div style="color:var(--text-muted);font-size:13px;">No hay tareas de seguimiento registradas.</div>`;
  } else {
    taskContainer.innerHTML = tasks
      .map((t) => {
        const lead = leadMap.get(t.lead_id);
        const leadLabel = lead ? `${lead.full_name} (${lead.company_name || "N/A"})` : `Lead #${t.lead_id}`;
        const canExecute = t.status === "pending";
        return `
          <div class="task-item">
            <div class="item-row">
              <strong>Paso #${t.step_number} &middot; ${escapeHtml(t.channel.toUpperCase())} &mdash; ${escapeHtml(leadLabel)}</strong>
              <span class="tier-badge ${t.status === "sent" || t.status === "replied" ? "tier-warm" : "tier-cold"}">${escapeHtml(t.status)}</span>
            </div>
            <div style="font-size:12.5px;color:var(--text-secondary);font-weight:600;">${escapeHtml(t.subject || "")}</div>
            <div style="font-size:12px;color:var(--text-muted);">${escapeHtml(t.body.slice(0, 150))}...</div>
            <div class="item-row" style="margin-top:4px;">
              <span class="mono" style="font-size:11px;color:var(--text-muted);">Programado: ${new Date(t.scheduled_at).toLocaleString()}</span>
              ${
                canExecute
                  ? `<button type="button" class="btn btn-primary btn-sm btn-exec-task" data-task-id="${t.id}">Enviar Paso Ahora</button>`
                  : ""
              }
            </div>
          </div>
        `;
      })
      .join("");

    for (const btn of taskContainer.querySelectorAll(".btn-exec-task")) {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.taskId);
        await fetchJson(`/api/v1/automation/tasks/${id}/execute`, { method: "POST" });
        showToast(`Paso de seguimiento #${id} enviado y registrado en el timeline.`);
        await refreshWorkspace();
      });
    }
  }

  const whContainer = document.getElementById("webhook-logs-list");
  if (!webhooks.length) {
    whContainer.innerHTML = `<div style="color:var(--text-muted);font-size:13px;">No hay eventos de webhook registrados.</div>`;
  } else {
    whContainer.innerHTML = webhooks
      .map(
        (w) => `
        <div class="webhook-item">
          <div class="item-row">
            <span class="mono" style="font-weight:700;color:var(--text-primary);">
              [${escapeHtml(w.direction.toUpperCase())}] ${escapeHtml(w.provider)} &middot; ${escapeHtml(w.event_type)}
            </span>
            <span class="tier-badge ${w.signature_valid ? "tier-warm" : "tier-disqualified"}">
              ${w.signature_valid ? "HMAC OK" : "REJECTED"} &middot; ${escapeHtml(w.status)}
            </span>
          </div>
          <div class="item-row" style="font-size:11.5px;color:var(--text-muted);">
            <span>Lead ID vinculado: #${w.lead_id || "N/A"}</span>
            <span class="mono">${new Date(w.created_at).toLocaleString()}</span>
          </div>
        </div>
      `
      )
      .join("");
  }
}

async function openLeadInspector(leadId) {
  const lead = await fetchJson(`/api/v1/leads/${leadId}`);
  const dialog = document.getElementById("lead-inspector-dialog");
  const container = document.getElementById("inspector-content");

  const reasoning = lead.ai_reasoning || {};
  const breakdown = reasoning.bant_breakdown || {
    budget_score: lead.budget_score,
    budget_rationale: "Evaluado por el motor BANT.",
    authority_score: lead.authority_score,
    authority_rationale: "Evaluado según cargo.",
    need_score: lead.need_score,
    need_rationale: "Evaluado según dolor comercial.",
    timeline_score: lead.timeline_score,
    timeline_rationale: "Evaluado según urgencia.",
  };
  const domainIntel = reasoning.domain_intelligence || {};
  const objections = reasoning.potential_objections || [];
  const talkingPoints = reasoning.talking_points || [];

  container.innerHTML = `
    <div class="dialog-header">
      <div>
        <span class="eyebrow">INSPECTOR DE AGENTE IA &middot; ${escapeHtml(lead.scoring_engine || "BANT Engine")}</span>
        <h2 id="inspector-lead-name">${escapeHtml(lead.full_name)} &mdash; ${escapeHtml(lead.company_name || "Sin Empresa")}</h2>
        <div style="font-size:13px;color:var(--text-muted);margin-top:2px;">
          ${escapeHtml(lead.job_title || "Cargo N/A")} &middot; <span class="mono">${escapeHtml(lead.email)}</span> &middot;
          País: ${escapeHtml(lead.country || "Global")} &middot; Web: ${escapeHtml(lead.company_website || "N/A")}
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span class="tier-badge tier-${escapeHtml(lead.qualification_tier)}" style="font-size:13px;padding:5px 11px;">
          ${escapeHtml(lead.qualification_tier.toUpperCase())} &middot; ${lead.bant_total_score}/100 BANT
        </span>
        <form method="dialog">
          <button type="submit" class="btn-close" aria-label="Cerrar inspector">&times;</button>
        </form>
      </div>
    </div>

    <!-- Executive AI Summary -->
    <div class="info-box" style="border-color:rgba(16,185,129,0.4);">
      <div class="item-row">
        <h3>Dictamen Ejecutivo del Agente IA</h3>
        <div style="display:flex;gap:8px;align-items:center;">
          <select id="inspector-stage-select" class="input-control" aria-label="Cambiar etapa del lead">
            ${Object.entries(STAGE_LABELS)
              .map(
                ([val, label]) =>
                  `<option value="${val}" ${lead.stage === val ? "selected" : ""}>Etapa: ${label}</option>`
              )
              .join("")}
          </select>
          <button type="button" class="btn btn-secondary btn-sm" id="btn-requalify-ai">
            &#10227; Re-Cualificar con IA
          </button>
        </div>
      </div>
      <p style="margin:0;color:var(--text-secondary);font-size:13.5px;">${escapeHtml(lead.ai_summary || "Pendiente de análisis.")}</p>
      <div style="display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--text-muted);">
        <span><strong>Ejecutivo Asignado:</strong> ${escapeHtml(lead.suggested_owner || "N/A")}</span>
        <span><strong>Intención:</strong> ${escapeHtml(lead.detected_intent || "N/A")}</span>
        <span><strong>Dominio Corporativo:</strong> ${domainIntel.is_corporate_domain ? "Sí (Verificado)" : "No (Correo gratuito)"}</span>
      </div>
    </div>

    <!-- 4 BANT Pillar Progress Bars -->
    <div class="bant-grid">
      <div class="bant-pillar">
        <div class="bant-pillar-top">
          <span>Budget (Presupuesto)</span>
          <span class="mono">${breakdown.budget_score}/25</span>
        </div>
        <div class="bant-bar-track"><div class="bant-bar-fill" style="inline-size:${(breakdown.budget_score / 25) * 100}%"></div></div>
        <div class="bant-rationale">${escapeHtml(breakdown.budget_rationale)}</div>
      </div>
      <div class="bant-pillar">
        <div class="bant-pillar-top">
          <span>Authority (Autoridad)</span>
          <span class="mono">${breakdown.authority_score}/25</span>
        </div>
        <div class="bant-bar-track"><div class="bant-bar-fill" style="inline-size:${(breakdown.authority_score / 25) * 100}%"></div></div>
        <div class="bant-rationale">${escapeHtml(breakdown.authority_rationale)}</div>
      </div>
      <div class="bant-pillar">
        <div class="bant-pillar-top">
          <span>Need (Necesidad/Dolor)</span>
          <span class="mono">${breakdown.need_score}/25</span>
        </div>
        <div class="bant-bar-track"><div class="bant-bar-fill" style="inline-size:${(breakdown.need_score / 25) * 100}%"></div></div>
        <div class="bant-rationale">${escapeHtml(breakdown.need_rationale)}</div>
      </div>
      <div class="bant-pillar">
        <div class="bant-pillar-top">
          <span>Timeline (Urgencia)</span>
          <span class="mono">${breakdown.timeline_score}/25</span>
        </div>
        <div class="bant-bar-track"><div class="bant-bar-fill" style="inline-size:${(breakdown.timeline_score / 25) * 100}%"></div></div>
        <div class="bant-rationale">${escapeHtml(breakdown.timeline_rationale)}</div>
      </div>
    </div>

    <!-- Live Reply Simulator inside Inspector -->
    <div class="info-box" style="border-color:rgba(249,115,22,0.45);">
      <h3>Simulador de Respuesta Entrante del Lead (AI Inbound Reply Handler)</h3>
      <p style="margin:0;font-size:12.5px;color:var(--text-muted);">
        Simula que <strong>${escapeHtml(lead.full_name)}</strong> responde un correo o WhatsApp. El Agente IA detectará la intención, pausará los envíos pendientes, moverá la columna del Kanban y redactará la respuesta comercial:
      </p>
      <div class="preset-replies">
        <button type="button" class="btn btn-secondary btn-sm btn-preset-reply" data-msg="Hola equipo, excelente propuesta. ¿Podemos agendar una demo mañana jueves a las 11:00 AM?">
          &#128197; Simular: "Quiero agendar demo mañana"
        </button>
        <button type="button" class="btn btn-secondary btn-sm btn-preset-reply" data-msg="Hola, antes de avanzar ¿me pueden enviar los precios y una cotización formal de los planes?">
          &#128176; Simular: "Envíame precios y propuesta"
        </button>
        <button type="button" class="btn btn-secondary btn-sm btn-preset-reply" data-msg="Actualmente ya usamos HubSpot y nos preocupa que sea complejo de integrar.">
          &#129300; Simular: Objeción técnica
        </button>
        <button type="button" class="btn btn-ghost btn-sm btn-preset-reply" data-msg="No me interesa por ahora, por favor dar de baja mi contacto.">
          &#128721; Simular: Solicitar baja
        </button>
      </div>
      <div style="display:flex;gap:8px;">
        <input type="text" id="custom-reply-input" class="input-control" style="flex:1;" placeholder="O escribe cualquier respuesta del cliente para que el Agente IA la analice..." />
        <button type="button" class="btn btn-primary btn-sm" id="btn-send-custom-reply">Analizar Respuesta con IA</button>
      </div>
    </div>

    <!-- Two Columns: Follow-Up Sequence + Interaction Timeline -->
    <div class="inspector-columns">
      <div class="info-box">
        <h3>Cadencia Multi-Canal Programada (${lead.follow_up_tasks.length} pasos)</h3>
        <div class="task-list" style="max-block-size:300px;">
          ${
            lead.follow_up_tasks.length
              ? lead.follow_up_tasks
                  .map(
                    (t) => `
                  <div class="task-item">
                    <div class="item-row">
                      <strong>Paso #${t.step_number} (${escapeHtml(t.channel.toUpperCase())})</strong>
                      <span class="tier-badge ${t.status === "sent" || t.status === "replied" ? "tier-warm" : "tier-cold"}">${escapeHtml(t.status)}</span>
                    </div>
                    <div style="font-size:12px;font-weight:600;">${escapeHtml(t.subject || "")}</div>
                    <div style="font-size:11.5px;color:var(--text-muted);white-space:pre-line;">${escapeHtml(t.body)}</div>
                    ${
                      t.status === "pending"
                        ? `<button type="button" class="btn btn-primary btn-sm btn-modal-exec-task" data-task-id="${t.id}">Ejecutar Paso #${t.step_number}</button>`
                        : ""
                    }
                  </div>
                `
                  )
                  .join("")
              : `<div style="color:var(--text-muted);font-size:12.5px;">Sin tareas activas (Lead descartado).</div>`
          }
        </div>

        <h3 style="margin-top:8px;">Objeciones Probables &amp; Argumentos IA</h3>
        <ul style="margin:0;padding-inline-start:18px;font-size:12px;color:var(--text-secondary);">
          ${objections.map((o) => `<li><strong>Objeción:</strong> ${escapeHtml(o)}</li>`).join("")}
          ${talkingPoints.map((tp) => `<li><strong>Talking Point:</strong> ${escapeHtml(tp)}</li>`).join("")}
        </ul>
      </div>

      <div class="info-box">
        <h3>Timeline de Interacciones y Trazabilidad (${lead.interactions.length})</h3>
        <div class="task-list" style="max-block-size:380px;">
          ${lead.interactions
            .map(
              (ev) => `
              <div class="task-item">
                <div class="item-row">
                  <strong style="font-size:12px;color:var(--accent-emerald);">${escapeHtml(ev.subject || ev.interaction_type)}</strong>
                  <span class="mono" style="font-size:10.5px;color:var(--text-muted);">${new Date(ev.created_at).toLocaleTimeString()}</span>
                </div>
                <div style="font-size:12px;color:var(--text-secondary);white-space:pre-line;">${escapeHtml(ev.content)}</div>
                <div style="font-size:11px;color:var(--text-muted);">Canal: ${escapeHtml(ev.channel)} &middot; Actor: ${escapeHtml(ev.actor)}</div>
              </div>
            `
            )
            .join("")}
        </div>
      </div>
    </div>
  `;

  if (!dialog.open) {
    dialog.showModal();
  }

  // Bind events inside the inspector
  document.getElementById("inspector-stage-select").addEventListener("change", async (e) => {
    const newStage = e.target.value;
    await fetchJson(`/api/v1/leads/${lead.id}/stage`, {
      method: "POST",
      body: JSON.stringify({ stage: newStage, reason: "Actualizado manualmente desde el Inspector BANT", actor: "sales_rep" }),
    });
    showToast(`Etapa cambiada a ${STAGE_LABELS[newStage] || newStage}`);
    await refreshWorkspace();
    await openLeadInspector(lead.id);
  });

  document.getElementById("btn-requalify-ai").addEventListener("click", async () => {
    await fetchJson(`/api/v1/ai/qualify/${lead.id}`, { method: "POST" });
    showToast("Agente IA re-calculó la matriz BANT del lead.");
    await refreshWorkspace();
    await openLeadInspector(lead.id);
  });

  for (const btn of container.querySelectorAll(".btn-modal-exec-task")) {
    btn.addEventListener("click", async () => {
      const taskId = Number(btn.dataset.taskId);
      await fetchJson(`/api/v1/automation/tasks/${taskId}/execute`, { method: "POST" });
      showToast(`Paso #${taskId} enviado exitosamente.`);
      await refreshWorkspace();
      await openLeadInspector(lead.id);
    });
  }

  async function submitSimulatedReply(messageText) {
    if (!messageText.trim()) return;
    const res = await fetchJson(`/api/v1/automation/leads/${lead.id}/reply`, {
      method: "POST",
      body: JSON.stringify({ channel: "email", message: messageText }),
    });
    showToast(`IA detectó intención '${res.detected_reply_intent}' → Nueva etapa: ${STAGE_LABELS[res.new_stage] || res.new_stage}`);
    await refreshWorkspace();
    await openLeadInspector(lead.id);
  }

  for (const btn of container.querySelectorAll(".btn-preset-reply")) {
    btn.addEventListener("click", () => submitSimulatedReply(btn.dataset.msg));
  }

  document.getElementById("btn-send-custom-reply").addEventListener("click", () => {
    const val = document.getElementById("custom-reply-input").value;
    submitSimulatedReply(val);
  });
}

function initEventListeners() {
  setupDialogLightDismissFallbacks();

  // View Tab Switching
  const tabBtns = document.querySelectorAll(".tab-btn");
  const panels = {
    kanban: document.getElementById("view-kanban"),
    table: document.getElementById("view-table"),
    automation: document.getElementById("view-automation"),
  };

  for (const btn of tabBtns) {
    btn.addEventListener("click", () => {
      for (const b of tabBtns) {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      }
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");

      const target = btn.dataset.tab;
      for (const [key, panel] of Object.entries(panels)) {
        if (key === target) {
          panel.hidden = false;
          panel.classList.add("active");
        } else {
          panel.hidden = true;
          panel.classList.remove("active");
        }
      }
    });
  }

  // Filters
  document.getElementById("filter-search").addEventListener("input", () => refreshWorkspace());
  document.getElementById("filter-tier").addEventListener("change", () => refreshWorkspace());
  document.getElementById("filter-source").addEventListener("change", () => refreshWorkspace());

  // 1-Click Recruiter Simulator Buttons
  for (const btn of document.querySelectorAll(".sim-btn")) {
    btn.addEventListener("click", async () => {
      const scenario = btn.dataset.scenario;
      btn.disabled = true;
      try {
        const res = await fetchJson(`/api/v1/demo/scenario/${scenario}`, { method: "POST" });
        showToast(res.title);
        await refreshWorkspace();
        if (res.lead && res.lead.id) {
          await openLeadInspector(res.lead.id);
        }
      } catch (err) {
        showToast(`Error en simulador: ${err.message}`);
      } finally {
        btn.disabled = false;
      }
    });
  }

  // Seed / Reset Demo Data
  document.getElementById("btn-seed-reset").addEventListener("click", async () => {
    await fetchJson("/api/v1/demo/seed?force_reset=true", { method: "POST" });
    showToast("Base de datos restaurada con 6 leads B2B de demostración.");
    await refreshWorkspace();
  });

  // Execute all due tasks
  document.getElementById("btn-run-all-due").addEventListener("click", async () => {
    const res = await fetchJson("/api/v1/automation/run-due?force_all_pending=true", { method: "POST" });
    showToast(`Se ejecutaron ${res.executed_count} pasos de seguimiento en lote.`);
    await refreshWorkspace();
  });

  // New Lead Dialog
  const newLeadDialog = document.getElementById("new-lead-dialog");
  document.getElementById("btn-open-new-lead").addEventListener("click", () => {
    newLeadDialog.showModal();
  });
  document.getElementById("btn-cancel-new-lead").addEventListener("click", () => {
    newLeadDialog.close();
  });

  document.getElementById("create-lead-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = {
      full_name: fd.get("full_name"),
      email: fd.get("email"),
      job_title: fd.get("job_title") || null,
      company_name: fd.get("company_name") || null,
      company_size: fd.get("company_size") || null,
      industry: fd.get("industry") || null,
      estimated_budget_usd: fd.get("estimated_budget_usd") ? Number(fd.get("estimated_budget_usd")) : null,
      timeline_urgency: fd.get("timeline_urgency") || null,
      primary_need: fd.get("primary_need") || null,
      source: "website_form",
    };
    const created = await fetchJson("/api/v1/leads", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    e.target.reset();
    newLeadDialog.close();
    showToast(`Lead ${created.full_name} cualificado (${created.bant_total_score}/100 BANT).`);
    await refreshWorkspace();
    await openLeadInspector(created.id);
  });

  document.getElementById("btn-submit-csv").addEventListener("click", async () => {
    const csvText = document.getElementById("csv-raw-input").value.trim();
    if (!csvText) return;
    const res = await fetchJson("/api/v1/leads/import/csv", {
      method: "POST",
      body: JSON.stringify({ csv_text: csvText }),
    });
    newLeadDialog.close();
    showToast(`CSV importado: ${res.created} nuevos, ${res.deduplicated} deduplicados.`);
    await refreshWorkspace();
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  initEventListeners();
  await refreshWorkspace();
});
