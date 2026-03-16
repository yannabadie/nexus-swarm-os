/**
 * NEXUS CEREBRO FileCommander
 * V12.1 RETINA: File Browser + Monaco Editor
 *
 * Split-pane layout with recursive file tree and code editor.
 * Integrates with /api/files/tree, /api/files/content, /api/files/save
 *
 * V12.1 Improvements (Conseiller 2 feedback):
 * - Mobile responsive layout (stacked on mobile, side-by-side on desktop)
 */
import { useState, useEffect, useCallback } from 'react';
import Editor from '@monaco-editor/react';
import {
  Folder,
  File,
  ChevronRight,
  ChevronDown,
  Save,
  RefreshCw,
  FileCode,
  AlertCircle,
} from 'lucide-react';
import { api } from '../../api/client';

// =============================================================================
// Types
// =============================================================================

interface TreeNode {
  name: string;
  type: 'file' | 'directory';
  path: string;
  children?: TreeNode[];
}

interface FileContent {
  path: string;
  content: string;
  size: number;
}

// =============================================================================
// File Type Detection
// =============================================================================

function getLanguage(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  const languageMap: Record<string, string> = {
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    py: 'python',
    json: 'json',
    md: 'markdown',
    css: 'css',
    html: 'html',
    yaml: 'yaml',
    yml: 'yaml',
    toml: 'toml',
    sh: 'shell',
    bash: 'shell',
    sql: 'sql',
    rs: 'rust',
    go: 'go',
    java: 'java',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
  };
  return languageMap[ext] || 'plaintext';
}

function getFileIcon(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  const iconMap: Record<string, string> = {
    py: 'text-yellow-400',
    ts: 'text-blue-400',
    tsx: 'text-blue-400',
    js: 'text-yellow-300',
    jsx: 'text-yellow-300',
    json: 'text-green-400',
    md: 'text-gray-400',
    css: 'text-pink-400',
    html: 'text-orange-400',
  };
  return iconMap[ext] || 'text-gray-400';
}

// =============================================================================
// Tree Item Component
// =============================================================================

interface TreeItemProps {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  expandedPaths: Set<string>;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
}

