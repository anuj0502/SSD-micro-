import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Network, RefreshCw, Server, Share2, Waypoints } from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import ServiceGraph from '../components/service-map/ServiceGraph';
import TraceTable from '../components/trace/TraceTable';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/Feedback';
import { useApp } from '../contexts/AppContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import { formatMs, formatNumber, formatPercent, timeAgo } from '../utils/format';

function EdgeRow({ edge, direction }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-canvas px-2.5 py-1.5">
      <span className="min-w-0 truncate text-[10.5px] font-semibold text-ink">
        {direction === 'in' ? edge.source : edge.target}
      </span>
      <span className="flex shrink-0 items-center gap-2 text-[9.5px] font-medium text-muted">
        {formatNumber(edge.calls)} calls
        <span className={edge.error_rate >= 2 ? 'font-bold text-danger' : 'font-bold text-success'}>
          {formatPercent(edge.error_rate)}
        </span>
      </span>
    </div>
  );
}

export default function ServiceMap() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { range, refreshTick } = useApp();
  const query = useApi(() => api.services(range), [range, refreshTick], { interval: 10000 });

  const services = query.data?.services || [];
  const edges = query.data?.edges || [];
  const selected = searchParams.get('service') || services[0]?.service || null;

  const detailQuery = useApi(() => api.service(selected, range), [selected, range], {
    interval: 10000,
    enabled: Boolean(selected),
  });
  const detail = detailQuery.data;

  useEffect(() => {
    if (!searchParams.get('service') && services.length) {
      setSearchParams({ service: services[0].service }, { replace: true });
    }
  }, [services, searchParams, setSearchParams]);

  const selectService = (name) => setSearchParams({ service: name }, { replace: true });

  return (
    <>
      <PageHeading
        eyebrow="Topology"
        title="Service Map"
        subtitle="Dependencies reconstructed from parent-child span relationships."
        actions={
          <Button variant="secondary" size="sm" icon={RefreshCw} onClick={query.refresh}>
            Refresh graph
          </Button>
        }
      />

      {query.loading && !query.data ? (
        <div className="grid gap-4 xl:grid-cols-3">
          <Skeleton className="h-[560px] rounded-card xl:col-span-2" />
          <Skeleton className="h-[560px] rounded-card" />
        </div>
      ) : query.error ? (
        <ErrorState message={query.error} onRetry={query.refresh} />
      ) : services.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            title="No service relationships observed yet"
            description="The graph is generated from real spans. Run a benchmark or send traffic through the gateway to populate it."
            action={
              <Button size="sm" icon={Waypoints} onClick={() => navigate('/benchmarks')}>
                Run a benchmark
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-3">
          <Card className="p-5 xl:col-span-2">
            <CardHeader
              title="Observed dependency graph"
              subtitle={`${services.length} services · ${edges.length} directional edges in the ${range} window`}
              icon={Network}
              action={
                <div className="hidden items-center gap-3 sm:flex">
                  {[
                    { label: 'Healthy', color: 'bg-success' },
                    { label: 'Warning', color: 'bg-accent' },
                    { label: 'Errors', color: 'bg-danger' },
                  ].map((legend) => (
                    <span key={legend.label} className="inline-flex items-center gap-1.5 text-[9.5px] font-semibold text-muted">
                      <span className={`h-1.5 w-4 rounded-full ${legend.color}`} /> {legend.label}
                    </span>
                  ))}
                </div>
              }
            />
            <div className="mt-4">
              <ServiceGraph services={services} edges={edges} selected={selected} onSelect={selectService} />
            </div>
            <p className="mt-3 flex items-center gap-1.5 text-[10px] font-medium text-muted">
              <Share2 size={11} /> Edge thickness scales with call volume; direction follows the parent span.
            </p>
          </Card>

          <div className="space-y-4">
            <Card className="p-5">
              <CardHeader
                title="Service detail"
                subtitle={selected ? `Observed metrics for ${selected}` : 'Select a node in the graph.'}
                icon={Server}
                action={detail ? <Badge status={detail.health} /> : null}
              />
              {detailQuery.loading && !detail ? (
                <Skeleton className="mt-4 h-40 w-full" />
              ) : detailQuery.error ? (
                <div className="mt-4">
                  <ErrorState compact message={detailQuery.error} onRetry={detailQuery.refresh} />
                </div>
              ) : detail ? (
                <>
                  <div className="mt-4 grid grid-cols-3 gap-2">
                    {[
                      { label: 'Requests', value: formatNumber(detail.requests) },
                      { label: 'Errors', value: formatPercent(detail.error_rate) },
                      { label: 'Latency', value: formatMs(detail.avg_latency_ms) },
                    ].map((item) => (
                      <div key={item.label} className="rounded-xl bg-canvas px-3 py-2.5">
                        <p className="text-[9px] font-bold uppercase tracking-wider text-muted">{item.label}</p>
                        <p className="mt-0.5 text-[14px] font-extrabold text-ink">{item.value}</p>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex items-center justify-between text-[10px] font-medium text-muted">
                    <span>Spans {formatNumber(detail.spans)}</span>
                    <span>Last seen {timeAgo(detail.last_seen)}</span>
                  </div>

                  <div className="mt-4">
                    <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted">Top operations</p>
                    {(detail.operations || []).length ? (
                      <div className="space-y-1">
                        {detail.operations.slice(0, 5).map((operation) => (
                          <div key={operation.operation} className="flex items-center justify-between gap-2">
                            <span className="truncate text-[10.5px] font-medium text-ink">{operation.operation}</span>
                            <span className="shrink-0 text-[9.5px] font-semibold text-muted">
                              {formatNumber(operation.requests)} · {formatMs(operation.avg_latency_ms)}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[10.5px] font-medium text-slate-400">No operations indexed.</p>
                    )}
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <div>
                      <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted">Inbound</p>
                      <div className="space-y-1">
                        {(detail.inbound_edges || []).length ? (
                          detail.inbound_edges.map((edge) => (
                            <EdgeRow key={`in-${edge.source}`} edge={edge} direction="in" />
                          ))
                        ) : (
                          <p className="text-[10px] font-medium text-slate-400">Entry point</p>
                        )}
                      </div>
                    </div>
                    <div>
                      <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted">Outbound</p>
                      <div className="space-y-1">
                        {(detail.outbound_edges || []).length ? (
                          detail.outbound_edges.map((edge) => (
                            <EdgeRow key={`out-${edge.target}`} edge={edge} direction="out" />
                          ))
                        ) : (
                          <p className="text-[10px] font-medium text-slate-400">Leaf service</p>
                        )}
                      </div>
                    </div>
                  </div>
                </>
              ) : null}
            </Card>
          </div>
        </div>
      )}

      {services.length ? (
        <div className="mt-4 grid gap-4 xl:grid-cols-3">
          <Card className="p-5 xl:col-span-2">
            <CardHeader
              title="Recent traces"
              subtitle={selected ? `Traces involving ${selected}` : 'Select a service'}
              icon={Waypoints}
              action={
                <button
                  type="button"
                  onClick={() => navigate(`/traces?q=${encodeURIComponent(selected || '')}`)}
                  className="inline-flex items-center gap-1 text-[10.5px] font-bold text-primary hover:text-blue-700"
                >
                  Explore <ArrowRight size={11} />
                </button>
              }
            />
            <div className="mt-3">
              <TraceTable
                traces={detail?.recent_traces || []}
                loading={detailQuery.loading}
                error={detailQuery.error}
                compact
                emptyTitle="No recent traces"
                emptyDescription="This service has no indexed traces in the selected window."
              />
            </div>
          </Card>

          <Card className="p-5">
            <CardHeader title="All services" subtitle="Ranked by request volume." icon={Server} />
            <div className="mt-3 space-y-1.5">
              {services.map((service) => (
                <button
                  key={service.service}
                  type="button"
                  onClick={() => selectService(service.service)}
                  className={`flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-left transition-colors ${
                    selected === service.service ? 'bg-blue-50 text-primary' : 'hover:bg-slate-50'
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[11.5px] font-bold text-ink">{service.service}</span>
                    <span className="block text-[9.5px] font-medium text-muted">
                      {formatNumber(service.requests)} requests · {formatMs(service.avg_latency_ms)}
                    </span>
                  </span>
                  <span className={`h-2 w-2 shrink-0 rounded-full ${service.health === 'healthy' ? 'bg-success' : service.health === 'warning' ? 'bg-accent' : 'bg-danger'}`} />
                </button>
              ))}
            </div>
          </Card>
        </div>
      ) : null}
    </>
  );
}
