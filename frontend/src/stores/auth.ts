/**
 * Authentication state.
 *
 * Zustand holds UI/session state; React Query owns server data. The token
 * itself lives in localStorage (see `tokenStore`) so a reload does not log the
 * user out — this store mirrors it for rendering decisions.
 */

import { create } from 'zustand'
import { tokenStore } from '@/api/client'
import type { CurrentUser } from '@/api/types'

interface AuthState {
  user: CurrentUser | null
  isAuthenticated: boolean
  /** True until the initial `/auth/me` settles, so routes don't flash. */
  isLoading: boolean
  setUser: (user: CurrentUser | null) => void
  setLoading: (loading: boolean) => void
  signOut: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: Boolean(tokenStore.access),
  isLoading: Boolean(tokenStore.access),

  setUser: (user) => set({ user, isAuthenticated: user !== null, isLoading: false }),
  setLoading: (isLoading) => set({ isLoading }),
  signOut: () => {
    tokenStore.clear()
    set({ user: null, isAuthenticated: false, isLoading: false })
  },
}))