function TreeItem({
  node,
  depth,
  selectedPath,
  expandedPaths,
  onSelect,
  onToggle,
}: TreeItemProps) {
  const isExpanded = expandedPaths.has(node.path);
  const isSelected = selectedPath === node.path;
  const isDir = node.type === 'directory';

  const handleClick = () => {
    if (isDir) {
      onToggle(node.path);
    } else {
      onSelect(node.path);
    }
  };

  return (
    <div>
      <div
        onClick={handleClick}
        className={`
          flex items-center gap-1.5 px-2 py-1 cursor-pointer
          hover:bg-gray-700/50 transition-colors text-sm
          ${isSelected ? 'bg-cyan-900/30 text-cyan-300' : 'text-gray-300'}
        `}
        style={{ paddingLeft: depth * 12 + 8 }}
      >
        {/* Expand/collapse chevron */}
        {isDir ? (
          isExpanded ? (
            <ChevronDown size={14} className="text-gray-500 flex-shrink-0" />
          ) : (
            <ChevronRight size={14} className="text-gray-500 flex-shrink-0" />
          )
        ) : (
          <span className="w-3.5" /> // Spacer for alignment
        )}

        {/* Icon */}
        {isDir ? (
          <Folder
            size={14}
            className={`flex-shrink-0 ${isExpanded ? 'text-yellow-400' : 'text-yellow-600'}`}
          />
        ) : (
          <File size={14} className={`flex-shrink-0 ${getFileIcon(node.name)}`} />
        )}

        {/* Name */}
        <span className="truncate">{node.name}</span>
      </div>

      {/* Children */}
      {isDir && isExpanded && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeItem
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              expandedPaths={expandedPaths}
              onSelect={onSelect}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export function FileCommander() {
  // Tree state
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [treeLoading, setTreeLoading] = useState(true);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set(['.']));

  // Editor state
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [content, setContent] = useState<string>('');
  const [originalContent, setOriginalContent] = useState<string>('');
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const isDirty = content !== originalContent;

  // ---------------------------------------------------------------------------
  // Load Tree
  // ---------------------------------------------------------------------------

  const loadTree = useCallback(async () => {
    setTreeLoading(true);
    setTreeError(null);

    try {
      const data = await api.get<TreeNode>('/api/files/tree?path=.&max_depth=4');
      setTree(data);
    } catch (error) {
      console.error('[FileCommander] Failed to load tree:', error);
      setTreeError(error instanceof Error ? error.message : 'Failed to load file tree');
    } finally {
      setTreeLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  // ---------------------------------------------------------------------------
  // Load File Content
  // ---------------------------------------------------------------------------

  const loadFile = useCallback(async (path: string) => {
    setFileLoading(true);
    setFileError(null);

    try {
      const data = await api.get<FileContent>(
        `/api/files/content?path=${encodeURIComponent(path)}`
      );
      setContent(data.content);
      setOriginalContent(data.content);
      setSelectedPath(path);
    } catch (error) {
      console.error('[FileCommander] Failed to load file:', error);
      setFileError(error instanceof Error ? error.message : 'Failed to load file');
    } finally {
      setFileLoading(false);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Save File
  // ---------------------------------------------------------------------------

  const saveFile = useCallback(async () => {
    if (!selectedPath || !isDirty) return;

    setSaving(true);
    try {
      await api.post('/api/files/save', {
        path: selectedPath,
        content: content,
      });
      setOriginalContent(content);
    } catch (error) {
      console.error('[FileCommander] Failed to save file:', error);
      setFileError(error instanceof Error ? error.message : 'Failed to save file');
    } finally {
      setSaving(false);
    }
  }, [selectedPath, content, isDirty]);

  // ---------------------------------------------------------------------------
  // Keyboard Shortcuts
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        saveFile();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [saveFile]);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleToggle = (path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col md:flex-row h-full bg-gray-900 rounded-lg border border-gray-700 overflow-hidden">
      {/* Tree Panel - V12.1: Responsive (full width on mobile, 256px on desktop) */}
      <div className="w-full md:w-64 h-48 md:h-full flex-shrink-0 border-b md:border-b-0 md:border-r border-gray-700 flex flex-col bg-gray-800/50">
        {/* Tree Header */}
        <div className="px-3 py-2 border-b border-gray-700 flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Files
          </span>
          <button
            onClick={loadTree}
            disabled={treeLoading}
            className="p-1 hover:bg-gray-700 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw
              size={12}
              className={`text-gray-400 ${treeLoading ? 'animate-spin' : ''}`}
            />
          </button>
        </div>

        {/* Tree Content */}
        <div className="flex-1 overflow-y-auto py-1">
          {treeLoading && !tree && (
            <div className="flex items-center gap-2 px-4 py-8 text-gray-500 text-sm">
              <RefreshCw size={14} className="animate-spin" />
              Loading...
            </div>
          )}

          {treeError && (
            <div className="px-4 py-4 text-red-400 text-sm">
              <AlertCircle size={14} className="inline mr-1" />
              {treeError}
            </div>
          )}

          {tree && (
            <TreeItem
              node={tree}
              depth={0}
              selectedPath={selectedPath}
              expandedPaths={expandedPaths}
              onSelect={loadFile}
              onToggle={handleToggle}
            />
          )}
        </div>
      </div>

      {/* Editor Panel */}
      <div className="flex-1 flex flex-col">
        {/* Editor Header */}
        <div className="px-3 py-2 border-b border-gray-700 flex items-center justify-between bg-gray-800/50">
          <div className="flex items-center gap-2 min-w-0">
            <FileCode size={14} className="text-gray-400 flex-shrink-0" />
            <span className="text-sm text-gray-300 truncate">
              {selectedPath || 'No file selected'}
            </span>
            {isDirty && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-600/20 text-yellow-400">
                Modified
              </span>
            )}
          </div>

          {selectedPath && (
            <button
              onClick={saveFile}
              disabled={!isDirty || saving}
              className={`
                flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium
                transition-colors
                ${
                  isDirty
                    ? 'bg-green-600 hover:bg-green-700 text-white'
                    : 'bg-gray-700 text-gray-500 cursor-not-allowed'
                }
              `}
            >
              <Save size={12} />
              {saving ? 'Saving...' : 'Save'}
              <span className="text-[10px] opacity-70">(Ctrl+S)</span>
            </button>
          )}
        </div>

        {/* Editor Content */}
        <div className="flex-1 relative">
          {fileLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80 z-10">
              <div className="flex items-center gap-2 text-gray-400">
                <RefreshCw size={16} className="animate-spin" />
                Loading file...
              </div>
            </div>
          )}

          {fileError && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center text-red-400">
                <AlertCircle size={24} className="mx-auto mb-2" />
                <p>{fileError}</p>
              </div>
            </div>
          )}

          {!selectedPath && !fileLoading && (
            <div className="absolute inset-0 flex items-center justify-center text-gray-500">
              <div className="text-center">
                <FileCode size={48} className="mx-auto mb-3 opacity-30" />
                <p>Select a file to edit</p>
              </div>
            </div>
          )}

          {selectedPath && !fileLoading && (
            <Editor
              height="100%"
              theme="vs-dark"
              language={getLanguage(selectedPath)}
              value={content}
              onChange={(value) => setContent(value || '')}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                lineNumbers: 'on',
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                padding: { top: 8, bottom: 8 },
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
