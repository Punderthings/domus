import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  type RouterHistory,
} from '@tanstack/react-router';
import { AppLayout } from './components/AppLayout';
import { NotFound } from './components/States';
import { AreaPage } from './pages/AreaPage';
import { BackupsPage } from './pages/BackupsPage';
import { DeviceEditPage, DeviceNewPage } from './pages/DeviceFormPage';
import { DevicePage } from './pages/DevicePage';
import { DevicesPage } from './pages/DevicesPage';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { SetupPage } from './pages/SetupPage';

const rootRoute = createRootRoute({ component: Outlet, notFoundComponent: NotFound });

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
});
const setupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/setup',
  component: SetupPage,
});

// Everything below requires a signed-in user; AppLayout redirects otherwise.
const appRoute = createRoute({ getParentRoute: () => rootRoute, id: 'app', component: AppLayout });

const overviewRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/',
  component: OverviewPage,
});

const areaRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/areas/$areaId',
  component: AreaPage,
});

export interface DevicesSearch {
  q?: string;
  area?: string;
}

const devicesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/devices',
  component: DevicesPage,
  validateSearch: (search: Record<string, unknown>): DevicesSearch => ({
    q: typeof search.q === 'string' && search.q ? search.q : undefined,
    area: typeof search.area === 'string' && search.area ? search.area : undefined,
  }),
});

const deviceRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/devices/$deviceId',
  component: DevicePage,
});

const deviceNewRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/devices/new',
  component: DeviceNewPage,
});

const deviceEditRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/devices/$deviceId/edit',
  component: DeviceEditPage,
});

const backupsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/admin/backups',
  component: BackupsPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  setupRoute,
  appRoute.addChildren([
    overviewRoute,
    areaRoute,
    devicesRoute,
    deviceNewRoute,
    deviceRoute,
    deviceEditRoute,
    backupsRoute,
  ]),
]);

export function createAppRouter(history: RouterHistory) {
  return createRouter({ routeTree, history, defaultPreload: 'intent' });
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}

export { areaRoute, deviceRoute, devicesRoute };
