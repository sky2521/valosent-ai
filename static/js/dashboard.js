const page = document.body.dataset.page;
const charts = new Map();
const palette = ['#ff4655', '#ece8e1', '#eab36b', '#4cd4a9', '#64b5f6', '#9eaab7'];

let VALOSENT_ASSETS = { agents: {}, maps: {}, roles: {} };
let _activeBackdropSlot = 0;

function _normAssetKey(name) {
  return String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

async function loadValorantAssets() {
  try {
    VALOSENT_ASSETS = await getJson('/api/assets');
  } catch (err) {
    console.warn('Could not load /api/assets:', err);
  }
}

function getAgentAsset(agentName) {
  const map = VALOSENT_ASSETS.agents || {};
  if (map[agentName]) return map[agentName];
  const key = _normAssetKey(agentName);
  const found = Object.values(map).find((item) => _normAssetKey(item.agent) === key);
  if (found) return found;
  const slug = key || 'agent';
  return {
    agent: agentName,
    icon: `/static/assets/fallbacks/agent_${slug}_icon.svg`,
    fallback_icon: `/static/assets/fallbacks/agent_${slug}_icon.svg`,
    portrait: `/static/assets/fallbacks/agent_${slug}_portrait.svg`,
    fallback_portrait: `/static/assets/fallbacks/agent_${slug}_portrait.svg`,
    background: null,
    role_icon: '/static/assets/fallbacks/role_duelist.svg',
    fallback_role_icon: '/static/assets/fallbacks/role_duelist.svg',
    accent: '#FF4655',
  };
}

function getMapAsset(mapName) {
  const map = VALOSENT_ASSETS.maps || {};
  if (map[mapName]) return map[mapName];
  const key = _normAssetKey(mapName);
  const found = Object.values(map).find((item) => _normAssetKey(item.map) === key);
  if (found) return found;
  const slug = key || 'ascent';
  return {
    map: mapName,
    splash: `/static/assets/fallbacks/map_${slug}_splash.svg`,
    fallback_splash: `/static/assets/fallbacks/map_${slug}_splash.svg`,
    banner: `/static/assets/fallbacks/map_${slug}_splash.svg`,
    coordinates: '// VALOSENT SECTOR',
    accent: '#FF4655',
  };
}

function getRoleAsset(roleName) {
  const roles = VALOSENT_ASSETS.roles || {};
  if (roles[roleName]) return roles[roleName];
  const key = _normAssetKey(roleName);
  return Object.values(roles).find((item) => _normAssetKey(item.role) === key) || null;
}

function createAgentAvatarElement(agentName, className = 'agent-avatar-xs') {
  const asset = getAgentAsset(agentName);
  const img = document.createElement('img');
  img.className = className;
  img.alt = agentName || 'Agent';
  img.loading = 'lazy';
  img.decoding = 'async';
  img.src = asset.icon || asset.fallback_icon;
  img.onerror = () => {
    if (img.dataset.fallbackApplied) return;
    img.dataset.fallbackApplied = '1';
    img.src = asset.fallback_icon;
  };
  return img;
}

function setHudBackdrop(primaryUrl, fallbackUrl = '') {
  const layerA = document.getElementById('hud-backdrop-a');
  const layerB = document.getElementById('hud-backdrop-b');
  if (!layerA || !layerB || !primaryUrl) return;

  const applyUrl = (url) => {
    const incoming = _activeBackdropSlot === 0 ? layerA : layerB;
    const outgoing = _activeBackdropSlot === 0 ? layerB : layerA;
    _activeBackdropSlot = _activeBackdropSlot === 0 ? 1 : 0;
    incoming.style.backgroundImage = `url("${url}")`;
    requestAnimationFrame(() => {
      incoming.classList.add('visible');
      outgoing.classList.remove('visible');
    });
  };

  const probe = new Image();
  probe.onload = () => applyUrl(primaryUrl);
  probe.onerror = () => {
    if (fallbackUrl) applyUrl(fallbackUrl);
  };
  probe.src = primaryUrl;
}

function setMapBackdrop(mapName) {
  if (!mapName || String(mapName).toLowerCase() === 'all') {
    const fallbackMap = getMapAsset('Summit');
    setHudBackdrop(fallbackMap.splash, fallbackMap.fallback_splash);
    return fallbackMap;
  }
  const asset = getMapAsset(mapName);
  setHudBackdrop(asset.splash, asset.fallback_splash);
  return asset;
}

function renderMapHeroBanner(prefix, mapName, topAgents = []) {
  const banner = document.getElementById(`${prefix}-hero-banner`);
  const coordsEl = document.getElementById(`${prefix}-hero-coords`);
  const nameEl = document.getElementById(`${prefix}-hero-name`);
  const subEl = document.getElementById(`${prefix}-hero-sub`);
  const agentsEl = document.getElementById(`${prefix}-hero-top-agents`);
  if (!banner) return;

  const asset = getMapAsset(mapName);
  banner.style.backgroundImage = `url("${asset.splash}"), url("${asset.fallback_splash}")`;
  if (coordsEl) coordsEl.textContent = `// SECTOR ${String(mapName || '').toUpperCase()} · ${asset.coordinates || 'VALOSENT PROTOCOL'}`;
  if (nameEl) nameEl.textContent = mapName;
  if (subEl) {
    subEl.textContent = prefix === 'recommend'
      ? `Official VALORANT map intel · Top meta recommendations on ${mapName} (2021–2026).`
      : `Official VALORANT map intel · Historical VCT pick & win performance on ${mapName}.`;
  }
  if (agentsEl) {
    agentsEl.replaceChildren();
    topAgents.slice(0, 5).forEach((entry) => {
      const name = entry.agent || entry.agent_name;
      if (!name) return;
      const chip = document.createElement('a');
      chip.className = 'map-meta-agent-chip';
      chip.href = `/agents/${encodeURIComponent(name)}`;
      chip.title = `Inspect ${name} dossier`;
      const img = createAgentAvatarElement(name, '');
      const textWrap = document.createElement('div');
      const strong = document.createElement('strong');
      strong.textContent = name;
      const small = document.createElement('small');
      if (entry.score !== undefined && entry.score !== null) {
        small.textContent = `${formatMetric(entry.score)} pts`;
      } else if (entry.map_win_rate !== undefined && entry.map_win_rate !== null) {
        small.textContent = `${formatPercent(entry.map_win_rate)} WR`;
      } else {
        small.textContent = entry.role || 'META';
      }
      textWrap.append(strong, small);
      chip.append(img, textWrap);
      agentsEl.append(chip);
    });
  }
}

async function getJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function notify(message) {
  const notice = document.getElementById('page-notice');
  if (!notice) return;
  notice.textContent = message;
  notice.hidden = false;
}

function formatNumber(value) {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? 'N/A'
    : new Intl.NumberFormat().format(Number(value));
}

function formatPercent(value) {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? 'N/A'
    : `${(Number(value) * 100).toFixed(1)}%`;
}

function formatMetric(value, digits = 1) {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? 'N/A'
    : Number(value).toFixed(digits);
}

function setOptions(select, values, { selected = '', all = false } = {}) {
  if (!select) return;
  select.replaceChildren();
  if (all) select.add(new Option('All', 'All'));
  for (const value of values) {
    select.add(new Option(value, value));
  }
  if (selected && [...select.options].some((option) => option.value === selected)) {
    select.value = selected;
  }
}

function showEmpty(element, message) {
  if (!element) return;
  element.replaceChildren();
  const row = document.createElement('tr');
  const cell = document.createElement('td');
  cell.colSpan = 9;
  cell.className = 'empty-state';
  cell.textContent = message;
  row.append(cell);
  element.append(row);
}

function renderTable(body, rows, columns, emptyMessage = 'Insufficient data for this selection.') {
  if (!body) return;
  body.replaceChildren();
  if (!rows.length) {
    showEmpty(body, emptyMessage);
    return;
  }
  for (const item of rows) {
    const row = document.createElement('tr');
    for (const column of columns) {
      const cell = document.createElement('td');
      const value = column.value(item);
      if (column.className) cell.className = column.className;
      if (column.rolePill && value && value !== 'N/A') {
        const pill = document.createElement('span');
        pill.className = 'role-pill';
        pill.textContent = value;
        cell.append(pill);
      } else if (column.agentAvatar && value && value !== 'N/A') {
        const wrap = column.link ? document.createElement('a') : document.createElement('span');
        wrap.className = 'agent-cell-inline';
        if (column.link) wrap.href = column.link(item);
        const img = createAgentAvatarElement(value, 'agent-avatar-xs');
        const label = document.createElement('span');
        label.textContent = value;
        wrap.append(img, label);
        cell.append(wrap);
      } else if (column.link) {
        const link = document.createElement('a');
        link.href = column.link(item);
        link.textContent = value ?? 'N/A';
        cell.append(link);
      } else {
        cell.textContent = value ?? 'N/A';
      }
      row.append(cell);
    }
    body.append(row);
  }
}

function renderChart(canvasId, config) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !window.Chart) return;
  charts.get(canvasId)?.destroy();
  charts.set(canvasId, new Chart(canvas, config));
}

function barOptions(percentAxis = false) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: '#c4cfcd', usePointStyle: true, boxWidth: 8, font: { size: 10 } } },
      tooltip: { backgroundColor: '#101718', borderColor: '#2b3a3b', borderWidth: 1, titleColor: '#f0f4f2', bodyColor: '#c4cfcd' },
    },
    scales: {
      x: { ticks: { color: '#9baaa7', maxRotation: 0, autoSkip: true }, grid: { display: false } },
      y: {
        beginAtZero: true,
        max: percentAxis ? 1 : undefined,
        ticks: { color: '#9baaa7', callback: percentAxis ? (value) => `${(value * 100).toFixed(0)}%` : undefined },
        grid: { color: '#2b3a3b' },
      },
    },
  };
}

function sentimentModelChartOptions() {
  return {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom', labels: { color: '#c4cfcd', usePointStyle: true, boxWidth: 8, padding: 14, font: { size: 10 } } },
      tooltip: {
        backgroundColor: '#101718', borderColor: '#2b3a3b', borderWidth: 1,
        titleColor: '#f0f4f2', bodyColor: '#c4cfcd',
        callbacks: { label: (item) => `${item.dataset.label}: ${(item.raw * 100).toFixed(1)}%` },
      },
    },
    scales: {
      x: {
        min: 0, max: 1,
        ticks: { color: '#9baaa7', callback: (value) => `${(value * 100).toFixed(0)}%` },
        grid: { color: '#2b3a3b' },
      },
      y: { ticks: { color: '#c4cfcd', font: { size: 10 } }, grid: { display: false } },
    },
  };
}

const MODEL_COMPARISON_ORDER = [
  'Majority baseline', 'SVM', 'Naive Bayes', 'LSTM', 'DistilBERT', 'Four-model ensemble',
];
const MODEL_COMPARISON_REFERENCES = [
  { name: 'Majority baseline', accuracy: 49.0 },
  { name: 'SVM', accuracy: 82.8 },
  { name: 'Naive Bayes', accuracy: 62.0 },
  { name: 'LSTM', accuracy: 46.4 },
  { name: 'DistilBERT', accuracy: 80.2 },
  { name: 'Four-model ensemble', accuracy: 87.0 },
];

// Saved evaluation metrics are fractions, but accept percent-form values too.
function normalizeComparisonPercent(value) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0 || numeric > 100) return null;
  return numeric <= 1 ? numeric * 100 : numeric;
}

function getMacroF1(result) {
  const report = result?.classification_report;
  const value = report?.['macro avg']?.['f1-score'] ?? report?.macro_f1 ?? result?.macro_f1;
  return normalizeComparisonPercent(value);
}

function getComparisonRows(evaluation) {
  const savedModels = evaluation?.models;
  if (!savedModels || typeof savedModels !== 'object' || Array.isArray(savedModels)) return [];
  return MODEL_COMPARISON_ORDER.flatMap((name) => {
    const result = savedModels[name];
    if (!result || typeof result !== 'object') return [];
    const accuracy = normalizeComparisonPercent(result.accuracy);
    const macroF1 = getMacroF1(result);
    const displayName = name === 'Four-model ensemble' ? 'Four-model Ensemble' : name;
    return accuracy === null && macroF1 === null ? [] : [{ name, displayName, accuracy, macroF1 }];
  });
}

