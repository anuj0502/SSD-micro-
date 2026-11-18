import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import Sidebar from './Sidebar';
import Topbar from './Topbar';
import RightSidebar from './RightSidebar';

export default function AppShell() {
  const [navOpen, setNavOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const location = useLocation();

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenNav={() => setNavOpen(true)} onOpenActivity={() => setActivityOpen(true)} />

        <div className="flex min-h-0 flex-1">
          <main className="panel-scroll min-w-0 flex-1 overflow-y-auto px-4 pb-12 pt-5 sm:px-6 lg:px-7">
            <div key={location.pathname} className="mx-auto w-full max-w-[1240px] animate-fade-up">
              <Outlet />
            </div>
          </main>
          <RightSidebar />
        </div>
      </div>

      {activityOpen ? (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-[2px] xl:hidden">
          <button
            type="button"
            aria-label="Close activity panel"
            className="absolute inset-0"
            onClick={() => setActivityOpen(false)}
          />
          <div className="relative h-full animate-fade-up shadow-lift">
            <RightSidebar drawer onClose={() => setActivityOpen(false)} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
