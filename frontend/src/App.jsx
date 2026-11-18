import { Route, Routes, useNavigate } from 'react-router-dom';

import AppShell from './components/layout/AppShell';
import PageHeading from './components/layout/PageHeading';
import Button from './components/ui/Button';
import { AppProvider } from './contexts/AppContext';
import { ToastProvider } from './contexts/ToastContext';
import Overview from './pages/Overview';
import LiveTraces from './pages/LiveTraces';
import TraceExplorer from './pages/TraceExplorer';
import TraceDetails from './pages/TraceDetails';
import ServiceMap from './pages/ServiceMap';
import Pipeline from './pages/Pipeline';
import Sampling from './pages/Sampling';
import Storage from './pages/Storage';
import FaultInjection from './pages/FaultInjection';
import Benchmarks from './pages/Benchmarks';
import RealDemo from './pages/RealDemo';

function NotFound() {
  const navigate = useNavigate();
  return (
    <>
      <PageHeading eyebrow="404" title="Page not found" subtitle="That route does not exist in TraceFlow." />
      <Button onClick={() => navigate('/')}>Back to overview</Button>
    </>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AppProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Overview />} />
            <Route path="live" element={<LiveTraces />} />
            <Route path="traces" element={<TraceExplorer />} />
            <Route path="traces/:traceId" element={<TraceDetails />} />
            <Route path="services" element={<ServiceMap />} />
            <Route path="pipeline" element={<Pipeline />} />
            <Route path="sampling" element={<Sampling />} />
            <Route path="storage" element={<Storage />} />
            <Route path="faults" element={<FaultInjection />} />
            <Route path="benchmarks" element={<Benchmarks />} />
            <Route path="real-demo" element={<RealDemo />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AppProvider>
    </ToastProvider>
  );
}