const percentageLabelsPlugin = {
  id: 'modelPercentageLabels',
  afterDatasetsDraw(chart, _args, options) {
    const { ctx } = chart;
    ctx.save();
    ctx.fillStyle = options.color || '#f5f2f2';
    ctx.font = `600 ${options.fontSize || 10}px "IBM Plex Sans", sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    chart.data.datasets.forEach((dataset, datasetIndex) => {
      const meta = chart.getDatasetMeta(datasetIndex);
      if (meta.hidden) return;
      meta.data.forEach((bar, index) => {
        const value = dataset.data[index];
        if (value === null || value === undefined || !Number.isFinite(Number(value))) return;
        const point = bar.getProps(['x', 'y'], true);
        ctx.fillText(`${Number(value).toFixed(1)}%`, point.x, Math.max(15, point.y - 5));
      });
    });
    ctx.restore();
  },
};

const paperBackgroundPlugin = {
  id: 'modelPaperBackground',
  beforeDraw(chart, _args, options) {
    if (!options.color) return;
    const { ctx, width, height } = chart;
    ctx.save();
    ctx.globalCompositeOperation = 'destination-over';
    ctx.fillStyle = options.color;
    ctx.fillRect(0, 0, width, height);
    ctx.restore();
  },
};

function modelPerformanceChartOptions({ paper = false, responsive = true, includeF1 = true } = {}) {
  const textColor = paper ? '#292d33' : '#c4cfcd';
  const mutedColor = paper ? '#4f5963' : '#9baaa7';
  const gridColor = paper ? '#dce1e6' : '#343438';
  return {
    responsive,
    maintainAspectRatio: false,
    devicePixelRatio: paper ? 3 : window.devicePixelRatio || 1,
    animation: false,
    layout: { padding: { top: 15, right: 12, left: 5, bottom: 2 } },
    plugins: {
      legend: { position: 'bottom', labels: { color: textColor, usePointStyle: true, boxWidth: 9, padding: 18, font: { size: 11 } } },
      title: {
        display: true,
        text: includeF1 ? 'Sentiment Model Accuracy and Macro F1 Comparison' : 'Sentiment Model Accuracy Comparison',
        color: textColor,
        padding: { top: 2, bottom: 18 },
        font: { family: 'IBM Plex Sans, sans-serif', size: 15, weight: '600' },
      },
      tooltip: {
        backgroundColor: paper ? '#ffffff' : '#101012',
        borderColor: paper ? '#c9d0d7' : '#39383c',
        borderWidth: 1,
        titleColor: textColor,
        bodyColor: textColor,
        callbacks: { label: (item) => `${item.dataset.label}: ${Number(item.raw).toFixed(1)}%` },
      },
      modelPercentageLabels: { color: paper ? '#292d33' : '#f5f2f2', fontSize: 10 },
      modelPaperBackground: { color: paper ? '#ffffff' : null },
    },
    scales: {
      x: {
        title: { display: true, text: 'Sentiment model', color: textColor, font: { size: 11, weight: '600' }, padding: { top: 9 } },
        ticks: { color: textColor, font: { size: 10 }, maxRotation: 0, minRotation: 0, autoSkip: false },
        grid: { display: false },
      },
      y: {
        min: 0,
        max: 100,
        title: { display: true, text: 'Score (%)', color: textColor, font: { size: 11, weight: '600' } },
        ticks: { color: mutedColor, stepSize: 10, callback: (value) => `${value}%` },
        grid: { color: gridColor },
      },
    },
  };
}

function drawModelComparison(evaluation, { fallback = false, errorMessage = '' } = {}) {
  const savedRows = fallback ? [] : getComparisonRows(evaluation);
  const rows = savedRows.length ? savedRows : MODEL_COMPARISON_REFERENCES.map((item) => ({
    ...item,
    displayName: item.name === 'Four-model ensemble' ? 'Four-model Ensemble' : item.name,
    macroF1: null,
  }));
  const isFallback = fallback || !savedRows.length;
  const accuracyAvailable = rows.some((item) => item.accuracy !== null && item.accuracy !== undefined);
  const f1Count = rows.filter((item) => item.macroF1 !== null && item.macroF1 !== undefined).length;
  const hasF1 = f1Count > 0;
  const labels = rows.map((item) => {
    const displayName = item.displayName || item.name;
    if (displayName === 'Majority baseline') return ['Majority', 'Baseline'];
    if (displayName === 'Four-model Ensemble') return ['Four-model', 'Ensemble'];
    return displayName;
  });
  const datasets = [];
  if (accuracyAvailable) {
    datasets.push({
      label: 'Accuracy',
      data: rows.map((item) => item.accuracy),
      backgroundColor: '#ff5966',
      borderColor: '#ff5966',
      borderWidth: 1,
      borderRadius: 2,
      maxBarThickness: 42,
    });
  }
  if (hasF1) {
    datasets.push({
      label: 'Macro F1',
      data: rows.map((item) => item.macroF1),
      backgroundColor: '#69d9c5',
      borderColor: '#69d9c5',
      borderWidth: 1,
      borderRadius: 2,
      maxBarThickness: 42,
    });
  }

  const status = document.getElementById('model-chart-status');
  const methodologyNote = document.getElementById('model-methodology-note');
  const savedDetails = evaluation?.methodology;
  if (isFallback) {
    const reason = errorMessage ? ` ${errorMessage}` : '';
    methodologyNote.textContent = `Saved evaluation results are unavailable.${reason} Showing the supplied reference accuracy values as a clearly labelled fallback; no F1-scores are available in this fallback.`;
  } else if (savedDetails) {
    methodologyNote.textContent = `${savedDetails.split || 'Saved held-out evaluation results.'} Seed: ${savedDetails.random_seed ?? 'not recorded'}. ${savedDetails.distilbert_status || ''}`.trim();
  } else {
    methodologyNote.textContent = 'Values are read from the saved evaluation file. The saved file does not include split methodology details.';
  }
  if (!isFallback) {
    const referenceChecks = MODEL_COMPARISON_REFERENCES.map((reference) => {
      const saved = savedRows.find((item) => item.name === reference.name)?.accuracy;
      return { name: reference.name, reference: reference.accuracy, saved };
    });
    const comparable = referenceChecks.filter((item) => item.saved !== null && item.saved !== undefined);
    const differences = comparable.filter((item) => item.saved.toFixed(1) !== item.reference.toFixed(1));
    if (comparable.length === MODEL_COMPARISON_REFERENCES.length && !differences.length) {
      methodologyNote.textContent += ' All six saved accuracies match the supplied reference values when rounded to one decimal place.';
    } else if (differences.length) {
      methodologyNote.textContent += ` Saved evaluation values take precedence over the supplied references; ${differences.slice(0, 2).map((item) => `${item.name} is ${item.saved.toFixed(1)}% versus ${item.reference.toFixed(1)}%`).join(', ')}.`;
    } else {
      methodologyNote.textContent += ' Saved metrics are shown for available models; reference values are used only when the evaluation is unavailable.';
    }
  }

  if (isFallback || !hasF1) {
    status.textContent = isFallback
      ? 'Reference accuracy fallback shown. Macro F1 is unavailable until saved evaluation results are restored.'
      : 'Macro F1 results are not present in the saved evaluation; only available accuracy values are shown.';
    status.hidden = false;
  } else if (f1Count < rows.length) {
    status.textContent = `Macro F1 is available for ${f1Count} of ${rows.length} saved models; missing values are left blank.`;
    status.hidden = false;
  } else {
    status.textContent = '';
    status.hidden = true;
  }
  if (!isFallback && !accuracyAvailable) {
    status.textContent = 'Accuracy results are missing from the saved evaluation; only available Macro F1 values are shown.';
    status.hidden = false;
  }

  const bestAccuracy = rows.filter((item) => item.accuracy !== null && item.accuracy !== undefined)
    .reduce((best, item) => !best || item.accuracy > best.accuracy ? item : best, null);
  const bestF1 = rows.filter((item) => item.macroF1 !== null && item.macroF1 !== undefined)
    .reduce((best, item) => !best || item.macroF1 > best.macroF1 ? item : best, null);
  const summary = [];
  if (bestAccuracy) summary.push(`Highest accuracy: ${bestAccuracy.displayName || bestAccuracy.name} (${bestAccuracy.accuracy.toFixed(1)}%)`);
  if (bestF1) summary.push(`Highest Macro F1: ${bestF1.displayName || bestF1.name} (${bestF1.macroF1.toFixed(1)}%)`);
  document.getElementById('model-best-summary').textContent = summary.length
    ? `${summary.join(' · ')}. These results describe this held-out split and score-derived labels; they are not a general performance guarantee.`
    : 'No valid accuracy or F1 metrics are available to identify a leading model.';

  if (!window.Chart) {
    status.textContent = 'Chart.js did not load, so the graph cannot be drawn. Check the network connection and reload this page.';
    status.hidden = false;
    return;
  }
  const chartLabels = rows.map((item) => item.displayName || item.name);
  renderChart('models-chart', {
    type: 'bar',
    data: { labels, datasets },
    plugins: [percentageLabelsPlugin, paperBackgroundPlugin],
    options: modelPerformanceChartOptions({ includeF1: hasF1 }),
  });
  // Keep exact values with the live chart for a reproducible vector export.
  const chart = charts.get('models-chart');
  if (chart) {
    chart.$modelComparisonRows = rows.map((item) => ({ ...item }));
    chart.$modelComparisonHasF1 = hasF1;
  }
  const canvas = document.getElementById('models-chart');
  if (canvas) canvas.dataset.modelLabels = JSON.stringify(chartLabels);
}

function downloadModelComparison(format) {
  const sourceChart = charts.get('models-chart');
  const status = document.getElementById('model-chart-status');
  if (!sourceChart) {
    status.textContent = 'The chart is not available to export.';
    status.hidden = false;
    return;
  }
  const anchor = document.createElement('a');
  if (format === 'svg') {
    const svg = createModelComparisonSvg(sourceChart);
    const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
    anchor.href = URL.createObjectURL(blob);
    anchor.download = 'valosent-model-accuracy-comparison.svg';
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
    return;
  }

  // Render a separate 3× canvas for a crisp 4500 × 3000 pixel PNG.
  const exportCanvas = document.createElement('canvas');
  exportCanvas.width = 1500;
  exportCanvas.height = 1000;
  let exportChart;
  try {
    exportChart = new Chart(exportCanvas, {
      type: sourceChart.config.type,
      data: {
        labels: sourceChart.data.labels,
        datasets: sourceChart.data.datasets.map((dataset) => ({
          ...dataset,
          data: [...dataset.data],
        })),
      },
      plugins: [percentageLabelsPlugin, paperBackgroundPlugin],
      options: modelPerformanceChartOptions({ paper: true, responsive: false, includeF1: sourceChart.$modelComparisonHasF1 }),
    });
    anchor.href = exportChart.toBase64Image('image/png', 1);
    anchor.download = 'valosent-model-accuracy-comparison-high-resolution.png';
    anchor.click();
  } catch (error) {
    status.textContent = `PNG export failed: ${error.message || 'unable to render the image'}`;
    status.hidden = false;
  } finally {
    exportChart?.destroy();
  }
}

function createModelComparisonSvg(chart) {
  const width = 1800;
  const height = 1100;
  const left = 150;
  const right = 80;
  const top = 130;
  const bottom = 250;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const rows = chart.$modelComparisonRows || [];
  const datasets = chart.data.datasets;
  const hasF1 = datasets.some((dataset) => dataset.label === 'Macro F1');
  const title = hasF1 ? 'Sentiment Model Accuracy and Macro F1 Comparison' : 'Sentiment Model Accuracy Comparison';
  const description = hasF1
    ? 'Grouped bars compare accuracy and macro F1 percentages for sentiment models on a held-out review test split.'
    : 'Bars compare available accuracy percentages for sentiment models on a held-out review test split.';
  const xmlEscape = (value) => String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;',
  })[character]);
  const yFor = (value) => top + plotHeight * (1 - value / 100);
  const pieces = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title description">`,
    `<title id="title">${xmlEscape(title)}</title>`,
    `<desc id="description">${xmlEscape(description)}</desc>`,
    `<rect width="${width}" height="${height}" fill="#ffffff"/>`,
    '<g font-family="Arial, Helvetica, sans-serif" fill="#292d33">',
    `<text x="${width / 2}" y="58" text-anchor="middle" font-size="28" font-weight="700">${xmlEscape(title)}</text>`,
    `<text x="${width / 2}" y="91" text-anchor="middle" font-size="15" fill="#58616b">Held-out review test split · percentage of test examples</text>`,
  ];
  for (let tick = 0; tick <= 100; tick += 10) {
    const y = yFor(tick);
    pieces.push(`<line x1="${left}" y1="${y}" x2="${left + plotWidth}" y2="${y}" stroke="#dce1e6" stroke-width="1"/>`);
    pieces.push(`<text x="${left - 18}" y="${y + 5}" text-anchor="end" font-size="14" fill="#4f5963">${tick}%</text>`);
  }
  const groupWidth = plotWidth / Math.max(rows.length, 1);
  rows.forEach((row, rowIndex) => {
    const groupCenter = left + groupWidth * (rowIndex + 0.5);
    const barWidth = Math.min(76, groupWidth * 0.28);
    const gap = 10;
    const visibleDatasets = datasets.filter((dataset) => dataset.data[rowIndex] !== null && dataset.data[rowIndex] !== undefined);
    const totalWidth = visibleDatasets.length * barWidth + Math.max(visibleDatasets.length - 1, 0) * gap;
    let barX = groupCenter - totalWidth / 2;
    visibleDatasets.forEach((dataset) => {
      const rawValue = Number(dataset.data[rowIndex]);
      const barY = yFor(rawValue);
      const color = Array.isArray(dataset.backgroundColor) ? dataset.backgroundColor[rowIndex] : dataset.backgroundColor;
      pieces.push(`<rect x="${barX}" y="${barY}" width="${barWidth}" height="${top + plotHeight - barY}" rx="3" fill="${xmlEscape(color)}"/>`);
      pieces.push(`<text x="${barX + barWidth / 2}" y="${barY - 11}" text-anchor="middle" font-size="15" font-weight="700">${rawValue.toFixed(1)}%</text>`);
      barX += barWidth + gap;
    });
    const displayName = row.displayName || row.name;
    const lineLabels = displayName === 'Majority baseline' ? ['Majority', 'Baseline']
      : displayName === 'Four-model Ensemble' ? ['Four-model', 'Ensemble'] : [displayName];
    lineLabels.forEach((line, index) => {
      pieces.push(`<text x="${groupCenter}" y="${top + plotHeight + 30 + index * 22}" text-anchor="middle" font-size="15">${xmlEscape(line)}</text>`);
    });
  });
  pieces.push(`<text x="${left + plotWidth / 2}" y="${height - 65}" text-anchor="middle" font-size="17" font-weight="600">Sentiment model</text>`);
  pieces.push(`<text transform="translate(42 ${top + plotHeight / 2}) rotate(-90)" text-anchor="middle" font-size="17" font-weight="600">Score (%)</text>`);
  const legendWidth = datasets.length * 190;
  const legendStart = (width - legendWidth) / 2;
  datasets.forEach((dataset, index) => {
    const x = legendStart + index * 190;
    const color = Array.isArray(dataset.backgroundColor) ? dataset.backgroundColor[0] : dataset.backgroundColor;
    pieces.push(`<rect x="${x}" y="${height - 28}" width="16" height="16" rx="2" fill="${xmlEscape(color)}"/>`);
    pieces.push(`<text x="${x + 25}" y="${height - 15}" font-size="15">${xmlEscape(dataset.label)}</text>`);
  });
  pieces.push('</g></svg>');
  return pieces.join('');
}

function doughnutOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '68%',
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (item) => `${item.label}: ${formatNumber(item.raw)}` } } },
  };
}

async function initializeDashboard() {
  const [summary, maps, sentiment, comparison] = await Promise.all([
    getJson('/api/dashboard-summary'),
    getJson('/api/maps'),
    getJson('/api/sentiment-distribution'),
    getJson('/api/model-comparison'),
  ]);

  document.getElementById('metric-map-groups').textContent = formatNumber(summary.map_groups);
  document.getElementById('metric-maps').textContent = formatNumber(summary.maps);
  document.getElementById('metric-agents').textContent = formatNumber(summary.agents);
  document.getElementById('metric-players').textContent = formatNumber(summary.player_labels);
  document.getElementById('snapshot-range').textContent = `${summary.date_start} - ${summary.date_end}`;

  const mapSelect = document.getElementById('dashboard-map');
  setOptions(mapSelect, maps.maps);
  const modelNames = ['Majority baseline', 'SVM', 'Naive Bayes', 'LSTM', 'DistilBERT', 'Four-model ensemble'];
  const modelStats = modelNames.filter((name) => comparison.models[name]).map((name) => {
    const result = comparison.models[name];
    const report = result.classification_report;
    return { name, accuracy: result.accuracy, macroF1: report['macro avg']['f1-score'] };
  }).sort((a, b) => b.accuracy - a.accuracy);
  const baseline = modelStats.find((item) => item.name === 'Majority baseline');
  const strongest = modelStats.filter((item) => item.name !== 'Majority baseline')
    .reduce((best, item) => item.accuracy > best.accuracy ? item : best);
  if (baseline && strongest) {
    const difference = (strongest.accuracy - baseline.accuracy) * 100;
    const direction = difference >= 0 ? 'higher' : 'lower';
    document.getElementById('dashboard-model-impact').textContent =
      `${strongest.name} leads with ${(strongest.accuracy * 100).toFixed(1)}% accuracy, ` +
      `${Math.abs(difference).toFixed(1)} percentage points ${direction} than the majority baseline ` +
      `(${(baseline.accuracy * 100).toFixed(1)}%).`;
  } else {
    document.getElementById('dashboard-model-impact').textContent =
      'Saved results do not include the majority baseline yet. Retrain the sentiment models to create the full comparison.';
  }
  const modelColors = { 'Majority baseline': '#788784', SVM: '#fa4f58', 'Naive Bayes': '#eab36b', LSTM: '#55d8c0', DistilBERT: '#75aaff', 'Four-model ensemble': '#d18bff' };
  renderChart('dashboard-model-chart', {
    type: 'bar',
    data: {
      labels: modelStats.map((item) => item.name),
      datasets: [
        { label: 'Accuracy', data: modelStats.map((item) => item.accuracy), backgroundColor: modelStats.map((item) => modelColors[item.name]), borderRadius: 3 },
        { label: 'Macro F1', data: modelStats.map((item) => item.macroF1), backgroundColor: modelStats.map((item) => `${modelColors[item.name]}99`), borderRadius: 3 },
      ],
    },
    options: sentimentModelChartOptions(),
  });
  renderSentimentChart('dashboard-sentiment-chart', 'sentiment-legend', sentiment);

  const updateMap = async () => {
    setMapBackdrop(mapSelect.value);
    const result = await getJson(`/api/agent-map-stats?map=${encodeURIComponent(mapSelect.value)}`);
    const rows = result.stats.slice(0, 10);
    renderChart('dashboard-agent-chart', {
      type: 'bar',
      data: {
        labels: rows.map((item) => item.agent_name),
        datasets: [
          { label: 'Pick rate', data: rows.map((item) => item.pick_rate), backgroundColor: '#ff4655', borderRadius: 2 },
          { label: 'Map win rate', data: rows.map((item) => item.map_win_rate), backgroundColor: '#ece8e1', borderRadius: 2 },
        ],
      },
      options: barOptions(true),
    });
    renderTable(document.getElementById('dashboard-agent-table'), rows, [
      { value: (item) => item.agent_name, link: (item) => `/agents/${encodeURIComponent(item.agent_name)}`, agentAvatar: true },
      { value: (item) => item.role || 'N/A', rolePill: true },
      { value: (item) => formatNumber(item.appearances) },
      { value: (item) => formatPercent(item.pick_rate) },
      { value: (item) => item.resolved_maps ? formatPercent(item.map_win_rate) : 'N/A' },
    ]);
  };
  mapSelect.addEventListener('change', () => updateMap().catch((error) => notify(error.message)));
  await updateMap();
}

function renderSentimentChart(canvasId, legendId, sentiment) {
  renderChart(canvasId, {
    type: 'doughnut',
    data: {
      labels: sentiment.labels,
      datasets: [{ data: sentiment.labels.map((label) => sentiment.counts[label]), backgroundColor: ['#ff4655', '#eab36b', '#d4d0d1'], borderColor: '#141416', borderWidth: 3 }],
    },
    options: doughnutOptions(),
  });
  const legend = document.getElementById(legendId);
  if (legend) {
    legend.replaceChildren();
    sentiment.labels.forEach((label, index) => {
      const item = document.createElement('div');
      item.className = 'legend-item';
      const swatch = document.createElement('span');
      swatch.className = 'legend-swatch';
      swatch.style.backgroundColor = ['#ff4655', '#eab36b', '#d4d0d1'][index];
      const text = document.createElement('span');
      text.innerHTML = `<strong>${formatPercent(sentiment.percentages[label] / 100)}</strong>${label} · ${formatNumber(sentiment.counts[label])}`;
      item.append(swatch, text);
      legend.append(item);
    });
  }
}

async function initializeMaps() {
  const [maps, roles] = await Promise.all([getJson('/api/maps'), getJson('/api/roles')]);
  const mapSelect = document.getElementById('map-filter');
  const roleSelect = document.getElementById('map-role-filter');
  const sideControls = document.getElementById('map-side-filter');
  setOptions(mapSelect, maps.maps, { selected: document.body.dataset.selectedMap });
  setOptions(roleSelect, roles.roles, { all: true });
  let side = 'both';
  sideControls.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-side]');
    if (!button) return;
    side = button.dataset.side;
    sideControls.querySelectorAll('button').forEach((item) => item.classList.toggle('selected', item === button));
    update().catch((error) => notify(error.message));
  });
  const update = async () => {
    const mapName = mapSelect.value;
    setMapBackdrop(mapName);
    const [map, stats] = await Promise.all([
      getJson(`/api/map/${encodeURIComponent(mapName)}`),
      getJson(`/api/agent-map-performance?map=${encodeURIComponent(mapName)}&role=${encodeURIComponent(roleSelect.value)}&side=${encodeURIComponent(side)}`),
    ]);
    const sorted = stats.stats;
    renderMapHeroBanner('map', map.map, sorted.slice(0, 5));
    document.getElementById('map-group-count').textContent = formatNumber(map.map_groups);
    document.getElementById('map-pick-count').textContent = formatNumber(map.player_agent_picks);
    document.getElementById('map-agent-count').textContent = formatNumber(sorted.length);
    document.getElementById('map-table-title').textContent = `${map.map} · ${roleSelect.value} · ${side === 'both' ? 'overall' : `${side} ACS`}`;
    renderTable(document.getElementById('map-agent-table'), sorted, [
      { value: (item) => item.agent_name, link: (item) => `/agents/${encodeURIComponent(item.agent_name)}`, agentAvatar: true },
      { value: (item) => item.role || 'N/A', rolePill: true },
      { value: (item) => formatNumber(item.appearances) },
      { value: (item) => formatPercent(item.pick_rate) },
      { value: (item) => item.resolved_maps ? formatPercent(item.map_win_rate) : 'N/A' },
      { value: (item) => item.attack_acs_samples ? `${formatMetric(item.attack_acs_median)} · n=${formatNumber(item.attack_acs_samples)}` : 'N/A' },
      { value: (item) => item.defense_acs_samples ? `${formatMetric(item.defense_acs_median)} · n=${formatNumber(item.defense_acs_samples)}` : 'N/A' },
    ]);
    const chartRows = sorted.slice(0, 10);
    renderChart('map-agent-chart', {
      type: 'bar',
      data: {
        labels: chartRows.map((item) => item.agent_name),
        datasets: [{
          label: side === 'attack' ? 'Median T-side ACS' : side === 'defense' ? 'Median CT-side ACS' : 'Map win rate',
          data: chartRows.map((item) => side === 'attack' ? item.attack_acs_median : side === 'defense' ? item.defense_acs_median : item.map_win_rate),
          backgroundColor: chartRows.map((_, index) => palette[index % palette.length]),
          borderRadius: 2,
        }],
      },
      options: barOptions(side === 'both'),
    });
  };
  mapSelect.addEventListener('change', () => update().catch((error) => notify(error.message)));
  roleSelect.addEventListener('change', () => update().catch((error) => notify(error.message)));
  await update();
}

