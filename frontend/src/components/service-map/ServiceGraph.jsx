import { useMemo } from 'react';
import ReactFlow, { Background, Controls, Handle, MarkerType, Position } from 'reactflow';
import 'reactflow/dist/style.css';

import { formatMs, formatNumber, formatPercent, statusStyle } from '../../utils/format';

const EDGE_COLORS = { healthy: '#10b981', warning: '#f97316', error: '#ec4899' };

function ServiceNode({ data }) {
  const service = data.service;
  const tone = statusStyle(service.health);
  return (
    <div
      className={`w-[200px] rounded-widget border bg-white px-4 py-3.5 shadow-card transition-all duration-300 hover:shadow-lift ${
        data.selected ? 'border-primary ring-2 ring-primary/15' : 'border-line'
      }`}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-slate-300" />
      <div className="flex items-center justify-between gap-2">
        <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
        <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ${tone.soft}`}>
          {tone.label}
        </span>
      </div>
      <p className="mt-2 truncate text-[12.5px] font-extrabold text-ink">{service.service}</p>
      <div className="mt-2.5 grid grid-cols-2 gap-1.5">
        <div>
          <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Requests</p>
          <p className="text-[12px] font-bold text-ink">{formatNumber(service.requests)}</p>
        </div>
        <div>
          <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Errors</p>
          <p className={`text-[12px] font-bold ${service.error_rate > 2 ? 'text-danger' : 'text-ink'}`}>
            {formatPercent(service.error_rate)}
          </p>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between border-t border-line pt-2">
        <span className="text-[9.5px] font-medium text-muted">Avg latency</span>
        <span className="text-[10.5px] font-bold text-ink">{formatMs(service.avg_latency_ms)}</span>
      </div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-primary" />
    </div>
  );
}

const nodeTypes = { serviceNode: ServiceNode };

function computeLayout(services, edges) {
  const depth = new Map(services.map((service) => [service.service, 0]));
  const names = new Set(services.map((service) => service.service));
  const usable = edges.filter((edge) => names.has(edge.source) && names.has(edge.target));
  for (let iteration = 0; iteration < services.length + 1; iteration += 1) {
    for (const edge of usable) {
      const candidate = (depth.get(edge.source) || 0) + 1;
      if (candidate > (depth.get(edge.target) || 0) && candidate <= services.length) {
        depth.set(edge.target, candidate);
      }
    }
  }
  const grouped = new Map();
  services.forEach((service) => {
    const level = depth.get(service.service) || 0;
    if (!grouped.has(level)) grouped.set(level, []);
    grouped.get(level).push(service);
  });
  const positions = new Map();
  [...grouped.entries()]
    .sort((a, b) => a[0] - b[0])
    .forEach(([level, list]) => {
      list.forEach((service, index) => {
        positions.set(service.service, {
          x: 60 + level * 290,
          y: 40 + (index - (list.length - 1) / 2) * 170 + 180,
        });
      });
    });
  return positions;
}

export default function ServiceGraph({ services = [], edges = [], selected, onSelect }) {
  const { nodes, flowEdges } = useMemo(() => {
    const positions = computeLayout(services, edges);
    const nodes = services.map((service) => ({
      id: service.service,
      type: 'serviceNode',
      position: positions.get(service.service) || { x: 60, y: 120 },
      data: { service, selected: selected === service.service },
      draggable: true,
    }));
    const flowEdges = edges
      .filter((edge) => edge.source !== edge.target)
      .map((edge) => {
        const color = EDGE_COLORS[edge.health] || '#94a3b8';
        return {
          id: `${edge.source}-${edge.target}`,
          source: edge.source,
          target: edge.target,
          type: 'smoothstep',
          animated: edge.health === 'error',
          label: `${formatNumber(edge.calls)} calls`,
          labelStyle: { fontSize: 9, fontWeight: 700, fill: '#64748b' },
          labelBgStyle: { fill: '#ffffff', fillOpacity: 0.9 },
          labelBgPadding: [5, 3],
          labelBgBorderRadius: 6,
          style: { stroke: color, strokeWidth: Math.min(5, 1.2 + Math.log10(edge.calls + 1) * 1.8) },
          markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
        };
      });
    return { nodes, flowEdges };
  }, [services, edges, selected]);

  if (!services.length) return null;

  return (
    <div className="h-[520px] w-full overflow-hidden rounded-widget border border-line bg-canvas/40">
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelect?.(node.id)}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        minZoom={0.4}
        maxZoom={1.4}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#e2e8f0" gap={22} size={1} />
        <Controls showInteractive={false} className="!rounded-lg !border !border-line !shadow-card" />
      </ReactFlow>
    </div>
  );
}
