// Collections = saved queries (dynamic groupings), not folders. See master spec §5.4.
// Each links to the dashboard with search params; Dashboard applies them.
import type { DashboardSearch } from '../router'

export interface Collection {
  id: string
  label: string
  search: DashboardSearch
}

// Static collections. (Tag collections are derived from live data in the sidebar.)
export const STATIC_COLLECTIONS: Collection[] = [
  { id: 'all', label: 'All sessions', search: {} },
  { id: 'favorites', label: 'Favorites', search: { favorite: true } },
]