async function initializeAgents() {
  const { agents } = await getJson('/api/agent-catalog');
  const select = document.getElementById('agent-filter');
  const stripEl = document.getElementById('agent-roster-strip');
  const names = agents.map((item) => item.agent);
  setOptions(select, names, { selected: document.body.dataset.selectedAgent || (names.includes('Veto') ? 'Veto' : names[0]) });
  if (!select.value) return;

  const syncStripActive = (activeName) => {
    if (!stripEl) return;
    stripEl.querySelectorAll('.agent-strip-btn').forEach((btn) => {
      const isActive = btn.dataset.agent === activeName;
      btn.classList.toggle('active', isActive);
      if (isActive) btn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    });
  };

  if (stripEl) {
    stripEl.replaceChildren();
    agents.forEach((item) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'agent-strip-btn';
      btn.dataset.agent = item.agent;
      btn.title = `${item.agent} (${item.role})`;
      btn.append(createAgentAvatarElement(item.agent, ''), document.createTextNode(item.agent));
      btn.addEventListener('click', () => {
        select.value = item.agent;
        update().catch((error) => notify(error.message));
      });
      stripEl.append(btn);
    });
  }

  const update = async () => {
    const result = await getJson(`/api/agents/${encodeURIComponent(select.value)}`);
    const historical = result.historical;
    const maps = historical?.maps || [];
    const overall = historical?.overall;
    const review = result.review_sentiment;
    const agentAsset = result.assets || getAgentAsset(result.agent);
    syncStripActive(result.agent);

    // Dynamic full-body portrait, background emblem, role icon & mini-avatar in Agent Dossier Hero
    const heroEl = document.getElementById('agent-profile-hero');
    const portraitEl = document.getElementById('agent-hero-portrait');
    const bgEl = document.getElementById('agent-hero-bg');
    const avatarEl = document.getElementById('agent-avatar-img');
    const roleMarkEl = document.getElementById('agent-role-mark');
    const roleIconEl = document.getElementById('agent-role-icon');

    if (heroEl && agentAsset.accent) {
      heroEl.style.setProperty('--agent-accent', `${agentAsset.accent}55`);
    }
    if (portraitEl) {
      portraitEl.hidden = false;
      portraitEl.dataset.fallbackApplied = '';
      portraitEl.alt = `${result.agent} full portrait`;
      portraitEl.src = agentAsset.portrait || agentAsset.fallback_portrait;
      portraitEl.onerror = () => {
        if (portraitEl.dataset.fallbackApplied) return;
        portraitEl.dataset.fallbackApplied = '1';
        portraitEl.src = agentAsset.fallback_portrait;
      };
    }
    if (bgEl) {
      if (agentAsset.background) {
        bgEl.hidden = false;
        bgEl.src = agentAsset.background;
        bgEl.onerror = () => { bgEl.hidden = true; };
      } else {
        bgEl.hidden = true;
      }
    }
    if (avatarEl) {
      avatarEl.hidden = false;
      avatarEl.dataset.fallbackApplied = '';
      avatarEl.alt = `${result.agent} icon`;
      avatarEl.src = agentAsset.icon || agentAsset.fallback_icon;
      avatarEl.onerror = () => {
        if (avatarEl.dataset.fallbackApplied) return;
        avatarEl.dataset.fallbackApplied = '1';
        avatarEl.src = agentAsset.fallback_icon;
      };
      if (roleMarkEl) roleMarkEl.hidden = true;
    }
    if (roleIconEl) {
      roleIconEl.hidden = false;
      roleIconEl.dataset.fallbackApplied = '';
      roleIconEl.alt = `${result.role || 'Agent'} icon`;
      roleIconEl.src = agentAsset.role_icon || agentAsset.fallback_role_icon;
      roleIconEl.onerror = () => {
        if (roleIconEl.dataset.fallbackApplied) return;
        roleIconEl.dataset.fallbackApplied = '1';
        roleIconEl.src = agentAsset.fallback_role_icon;
      };
    }

    // Subtle page backdrop synced to the agent's Best Qualified Map
    const backdropMap = result.best_maps?.[0]?.map || 'Summit';
    setMapBackdrop(backdropMap);

    document.getElementById('agent-name').textContent = result.agent;
    document.getElementById('agent-role').textContent = (result.role || 'Role unavailable').toUpperCase();
    if (roleMarkEl) roleMarkEl.textContent = (result.role || 'NA').slice(0, 2).toUpperCase();
    document.getElementById('agent-appearances').textContent = overall ? formatNumber(overall.appearances) : 'N/A';
    document.getElementById('agent-pick-rate').textContent = overall ? formatPercent(overall.pick_rate) : 'N/A';
    document.getElementById('agent-win-rate').textContent = overall?.map_win_rate === null || overall?.map_win_rate === undefined ? 'N/A' : formatPercent(overall.map_win_rate);
    document.getElementById('agent-attack-acs').textContent = overall?.attack_acs_samples ? `${formatMetric(overall.attack_acs_median)} · n=${formatNumber(overall.attack_acs_samples)}` : 'N/A';
    document.getElementById('agent-defense-acs').textContent = overall?.defense_acs_samples ? `${formatMetric(overall.defense_acs_median)} · n=${formatNumber(overall.defense_acs_samples)}` : 'N/A';
    document.getElementById('agent-best-map').textContent = result.best_maps?.[0]?.map || 'Insufficient data';
    document.getElementById('agent-worst-map').textContent = result.worst_maps?.[0]?.map || 'Insufficient data';
    const heroMentions = document.getElementById('agent-hero-mentions');
    if (heroMentions) heroMentions.textContent = formatNumber(review?.total_mentions || 0);
    document.getElementById('agent-positive').textContent = review?.total_mentions ? formatPercent(review.positive_percentage / 100) : 'N/A';
    document.getElementById('agent-neutral').textContent = review?.total_mentions ? formatPercent(review.neutral_percentage / 100) : 'N/A';
    document.getElementById('agent-negative').textContent = review?.total_mentions ? formatPercent(review.negative_percentage / 100) : 'N/A';
    document.getElementById('agent-positive-count').textContent = `${formatNumber(review?.positive_reviews || 0)} reviews`;
    document.getElementById('agent-neutral-count').textContent = `${formatNumber(review?.neutral_reviews || 0)} reviews`;
    document.getElementById('agent-negative-count').textContent = `${formatNumber(review?.negative_reviews || 0)} reviews`;
    document.getElementById('agent-mentions').textContent = formatNumber(review?.total_mentions || 0);
    document.getElementById('agent-sentiment-method').textContent = review?.method || 'No review-mention analysis is available.';
    const trend = review?.trend || [];
    document.getElementById('agent-sentiment-trend-wrap').hidden = trend.length === 0;
    document.getElementById('agent-sentiment-trend-empty').hidden = trend.length > 0;
    if (trend.length) {
      renderChart('agent-sentiment-trend', {
        type: 'line',
        data: {
          labels: trend.map((item) => item.date),
          datasets: [
            { label: 'Positive', data: trend.map((item) => item.Positive), borderColor: '#d4d0d1', backgroundColor: '#d4d0d1', tension: 0.2 },
            { label: 'Neutral', data: trend.map((item) => item.Neutral), borderColor: '#eab36b', backgroundColor: '#eab36b', tension: 0.2 },
            { label: 'Negative', data: trend.map((item) => item.Negative), borderColor: '#ff4655', backgroundColor: '#ff4655', tension: 0.2 },
          ],
        },
        options: barOptions(),
      });
    } else {
      document.getElementById('agent-sentiment-trend-empty').textContent = review?.total_mentions
        ? 'No valid review dates for these mentions.'
        : 'No detected review mentions for this agent.';
    }
    renderTable(document.getElementById('agent-map-table'), maps, [
      { value: (item) => item.map, link: (item) => `/maps/${encodeURIComponent(item.map)}` },
      { value: (item) => formatNumber(item.appearances) },
      { value: (item) => formatPercent(item.pick_rate) },
      { value: (item) => item.resolved_maps ? formatPercent(item.map_win_rate) : 'N/A' },
      { value: (item) => item.attack_acs_samples ? `${formatMetric(item.attack_acs_median)} · n=${formatNumber(item.attack_acs_samples)}` : 'N/A' },
      { value: (item) => item.defense_acs_samples ? `${formatMetric(item.defense_acs_median)} · n=${formatNumber(item.defense_acs_samples)}` : 'N/A' },
    ]);
    renderChart('agent-map-chart', {
      type: 'bar',
      data: {
        labels: maps.map((item) => item.map),
        datasets: [
          { label: 'Pick rate', data: maps.map((item) => item.pick_rate), backgroundColor: '#ff4655', borderRadius: 2 },
          { label: 'Map win rate', data: maps.map((item) => item.map_win_rate), backgroundColor: '#d4d0d1', borderRadius: 2 },
        ],
      },
      options: barOptions(true),
    });
    renderChart('agent-side-acs-chart', {
      type: 'bar',
      data: {
        labels: maps.map((item) => item.map),
        datasets: [
          { label: 'Median T-side ACS', data: maps.map((item) => item.attack_acs_median), backgroundColor: '#ff4655', borderRadius: 2 },
          { label: 'Median CT-side ACS', data: maps.map((item) => item.defense_acs_median), backgroundColor: '#d4d0d1', borderRadius: 2 },
        ],
      },
      options: barOptions(),
    });
  };
  select.addEventListener('change', () => update().catch((error) => notify(error.message)));
  await update();
}

function attachSegmented(containerId, initialValue, onChange) {
  const container = document.getElementById(containerId);
  let value = initialValue;
  container.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-side]');
    if (!button) return;
    value = button.dataset.side;
    container.querySelectorAll('button').forEach((item) => item.classList.toggle('selected', item === button));
    onChange(value);
  });
  return () => value;
}

async function initializeRecommendations() {
  const [maps, roles, agents] = await Promise.all([getJson('/api/maps'), getJson('/api/roles'), getJson('/api/agents')]);
  const mapSelect = document.getElementById('recommend-map');
  const roleSelect = document.getElementById('recommend-role');
  const synergyAgent = document.getElementById('synergy-agent');
  setOptions(mapSelect, maps.maps, { selected: document.body.dataset.selectedMap });
  setOptions(roleSelect, roles.roles, { all: true });
  setOptions(synergyAgent, agents.agents.map((item) => item.agent));
  let side = 'both';
  let update;
  attachSegmented('recommend-side', side, (value) => {
    side = value;
    update?.().catch((error) => notify(error.message));
  });

  update = async () => {
    const mapName = mapSelect.value;
    const role = roleSelect.value;
    setMapBackdrop(mapName);
    const result = await getJson(`/api/recommend?map=${encodeURIComponent(mapName)}&side=${side}&role=${encodeURIComponent(role)}`);
    renderMapHeroBanner('recommend', mapName, result.recommendations.slice(0, 5));
    document.getElementById('recommend-title').textContent = `${mapName} · ${role} · ${side}`;
    document.getElementById('recommendation-method').textContent = side === 'both'
      ? 'Sorted by Wilson 95% lower bound for historical map win rate; minimum 20 agent-map picks. This is not a causal agent effect.'
      : `Sorted by percentile of median ${side === 'attack' ? 'T-side' : 'CT-side'} ACS; minimum map-pick and side-sample thresholds apply. This is not a side win rate.`;
    const list = document.getElementById('recommendation-list');
    list.replaceChildren();
    if (!result.recommendations.length) {
      list.textContent = 'Insufficient data for this map, role, and side combination.';
    }
    for (const item of result.recommendations) {
      const card = document.createElement('article');
      card.className = 'recommendation-card';
      const top = document.createElement('div');
      top.className = 'recommendation-top';
      const title = document.createElement('strong');
      title.className = 'agent-cell-inline';
      title.append(createAgentAvatarElement(item.agent, 'agent-avatar-sm'), document.createTextNode(`#${item.rank} ${item.agent} · ${item.role}`));
      const score = document.createElement('span');
      score.className = 'recommendation-score';
      score.textContent = `${formatMetric(item.score)} pts`;
      top.append(title, score);
      const why = document.createElement('ul');
      item.why.forEach((reason) => {
        const entry = document.createElement('li');
        entry.textContent = reason;
        why.append(entry);
      });
      card.append(top, why);
      list.append(card);
    }
    await updateCompositions(mapName);
    await updateSynergy(mapName);
  };
  const updateCompositions = async (mapName) => {
    const result = await getJson(`/api/team-composition?map=${encodeURIComponent(mapName)}`);
    const container = document.getElementById('composition-list');
    container.replaceChildren();
    if (!result.compositions.length) {
      container.textContent = 'Insufficient repeated lineup data for this map.';
      return;
    }
    result.compositions.forEach((item) => {
      const card = document.createElement('article');
      card.className = 'composition-card';
      const summary = document.createElement('p');
      const lbText = item.win_rate_lower_bound !== undefined
        ? ` · Wilson 95% LB ${formatPercent(item.win_rate_lower_bound)}`
        : '';
      summary.textContent = `${formatPercent(item.win_rate)} win rate${lbText} · ${formatNumber(item.appearances)} map appearances`;
      const lineup = document.createElement('div');
      lineup.className = 'composition-agents';
      item.composition.split(' | ').forEach((agent) => {
        const chip = document.createElement('span');
        chip.className = 'agent-cell-inline';
        chip.append(createAgentAvatarElement(agent, 'agent-avatar-xs'), document.createTextNode(agent));
        lineup.append(chip);
      });
      card.append(summary, lineup);
      container.append(card);
    });
  };
  const updateSynergy = async (mapName) => {
    if (!synergyAgent.value) return;
    const result = await getJson(`/api/agent-synergy?agent=${encodeURIComponent(synergyAgent.value)}&map=${encodeURIComponent(mapName)}`);
    renderTable(document.getElementById('synergy-table'), result.pairings, [
      { value: (item) => item.partner, link: (item) => `/agents/${encodeURIComponent(item.partner)}`, agentAvatar: true },
      { value: (item) => item.map },
      { value: (item) => formatNumber(item.appearances) },
      { value: (item) => formatPercent(item.win_rate) },
      { value: (item) => item.win_rate_lower_bound !== undefined ? formatPercent(item.win_rate_lower_bound) : 'N/A' },
    ]);
  };
  mapSelect.addEventListener('change', () => update().catch((error) => notify(error.message)));
  roleSelect.addEventListener('change', () => update().catch((error) => notify(error.message)));
  document.getElementById('run-recommendation').addEventListener('click', () => update().catch((error) => notify(error.message)));
  synergyAgent.addEventListener('change', () => updateSynergy(mapSelect.value).catch((error) => notify(error.message)));
  initializeDraftSimulator(mapSelect, agents.agents.map((item) => item.agent));
  await update();
}

