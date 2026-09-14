import { createContext, useContext } from "react";

export type StudioNodeActions = {
  /** Open Field Mapper overlay immediately (single-click chrome button). */
  openMapper: (nodeId: string) => void;
  /** Double-click activate: mapper overlay, join inspector, or inspector focus. */
  activateNode: (nodeId: string, componentType: string) => void;
};

export const StudioNodeActionsContext = createContext<StudioNodeActions | null>(null);

export function useStudioNodeActions(): StudioNodeActions | null {
  return useContext(StudioNodeActionsContext);
}
