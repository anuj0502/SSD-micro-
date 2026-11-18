import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Filter, RefreshCw, Search, X } from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import { EmptyState, ErrorState, SkeletonRows } from '../components/ui/Feedback';
import { Field, Input, Select } from '../components/ui/Fields';
import { useApp } from '../contexts/AppContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import { formatMs, formatNumber, formatTime, shortId } from '../utils/format';

const EMPTY_FILTERS = {
  traceId: '',
  service: '',
  operation: '',
  status: '',
  minDuration: '',
  sort: 'start_time',
  order: 'desc',
};

const PAGE_SIZE = 15;

export default function TraceExplorer() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { range, services: servicesPayload } = useApp();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);

  // The global search bar navigates here with ?q=; map it to the best filter.
  useEffect(() => {
    const q = searchParams.get('q');
    if (!q) return;
    const isTraceId = /^[0-9a-f]{8,64}$/i.test(q.trim());
    const next = {
      ...EMPTY_FILTERS,
      ...(isTraceId ? { traceId: q.trim() } : { operation: q.trim() }),
    };
    setFilters(next);
    setApplied(next);
    setPage(1);
  }, [searchParams]);

  const query = useApi(
    () =>
      api.traces({
        page,
        page_size: PAGE_SIZE,
        range,
        sort: applied.sort,
        order: applied.order,
        ...(applied.traceId ? { trace_id: applied.traceId } : {}),
        ...(applied.service ? { service: applied.service } : {}),
        ...(applied.operation ? { operation: applied.operation } : {}),
        ...(applied.status ? { status: applied.status } : {}),
        ...(applied.minDuration ? { min_duration_ms: Number(applied.minDuration) } : {}),
      }),
    [applied, page, range]
  );

  const services = servicesPayload?.services || [];
  const data = query.data;
  const totalPages = data?.pages || 1;

  const apply = (event) => {
    event?.preventDefault?.();
    setApplied(filters);
    setPage(1);
  };

  const reset = () => {
    setFilters(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setPage(1);
  };

  const activeFilters = Object.entries(applied).filter(
    ([key, value]) => value && !['sort', 'order'].includes(key)
  );

  return (
    <>
      <PageHeading
        eyebrow="Investigate"
        title="Trace Explorer"
        subtitle="Search indexed trace metadata, then open the complete stored trace."
        actions={
          <Button variant="secondary" size="sm" icon={RefreshCw} onClick={query.refresh}>
            Refresh results
          </Button>
        }
      />

      <Card className="p-5">
        <CardHeader
          title="Search filters"
          subtitle="Metadata is queried in PostgreSQL; span bodies are fetched from object storage on open."
          icon={Filter}
          action={
            activeFilters.length ? (
              <button
                type="button"
                onClick={reset}
                className="inline-flex items-center gap-1 text-[10.5px] font-bold text-muted hover:text-ink"
              >
                <X size={11} /> Clear all
              </button>
            ) : null
          }
        />
        <form onSubmit={apply} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <Field label="Trace ID" className="xl:col-span-2">
            <Input
              value={filters.traceId}
              onChange={(event) => setFilters({ ...filters, traceId: event.target.value })}
              placeholder="e.g. 1a2b3c4d…"
              className="font-mono text-[11.5px]"
            />
          </Field>
          <Field label="Service">
            <Select
              value={filters.service}
              onChange={(event) => setFilters({ ...filters, service: event.target.value })}
            >
              <option value="">All services</option>
              {services.map((service) => (
                <option key={service.service} value={service.service}>
                  {service.service}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Operation">
            <Input
              value={filters.operation}
              onChange={(event) => setFilters({ ...filters, operation: event.target.value })}
              placeholder="POST /checkout"
            />
          </Field>
          <Field label="Status">
            <Select
              value={filters.status}
              onChange={(event) => setFilters({ ...filters, status: event.target.value })}
            >
              <option value="">Any status</option>
              <option value="success">Success</option>
              <option value="error">Error</option>
              <option value="slow">Slow</option>
            </Select>
          </Field>
          <Field label="Min duration (ms)">
            <Input
              type="number"
              min="0"
              value={filters.minDuration}
              onChange={(event) => setFilters({ ...filters, minDuration: event.target.value })}
              placeholder="500"
            />
          </Field>
          <Field label="Sort by">
            <Select value={filters.sort} onChange={(event) => setFilters({ ...filters, sort: event.target.value })}>
              <option value="start_time">Start time</option>
              <option value="duration">Duration</option>
              <option value="span_count">Span count</option>
            </Select>
          </Field>
          <Field label="Order">
            <Select value={filters.order} onChange={(event) => setFilters({ ...filters, order: event.target.value })}>
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </Select>
          </Field>
          <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-1">
            <Button type="submit" icon={Search} className="w-full">
              Search
            </Button>
          </div>
        </form>
      </Card>

      <Card className="mt-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-[16px] font-bold text-ink">Results</h3>
            <p className="mt-0.5 text-[11.5px] font-medium text-muted">
              {data ? `${formatNumber(data.total)} traces match in the ${range} window` : 'Querying trace index…'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((value) => Math.max(1, value - 1))}
              disabled={page <= 1}
              className="focus-ring grid h-8 w-8 place-items-center rounded-btn border border-line bg-white text-muted transition-colors hover:text-ink disabled:opacity-40"
              aria-label="Previous page"
            >
              <ChevronLeft size={15} />
            </button>
            <span className="text-[11px] font-semibold text-muted">
              Page {page} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
              disabled={page >= totalPages}
              className="focus-ring grid h-8 w-8 place-items-center rounded-btn border border-line bg-white text-muted transition-colors hover:text-ink disabled:opacity-40"
              aria-label="Next page"
            >
              <ChevronRight size={15} />
            </button>
          </div>
        </div>

        <div className="mt-3">
          {query.loading && !data ? (
            <SkeletonRows rows={6} />
          ) : query.error ? (
            <ErrorState message={query.error} onRetry={query.refresh} />
          ) : !data?.items?.length ? (
            <EmptyState
              title="No traces match these filters"
              description="Broaden the time range or clear filters. New telemetry appears here as soon as it is indexed."
              action={
                <Button variant="secondary" size="sm" onClick={reset}>
                  Reset filters
                </Button>
              }
            />
          ) : (
            <div className="-mx-1 overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head pb-2.5 pl-2 pr-3 text-left">Trace ID</th>
                    <th className="table-head pb-2.5 pr-3 text-left">Root service</th>
                    <th className="table-head pb-2.5 pr-3 text-left">Operations</th>
                    <th className="table-head pb-2.5 pr-3 text-right">Spans</th>
                    <th className="table-head pb-2.5 pr-3 text-right">Duration</th>
                    <th className="table-head pb-2.5 pr-3 text-left">Status</th>
                    <th className="table-head pb-2.5 pr-3 text-left">Decision</th>
                    <th className="table-head pb-2.5 pr-2 text-right">Start time</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((trace) => (
                    <tr
                      key={trace.trace_id}
                      onClick={() => navigate(`/traces/${trace.trace_id}`)}
                      className="cursor-pointer border-t border-line transition-colors hover:bg-slate-50/80"
                    >
                      <td className="py-3 pl-2 pr-3 font-mono text-[11px] font-semibold text-ink">
                        {shortId(trace.trace_id, 14, 4)}
                      </td>
                      <td className="py-3 pr-3 text-[11.5px] font-semibold text-ink">{trace.root_service}</td>
                      <td className="max-w-[200px] truncate py-3 pr-3 text-[11px] font-medium text-muted">
                        {trace.root_operation}
                      </td>
                      <td className="py-3 pr-3 text-right text-[11px] font-semibold text-ink">
                        {formatNumber(trace.span_count)}
                      </td>
                      <td
                        className={`py-3 pr-3 text-right text-[11.5px] font-bold ${
                          trace.status === 'slow' ? 'text-accent' : 'text-ink'
                        }`}
                      >
                        {formatMs(trace.duration_ms)}
                      </td>
                      <td className="py-3 pr-3">
                        <Badge status={trace.status} />
                      </td>
                      <td className="py-3 pr-3">
                        <span
                          className={`rounded-full px-2 py-1 text-[10px] font-semibold ${
                            trace.sampled ? 'bg-emerald-50 text-success' : 'bg-slate-100 text-muted'
                          }`}
                        >
                          {trace.sampled ? trace.decision_reason || 'retained' : 'discarded'}
                        </span>
                      </td>
                      <td className="py-3 pr-2 text-right text-[10.5px] font-medium text-muted">
                        {formatTime(trace.start_time)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </>
  );
}