function initializeDraftSimulator(mapSelect, agentNames) {
  const container = document.getElementById('draft-simulator');
  if (!container) return;
  const selects = Array.from(container.querySelectorAll('.draft-select'));
  const t1Selects = selects.filter((el) => el.dataset.team === '1');
  const t2Selects = selects.filter((el) => el.dataset.team === '2');
  const defaultT1 = ['Clove', 'Hush', 'Miks', 'Tejo', 'Veto'];
  const defaultT2 = ['Astra', 'Gekko', 'Vyse', 'Waylay', 'Yoru'];
  const mapPresets = {
    Ascent: [['Clove', 'Deadlock', 'Jett', 'KAY/O', 'Sova'], ['Iso', 'KAY/O', 'Omen', 'Sova', 'Veto']],
    Icebox: [['Gekko', 'Harbor', 'Jett', 'Killjoy', 'Viper'], ['Deadlock', 'Gekko', 'Killjoy', 'Sova', 'Viper']],
    Haven: [['Breach', 'Iso', 'Omen', 'Sova', 'Veto'], ['Cypher', 'Hush', 'Miks', 'Sova', 'Tejo']],
    Bind: [['Brimstone', 'Deadlock', 'Gekko', 'Raze', 'Viper'], ['Brimstone', 'Clove', 'Skye', 'Viper', 'Yoru']],
    Split: [['Clove', 'Omen', 'Raze', 'Vyse', 'Waylay'], ['Miks', 'Raze', 'Sage', 'Vyse', 'Yoru']],
    Breeze: [['Astra', 'KAY/O', 'Viper', 'Vyse', 'Waylay'], ['Chamber', 'Miks', 'Sova', 'Viper', 'Yoru']],
    Fracture: [['Breach', 'Brimstone', 'Cypher', 'Tejo', 'Waylay'], ['Brimstone', 'Deadlock', 'Hush', 'Raze', 'Tejo']],
    Pearl: [['Astra', 'Miks', 'Sova', 'Vyse', 'Yoru'], ['Astra', 'Gekko', 'Hush', 'Killjoy', 'Veto']],
    Lotus: [['Miks', 'Omen', 'Raze', 'Tejo', 'Vyse'], ['Clove', 'Fade', 'Iso', 'Killjoy', 'Waylay']],
    Sunset: [['Breach', 'Clove', 'Cypher', 'Gekko', 'Neon'], ['Clove', 'Cypher', 'Gekko', 'Hush', 'Tejo']],
    Abyss: [['Astra', 'Cypher', 'Jett', 'Sova', 'Vyse'], ['Astra', 'Cypher', 'Sova', 'Veto', 'Waylay']],
    Corrode: [['Hush', 'Miks', 'Tejo', 'Veto', 'Yoru'], ['Miks', 'Phoenix', 'Tejo', 'Veto', 'Waylay']],
    Summit: [['Miks', 'Sova', 'Tejo', 'Veto', 'Waylay'], ['Fade', 'Jett', 'KAY/O', 'Omen', 'Vyse']],
  };

  const renderDraftAvatars = () => {
    const paint = (stripId, teamSelects) => {
      const strip = document.getElementById(stripId);
      if (!strip) return;
      strip.replaceChildren();
      teamSelects.forEach((sel) => {
        const agent = sel.value;
        if (!agent) return;
        const pill = document.createElement('span');
        pill.className = 'draft-avatar-pill';
        pill.append(createAgentAvatarElement(agent, ''), document.createTextNode(agent));
        strip.append(pill);
      });
    };
    paint('draft-team1-avatars', t1Selects);
    paint('draft-team2-avatars', t2Selects);
  };

  const applyLineups = (lineup1, lineup2) => {
    t1Selects.forEach((el, idx) => setOptions(el, agentNames, { selected: lineup1[idx] || agentNames[idx] }));
    t2Selects.forEach((el, idx) => setOptions(el, agentNames, { selected: lineup2[idx] || agentNames[idx + 5] }));
    renderDraftAvatars();
  };
  applyLineups(defaultT1, defaultT2);
  selects.forEach((sel) => sel.addEventListener('change', renderDraftAvatars));

  document.getElementById('draft-load-preset').addEventListener('click', () => {
    const preset = mapPresets[mapSelect.value] || [defaultT1, defaultT2];
    applyLineups(preset[0], preset[1]);
  });

  const renderTeamBox = (title, team) => {
    const box = document.createElement('article');
    box.className = 'analysis-card';
    const heading = document.createElement('strong');
    heading.textContent = `${title} · ${team.agents.join(' | ')}`;
    const rolesText = Object.entries(team.role_counts).map(([role, count]) => `${role}: ${count}`).join(' · ');
    const roleLine = document.createElement('p');
    roleLine.textContent = rolesText;
    const compLine = document.createElement('p');
    compLine.textContent = team.historical_composition
      ? `Observed on map: ${formatPercent(team.historical_composition.win_rate)} win rate (Wilson LB ${formatPercent(team.historical_composition.win_rate_lower_bound)}, n=${formatNumber(team.historical_composition.appearances)})`
      : 'Exact 5-agent composition not observed on this map in the 2021-2026 dataset.';
    const synLine = document.createElement('p');
    synLine.textContent = team.average_pair_win_rate !== null
      ? `Weighted teammate pair win rate: ${formatPercent(team.average_pair_win_rate)} across ${team.observed_pairs}/10 observed pairs.`
      : 'No observed teammate pair synergy data on this map.';
    box.append(heading, roleLine, compLine, synLine);
    if (team.warnings.length) {
      const list = document.createElement('ul');
      list.className = 'draft-warning-list';
      team.warnings.forEach((warning) => {
        const li = document.createElement('li');
        li.textContent = warning;
        list.append(li);
      });
      box.append(list);
    }
    return box;
  };

  document.getElementById('run-draft-analysis').addEventListener('click', async () => {
    const output = document.getElementById('draft-results');
    const team1 = t1Selects.map((el) => el.value);
    const team2 = t2Selects.map((el) => el.value);
    try {
      const response = await fetch('/api/match/predict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ map: mapSelect.value, team1, team2 }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Draft analysis failed.');
      output.replaceChildren();
      if (data.ml_prediction) {
        const mlBox = document.createElement('article');
        mlBox.className = 'prediction-overall';
        const p1 = (data.ml_prediction.team1_win_probability * 100).toFixed(1);
        const p2 = (data.ml_prediction.team2_win_probability * 100).toFixed(1);
        const header = document.createElement('div');
        header.className = 'draft-prob-header';
        header.innerHTML = `<span>TEAM 1: ${p1}%</span><span>${data.map.toUpperCase()} · ${data.ml_prediction.model}</span><span>TEAM 2: ${p2}%</span>`;
        const bar = document.createElement('div');
        bar.className = 'draft-prob-bar';
        const seg1 = document.createElement('div');
        seg1.className = 'draft-prob-t1';
        seg1.style.width = `${p1}%`;
        const seg2 = document.createElement('div');
        seg2.className = 'draft-prob-t2';
        seg2.style.width = `${p2}%`;
        bar.append(seg1, seg2);
        const note = document.createElement('small');
        note.textContent = `Patch ${data.ml_prediction.patch_used} · ${data.ml_prediction.note}`;
        mlBox.append(header, bar, note);
        output.append(mlBox);
      }
      const teamsGrid = document.createElement('div');
      teamsGrid.className = 'draft-grid';
      teamsGrid.append(renderTeamBox('TEAM 1', data.team1), renderTeamBox('TEAM 2', data.team2));
      output.append(teamsGrid);
      output.hidden = false;
      document.getElementById('page-notice').hidden = true;
    } catch (error) {
      notify(error.message);
    }
  });
}

async function initializeCompare() {
  const [maps, agentsData] = await Promise.all([getJson('/api/maps'), getJson('/api/agents')]);
  const allAgents = agentsData.agents || [];
  const mapSelect = document.getElementById('compare-map');
  const trayEl = document.getElementById('compare-selected-tray');
  const countEl = document.getElementById('compare-selected-count');
  const gridEl = document.getElementById('compare-agent-grid');
  const hintEl = document.getElementById('compare-picker-hint');
  const resultsWrap = document.getElementById('compare-results-wrap');
  const searchInput = document.getElementById('compare-agent-search');
  const roleTabsWrap = document.getElementById('compare-role-tabs');

  setOptions(mapSelect, maps.maps, { all: true });
  if (mapSelect.options[0]) mapSelect.options[0].textContent = 'All Maps';

  let activeRole = 'All';
  let searchQuery = '';
  const allNameSet = new Set(allAgents.map((item) => item.agent));
  let selectedAgents = allNameSet.has('Veto') && allNameSet.has('Vyse')
    ? ['Veto', 'Vyse']
    : allAgents.slice(0, 2).map((item) => item.agent);

  const roleColorClass = (role) => {
    const r = String(role || '').toLowerCase();
    if (r === 'duelist') return 'role-duelist';
    if (r === 'controller') return 'role-controller';
    if (r === 'initiator') return 'role-initiator';
    if (r === 'sentinel') return 'role-sentinel';
    return '';
  };

  const renderTray = () => {
    countEl.textContent = String(selectedAgents.length);
    trayEl.replaceChildren();
    if (!selectedAgents.length) {
      const empty = document.createElement('span');
      empty.className = 'tray-empty';
      empty.textContent = 'Click 2–5 agents below to start comparing...';
      trayEl.append(empty);
      return;
    }
    selectedAgents.forEach((name) => {
      const entry = allAgents.find((a) => a.agent === name);
      const pill = document.createElement('button');
      pill.type = 'button';
      pill.className = `selected-agent-pill ${roleColorClass(entry?.role)}`;
      pill.title = `Remove ${name}`;
      pill.append(
        createAgentAvatarElement(name, 'agent-avatar-xs'),
        Object.assign(document.createElement('span'), { textContent: name }),
        Object.assign(document.createElement('span'), { className: 'pill-remove', textContent: '×' }),
      );
      pill.addEventListener('click', () => {
        selectedAgents = selectedAgents.filter((a) => a !== name);
        syncPickerAndCompare();
      });
      trayEl.append(pill);
    });
  };

  const renderGrid = () => {
    gridEl.replaceChildren();
    const q = searchQuery.trim().toLowerCase();
    const filtered = allAgents.filter((item) => {
      const roleMatch = activeRole === 'All' || item.role === activeRole;
      const textMatch = !q || item.agent.toLowerCase().includes(q) || String(item.role || '').toLowerCase().includes(q);
      return roleMatch && textMatch;
    });
    if (!filtered.length) {
      const empty = document.createElement('p');
      empty.className = 'panel-note';
      empty.textContent = 'No agents match your filter.';
      gridEl.append(empty);
      return;
    }
    filtered.forEach((item) => {
      const isSelected = selectedAgents.includes(item.agent);
      const tile = document.createElement('button');
      tile.type = 'button';
      tile.className = `agent-tile ${roleColorClass(item.role)}${isSelected ? ' selected' : ''}`;
      tile.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
      const avatar = createAgentAvatarElement(item.agent, 'agent-avatar-sm');
      const info = document.createElement('div');
      info.className = 'agent-tile-info';
      info.innerHTML = `<span class="agent-tile-head"><span class="role-dot"></span><strong>${item.agent}</strong>${isSelected ? '<span class="tile-check">✓</span>' : ''}</span><small>${item.role}</small>`;
      tile.append(avatar, info);
      tile.addEventListener('click', () => {
        if (isSelected) {
          selectedAgents = selectedAgents.filter((a) => a !== item.agent);
        } else {
          if (selectedAgents.length >= 5) {
            notify('You can compare up to 5 agents at once. Click any selected agent to remove it first.');
            return;
          }
          selectedAgents = [...selectedAgents, item.agent];
        }
        document.getElementById('page-notice').hidden = true;
        syncPickerAndCompare();
      });
      gridEl.append(tile);
    });
  };

  const renderHeadToHeadMatrix = (profiles) => {
    const head = document.getElementById('compare-matrix-head');
    const body = document.getElementById('compare-matrix-body');
    head.replaceChildren();
    body.replaceChildren();

    const hRow = document.createElement('tr');
    const firstTh = document.createElement('th');
    firstTh.textContent = 'METRIC';
    hRow.append(firstTh);
    profiles.forEach((p) => {
      const th = document.createElement('th');
      const wrap = document.createElement('span');
      wrap.className = 'agent-cell-inline';
      wrap.append(createAgentAvatarElement(p.agent, 'agent-avatar-xs'), document.createTextNode(`${p.agent} (${p.role})`));
      th.append(wrap);
      hRow.append(th);
    });
    head.append(hRow);

    const metricRows = [
      { label: 'Map Win Rate', get: (p) => p.map_win_rate, fmt: (v) => formatPercent(v), numeric: true },
      { label: 'Pick Rate', get: (p) => p.pick_rate, fmt: (v) => formatPercent(v), numeric: true },
      { label: 'Appearances', get: (p) => p.appearances, fmt: (v) => formatNumber(v), numeric: true },
      { label: 'Attack (T-Side) Median ACS', get: (p) => p.attack_acs_median, fmt: (v) => formatMetric(v), numeric: true },
      { label: 'Defense (CT-Side) Median ACS', get: (p) => p.defense_acs_median, fmt: (v) => formatMetric(v), numeric: true },
      { label: 'Positive Sentiment %', get: (p) => p.sentiment?.total_mentions ? p.sentiment.positive_percentage / 100 : null, fmt: (v) => formatPercent(v), numeric: true },
      { label: 'Review Mentions', get: (p) => p.sentiment?.total_mentions ?? 0, fmt: (v) => formatNumber(v), numeric: true },
      { label: 'Best Qualified Map', get: (p) => p.best_map, fmt: (v) => v || 'N/A', numeric: false },
      { label: 'Worst Qualified Map', get: (p) => p.worst_map, fmt: (v) => v || 'N/A', numeric: false },
    ];

    metricRows.forEach((rowDef) => {
      const tr = document.createElement('tr');
      const labelTd = document.createElement('td');
      labelTd.className = 'matrix-label';
      labelTd.textContent = rowDef.label;
      tr.append(labelTd);

      const vals = profiles.map((p) => rowDef.get(p));
      const numericVals = rowDef.numeric ? vals.filter((v) => v !== null && v !== undefined && !Number.isNaN(Number(v))) : [];
      const maxVal = numericVals.length ? Math.max(...numericVals.map(Number)) : null;

      vals.forEach((v) => {
        const td = document.createElement('td');
        const isWinner = rowDef.numeric && maxVal !== null && v !== null && v !== undefined && Number(v) === maxVal && numericVals.length > 1;
        if (isWinner) td.className = 'matrix-winner';
        td.textContent = rowDef.fmt(v) + (isWinner ? ' ★' : '');
        tr.append(td);
      });
      body.append(tr);
    });
  };

  let compareRequestId = 0;
  const updateComparison = async () => {
    if (selectedAgents.length < 2) {
      resultsWrap.hidden = true;
      hintEl.textContent = `Select ${2 - selectedAgents.length} more agent${selectedAgents.length === 1 ? '' : 's'} to view head-to-head comparison.`;
      return;
    }
    hintEl.textContent = `Comparing ${selectedAgents.join(' vs ')} on ${mapSelect.value === 'All' ? 'All Maps (2021–2026)' : mapSelect.value}. Click any tile to adjust.`;
    const requestId = ++compareRequestId;
    const query = new URLSearchParams();
    selectedAgents.forEach((agent) => query.append('agent', agent));
    if (mapSelect.value !== 'All') query.set('map', mapSelect.value);

    const result = await getJson(`/api/agent-comparison?${query}`);
    if (requestId !== compareRequestId) return;

    const profiles = result.profiles || [];
    const advantages = result.advantages || [];
    const pairSynergies = result.pair_synergies || [];
    const records = result.stats || [];
    resultsWrap.hidden = false;

    // 0. Head-to-Head Verdict Banner
    const verdictEl = document.getElementById('compare-verdict');
    const winCounts = {};
    advantages.forEach((a) => { winCounts[a.winner] = (winCounts[a.winner] || 0) + 1; });
    const sortedLeaders = Object.entries(winCounts).sort((a, b) => b[1] - a[1]);
    setMapBackdrop(mapSelect.value);
    const topLeader = sortedLeaders[0];
    const scopeLabel = mapSelect.value === 'All' ? 'all 13 maps (2021–2026)' : mapSelect.value;
    const highlights = advantages.map((a) => `${a.winner} leads ${a.metric} (${a.metric.includes('ACS') ? `${formatMetric(a.value)} ACS` : formatPercent(a.value)})`).join(' · ');
    verdictEl.innerHTML = `
      <div class="verdict-head">
        <div>
          <p class="kicker">HEAD-TO-HEAD VERDICT · ${scopeLabel.toUpperCase()}</p>
          <h2>${topLeader ? `${topLeader[0]} wins ${topLeader[1]}/${advantages.length} key metrics` : 'Balanced matchup'}</h2>
        </div>
        <span class="role-pill">${profiles.map((p) => p.agent).join(' vs ')}</span>
      </div>
      <p class="panel-note">${highlights}</p>
    `;

    // 1. Winner / Advantage Callout Strip
    const advWrap = document.getElementById('compare-advantages');
    advWrap.replaceChildren();
    advantages.forEach((adv) => {
      const card = document.createElement('article');
      card.className = 'advantage-card';
      const label = document.createElement('span');
      label.textContent = adv.metric.toUpperCase();
      const winner = document.createElement('strong');
      winner.className = 'agent-cell-inline';
      winner.append(createAgentAvatarElement(adv.winner, 'agent-avatar-xs'), document.createTextNode(`★ ${adv.winner}`));
      const val = document.createElement('small');
      const isAcs = adv.metric.includes('ACS');
      val.textContent = isAcs ? `${formatMetric(adv.value)} ACS` : formatPercent(adv.value);
      card.append(label, winner, val);
      advWrap.append(card);
    });

    // 2. Direct Head-to-Head Matrix
    renderHeadToHeadMatrix(profiles);

    // 3. Side-by-Side Agent Profile Cards with Official Portraits & Mini-Avatars
    const profWrap = document.getElementById('compare-profiles');
    profWrap.replaceChildren();
    profiles.forEach((prof) => {
      const card = document.createElement('article');
      card.className = 'panel compare-profile-card';
      const asset = getAgentAsset(prof.agent);
      const sent = prof.sentiment;
      const posPct = sent?.total_mentions ? sent.positive_percentage : 0;
      const neuPct = sent?.total_mentions ? sent.neutral_percentage : 0;
      const negPct = sent?.total_mentions ? sent.negative_percentage : 0;
      card.innerHTML = `
        <img class="compare-card-art" src="${asset.portrait || asset.fallback_portrait}" alt="" aria-hidden="true" onerror="this.onerror=null;this.src='${asset.fallback_portrait}'" />
        <div class="compare-profile-head">
          <div class="compare-head-id">
            <img class="agent-avatar-md" src="${asset.icon || asset.fallback_icon}" alt="${prof.agent}" onerror="this.onerror=null;this.src='${asset.fallback_icon}'" />
            <div>
              <p class="kicker agent-role-line">
                <img class="role-icon-mini" src="${asset.role_icon || asset.fallback_role_icon}" alt="" onerror="this.onerror=null;this.src='${asset.fallback_role_icon}'" />
                <span>${prof.role || 'AGENT'}</span>
              </p>
              <h3><a class="text-link" href="/agents/${encodeURIComponent(prof.agent)}">${prof.agent} ↗</a></h3>
            </div>
          </div>
          <span class="role-pill">${formatNumber(prof.appearances)} picks</span>
        </div>
        <div class="analysis-metrics">
          <div class="analysis-metric"><span>Pick Rate</span><strong>${formatPercent(prof.pick_rate)}</strong></div>
          <div class="analysis-metric"><span>Map Win Rate</span><strong>${prof.map_win_rate !== null ? formatPercent(prof.map_win_rate) : 'N/A'}</strong></div>
          <div class="analysis-metric"><span>Attack (T) ACS</span><strong>${prof.attack_acs_median !== null ? formatMetric(prof.attack_acs_median) : 'N/A'}</strong></div>
          <div class="analysis-metric"><span>Defense (CT) ACS</span><strong>${prof.defense_acs_median !== null ? formatMetric(prof.defense_acs_median) : 'N/A'}</strong></div>
          <div class="analysis-metric"><span>Best Map</span><strong>${prof.best_map || 'N/A'}</strong></div>
          <div class="analysis-metric"><span>Worst Map</span><strong>${prof.worst_map || 'N/A'}</strong></div>
        </div>
        <div class="prob-bars">
          <div class="prob-bar-row"><span>Pos</span><div class="prob-bar-track"><div class="prob-bar-fill pos" style="width:${posPct.toFixed(1)}%"></div></div><span>${posPct.toFixed(0)}%</span></div>
          <div class="prob-bar-row"><span>Neu</span><div class="prob-bar-track"><div class="prob-bar-fill neu" style="width:${neuPct.toFixed(1)}%"></div></div><span>${neuPct.toFixed(0)}%</span></div>
          <div class="prob-bar-row"><span>Neg</span><div class="prob-bar-track"><div class="prob-bar-fill neg" style="width:${negPct.toFixed(1)}%"></div></div><span>${negPct.toFixed(0)}%</span></div>
        </div>
        <p class="panel-note">Community mentions: ${formatNumber(sent?.total_mentions || 0)} (${sent?.positive_reviews || 0} pos · ${sent?.neutral_reviews || 0} neu · ${sent?.negative_reviews || 0} neg)</p>
      `;
      profWrap.append(card);
    });

    // 4. Role Synergy & Co-Pick Strip
    const synWrap = document.getElementById('compare-synergies');
    synWrap.replaceChildren();
    pairSynergies.forEach((pair) => {
      const card = document.createElement('article');
      card.className = 'analysis-card';
      const title = document.createElement('strong');
      title.textContent = `${pair.agent_a} + ${pair.agent_b} · ${pair.role_synergy}`;
      const detail = document.createElement('p');
      detail.textContent = pair.appearances > 0
        ? `Played together in ${formatNumber(pair.appearances)} maps · ${formatPercent(pair.win_rate)} co-pick win rate (Wilson 95% LB ${formatPercent(pair.win_rate_lower_bound)})`
        : `No direct co-pick maps recorded on ${result.map} yet.`;
      card.append(title, detail);
      synWrap.append(card);
    });

    // 5. Dual Visual Comparison Charts
    renderChart('compare-chart', {
      type: 'bar',
      data: {
        labels: profiles.map((p) => p.agent),
        datasets: [
          { label: 'Map Win Rate', data: profiles.map((p) => p.map_win_rate || 0), backgroundColor: '#ff4655', borderRadius: 2 },
          { label: 'Positive Sentiment', data: profiles.map((p) => (p.sentiment?.positive_percentage || 0) / 100), backgroundColor: '#4cd4a9', borderRadius: 2 },
          { label: 'Pick Rate', data: profiles.map((p) => p.pick_rate || 0), backgroundColor: '#75aaff', borderRadius: 2 },
        ],
      },
      options: barOptions(true),
    });

    renderChart('compare-acs-chart', {
      type: 'bar',
      data: {
        labels: profiles.map((p) => p.agent),
        datasets: [
          { label: 'Attack (T-Side) Median ACS', data: profiles.map((p) => p.attack_acs_median || 0), backgroundColor: '#ff4655', borderRadius: 2 },
          { label: 'Defense (CT-Side) Median ACS', data: profiles.map((p) => p.defense_acs_median || 0), backgroundColor: '#d4d0d1', borderRadius: 2 },
        ],
      },
      options: barOptions(false),
    });

    // 6. Detailed Per-Map Breakdown Table
    renderTable(document.getElementById('compare-table'), records, [
      { value: (item) => item.agent_name, link: (item) => `/agents/${encodeURIComponent(item.agent_name)}`, agentAvatar: true },
      { value: (item) => item.role || 'N/A', rolePill: true },
      { value: (item) => item.map, link: (item) => `/maps/${encodeURIComponent(item.map)}` },
      { value: (item) => formatNumber(item.appearances) },
      { value: (item) => formatPercent(item.pick_rate) },
      { value: (item) => item.resolved_maps ? formatPercent(item.map_win_rate) : 'N/A' },
      { value: (item) => item.attack_acs_samples ? formatMetric(item.attack_acs_median) : 'N/A' },
      { value: (item) => item.defense_acs_samples ? formatMetric(item.defense_acs_median) : 'N/A' },
    ]);
    document.getElementById('page-notice').hidden = true;
  };

  const syncPickerAndCompare = () => {
    renderTray();
    renderGrid();
    updateComparison().catch((error) => notify(error.message));
  };

  // Wire up Role Tabs, Live Search, Quick Matchups, Map Scope & Clear button
  roleTabsWrap.addEventListener('click', (event) => {
    const btn = event.target.closest('.role-tab');
    if (!btn) return;
    activeRole = btn.dataset.role;
    roleTabsWrap.querySelectorAll('.role-tab').forEach((el) => el.classList.toggle('active', el === btn));
    renderGrid();
  });

  searchInput.addEventListener('input', () => {
    searchQuery = searchInput.value;
    renderGrid();
  });

  document.querySelectorAll('.compare-preset').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectedAgents = btn.dataset.agents.split(',').map((s) => s.trim()).filter((n) => allNameSet.has(n));
      mapSelect.value = 'All';
      syncPickerAndCompare();
    });
  });

  document.getElementById('compare-clear-btn').addEventListener('click', () => {
    selectedAgents = [];
    syncPickerAndCompare();
  });

  mapSelect.addEventListener('change', () => updateComparison().catch((error) => notify(error.message)));
  syncPickerAndCompare();
}

