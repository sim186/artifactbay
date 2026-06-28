import {
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { RootLayout } from './components/RootLayout'
import { ArtifactPage } from './routes/ArtifactPage'
import { CollectionPage } from './routes/CollectionPage'
import { Dashboard } from './routes/Dashboard'
import { SessionPage } from './routes/SessionPage'
import { Settings } from './routes/Settings'

const rootRoute = createRootRoute({ component: RootLayout })

export interface DashboardSearch {
  agent?: string
  favorite?: boolean
  tag?: string
  q?: string
}

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: Dashboard,
  validateSearch: (s: Record<string, unknown>): DashboardSearch => ({
    agent: typeof s.agent === 'string' ? s.agent : undefined,
    favorite: s.favorite === true || s.favorite === 'true' ? true : undefined,
    tag: typeof s.tag === 'string' ? s.tag : undefined,
    q: typeof s.q === 'string' ? s.q : undefined,
  }),
})

const sessionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/s/$sessionId',
  component: SessionPage,
  validateSearch: (s: Record<string, unknown>): { t?: string } => ({
    t: typeof s.t === 'string' ? s.t : undefined,
  }),
})

const artifactRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/a/$artifactId',
  component: ArtifactPage,
})

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: Settings,
})

const collectionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/c/$collectionId',
  component: CollectionPage,
})

const routeTree = rootRoute.addChildren([
  indexRoute, sessionRoute, artifactRoute, settingsRoute, collectionRoute,
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
