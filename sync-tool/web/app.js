"use strict";

const state = {
  envList: [],
  comparisons: [],
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function fetchJSON(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      if (data.error) msg = data.error;
    } catch (_) {}
    throw new Error(msg);
  }
  return resp.json();
}

async function loadState() {
  const data = await fetchJSON("/api/state");
  state.data = data;
  renderGit(data.git);
  renderEnvs(data.environments);
  renderComparisons(data.comparisons);
}

function renderGit(git) {
  const chip = document.getElementById("git-chip");
  if (!git || git.sha === null) {
    chip.textContent = "仓库状态不可用";
    return;
  }
  const dirty = git.dirty_count > 0 ? `，${git.dirty_count} 个未提交改动` : "";
  chip.textContent = `${git.branch} @ ${git.sha}${dirty}`;
}

function renderEnvs(environments) {
  const grid = document.getElementById("env-cards");
  grid.replaceChildren();
  Object.values(environments).forEach((env) => {
    const card = el("div", "env-card");
    card.appendChild(el("h3", null, `${env.name} (${env.key})`));
    const urlRow = el("div", "row");
    urlRow.appendChild(el("span", "label", "Dify 地址"));
    urlRow.appendChild(el("span", null, env.base_url));
    card.appendChild(urlRow);

    const countRow = el("div", "row");
    countRow.appendChild(el("span", "label", "已记录工作流"));
    countRow.appendChild(el("span", null, String(env.apps_count)));
    card.appendChild(countRow);

    const timeRow = el("div", "row");
    timeRow.appendChild(el("span", "label", "最近一次导出"));
    timeRow.appendChild(el("span", null, env.last_export || "尚未导出"));
    card.appendChild(timeRow);

    const actions = el("div", "actions");
    const btn = el("button", null, "一键导出全部");
    btn.type = "button";
    btn.addEventListener("click", () => exportEnv(env.key, btn));
    actions.appendChild(btn);
    card.appendChild(actions);
    grid.appendChild(card);
  });
}

function renderComparisons(comparisons) {
  const views = document.getElementById("compare-views");
  views.replaceChildren();
  const keys = Object.keys(comparisons);
  if (keys.length === 0) {
    views.appendChild(el("p", "hint", "需要至少两个环境才能对比。"));
    return;
  }

  const warningsBox = document.getElementById("warnings");
  warningsBox.replaceChildren();
  const allWarnings = [];
  keys.forEach((key) => {
    const cmp = comparisons[key];
    allWarnings.push(...cmp.warnings);
  });
  if (allWarnings.length > 0) {
    warningsBox.classList.remove("hidden");
    allWarnings.forEach((w) => {
      warningsBox.appendChild(el("div", `warning-item ${w.level}`, w.text));
    });
  } else {
    warningsBox.classList.add("hidden");
  }

  keys.forEach((key) => {
    const cmp = comparisons[key];
    const block = el("div", "compare-block");
    const header = el("h3", "panel-head");
    header.appendChild(
      el("span", null, `${cmp.env_a.label} ↔ ${cmp.env_b.label}`)
    );
    block.appendChild(header);

    const table = el("table");
    const thead = el("thead");
    const headRow = el("tr");
    ["工作流", cmp.env_a.label + " 上次更改", cmp.env_b.label + " 上次更改", "差异", "仓库文件"].forEach((t) =>
      headRow.appendChild(el("th", null, t))
    );
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = el("tbody");
    if (cmp.rows.length === 0) {
      const tr = el("tr");
      tr.appendChild(el("td", null, "暂无记录"));
      tbody.appendChild(tr);
    }
    cmp.rows.forEach((row) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, row.name));
      tr.appendChild(el("td", null, row.a_time));
      tr.appendChild(el("td", null, row.b_time));
      const statusTd = el("td");
      statusTd.appendChild(el("span", `status-tag status-${row.status}`, row.delta_text));
      tr.appendChild(statusTd);
      const filesTd = el("td");
      filesTd.appendChild(
        el(
          "div",
          null,
          `${cmp.env_a.label}: ${row.a_file_exists ? "有" : "无"} / ${cmp.env_b.label}: ${row.b_file_exists ? "有" : "无"}`
        )
      );
      tr.appendChild(filesTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    block.appendChild(table);
    views.appendChild(block);
  });
}

async function exportEnv(envKey, btn) {
  const log = document.getElementById("export-log");
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "导出中…";
  log.textContent = "正在连接 Dify 并导出，请稍候…";
  try {
    const data = await fetchJSON("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env: envKey }),
    });
    renderEnvs(data.state.environments);
    renderComparisons(data.state.comparisons);
    const lines = [];
    lines.push(`环境 ${data.label}：共 ${data.app_count} 个工作流`);
    lines.push(`导出 ${data.exported.length} 个，失败 ${data.errors.length} 个`);
    (data.logs || []).forEach((l) => lines.push(l));
    data.exported.forEach((e) => {
      const ts = e.dify_updated_at
        ? new Date(e.dify_updated_at * 1000).toLocaleString("zh-CN", { hour12: false })
        : "未知";
      lines.push(`  [${e.changed ? "已变更" : "未变更"}] ${e.name} (${ts}) ${e.file}`);
    });
    data.errors.forEach((e) => lines.push(`  [失败] ${e.name}: ${e.error}`));
    lines.push("导出完成，请在 git 中提交本次导出结果。");
    log.textContent = lines.join("\n");
  } catch (err) {
    log.textContent = `导出失败：${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

document.getElementById("refresh-btn").addEventListener("click", () =>
  loadState().catch((err) => {
    const log = document.getElementById("export-log");
    log.textContent = `刷新失败：${err.message}`;
  })
);

loadState().catch((err) => {
  const log = document.getElementById("export-log");
  log.textContent = `加载失败：${err.message}`;
});