async function initializeSentiment() {
  let cachedAgents = [];
  const agentSearchInput = document.getElementById('sentiment-agent-search');

  const renderAgentMentionTable = () => {
    const q = (agentSearchInput?.value || '').trim().toLowerCase();
    const filtered = q
      ? cachedAgents.filter((item) => item.agent.toLowerCase().includes(q) || String(item.role || '').toLowerCase().includes(q))
      : cachedAgents;
    renderTable(document.getElementById('sentiment-agent-table'), filtered, [
      { value: (item) => item.agent, link: (item) => `/agents/${encodeURIComponent(item.agent)}`, agentAvatar: true },
      { value: (item) => item.role || 'N/A', rolePill: true },
      { value: (item) => item.average_score !== null && item.average_score !== undefined ? `${formatMetric(item.average_score, 1)} / 10` : 'N/A' },
      { value: (item) => formatNumber(item.positive_reviews) },
      { value: (item) => formatPercent(item.positive_percentage / 100) },
      { value: (item) => formatNumber(item.neutral_reviews) },
      { value: (item) => formatPercent(item.neutral_percentage / 100) },
      { value: (item) => formatNumber(item.negative_reviews) },
      { value: (item) => formatPercent(item.negative_percentage / 100) },
      { value: (item) => formatNumber(item.total_mentions) },
    ], 'No matching agents found.');
  };

  const refreshSentimentTelemetry = async (pulse = false) => {
    const [distribution, scoreData, agentSentiment] = await Promise.all([
      getJson('/api/sentiment/distribution'),
      getJson('/api/sentiment/scores'),
      getJson('/api/sentiment/by-agent'),
    ]);

    const totalEl = document.getElementById('sent-kpi-total');
    const avgEl = document.getElementById('sent-kpi-avg');
    const posEl = document.getElementById('sent-kpi-pos');
    const posCntEl = document.getElementById('sent-kpi-pos-count');
    const liveEl = document.getElementById('sent-kpi-live');
    const rangeEl = document.getElementById('sent-kpi-range');
    if (totalEl) totalEl.textContent = formatNumber(distribution.total_reviews);
    if (avgEl) avgEl.textContent = `${formatMetric(scoreData.average_score ?? distribution.average_score, 2)} / 10`;
    if (posEl) posEl.textContent = `${formatMetric(distribution.percentages.Positive, 1)}%`;
    if (posCntEl) posCntEl.textContent = `${formatNumber(distribution.counts.Positive)} positive reviews`;
    if (liveEl) {
      const liveCnt = distribution.live_analyzed_count || 0;
      liveEl.textContent = liveCnt > 0 ? `+${formatNumber(liveCnt)} live analyzed synced` : 'June 2020 – Nov 2026 corpus';
    }
    if (rangeEl) rangeEl.textContent = distribution.date_range || '2020-06 to 2026-11';
    if (pulse && totalEl) {
      const card = totalEl.closest('.metric');
      if (card) {
        card.classList.remove('live-pulse');
        void card.offsetWidth;
        card.classList.add('live-pulse');
      }
    }

    renderSentimentChart('sentiment-chart', 'sentiment-counts', distribution);
    document.getElementById('sentiment-source-note').textContent = distribution.label_source;
    renderChart('score-distribution-chart', {
      type: 'bar',
      data: {
        labels: scoreData.score_distribution.map((item) => String(item.score)),
        datasets: [{ label: 'Reviews', data: scoreData.score_distribution.map((item) => item.count), backgroundColor: '#64b5f6', borderRadius: 2 }],
      },
      options: barOptions(),
    });
    const sentimentOrder = ['Negative', 'Neutral', 'Positive'];
    renderChart('score-sentiment-chart', {
      type: 'bar',
      data: {
        labels: sentimentOrder,
        datasets: [{ label: 'Reviews', data: sentimentOrder.map((label) => scoreData.sentiment_distribution[label].count), backgroundColor: ['#ff4655', '#eab36b', '#4cd4a9'], borderRadius: 2 }],
      },
      options: barOptions(),
    });
    renderTable(document.getElementById('score-sentiment-table'), sentimentOrder.map((label) => ({
      label,
      range: scoreData.label_mapping[label.toLowerCase()],
      ...scoreData.sentiment_distribution[label],
    })), [
      { value: (item) => item.label },
      { value: (item) => item.range },
      { value: (item) => formatNumber(item.count) },
      { value: (item) => formatPercent(item.percentage / 100) },
      { value: (item) => item.average_score === null ? 'N/A' : formatMetric(item.average_score, 2) },
    ]);
    cachedAgents = (agentSentiment.agents || []).slice().sort((a, b) => (b.total_mentions || 0) - (a.total_mentions || 0));
    renderAgentMentionTable();
    document.getElementById('agent-sentiment-note').textContent = agentSentiment.method;
  };

  if (agentSearchInput) {
    agentSearchInput.addEventListener('input', renderAgentMentionTable);
  }
  await refreshSentimentTelemetry(false);

  const form = document.getElementById('dashboard-predict-form');
  const reviewInput = document.getElementById('dashboard-review');
  const output = document.getElementById('prediction-results');
  const submitBtn = document.getElementById('analyze-submit-btn');
  const recordCheckbox = document.getElementById('record-live-checkbox');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const review = reviewInput.value.trim();
    if (!review) {
      notify('Enter a review before analyzing.');
      return;
    }
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'ANALYZING...';
    }
    try {
      const recordLive = recordCheckbox ? recordCheckbox.checked : true;
      const response = await fetch('/api/sentiment/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ review, record_live: recordLive }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Prediction failed.');
      await renderPredictionAnalysis(output, result, review);
      output.hidden = false;
      document.getElementById('page-notice').hidden = true;
      if (result.recorded_live) {
        await refreshSentimentTelemetry(true);
      }
    } catch (error) {
      notify(error.message);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'ANALYZE';
      }
    }
  });

  document.getElementById('clear-review').addEventListener('click', () => {
    reviewInput.value = '';
    output.replaceChildren();
    output.hidden = true;
  });

  const samplePresets = {
    mixed: 'Veto is amazing and super fun on Corrode, and the gunplay feels clean, but matchmaking is terrible and Hush feels broken after the latest patch.',
    negative: 'Vanguard anti-cheat crashes my system on Corrode, servers are laggy with awful hitreg, and playing against Hush in toxic AFK lobbies is frustrating.',
    positive: 'Incredible tactical FPS! Miks feels awesome and balanced on Summit, runs at smooth 240 FPS, crisp gunplay, and Gekko is really useful for team strategy.',
    neutral: 'Solid free-to-play tactical shooter with Vyse and Clove on Abyss, though skin prices are too high and solo queue matchmaking still fluctuates.',
  };
  document.querySelectorAll('.preset-chip').forEach((button) => {
    button.addEventListener('click', () => {
      const text = samplePresets[button.dataset.preset];
      if (!text) return;
      reviewInput.value = text;
      form.requestSubmit();
    });
  });

  initializeBatchAnalyzer();
}

function initializeBatchAnalyzer() {
  const batchForm = document.getElementById('batch-predict-form');
  if (!batchForm) return;
  const fileInput = document.getElementById('batch-file');
  const fileStatus = document.getElementById('batch-file-status');
  const textarea = document.getElementById('batch-textarea');
  const includeBert = document.getElementById('batch-include-distilbert');
  const runBtn = document.getElementById('run-batch-btn');
  const exportBtn = document.getElementById('batch-export-csv');
  const clearBtn = document.getElementById('batch-clear-btn');
  const resultsWrap = document.getElementById('batch-results');
  const searchInput = document.getElementById('batch-search-input');
  const filterTabs = document.getElementById('batch-sentiment-filter');
  const prevBtn = document.getElementById('batch-prev-page');
  const nextBtn = document.getElementById('batch-next-page');
  const pageInfo = document.getElementById('batch-page-info');

  let lastBatchReport = null;
  let batchSentimentFilter = 'All';
  let batchSearchQuery = '';
  let batchPage = 1;
  const PAGE_SIZE = 25;

  const updateFileStatus = () => {
    if (!fileStatus) return;
    if (fileInput.files && fileInput.files.length > 0) {
      const f = fileInput.files[0];
      fileStatus.textContent = `Selected file: ${f.name} (${(f.size / 1024).toFixed(1)} KB)`;
    } else {
      fileStatus.textContent = 'No file selected (will analyze pasted lines)';
    }
  };
  fileInput.addEventListener('change', updateFileStatus);

  const renderBatchTablePage = () => {
    if (!lastBatchReport) return;
    const q = batchSearchQuery.trim().toLowerCase();
    const filtered = (lastBatchReport.items || []).filter((item) => {
      const sentOk = batchSentimentFilter === 'All' || item.sentiment === batchSentimentFilter;
      const hay = `${item.review} ${item.sentiment} ${(item.agents || []).join(' ')} ${(item.maps || []).join(' ')} ${(item.topics || []).join(' ')}`.toLowerCase();
      return sentOk && (!q || hay.includes(q));
    });
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (batchPage > totalPages) batchPage = totalPages;
    const start = (batchPage - 1) * PAGE_SIZE;
    const slice = filtered.slice(start, start + PAGE_SIZE);

    const tbody = document.getElementById('batch-table-body');
    tbody.replaceChildren();
    if (!slice.length) {
      showEmpty(tbody, 'No batch rows match your filter.');
    } else {
      slice.forEach((item) => {
        const tr = document.createElement('tr');
        const tdIdx = document.createElement('td');
        tdIdx.textContent = String(item.index);
        const tdRev = document.createElement('td');
        tdRev.style.whiteSpace = 'normal';
        tdRev.style.maxWidth = '420px';
        tdRev.textContent = item.review;
        const tdSent = document.createElement('td');
        const pill = document.createElement('span');
        pill.className = `sentiment-pill ${String(item.sentiment || 'neutral').toLowerCase()}`;
        pill.textContent = item.sentiment;
        tdSent.append(pill);
        const tdDerived = document.createElement('td');
        tdDerived.textContent = `${formatMetric(item.derived_score, 1)} / 10`;
        const tdConf = document.createElement('td');
        tdConf.textContent = `${(Number(item.confidence ?? item.score ?? 0) * 100).toFixed(1)}%`;
        const tdAspects = document.createElement('td');
        tdAspects.style.whiteSpace = 'normal';
        const tags = [...(item.agents || []), ...(item.maps || []), ...(item.topics || [])];
        tdAspects.textContent = tags.length ? tags.join(' · ') : '—';
        tr.append(tdIdx, tdRev, tdSent, tdDerived, tdConf, tdAspects);
        tbody.append(tr);
      });
    }
    if (pageInfo) pageInfo.textContent = `Page ${batchPage} of ${totalPages} (${formatNumber(filtered.length)} rows)`;
    if (prevBtn) prevBtn.disabled = batchPage <= 1;
    if (nextBtn) nextBtn.disabled = batchPage >= totalPages;
  };

  if (searchInput) {
    searchInput.addEventListener('input', () => {
      batchSearchQuery = searchInput.value;
      batchPage = 1;
      renderBatchTablePage();
    });
  }
  if (filterTabs) {
    filterTabs.addEventListener('click', (ev) => {
      const btn = ev.target.closest('button[data-sent]');
      if (!btn) return;
      batchSentimentFilter = btn.dataset.sent;
      filterTabs.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
      batchPage = 1;
      renderBatchTablePage();
    });
  }
  if (prevBtn) prevBtn.addEventListener('click', () => { if (batchPage > 1) { batchPage -= 1; renderBatchTablePage(); } });
  if (nextBtn) nextBtn.addEventListener('click', () => { batchPage += 1; renderBatchTablePage(); });

  document.getElementById('batch-load-sample').addEventListener('click', () => {
    fileInput.value = '';
    updateFileStatus();
    textarea.value = [
      'Veto is amazing on Summit and the gunplay feels super crisp and rewarding!',
      'Vanguard anti-cheat caused crashes on Corrode and matchmaking is terrible with constant lag.',
      'Hush feels broken in tight chokes, though Abyss rotations play much better after the patch.',
      'Miks is such a fun and balanced controller on Lotus. Smooth 240 FPS performance!',
      'Decent core gameplay with Vyse and Clove, but skin prices are too high and solo queue fluctuates.',
      'Worst matchmaking experience ever on Bind, awful hit registration and toxic teammates every game.',
      'Waylay entry pace on Split is awesome when paired with Tejo and Gekko in a 5-stack!',
      'Yoru on Pearl sits in an average spot — solid in coordinated squads, tricky in solo ranked.',
    ].join('\n');
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      fileInput.value = '';
      textarea.value = '';
      updateFileStatus();
      resultsWrap.hidden = true;
      exportBtn.hidden = true;
      lastBatchReport = null;
    });
  }

  exportBtn.addEventListener('click', () => {
    if (!lastBatchReport || !lastBatchReport.items.length) return;
    const escapeCsv = (val) => `"${String(val ?? '').replace(/"/g, '""')}"`;
    const header = ['index', 'sentiment', 'derived_score_10', 'confidence', 'prob_negative', 'prob_neutral', 'prob_positive', 'agents', 'maps', 'topics', 'review'];
    const lines = [header.join(',')];
    lastBatchReport.items.forEach((item) => {
      lines.push([
        item.index,
        item.sentiment,
        item.derived_score,
        item.confidence ?? item.score,
        item.probabilities?.Negative ?? '',
        item.probabilities?.Neutral ?? '',
        item.probabilities?.Positive ?? '',
        (item.agents || []).join('; '),
        (item.maps || []).join('; '),
        (item.topics || []).join('; '),
        item.review,
      ].map(escapeCsv).join(','));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'valosent-batch-sentiment-results.csv';
    link.click();
    URL.revokeObjectURL(url);
  });

  batchForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const hasFile = fileInput.files && fileInput.files.length > 0;
    const rawLines = textarea.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (!hasFile && !rawLines.length) {
      notify('Upload a CSV/TXT file or paste at least one review line for batch analysis.');
      return;
    }
    runBtn.disabled = true;
    runBtn.textContent = 'ANALYZING BATCH...';
    try {
      let response;
      if (hasFile) {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('include_distilbert', includeBert.checked ? 'true' : 'false');
        response = await fetch('/api/sentiment/batch', { method: 'POST', body: formData });
      } else {
        response = await fetch('/api/sentiment/batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ reviews: rawLines, include_distilbert: includeBert.checked }),
        });
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Batch analysis failed.');
      lastBatchReport = data;
      batchSentimentFilter = 'All';
      batchSearchQuery = '';
      batchPage = 1;
      if (searchInput) searchInput.value = '';
      if (filterTabs) filterTabs.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.sent === 'All'));

      const metricsEl = document.getElementById('batch-metrics');
      metricsEl.innerHTML = [
        `<article class="metric"><span>ANALYZED</span><strong>${formatNumber(data.processed_count)}</strong><small>${data.models_used.join(' + ')}</small></article>`,
        `<article class="metric"><span>AVG SCORE</span><strong>${formatMetric(data.average_derived_score, 1)} / 10</strong><small>Derived 0–10 mean</small></article>`,
        `<article class="metric"><span>POSITIVE</span><strong>${data.sentiment_percentages.Positive}%</strong><small>${formatNumber(data.sentiment_counts.Positive)} reviews</small></article>`,
        `<article class="metric"><span>NEUTRAL</span><strong>${data.sentiment_percentages.Neutral}%</strong><small>${formatNumber(data.sentiment_counts.Neutral)} reviews</small></article>`,
        `<article class="metric"><span>NEGATIVE</span><strong>${data.sentiment_percentages.Negative}%</strong><small>${formatNumber(data.sentiment_counts.Negative)} reviews</small></article>`,
      ].join('');

      renderChart('batch-sentiment-chart', {
        type: 'doughnut',
        data: {
          labels: ['Negative', 'Neutral', 'Positive'],
          datasets: [{
            data: [data.sentiment_counts.Negative, data.sentiment_counts.Neutral, data.sentiment_counts.Positive],
            backgroundColor: ['#ff4655', '#eab36b', '#4cd4a9'],
            borderWidth: 0,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: 'bottom', labels: { color: '#ece8e1' } } },
        },
      });

      const hist = data.score_histogram || [];
      renderChart('batch-score-hist-chart', {
        type: 'bar',
        data: {
          labels: hist.map((h) => String(h.score)),
          datasets: [{
            label: 'Batch Reviews by Derived Score (0–10)',
            data: hist.map((h) => h.count),
            backgroundColor: hist.map((h) => h.score <= 4 ? '#ff4655' : (h.score <= 6 ? '#eab36b' : '#4cd4a9')),
            borderRadius: 2,
          }],
        },
        options: barOptions(),
      });

      const aspectsEl = document.getElementById('batch-aspects');
      aspectsEl.replaceChildren();
      const agentBreakdown = data.agent_sentiment_breakdown || [];
      if (agentBreakdown.length) {
        const card = document.createElement('article');
        card.className = 'analysis-card';
        const h = document.createElement('strong');
        h.textContent = 'DETECTED AGENTS IN BATCH';
        const chipRow = document.createElement('div');
        chipRow.className = 'composition-agents';
        agentBreakdown.forEach((a) => {
          const chip = document.createElement('span');
          chip.className = 'agent-cell-inline';
          chip.append(
            createAgentAvatarElement(a.agent, 'agent-avatar-xs'),
            document.createTextNode(`${a.agent} (${a.mentions} · avg ${formatMetric(a.avg_score, 1)}/10)`),
          );
          chipRow.append(chip);
        });
        card.append(h, chipRow);
        aspectsEl.append(card);
      }
      const buildSummaryCard = (heading, entries, formatter) => {
        const card = document.createElement('article');
        card.className = 'analysis-card';
        const h = document.createElement('strong');
        h.textContent = heading;
        const p = document.createElement('p');
        p.textContent = entries.length ? entries.map(formatter).join(' · ') : 'None detected in this batch.';
        card.append(h, p);
        return card;
      };
      aspectsEl.append(
        buildSummaryCard('TOP MENTIONED MAPS', data.top_maps, (m) => `${m.map} (${m.mentions})`),
        buildSummaryCard('TOPIC SIGNALS', data.top_topics, (t) => `${t.topic}: ${t.mentions} (${t.negative_mentions} neg)`),
      );

      renderBatchTablePage();
      exportBtn.hidden = false;
      resultsWrap.hidden = false;
      document.getElementById('page-notice').hidden = true;
    } catch (error) {
      notify(error.message);
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = 'RUN BATCH ANALYSIS';
    }
  });
}

