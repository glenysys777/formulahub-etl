import { useEffect, useMemo, useState } from "react";
import type { Pipeline } from "./api";

export const DEFAULT_WORKSPACE_FOLDERS = [
  "Pipelines/My pipelines",
  "Pipelines/Demos",
  "Masters",
  "Reusable",
] as const;

export const DEFAULT_MY_PIPELINES = "Pipelines/My pipelines";

export type WorkspaceState = {
  folders: string[];
  pipelineFolders: Record<string, string>;
};

type TreeNode = {
  name: string;
  path: string;
  children: TreeNode[];
  pipelines: Pipeline[];
};

function folderForPipeline(
  p: Pipeline,
  pipelineFolders: Record<string, string>,
): string {
  const meta = p.metadata?.workspace_folder;
  if (typeof meta === "string" && meta.trim()) return meta.trim().replace(/\\/g, "/");
  return pipelineFolders[p.id] || DEFAULT_MY_PIPELINES;
}

function buildTree(
  folders: string[],
  pipelines: Pipeline[],
  pipelineFolders: Record<string, string>,
): TreeNode {
  const root: TreeNode = { name: "Workspace", path: "", children: [], pipelines: [] };
  const byPath = new Map<string, TreeNode>([["", root]]);

  const ensure = (folderPath: string): TreeNode => {
    const parts = folderPath.split("/").filter(Boolean);
    let cur = root;
    let acc = "";
    for (const part of parts) {
      acc = acc ? `${acc}/${part}` : part;
      let next = byPath.get(acc);
      if (!next) {
        next = { name: part, path: acc, children: [], pipelines: [] };
        cur.children.push(next);
        byPath.set(acc, next);
      }
      cur = next;
    }
    return cur;
  };

  for (const f of folders) {
    if (f.trim()) ensure(f.trim());
  }

  for (const p of pipelines) {
    ensure(folderForPipeline(p, pipelineFolders)).pipelines.push(p);
  }

  const folderRank = (name: string) => {
    if (name === "My pipelines") return 0;
    if (name === "Demos") return 1;
    return 2;
  };

  const sortNode = (n: TreeNode) => {
    n.children.sort((a, b) => {
      const ra = folderRank(a.name);
      const rb = folderRank(b.name);
      if (ra !== rb) return ra - rb;
      return a.name.localeCompare(b.name);
    });
    n.pipelines.sort((a, b) => a.name.localeCompare(b.name));
    n.children.forEach(sortNode);
  };
  sortNode(root);
  return root;
}

function pathContains(parent: string, child: string): boolean {
  if (!parent) return true;
  return child === parent || child.startsWith(`${parent}/`);
}

function branchHasActive(node: TreeNode, activeId: string | null): boolean {
  if (!activeId) return false;
  if (node.pipelines.some((p) => p.id === activeId)) return true;
  return node.children.some((c) => branchHasActive(c, activeId));
}

type Props = {
  workspace: WorkspaceState | null;
  pipelines: Pipeline[];
  activePipelineId: string | null;
  selectedFolder: string;
  busy?: boolean;
  onSelectFolder: (folder: string) => void;
  onOpenPipeline: (id: string) => void;
  onNewPipeline: () => void;
  onMovePipeline?: (pipelineId: string, folder: string) => void;
  onRefresh?: () => void;
};

