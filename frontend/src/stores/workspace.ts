/**
 * Which workspace is active, and which documents are scoped into a question.
 *
 * The active workspace is persisted so a reload returns the user where they
 * were rather than to an arbitrary first workspace.
 */

import { create } from 'zustand'

const ACTIVE_WORKSPACE_KEY = 'avocado.active_workspace'

interface WorkspaceState {
  activeWorkspaceId: string | null
  /** Empty means "search the whole workspace". */
  scopedDocumentIds: string[]
  setActiveWorkspace: (id: string | null) => void
  toggleScopedDocument: (id: string) => void
  clearScopedDocuments: () => void
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  activeWorkspaceId: localStorage.getItem(ACTIVE_WORKSPACE_KEY),
  scopedDocumentIds: [],

  setActiveWorkspace: (id) => {
    if (id) localStorage.setItem(ACTIVE_WORKSPACE_KEY, id)
    else localStorage.removeItem(ACTIVE_WORKSPACE_KEY)
    // Switching workspace must drop the scope: those document ids belong to
    // the workspace being left.
    set({ activeWorkspaceId: id, scopedDocumentIds: [] })
  },

  toggleScopedDocument: (id) =>
    set((state) => ({
      scopedDocumentIds: state.scopedDocumentIds.includes(id)
        ? state.scopedDocumentIds.filter((existing) => existing !== id)
        : [...state.scopedDocumentIds, id],
    })),

  clearScopedDocuments: () => set({ scopedDocumentIds: [] }),
}))