function escapeHtmlSafe(str) {
  return String(str || '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);
}

function buildHighlightedReviewHtml(rawText, explanation) {
  let html = escapeHtmlSafe(rawText || '');
  if (!explanation || !explanation.available) return html;
  const terms = [
    ...(explanation.positive_terms || []).map((t) => ({ term: t.term, cls: 'xai-hl-pos' })),
    ...(explanation.negative_terms || []).map((t) => ({ term: t.term, cls: 'xai-hl-neg' })),
  ].sort((a, b) => b.term.length - a.term.length);
  const used = new Set();
  for (const { term, cls } of terms) {
    const cleanTerm = String(term || '').trim();
    if (!cleanTerm || cleanTerm.length < 3 || used.has(cleanTerm.toLowerCase())) continue;
    used.add(cleanTerm.toLowerCase());
    const escaped = cleanTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`\\b(${escaped})\\b`, 'gi');
    html = html.replace(regex, `<mark class="${cls}">$1</mark>`);
  }
  return html;
}

function createAnalysisSection(title) {
  const section = document.createElement('section');
  section.className = 'analysis-section';
  const heading = document.createElement('h3');
  heading.textContent = title;
  section.append(heading);
  return section;
}

function addAnalysisMetric(container, label, value) {
  const metric = document.createElement('div');
  metric.className = 'analysis-metric';
  const name = document.createElement('span');
  name.textContent = label;
  const result = document.createElement('strong');
  result.textContent = value;
  metric.append(name, result);
  container.append(metric);
}