function FolderBranch({
  node,
  depth,
  activePipelineId,
  selectedFolder,
  busy,
  folders,
  onSelectFolder,
  onOpenPipeline,
  onMovePipeline,
}: {
  node: TreeNode;
  depth: number;
  activePipelineId: string | null;
  selectedFolder: string;
  busy?: boolean;
  folders: string[];
  onSelectFolder: (folder: string) => void;
  onOpenPipeline: (id: string) => void;
  onMovePipeline?: (pipelineId: string, folder: string) => void;
}) {
  const shouldReveal =
    depth < 1 ||
    pathContains(node.path, selectedFolder) ||
    branchHasActive(node, activePipelineId);

  const [open, setOpen] = useState(shouldReveal);

  useEffect(() => {
    if (shouldReveal) setOpen(true);
  }, [shouldReveal]);

  return (
    <div className="ws-branch" style={{ ["--ws-depth" as string]: depth }}>
      {node.path !== "" && (
        <div
          className={`ws-folder${selectedFolder === node.path ? " is-selected" : ""}`}
          data-testid={`workspace-folder-${node.path}`}
        >
          <button
            type="button"
            className="ws-chevron-btn"
            aria-label={open ? "Collapse folder" : "Expand folder"}
            aria-expanded={open}
            disabled={busy}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "▾" : "▸"}
          </button>
          <button
            type="button"
            className="ws-folder-main"
            disabled={busy}
            title={node.path}
            onClick={() => {
              onSelectFolder(node.path);
              setOpen(true);
            }}
          >
            <span className="ws-folder-label">
              {node.name}
              {node.name === "Reusable" ? (
                <span className="ws-folder-hint"> · Child pipelines</span>
              ) : null}
            </span>
          </button>
        </div>
      )}
      {open && (
        <div className="ws-children">
          {node.children.map((child) => (
            <FolderBranch
              key={child.path}
              node={child}
              depth={depth + 1}
              activePipelineId={activePipelineId}
              selectedFolder={selectedFolder}
              busy={busy}
              folders={folders}
              onSelectFolder={onSelectFolder}
              onOpenPipeline={onOpenPipeline}
              onMovePipeline={onMovePipeline}
            />
          ))}
          {node.pipelines.map((p) => (
            <div key={p.id} className="ws-pipeline-row">
              <button
                type="button"
                className={`ws-pipeline${activePipelineId === p.id ? " is-active" : ""}`}
                data-testid={`workspace-pipeline-${p.id}`}
                disabled={busy}
                onClick={() => onOpenPipeline(p.id)}
                title={`${p.name}\n${p.id}`}
                ref={(el) => {
                  if (el && activePipelineId === p.id) {
                    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
                  }
                }}
              >
                <span className="ws-pipeline-icon" aria-hidden>
                  ▢
                </span>
                <span className="ws-pipeline-name">{p.name || p.id}</span>
              </button>
              {onMovePipeline && folders.length > 0 && (
                <label className="ws-move" title="Move to folder">
                  <span className="sr-only">Move to</span>
                  <select
                    data-testid={`workspace-move-${p.id}`}
                    disabled={busy}
                    value={node.path}
                    onChange={(e) => {
                      const next = e.target.value;
                      if (next && next !== node.path) onMovePipeline(p.id, next);
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {folders.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function WorkspacePanel({
  workspace,
  pipelines,
  activePipelineId,
  selectedFolder,
  busy,
  onSelectFolder,
  onOpenPipeline,
  onNewPipeline,
  onMovePipeline,
  onRefresh,
}: Props) {
  const folders = workspace?.folders?.length
    ? workspace.folders
    : [...DEFAULT_WORKSPACE_FOLDERS];
  const pipelineFolders = workspace?.pipelineFolders || {};

  const tree = useMemo(
    () => buildTree(folders, pipelines, pipelineFolders),
    [folders, pipelines, pipelineFolders],
  );

  return (
    <aside className="workspace-panel" data-testid="workspace-panel" aria-label="Workspace">
      <div className="workspace-header">
        <h3>Workspace</h3>
        <div className="workspace-header-actions">
          {onRefresh && (
            <button
              type="button"
              className="btn ws-icon-btn"
              data-testid="workspace-refresh"
              disabled={busy}
              title="Refresh Workspace"
              onClick={onRefresh}
            >
              ↻
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary ws-new-btn"
            data-testid="workspace-new-pipeline"
            disabled={busy}
            title={`Create blank pipeline in ${selectedFolder || DEFAULT_MY_PIPELINES}`}
            onClick={onNewPipeline}
          >
            New
          </button>
        </div>
      </div>
      <p className="workspace-hint">
        Pipelines · Masters · Reusable — click to open
      </p>
      <div className="workspace-tree" data-testid="workspace-tree">
        {tree.children.map((child) => (
          <FolderBranch
            key={child.path}
            node={child}
            depth={0}
            activePipelineId={activePipelineId}
            selectedFolder={selectedFolder}
            busy={busy}
            folders={folders}
            onSelectFolder={onSelectFolder}
            onOpenPipeline={onOpenPipeline}
            onMovePipeline={onMovePipeline}
          />
        ))}
        {!pipelines.length && (
          <p className="empty-hint">No pipelines yet — create one with New.</p>
        )}
      </div>
    </aside>
  );
}
