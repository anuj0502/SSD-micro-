import axios from 'axios';

// Same-origin /api: Vite proxies to the collector during development and the
// collector serves the built dashboard in a container deployment.
export const http = axios.create({ baseURL: '/api', timeout: 60000 });

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const payload = error.response?.data;
    const detail = payload?.detail ?? payload?.error ?? error.message;
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg || d.detail || JSON.stringify(d)).join(', ')
          : JSON.stringify(detail);
    const wrapped = new Error(message || 'Request failed');
    wrapped.status = error.response?.status;
    return Promise.reject(wrapped);
  }
);

const get = (url, params) => http.get(url, { params }).then((r) => r.data);
const post = (url, body, params) => http.post(url, body ?? {}, { params }).then((r) => r.data);
const put = (url, body) => http.put(url, body).then((r) => r.data);

export const api = {
  // system
  health: () => get('/health'),

  // dashboard
  overview: (range) => get('/dashboard/overview', { range }),
  timeseries: (range, buckets = 24) => get('/dashboard/timeseries', { range, buckets }),

  // traces
  traces: (params) => get('/traces', params),
  trace: (traceId) => get(`/traces/${encodeURIComponent(traceId)}`),

  // services
  services: (range) => get('/services', { range }),
  service: (name, range) => get(`/services/${encodeURIComponent(name)}`, { range }),

  // pipeline
  pipeline: () => get('/pipeline/stats'),
  telemetryStats: () => get('/telemetry/stats'),

  // sampling
  samplingConfig: () => get('/sampling/config'),
  updateSamplingConfig: (config) => put('/sampling/config', config),
  samplingStats: () => get('/sampling/stats'),
  resetSamplingStats: () => post('/sampling/reset-stats'),

  // batches
  batches: (params) => get('/batches', params),
  batch: (batchId) => get(`/batches/${encodeURIComponent(batchId)}`),
  batchConfig: () => get('/batches/config'),
  updateBatchConfig: (config) => put('/batches/config', config),
  flushBatches: () => post('/batches/flush'),
  retryBatch: (batchId) => post(`/batches/${encodeURIComponent(batchId)}/retry`),

  // storage
  storageStats: () => get('/storage/stats'),
  objects: (prefix = 'data/batches/') => get('/storage/objects', { prefix, limit: 100 }),
  inspectObject: (key) => get('/storage/objects/inspect', { key }),

  // events
  events: (params) => get('/events', params),
  eventCategories: () => get('/events/categories'),

  // faults
  faultScenarios: () => get('/faults/scenarios'),
  triggerFault: (scenario, options) => post(`/faults/${encodeURIComponent(scenario)}`, options || {}),
  faultRuns: (params) => get('/faults/runs', params),
  faultRun: (runId) => get(`/faults/runs/${encodeURIComponent(runId)}`),

  // bounded Render application scenarios (local infra scenarios remain unchanged)
  renderFaultScenarios: () => get('/faults/render/scenarios'),
  renderFaultRuns: () => get('/faults/render/runs'),
  triggerRenderFault: (scenario) => post(`/faults/render/${encodeURIComponent(scenario)}`),

  // benchmarks
  runBenchmark: (config) => post('/benchmarks/run', { config }),
  benchmarkResults: (limit = 20) => get('/benchmarks/results', { limit }),
  benchmarkResult: (runId) => get(`/benchmarks/results/${encodeURIComponent(runId)}`),

  // traffic
  generateTraffic: (payload) => post('/telemetry/traffic', payload),
};

export default api;