function normalizeLookup(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

async function renderPredictionAnalysis(output, result, rawReviewText = '') {
  output.replaceChildren();
  output.classList.add('has-analysis');

  const overallLabelVal = result.overall?.label || result.ensemble?.label || 'Neutral';
  const derivedScore = result.overall?.derived_score ?? result.ensemble?.derived_score ?? 5.5;
  const confPct = result.ensemble?.confidence !== null && result.ensemble?.confidence !== undefined
    ? `${(Number(result.ensemble.confidence) * 100).toFixed(1)}%`
    : (result.ensemble?.score ? `${(Number(result.ensemble.score) * 100).toFixed(1)}%` : 'N/A');

  const hero = document.createElement('article');
  hero.className = `prediction-hero-verdict ${overallLabelVal.toLowerCase()}`;
  hero.innerHTML = `
    <div class="verdict-score-box">
      <span class="verdict-score-num">${formatMetric(derivedScore, 1)}</span>
      <span class="verdict-score-den">/ 10.0 DERIVED SCORE</span>
    </div>
    <div class="verdict-meta">
      <div class="verdict-badge-row">
        <span class="sentiment-pill ${overallLabelVal.toLowerCase()}">${overallLabelVal.toUpperCase()}</span>
        <span class="role-pill">CONFIDENCE ${confPct}</span>
        <span class="role-pill">${result.ensemble.agreement}/${result.ensemble.model_count} MODELS AGREE</span>
        ${result.recorded_live ? '<span class="role-pill" style="border-color:#4cd4a9;color:#4cd4a9;">✓ SYNCED TO LIVE 100K+ TELEMETRY</span>' : ''}
      </div>
      <small style="color:#9eaab7;">${escapeHtmlSafe(result.selected_model)} · ${result.ensemble.strategy === 'validation_macro_f1' ? 'Validation Macro-F1 weighted probability ensemble' : 'Probability ensemble'}</small>
    </div>
  `;
  output.append(hero);

  // Community Comparison Card (vs 100,000+ community averages)
  const comparisons = result.community_comparison || [];
  if (comparisons.length) {
    const compSec = createAnalysisSection('COMMUNITY COMPARISON · VS 100,000+ CORPUS');
    const compGrid = document.createElement('div');
    compGrid.className = 'community-compare-grid';
    comparisons.forEach((c) => {
      const card = document.createElement('article');
      card.className = 'community-compare-card';
      const head = document.createElement('div');
      head.className = 'verdict-badge-row';
      if (c.entity_type === 'agent') {
        head.append(createAgentAvatarElement(c.entity, 'agent-avatar-xs'));
      }
      const title = document.createElement('strong');
      title.textContent = c.entity;
      const deltaClass = c.delta > 0.3 ? 'above' : (c.delta < -0.3 ? 'below' : 'even');
      const deltaSign = c.delta >= 0 ? '+' : '';
      const deltaPill = document.createElement('span');
      deltaPill.className = `compare-delta ${deltaClass}`;
      deltaPill.textContent = `${deltaSign}${formatMetric(c.delta, 1)} vs avg`;
      head.append(title, deltaPill);

      const line = document.createElement('p');
      line.className = 'panel-note';
      line.style.margin = '0';
      line.textContent = `Your review: ${formatMetric(c.review_score, 1)}/10 · Community avg: ${formatMetric(c.community_avg_score, 1)}/10 (${formatMetric(c.positive_percentage, 1)}% pos across ${formatNumber(c.total_mentions)} reviews)`;
      card.append(head, line);
      compGrid.append(card);
    });
    compSec.append(compGrid);
    output.append(compSec);
  }

  const models = createAnalysisSection('4-MODEL ENSEMBLE BREAKDOWN');
  const modelGrid = document.createElement('div');
  modelGrid.className = 'analysis-grid';
  const predictionEntries = Object.entries({
    LinearSVC: result.svm,
    'Naive Bayes': result.naive_bayes,
    BiLSTM: result.lstm,
    DistilBERT: result.distilbert,
  });
  if (result.ensemble.model_count > 1) {
    predictionEntries.unshift([result.selected_model, result.ensemble]);
  }
  const renderProbBars = (probabilities) => {
    if (!probabilities) return null;
    const wrap = document.createElement('div');
    wrap.className = 'prob-bars';
    [
      ['Neg', probabilities.Negative, 'neg'],
      ['Neu', probabilities.Neutral, 'neu'],
      ['Pos', probabilities.Positive, 'pos'],
    ].forEach(([shortLabel, val, cls]) => {
      const pct = Math.max(0, Math.min(100, Number(val || 0) * 100));
      const row = document.createElement('div');
      row.className = 'prob-bar-row';
      row.innerHTML = `<span>${shortLabel}</span><div class="prob-bar-track"><div class="prob-bar-fill ${cls}" style="width:${pct.toFixed(1)}%"></div></div><span>${pct.toFixed(0)}%</span>`;
      wrap.append(row);
    });
    return wrap;
  };
  for (const [name, prediction] of predictionEntries) {
    if (!prediction) continue;
    const card = document.createElement('article');
    card.className = 'prediction-result';
    const label = document.createElement('span');
    label.textContent = name;
    const sentiment = document.createElement('strong');
    sentiment.textContent = prediction.label;
    if (prediction.derived_score !== null && prediction.derived_score !== undefined) {
      const sb = document.createElement('em');
      sb.className = 'model-score-badge';
      sb.style.fontStyle = 'normal';
      sb.textContent = `${formatMetric(prediction.derived_score, 1)} / 10`;
      sentiment.append(sb);
    }
    const detail = document.createElement('small');
    detail.textContent = prediction === result.ensemble
      ? `${prediction.agreement}/${prediction.model_count} model votes`
      : prediction.confidence === null || prediction.confidence === undefined
        ? 'Model score unavailable'
        : `Confidence: ${(prediction.confidence * 100).toFixed(1)}%`;
    card.append(label, sentiment, detail);
    const bars = renderProbBars(prediction.probabilities);
    if (bars) card.append(bars);
    modelGrid.append(card);
  }
  models.append(modelGrid);
  output.append(models);

  if (result.explanation && result.explanation.available) {
    const xai = createAnalysisSection('EXPLAINABLE AI · INLINE TOKEN HIGHLIGHTS');
    if (rawReviewText) {
      const hlBox = document.createElement('div');
      hlBox.className = 'xai-highlighted-review';
      hlBox.innerHTML = buildHighlightedReviewHtml(rawReviewText, result.explanation);
      xai.append(hlBox);
    }
    const xaiNote = document.createElement('p');
    xaiNote.className = 'panel-note';
    xaiNote.textContent = result.explanation.method;
    const xaiCols = document.createElement('div');
    xaiCols.className = 'xai-columns';

    const buildXaiBox = (title, terms, cls) => {
      const box = document.createElement('div');
      box.className = 'xai-box';
      const h = document.createElement('h4');
      h.textContent = title;
      const list = document.createElement('div');
      list.className = 'xai-pill-list';
      if (!terms.length) {
        const empty = document.createElement('small');
        empty.textContent = 'No strong vocabulary terms in this direction.';
        list.append(empty);
      } else {
        terms.forEach((item) => {
          const pill = document.createElement('span');
          pill.className = `xai-pill ${cls}`;
          const sign = item.impact >= 0 ? '+' : '';
          pill.textContent = `${item.term} (${sign}${item.impact.toFixed(2)})`;
          list.append(pill);
        });
      }
      box.append(h, list);
      return box;
    };

    xaiCols.append(
      buildXaiBox('POSITIVE-DRIVING TERMS', result.explanation.positive_terms, 'pos'),
      buildXaiBox('NEGATIVE-DRIVING TERMS', result.explanation.negative_terms, 'neg'),
    );
    xai.append(xaiNote, xaiCols);
    output.append(xai);
  }

  const analysis = result.analysis;
  const aspectRows = [
    ...analysis.agents.map((item) => ({ label: `Agent: ${item.agent}`, sentiment: item.sentiment })),
    ...analysis.maps.map((item) => ({ label: `Map: ${item.map}`, sentiment: item.sentiment })),
    ...Object.entries(analysis.topics)
      .filter(([, topic]) => topic.detected)
      .map(([name, topic]) => ({ label: `Topic: ${name}`, sentiment: topic.sentiment || 'No polarity' })),
  ];
  const graph = createAnalysisSection('NLP SENTIMENT GRAPH');
  const graphNote = document.createElement('p');
  graphNote.className = 'panel-note';
  graphNote.textContent = 'Polarity detected near named agents, maps, and topic keywords. This rule based aspect analysis is separate from the review sentiment models.';
  graph.append(graphNote);
  if (aspectRows.length) {
    const chartWrap = document.createElement('div');
    chartWrap.className = 'chart-wrap nlp-chart-wrap';
    const canvas = document.createElement('canvas');
    canvas.id = 'prediction-nlp-chart';
    canvas.setAttribute('aria-label', 'NLP aspect sentiment by detected agent, map, and topic');
    chartWrap.append(canvas);
    graph.append(chartWrap);
    const labels = ['Positive', 'Neutral', 'Negative', 'Mixed', 'No polarity'];
    renderChart(canvas.id, {
      type: 'bar',
      data: {
        labels: aspectRows.map((item) => item.label),
        datasets: labels.map((label, index) => ({
          label,
          data: aspectRows.map((item) => item.sentiment === label ? 1 : 0),
          backgroundColor: ['#d4d0d1', '#eab36b', '#ff4655', '#c9a5ff', '#71817f'][index],
          borderRadius: 2,
        })),
      },
      options: {
        ...barOptions(),
        indexAxis: 'y',
        scales: {
          x: { stacked: true, beginAtZero: true, max: 1, ticks: { display: false }, grid: { display: false } },
          y: { stacked: true, ticks: { color: '#c4cfcd' }, grid: { display: false } },
        },
        plugins: { ...barOptions().plugins, legend: { ...barOptions().plugins.legend, position: 'bottom' } },
      },
    });
  } else {
    graph.append(document.createTextNode('No agent, map, or topic aspects were detected in this review.'));
  }
  output.append(graph);

  const agents = createAnalysisSection('DETECTED AGENTS');
  if (!analysis.agents.length) {
    agents.append(document.createTextNode(analysis.agent_detection_message));
  }
  for (const item of analysis.agents) {
    const card = document.createElement('article');
    card.className = 'analysis-card';
    const title = document.createElement('strong');
    title.className = 'agent-cell-inline';
    title.append(createAgentAvatarElement(item.agent, 'agent-avatar-xs'), document.createTextNode(`${item.agent} · ${item.sentiment}`));
    const role = item.historical_performance?.role || 'Role unavailable';
    const details = document.createElement('p');
    details.textContent = `${role}${item.evidence.length ? ` · Evidence: ${item.evidence.join(', ')}` : ' · No polarity words found near the mention.'}`;
    card.append(title, details);
    const overallStats = item.historical_performance?.overall;
    if (overallStats) {
      const metrics = document.createElement('div');
      metrics.className = 'analysis-metrics';
      addAnalysisMetric(metrics, 'Pick rate', formatPercent(overallStats.pick_rate));
      addAnalysisMetric(metrics, 'Map win rate', overallStats.map_win_rate === null ? 'N/A' : formatPercent(overallStats.map_win_rate));
      addAnalysisMetric(metrics, 'T-side median ACS', overallStats.attack_acs_samples ? `${formatMetric(overallStats.attack_acs_median)} · n=${formatNumber(overallStats.attack_acs_samples)}` : 'N/A');
      addAnalysisMetric(metrics, 'CT-side median ACS', overallStats.defense_acs_samples ? `${formatMetric(overallStats.defense_acs_median)} · n=${formatNumber(overallStats.defense_acs_samples)}` : 'N/A');
      card.append(metrics);
    } else {
      const unavailable = document.createElement('p');
      unavailable.textContent = 'Insufficient historical performance data for this agent.';
      card.append(unavailable);
    }
    agents.append(card);
  }
  output.append(agents);

  const maps = createAnalysisSection('DETECTED MAPS');
  if (!analysis.maps.length) {
    maps.append(document.createTextNode(analysis.map_detection_message));
  }
  for (const item of analysis.maps) {
    const card = document.createElement('article');
    card.className = 'analysis-card';
    const title = document.createElement('strong');
    title.textContent = `${item.map} · ${item.sentiment}`;
    const evidence = document.createElement('p');
    evidence.textContent = item.evidence.length ? `Context evidence: ${item.evidence.join(', ')}` : 'No polarity words found near the map mention.';
    card.append(title, evidence);
    try {
      const map = await getJson(`/api/maps/${encodeURIComponent(item.map)}`);
      const details = document.createElement('p');
      details.textContent = `${formatNumber(map.map_groups)} historical map groups · ${map.data_period.start} to ${map.data_period.end}`;
      card.append(details);
      const agentRows = analysis.agents.map((agent) => map.agents.find((entry) => normalizeLookup(entry.agent_name) === normalizeLookup(agent.agent))).filter(Boolean);
      if (agentRows.length) {
        const metrics = document.createElement('div');
        metrics.className = 'analysis-metrics';
        agentRows.forEach((entry) => {
          addAnalysisMetric(metrics, `${entry.agent_name} pick rate`, formatPercent(entry.pick_rate));
          addAnalysisMetric(metrics, `${entry.agent_name} map win rate`, entry.resolved_maps ? formatPercent(entry.map_win_rate) : 'N/A');
          addAnalysisMetric(metrics, `${entry.agent_name} T-side ACS`, entry.attack_acs_samples ? `${formatMetric(entry.attack_acs_median)} · n=${formatNumber(entry.attack_acs_samples)}` : 'N/A');
          addAnalysisMetric(metrics, `${entry.agent_name} CT-side ACS`, entry.defense_acs_samples ? `${formatMetric(entry.defense_acs_median)} · n=${formatNumber(entry.defense_acs_samples)}` : 'N/A');
        });
        card.append(metrics);
      }
    } catch (error) {
      const unavailable = document.createElement('p');
      unavailable.textContent = 'Insufficient historical map data.';
      card.append(unavailable);
    }
    maps.append(card);
  }
  output.append(maps);

  const topics = createAnalysisSection('TOPIC ANALYSIS');
  const detectedTopics = Object.entries(analysis.topics).filter(([, topic]) => topic.detected);
  if (!detectedTopics.length) {
    topics.append(document.createTextNode('No supported topic keywords detected.'));
  }
  detectedTopics.forEach(([name, topic]) => {
    const card = document.createElement('article');
    card.className = 'analysis-card';
    const title = document.createElement('strong');
    title.textContent = `${name} · ${topic.sentiment || 'No polarity detected'}`;
    const evidence = document.createElement('p');
    evidence.textContent = topic.evidence.length ? `Context evidence: ${topic.evidence.join(', ')}` : topic.basis;
    card.append(title, evidence);
    topics.append(card);
  });
  const method = document.createElement('p');
  method.className = 'panel-note';
  method.textContent = analysis.aspect_method;
  topics.append(method);
  output.append(topics);
}

async function initializeModels() {
  const [evaluationResult, matchResult] = await Promise.allSettled([
    getJson('/api/model-comparison'),
    getJson('/api/match-model-results'),
  ]);
  let evaluation = evaluationResult.status === 'fulfilled' ? evaluationResult.value : null;
  const savedRows = getComparisonRows(evaluation);
  const evaluationIsAvailable = savedRows.length > 0;
  const evaluationError = evaluationResult.status === 'rejected'
    ? 'The evaluation API could not be reached or returned invalid JSON.'
    : 'The saved file has no valid comparison metrics.';
  if (!evaluationIsAvailable) {
    evaluation = {
      labels: [],
      models: Object.fromEntries(MODEL_COMPARISON_REFERENCES.map((item) => [item.name, {
        accuracy: item.accuracy / 100,
        classification_report: {},
        confusion_matrix: [],
        error_examples: [],
      }])),
    };
  }
  drawModelComparison(evaluation, { fallback: !evaluationIsAvailable, errorMessage: evaluationError });
  document.getElementById('download-model-chart-png').onclick = () => downloadModelComparison('png');
  document.getElementById('download-model-chart-svg').onclick = () => downloadModelComparison('svg');

  const models = Object.entries(evaluation.models || {}).map(([name, result]) => ({ name, ...result }))
    .sort((a, b) => (normalizeComparisonPercent(b.accuracy) ?? -1) - (normalizeComparisonPercent(a.accuracy) ?? -1));
  const labels = Array.isArray(evaluation.labels) ? evaluation.labels : [];
  renderTable(document.getElementById('models-table'), models, [
    { value: (item) => item.name },
    { value: (item) => item.accuracy === null || item.accuracy === undefined ? 'N/A' : `${normalizeComparisonPercent(item.accuracy).toFixed(1)}%` },
    { value: (item) => {
      const value = item.classification_report?.['macro avg']?.['f1-score'];
      const normalized = normalizeComparisonPercent(value);
      return normalized === null ? 'N/A' : `${normalized.toFixed(1)}%`;
    } },
    { value: (item) => {
      const value = item.classification_report?.['weighted avg']?.['f1-score'];
      const normalized = normalizeComparisonPercent(value);
      return normalized === null ? 'N/A' : `${normalized.toFixed(1)}%`;
    } },
    { value: (item) => formatMetric(item.training_time_seconds, 2) },
    { value: (item) => formatMetric(item.inference_latency_ms_per_review, 2) },
    { value: (item) => formatNumber(item.test_samples) },
  ]);
  const classRows = models.flatMap((model) => labels.map((label) => {
    const metrics = model.classification_report?.[label];
    if (!metrics) return null;
    return { model: model.name, label, ...metrics };
  }).filter(Boolean));
  renderTable(document.getElementById('per-class-table'), classRows, [
    { value: (item) => item.model },
    { value: (item) => item.label },
    { value: (item) => formatPercent(item.precision) },
    { value: (item) => formatPercent(item.recall) },
    { value: (item) => formatPercent(item['f1-score']) },
    { value: (item) => formatNumber(item.support) },
  ]);

  const errorSelect = document.getElementById('error-model-select');
  const errorContainer = document.getElementById('model-error-examples');
  setOptions(errorSelect, models.map((model) => model.name));
  const showModelErrors = () => {
    const selectedModel = models.find((model) => model.name === errorSelect.value);
    const errors = Array.isArray(selectedModel?.error_examples) ? selectedModel.error_examples : [];
    errorContainer.replaceChildren();
    const summary = document.createElement('p');
    summary.className = 'error-summary';
    summary.textContent = `${formatNumber(errors.length)} saved test errors for ${selectedModel?.name || 'this model'}.`;
    errorContainer.append(summary);
    if (!errors.length) {
      const empty = document.createElement('p');
      empty.className = 'panel-note';
      empty.textContent = 'No saved errors are available. Retrain the sentiment models to generate the error analysis.';
      errorContainer.append(empty);
      return;
    }
    errors.slice(0, 30).forEach((error) => {
      const card = document.createElement('article');
      card.className = 'error-example';
      const labels = document.createElement('strong');
      labels.textContent = `Actual: ${error.actual} · Predicted: ${error.predicted}`;
      const review = document.createElement('p');
      review.textContent = error.text;
      card.append(labels, review);
      errorContainer.append(card);
    });
  };
  errorSelect.addEventListener('change', showModelErrors);
  showModelErrors();
  const container = document.getElementById('confusion-matrices');
  container.replaceChildren();
  const modelsWithMatrices = models.filter((model) => Array.isArray(model.confusion_matrix) && model.confusion_matrix.length);
  modelsWithMatrices.forEach((model) => {
    const section = document.createElement('section');
    section.className = 'panel matrix-card';
    const heading = document.createElement('h3');
    heading.textContent = `${model.name} · Confusion matrix`;
    const grid = document.createElement('div');
    grid.className = 'matrix-grid';
    model.confusion_matrix.forEach((row, rowIndex) => row.forEach((value, columnIndex) => {
      const cell = document.createElement('div');
      cell.className = 'matrix-cell';
      const count = document.createElement('strong');
      count.textContent = formatNumber(value);
      const label = document.createElement('small');
      label.textContent = `${labels[rowIndex]} → ${labels[columnIndex]}`;
      cell.append(count, label);
      grid.append(cell);
    }));
    section.append(heading, grid);
    container.append(section);
  });
  if (!modelsWithMatrices.length) {
    const unavailable = document.createElement('p');
    unavailable.className = 'panel-note';
    unavailable.textContent = 'Confusion matrices are unavailable in the current saved evaluation.';
    container.append(unavailable);
  }

  const matchEvaluation = matchResult.status === 'fulfilled' ? matchResult.value : null;
  const matchBaseline = matchEvaluation?.baseline;
  const matchBaselineMacro = matchBaseline?.classification_report?.['macro avg'];
  const matchHasCoreMetrics = [
    matchEvaluation?.accuracy,
    matchEvaluation?.f1_macro,
    matchEvaluation?.precision_macro,
    matchEvaluation?.recall_macro,
    matchBaseline?.accuracy,
    matchBaseline?.f1_macro,
    matchBaselineMacro?.precision,
    matchBaselineMacro?.recall,
    matchBaselineMacro?.['f1-score'],
  ].every((value) => value !== null && value !== undefined && Number.isFinite(Number(value)));
  if (!matchEvaluation || !matchBaseline || !Array.isArray(matchEvaluation.confusion_matrix)
    || !Array.isArray(matchBaseline.confusion_matrix) || !matchHasCoreMetrics) {
    renderTable(document.getElementById('match-model-table'), [], []);
    document.getElementById('match-model-warning').textContent = 'Match model evaluation is unavailable. Sentiment-model results above are loaded independently.';
    document.getElementById('match-model-matrices').replaceChildren();
    return;
  }
  const matchModel = matchEvaluation;
  const baseline = matchModel.baseline;
  const matchRows = [
    {
      name: matchModel.model,
      accuracy: matchModel.accuracy,
      macroF1: matchModel.f1_macro,
      precision: matchModel.precision_macro,
      recall: matchModel.recall_macro,
      trainingMaps: matchModel.train_map_outcomes,
      testMaps: matchModel.test_map_outcomes,
    },
    {
      name: baseline.model,
      accuracy: baseline.accuracy,
      macroF1: baseline.f1_macro,
      precision: baseline.classification_report['macro avg'].precision,
      recall: baseline.classification_report['macro avg'].recall,
      trainingMaps: matchModel.train_map_outcomes,
      testMaps: matchModel.test_map_outcomes,
    },
  ];
  renderTable(document.getElementById('match-model-table'), matchRows, [
    { value: (item) => item.name },
    { value: (item) => formatPercent(item.accuracy) },
    { value: (item) => formatMetric(item.macroF1, 3) },
    { value: (item) => formatMetric(item.precision, 3) },
    { value: (item) => formatMetric(item.recall, 3) },
    { value: (item) => formatNumber(item.trainingMaps) },
    { value: (item) => formatNumber(item.testMaps) },
  ]);
  renderChart('match-model-chart', {
    type: 'bar',
    data: {
      labels: matchRows.map((item) => item.name),
      datasets: [
        { label: 'Accuracy', data: matchRows.map((item) => item.accuracy), backgroundColor: '#ff4655', borderRadius: 2 },
        { label: 'Macro F1', data: matchRows.map((item) => item.macroF1), backgroundColor: '#d4d0d1', borderRadius: 2 },
      ],
    },
    options: barOptions(true),
  });
  document.getElementById('match-model-warning').textContent =
    `Experimental: accuracy is ${(matchModel.accuracy * 100).toFixed(1)}% versus ${(baseline.accuracy * 100).toFixed(1)}% for the majority baseline; macro F1 is ${(matchModel.f1_macro * 100).toFixed(1)}% versus ${(baseline.f1_macro * 100).toFixed(1)}%. Split is grouped by reconstructed date/team pairing; event-level IDs are unavailable.`;

  const matchMatrices = document.getElementById('match-model-matrices');
  matchMatrices.replaceChildren();
  [matchModel, baseline].forEach((model) => {
    const matrix = model.confusion_matrix;
    const card = document.createElement('article');
    card.className = 'panel matrix-card';
    const heading = document.createElement('h3');
    heading.textContent = `${model.model} · Confusion matrix`;
    const grid = document.createElement('div');
    grid.className = 'matrix-grid';
    matrix.forEach((row, rowIndex) => row.forEach((value, columnIndex) => {
      const cell = document.createElement('div');
      cell.className = 'matrix-cell';
      const count = document.createElement('strong');
      count.textContent = formatNumber(value);
      const label = document.createElement('small');
      label.textContent = `${['Team 2 wins', 'Team 1 wins'][rowIndex]} → ${['Team 2 wins', 'Team 1 wins'][columnIndex]}`;
      cell.append(count, label);
      grid.append(cell);
    }));
    card.append(heading, grid);
    matchMatrices.append(card);
  });
}

async function initializeReviews() {
  const { agents } = await getJson('/api/agent-catalog');
  const agentNames = agents.map((item) => item.agent);
  const agentFilterSelect = document.getElementById('reviews-filter-agent');
  const sortSelect = document.getElementById('reviews-sort');
  const categoryTabs = document.getElementById('reviews-category-tabs');
  const feedEl = document.getElementById('reviews-feed');
  const countEl = document.getElementById('reviews-feed-count');
  const isAuthenticated = document.body.dataset.authenticated === 'true';

  setOptions(agentFilterSelect, agentNames, { all: true });
  if (agentFilterSelect.options[0]) agentFilterSelect.options[0].textContent = 'All Agents';

  let activeCategory = (document.body.dataset.mineOnly === 'true' && isAuthenticated) ? 'mine' : 'all';
  if (activeCategory === 'mine') {
    categoryTabs.querySelectorAll('.role-tab').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.category === 'mine');
    });
  }

  const updateSummary = (summary) => {
    if (!summary) return;
    document.getElementById('rev-stat-total').textContent = formatNumber(summary.total_reviews);
    document.getElementById('rev-stat-split').textContent = `${summary.website_reviews} website · ${summary.agent_reviews} agent`;
    document.getElementById('rev-stat-avg').textContent = `${formatMetric(summary.average_rating, 2)} ★`;
    document.getElementById('rev-stat-pos').textContent = `${formatMetric(summary.positive_percentage, 1)}%`;
    document.getElementById('rev-stat-sent-counts').textContent = `${summary.positive_count} pos · ${summary.neutral_count} neu · ${summary.negative_count} neg`;
    document.getElementById('rev-stat-authors').textContent = formatNumber(summary.unique_authors);
  };

  const renderStars = (rating) => '★'.repeat(rating) + '☆'.repeat(Math.max(0, 5 - rating));

  const formatDate = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  };

  const loadFeed = async () => {
    const params = new URLSearchParams();
    if (activeCategory === 'mine') {
      params.set('mine', '1');
    } else if (activeCategory !== 'all') {
      params.set('category', activeCategory);
    }
    if (agentFilterSelect.value && agentFilterSelect.value !== 'All') {
      params.set('agent', agentFilterSelect.value);
    }
    params.set('sort', sortSelect.value || 'newest');

    const data = await getJson(`/api/reviews?${params}`);
    updateSummary(data.summary);
    countEl.textContent = formatNumber(data.filtered_count);
    feedEl.replaceChildren();

    if (!data.reviews.length) {
      const empty = document.createElement('p');
      empty.className = 'panel-note';
      empty.textContent = activeCategory === 'mine'
        ? 'You have not posted any reviews yet. Use the form above to write your first review!'
        : 'No reviews match this filter yet.';
      feedEl.append(empty);
      return;
    }

    data.reviews.forEach((rev) => {
      const card = document.createElement('article');
      card.className = 'review-card';

      const head = document.createElement('div');
      head.className = 'review-card-head';

      const meta = document.createElement('div');
      meta.className = 'review-author-meta';
      if (rev.author_avatar) {
        const av = document.createElement('img');
        av.className = 'user-avatar-mini';
        av.src = rev.author_avatar;
        av.alt = rev.username;
        av.referrerPolicy = 'no-referrer';
        meta.append(av);
      }
      const authorEl = document.createElement('strong');
      authorEl.textContent = `@${rev.username}`;
      meta.append(authorEl);
      if (rev.author_verified) {
        const ver = document.createElement('span');
        ver.className = 'verified-tag';
        ver.title = 'Verified operator';
        ver.textContent = '✓';
        meta.append(ver);
      }
      if (rev.author_main_role) {
        const roleTag = document.createElement('span');
        roleTag.className = 'role-pill';
        roleTag.textContent = rev.author_favorite_agent
          ? `${rev.author_favorite_agent} · ${rev.author_main_role}`
          : rev.author_main_role;
        meta.append(roleTag);
      }
      if (rev.author_role === 'admin') {
        const badge = document.createElement('span');
        badge.className = 'admin-tag';
        badge.textContent = 'ADMIN';
        meta.append(badge);
      }
      const dateEl = document.createElement('small');
      dateEl.textContent = formatDate(rev.created_at) + (rev.updated_at ? ' (edited)' : '');
      meta.append(dateEl);

      const badges = document.createElement('div');
      badges.className = 'review-badges';
      if (rev.agent_name) {
        const targetLink = document.createElement('a');
        targetLink.className = 'target-badge agent';
        targetLink.href = `/agents/${encodeURIComponent(rev.agent_name)}`;
        targetLink.append(
          createAgentAvatarElement(rev.agent_name, ''),
          document.createTextNode(`AGENT · ${rev.agent_name} ↗`),
        );
        badges.append(targetLink);
      } else {
        const targetSpan = document.createElement('span');
        targetSpan.className = 'target-badge website';
        targetSpan.textContent = 'WEBSITE FEEDBACK';
        badges.append(targetSpan);
      }
      const sentBadge = document.createElement('span');
      sentBadge.className = `sentiment-pill ${rev.sentiment_label.toLowerCase()}`;
      sentBadge.textContent = rev.sentiment_label;
      badges.append(sentBadge);

      head.append(meta, badges);

      const starRow = document.createElement('div');
      starRow.className = 'review-stars';
      starRow.setAttribute('aria-label', `${rev.rating} out of 5 stars`);
      starRow.textContent = `${renderStars(rev.rating)}  ${rev.rating}.0 / 5`;

      const body = document.createElement('p');
      body.className = 'review-body';
      body.textContent = rev.comment;

      card.append(head, starRow, body);

      if (rev.can_edit || rev.can_delete) {
        const actions = document.createElement('div');
        actions.className = 'review-actions';

        if (rev.can_edit) {
          const editBtn = document.createElement('button');
          editBtn.type = 'button';
          editBtn.className = 'quiet-button small-btn';
          editBtn.textContent = 'EDIT';
          editBtn.addEventListener('click', () => {
            if (card.querySelector('.review-inline-edit')) return;
            const editor = document.createElement('form');
            editor.className = 'review-inline-edit';
            editor.innerHTML = `
              <div class="inline-edit-row">
                <label class="field compact-field">RATING
                  <select name="rating">${[5, 4, 3, 2, 1].map((n) => `<option value="${n}" ${n === rev.rating ? 'selected' : ''}>${n} ★</option>`).join('')}</select>
                </label>
              </div>
              <label class="field">COMMENT<textarea name="comment" rows="3" minlength="5" maxlength="2000" required></textarea></label>
              <div class="button-row">
                <button type="submit" class="primary-button small-btn">SAVE CHANGES</button>
                <button type="button" class="quiet-button small-btn cancel-edit">CANCEL</button>
              </div>
            `;
            editor.querySelector('textarea').value = rev.comment;
            editor.querySelector('.cancel-edit').addEventListener('click', () => editor.remove());
            editor.addEventListener('submit', async (ev) => {
              ev.preventDefault();
              try {
                const res = await fetch(`/api/reviews/${rev.id}`, {
                  method: 'PUT',
                  headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                  body: JSON.stringify({
                    rating: Number(editor.querySelector('select').value),
                    comment: editor.querySelector('textarea').value.trim(),
                  }),
                });
                const payload = await res.json();
                if (!res.ok) throw new Error(payload.error || 'Could not update review.');
                document.getElementById('page-notice').hidden = true;
                await loadFeed();
              } catch (err) {
                notify(err.message);
              }
            });
            card.append(editor);
          });
          actions.append(editBtn);
        }

        if (rev.can_delete) {
          const delBtn = document.createElement('button');
          delBtn.type = 'button';
          delBtn.className = 'quiet-button small-btn danger-btn';
          delBtn.textContent = 'DELETE';
          delBtn.addEventListener('click', async () => {
            try {
              const res = await fetch(`/api/reviews/${rev.id}`, { method: 'DELETE', headers: { Accept: 'application/json' } });
              const payload = await res.json();
              if (!res.ok) throw new Error(payload.error || 'Could not delete review.');
              document.getElementById('page-notice').hidden = true;
              await loadFeed();
            } catch (err) {
              notify(err.message);
            }
          });
          actions.append(delBtn);
        }

        card.append(actions);
      }

      feedEl.append(card);
    });
  };

  // Wire up compose form if authenticated
  const composeForm = document.getElementById('community-review-form');
  if (composeForm) {
    const agentSelect = document.getElementById('review-agent-select');
    const agentWrap = document.getElementById('review-agent-wrap');
    const targetToggle = document.getElementById('review-target-toggle');
    const starPicker = document.getElementById('review-star-picker');
    const starLabel = document.getElementById('review-star-label');
    const commentInput = document.getElementById('review-comment-input');
    const submitBtn = document.getElementById('submit-review-btn');
    const previewAvatar = document.getElementById('review-agent-preview-avatar');
    setOptions(agentSelect, agentNames);

    const syncReviewAgentAvatar = () => {
      if (!previewAvatar || !agentSelect.value) return;
      const asset = getAgentAsset(agentSelect.value);
      previewAvatar.hidden = false;
      previewAvatar.dataset.fallbackApplied = '';
      previewAvatar.alt = agentSelect.value;
      previewAvatar.src = asset.icon || asset.fallback_icon;
      previewAvatar.onerror = () => {
        if (previewAvatar.dataset.fallbackApplied) return;
        previewAvatar.dataset.fallbackApplied = '1';
        previewAvatar.src = asset.fallback_icon;
      };
    };
    agentSelect.addEventListener('change', syncReviewAgentAvatar);
    syncReviewAgentAvatar();

    let targetType = 'website';
    let selectedRating = 5;

    const paintStars = (val) => {
      selectedRating = val;
      starLabel.textContent = `${val} / 5`;
      starPicker.querySelectorAll('.star-btn').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.rating) <= val);
      });
    };

    starPicker.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.star-btn');
      if (!btn) return;
      paintStars(Number(btn.dataset.rating));
    });

    targetToggle.addEventListener('click', (ev) => {
      const btn = ev.target.closest('button[data-target]');
      if (!btn) return;
      targetType = btn.dataset.target;
      targetToggle.querySelectorAll('button').forEach((b) => b.classList.toggle('selected', b === btn));
      agentWrap.hidden = targetType !== 'agent';
    });

    document.getElementById('reset-review-btn').addEventListener('click', () => {
      commentInput.value = '';
      paintStars(5);
      targetType = 'website';
      targetToggle.querySelectorAll('button').forEach((b) => b.classList.toggle('selected', b.dataset.target === 'website'));
      agentWrap.hidden = true;
    });

    composeForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const comment = commentInput.value.trim();
      if (comment.length < 5) {
        notify('Please write at least 5 characters for your review.');
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = 'PUBLISHING...';
      try {
        const res = await fetch('/api/reviews', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            rating: selectedRating,
            comment,
            agent_name: targetType === 'agent' ? agentSelect.value : null,
          }),
        });
        const payload = await res.json();
        if (!res.ok) throw new Error(payload.error || 'Could not publish review.');
        commentInput.value = '';
        paintStars(5);
        document.getElementById('page-notice').hidden = true;
        await loadFeed();
      } catch (err) {
        notify(err.message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'PUBLISH REVIEW';
      }
    });
  }

  categoryTabs.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.role-tab');
    if (!btn) return;
    activeCategory = btn.dataset.category;
    categoryTabs.querySelectorAll('.role-tab').forEach((el) => el.classList.toggle('active', el === btn));
    if (activeCategory === 'website') agentFilterSelect.value = 'All';
    loadFeed().catch((err) => notify(err.message));
  });
  agentFilterSelect.addEventListener('change', () => {
    if (agentFilterSelect.value !== 'All' && activeCategory === 'website') {
      activeCategory = 'agent';
      categoryTabs.querySelectorAll('.role-tab').forEach((el) => el.classList.toggle('active', el.dataset.category === 'agent'));
    }
    loadFeed().catch((err) => notify(err.message));
  });
  sortSelect.addEventListener('change', () => loadFeed().catch((err) => notify(err.message)));

  await loadFeed();
}

async function initializeProfile() {
  const [profileData, catalogData] = await Promise.all([
    getJson('/api/profile'),
    getJson('/api/agent-catalog'),
  ]);

  const user = profileData.user || {};
  const stats = profileData.stats || {};
  const allAgents = catalogData.agents || [];

  const usernameInput = document.getElementById('profile-username-input');
  const bioInput = document.getElementById('profile-bio-input');
  const roleSelector = document.getElementById('profile-role-selector');
  const avatarGrid = document.getElementById('profile-avatar-grid');
  const avatarRoleTabs = document.getElementById('profile-avatar-role-tabs');
  const avatarSearch = document.getElementById('profile-avatar-search');
  const googleWrap = document.getElementById('profile-google-avatar-wrap');
  const googleBtn = document.getElementById('profile-google-avatar-btn');
  const googleImg = document.getElementById('profile-google-avatar-img');
  const googleCheck = document.getElementById('google-avatar-check');
  const feedbackEl = document.getElementById('profile-feedback');
  const saveStatusPill = document.getElementById('profile-save-status');
  const saveBtn = document.getElementById('profile-save-btn');
  const form = document.getElementById('profile-edit-form');

  let selectedRole = user.main_role || '';
  let selectedAgent = user.favorite_agent || '';
  let avatarMode = (user.avatar_url && user.google_avatar_url && user.avatar_url === user.google_avatar_url)
    ? 'google'
    : 'agent';
  let filterRole = 'All';
  let searchQuery = '';

  usernameInput.value = user.username || '';
  bioInput.value = user.bio || '';
  document.getElementById('profile-stat-email').textContent = user.email || '';
  document.getElementById('profile-stat-reviews').textContent = formatNumber(stats.total_reviews || 0);
  document.getElementById('profile-stat-rating').textContent = stats.average_rating ? `${formatMetric(stats.average_rating, 2)} ★` : '--';

  if (user.google_avatar_url && googleWrap && googleImg) {
    googleWrap.hidden = false;
    googleImg.src = user.google_avatar_url;
  }

  const paintRoleSelector = () => {
    roleSelector.querySelectorAll('button[data-role]').forEach((btn) => {
      btn.classList.toggle('selected', btn.dataset.role === selectedRole);
    });
  };

  const paintPreview = () => {
    const previewUser = document.getElementById('profile-preview-username');
    const previewRole = document.getElementById('profile-preview-role');
    const previewFav = document.getElementById('profile-preview-fav-agent');
    const previewBio = document.getElementById('profile-preview-bio');
    const previewAvatar = document.getElementById('profile-preview-avatar');
    const previewInitials = document.getElementById('profile-preview-initials');
    const previewRoleIcon = document.getElementById('profile-preview-role-icon');
    const heroPortrait = document.getElementById('profile-hero-portrait');
    const heroCard = document.getElementById('profile-hero-card');

    const uname = (usernameInput.value || user.username || 'Agent').trim();
    previewUser.textContent = `@${uname}`;
    previewRole.textContent = (selectedRole || 'UNASSIGNED ROLE').toUpperCase();
    previewFav.textContent = selectedAgent ? `· MAIN: ${selectedAgent.toUpperCase()}` : '';
    previewBio.textContent = (bioInput.value || '').trim() || 'Add a short tactical bio to showcase your playstyle.';

    if (selectedRole) {
      const rAsset = getRoleAsset(selectedRole);
      if (rAsset && previewRoleIcon) {
        previewRoleIcon.hidden = false;
        previewRoleIcon.src = rAsset.icon || rAsset.fallback_icon;
      }
    } else if (previewRoleIcon) {
      previewRoleIcon.hidden = true;
    }

    if (avatarMode === 'google' && user.google_avatar_url) {
      previewAvatar.hidden = false;
      previewAvatar.src = user.google_avatar_url;
      previewInitials.hidden = true;
    } else if (selectedAgent) {
      const asset = getAgentAsset(selectedAgent);
      previewAvatar.hidden = false;
      previewAvatar.dataset.fallbackApplied = '';
      previewAvatar.src = asset.icon || asset.fallback_icon;
      previewAvatar.onerror = () => {
        if (previewAvatar.dataset.fallbackApplied) return;
        previewAvatar.dataset.fallbackApplied = '1';
        previewAvatar.src = asset.fallback_icon;
      };
      previewInitials.hidden = true;
    } else if (user.avatar_url) {
      previewAvatar.hidden = false;
      previewAvatar.src = user.avatar_url;
      previewInitials.hidden = true;
    } else {
      previewAvatar.hidden = true;
      previewInitials.hidden = false;
      previewInitials.textContent = uname.slice(0, 2).toUpperCase();
    }

    if (selectedAgent && heroPortrait) {
      const asset = getAgentAsset(selectedAgent);
      heroPortrait.hidden = false;
      heroPortrait.dataset.fallbackApplied = '';
      heroPortrait.src = asset.portrait || asset.fallback_portrait;
      heroPortrait.onerror = () => {
        if (heroPortrait.dataset.fallbackApplied) return;
        heroPortrait.dataset.fallbackApplied = '1';
        heroPortrait.src = asset.fallback_portrait;
      };
      if (heroCard && asset.accent) {
        heroCard.style.setProperty('--agent-accent', `${asset.accent}55`);
      }
    } else if (heroPortrait) {
      heroPortrait.hidden = true;
    }

    if (googleBtn && googleCheck) {
      const isGoogleActive = avatarMode === 'google' && Boolean(user.google_avatar_url);
      googleBtn.classList.toggle('selected', isGoogleActive);
      googleCheck.hidden = !isGoogleActive;
    }
  };

  const renderAvatarGrid = () => {
    avatarGrid.replaceChildren();
    const q = searchQuery.trim().toLowerCase();
    const filtered = allAgents.filter((item) => {
      const roleOk = filterRole === 'All' || item.role === filterRole;
      const textOk = !q || item.agent.toLowerCase().includes(q) || String(item.role || '').toLowerCase().includes(q);
      return roleOk && textOk;
    });
    filtered.forEach((item) => {
      const isSelected = avatarMode === 'agent' && selectedAgent === item.agent;
      const tile = document.createElement('button');
      tile.type = 'button';
      const roleCls = `role-${String(item.role || '').toLowerCase()}`;
      tile.className = `agent-tile ${roleCls}${isSelected ? ' selected' : ''}`;
      tile.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
      const av = createAgentAvatarElement(item.agent, 'agent-avatar-sm');
      const info = document.createElement('div');
      info.className = 'agent-tile-info';
      info.innerHTML = `<span class="agent-tile-head"><span class="role-dot"></span><strong>${item.agent}</strong>${isSelected ? '<span class="tile-check">✓</span>' : ''}</span><small>${item.role}</small>`;
      tile.append(av, info);
      tile.addEventListener('click', () => {
        avatarMode = 'agent';
        selectedAgent = item.agent;
        if (!selectedRole && item.role) {
          selectedRole = item.role;
          paintRoleSelector();
        }
        paintPreview();
        renderAvatarGrid();
      });
      avatarGrid.append(tile);
    });
  };

  if (googleBtn) {
    googleBtn.addEventListener('click', () => {
      avatarMode = 'google';
      paintPreview();
      renderAvatarGrid();
    });
  }

  roleSelector.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-role]');
    if (!btn) return;
    selectedRole = btn.dataset.role;
    paintRoleSelector();
    paintPreview();
  });

  avatarRoleTabs.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.role-tab');
    if (!btn) return;
    filterRole = btn.dataset.role;
    avatarRoleTabs.querySelectorAll('.role-tab').forEach((b) => b.classList.toggle('active', b === btn));
    renderAvatarGrid();
  });

  avatarSearch.addEventListener('input', () => {
    searchQuery = avatarSearch.value;
    renderAvatarGrid();
  });
  usernameInput.addEventListener('input', paintPreview);
  bioInput.addEventListener('input', paintPreview);

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    saveBtn.disabled = true;
    saveBtn.textContent = 'SAVING PROFILE...';
    feedbackEl.hidden = true;
    try {
      const res = await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          username: usernameInput.value.trim(),
          main_role: selectedRole,
          favorite_agent: selectedAgent,
          avatar_mode: avatarMode,
          bio: bioInput.value.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not save profile.');
      const updated = data.user || {};
      feedbackEl.hidden = false;
      feedbackEl.className = 'otp-feedback success';
      feedbackEl.textContent = 'Profile saved! Your VALORANT callsign and avatar are now synced across the platform.';
      if (saveStatusPill) saveStatusPill.hidden = false;

      // Sync top navbar username & avatar live without requiring page reload
      const topUserEl = document.getElementById('topbar-username-text');
      if (topUserEl && updated.username) topUserEl.textContent = `@${updated.username}`;
      const badgeEl = document.getElementById('topbar-user-badge');
      if (badgeEl && updated.avatar_url) {
        let imgEl = document.getElementById('topbar-avatar-img');
        const dotEl = document.getElementById('topbar-avatar-dot');
        if (!imgEl) {
          imgEl = document.createElement('img');
          imgEl.id = 'topbar-avatar-img';
          imgEl.className = 'user-avatar-mini';
          imgEl.referrerPolicy = 'no-referrer';
          if (dotEl) dotEl.replaceWith(imgEl);
          else badgeEl.prepend(imgEl);
        }
        imgEl.src = updated.avatar_url;
        imgEl.alt = updated.username || 'Operator';
      }
      paintPreview();
    } catch (err) {
      feedbackEl.hidden = false;
      feedbackEl.className = 'otp-feedback error';
      feedbackEl.textContent = err.message;
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'SAVE AGENT PROFILE';
    }
  });

  paintRoleSelector();
  paintPreview();
  renderAvatarGrid();
}

async function initializePage() {
  try {
    await loadValorantAssets();
    if (page === 'dashboard') await initializeDashboard();
    if (page === 'maps') await initializeMaps();
    if (page === 'agents') await initializeAgents();
    if (page === 'recommend') await initializeRecommendations();
    if (page === 'compare') await initializeCompare();
    if (page === 'sentiment') {
      setMapBackdrop('Ascent');
      await initializeSentiment();
    }
    if (page === 'models') {
      setMapBackdrop('Abyss');
      await initializeModels();
    }
    if (page === 'reviews') {
      setMapBackdrop('Corrode');
      await initializeReviews();
    }
    if (page === 'profile') {
      setMapBackdrop('Summit');
      await initializeProfile();
    }
    if (page === 'about') {
      setMapBackdrop('Summit');
    }
  } catch (error) {
    notify(error.message || 'Unable to load this view.');
    console.error(error);
  }
}

document.addEventListener('DOMContentLoaded', initializePage);
