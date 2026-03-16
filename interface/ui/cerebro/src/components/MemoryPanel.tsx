/**
 * NEXUS V13.0 MEMORIA UNIVERSALIS - Memory Panel Component
 *
 * Displays RAG memory stats, namespaces, and file upload.
 * Features:
 * - Project and Agent RAG statistics
 * - Namespace selector
 * - Drag & drop file upload
 * - Create/Delete namespace
 */
import { useState, useEffect, useCallback, DragEvent } from 'react';
import { api } from '../api/client';
import {
  Brain,
  Database,
  Upload,
  Trash2,
  Plus,
  RefreshCw,
  FolderOpen,
  FileText,
  AlertCircle,
  CheckCircle,
} from 'lucide-react';

// =============================================================================
// Types
// =============================================================================

interface NamespaceInfo {
  name: string;
  type: 'project' | 'agent';
  path: string;
  created_at: string;
  chunks_count: number;
  files_count: number;
  metadata?: Record<string, unknown>;
}

interface MemoryStats {
  namespace_count: number;
  project_namespace: number;
  agent_namespaces: number;
  total_chunks: number;
  total_files: number;
  namespaces: NamespaceInfo[];
}

// =============================================================================
// Component
// =============================================================================

export function MemoryPanel() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [selectedNamespace, setSelectedNamespace] = useState<string>('project');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newNamespaceName, setNewNamespaceName] = useState('');

  // Fetch stats
  const fetchStats = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<MemoryStats>('/api/memory/stats');
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch stats');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  // Handle file upload
  const handleFileUpload = async (files: FileList) => {
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      for (const file of Array.from(files)) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('namespace', selectedNamespace);

        const response = await fetch('/api/memory/ingest', {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${localStorage.getItem('nexus_token') || ''}`,
          },
          body: formData,
        });

        if (!response.ok) {
          const err = await response.json();
          throw new Error(err.detail || 'Upload failed');
        }

        const result = await response.json();
        setSuccess(`Ingested ${file.name}: ${result.chunks_created} chunks`);
      }
      fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setLoading(false);
    }
  };

  // Drag & drop handlers
  const handleDragEnter = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files);
    }
  };

  // Create namespace
  const handleCreateNamespace = async () => {
    if (!newNamespaceName.trim()) return;

    setLoading(true);
    setError(null);
    try {
      await api.post('/api/memory/namespaces', { name: newNamespaceName.trim() });
      setSuccess(`Created namespace: ${newNamespaceName}`);
      setNewNamespaceName('');
      setShowCreateModal(false);
      fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create namespace');
    } finally {
      setLoading(false);
    }
  };

  // Delete namespace
  const handleDeleteNamespace = async (name: string) => {
    if (name === 'project') return;
    if (!confirm(`Delete namespace "${name}"? This cannot be undone.`)) return;

    setLoading(true);
    setError(null);
    try {
      await api.delete(`/api/memory/namespaces/${name}`);
      setSuccess(`Deleted namespace: ${name}`);
      if (selectedNamespace === name) {
        setSelectedNamespace('project');
      }
      fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete namespace');
    } finally {
      setLoading(false);
    }
  };

  // Get current namespace info
  const currentNamespace = stats?.namespaces.find((ns) => ns.name === selectedNamespace);

  return (
    <div className="bg-nexus-dark rounded-lg border border-gray-700 flex flex-col">
      {/* Header */}
      <div className="flex justify-between items-center px-4 py-3 border-b border-gray-700">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Brain className="w-5 h-5 text-primary" />
          Project Memory
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchStats}
            disabled={loading}
            className="p-1.5 text-gray-400 hover:text-white transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="p-1.5 text-gray-400 hover:text-white transition-colors"
            title="Create Agent RAG"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Alerts */}
      {error && (
        <div className="mx-4 mt-3 p-2 bg-red-900/30 border border-red-700 rounded flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}
      {success && (
        <div className="mx-4 mt-3 p-2 bg-green-900/30 border border-green-700 rounded flex items-center gap-2 text-green-400 text-sm">
          <CheckCircle className="w-4 h-4" />
          {success}
        </div>
      )}

      {/* Namespace Selector */}
      <div className="px-4 py-3 border-b border-gray-700">
        <label className="block text-sm text-gray-400 mb-1">Namespace</label>
        <div className="flex gap-2">
          <select
            value={selectedNamespace}
            onChange={(e) => setSelectedNamespace(e.target.value)}
            className="flex-1 bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-white text-sm focus:outline-none focus:border-primary"
          >
            {stats?.namespaces.map((ns) => (
              <option key={ns.name} value={ns.name}>
                {ns.name} ({ns.type}) - {ns.chunks_count} chunks
              </option>
            ))}
          </select>
          {selectedNamespace !== 'project' && (
            <button
              onClick={() => handleDeleteNamespace(selectedNamespace)}
              className="p-1.5 text-red-400 hover:text-red-300 transition-colors"
              title="Delete namespace"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="px-4 py-3 grid grid-cols-2 gap-3">
        <div className="bg-gray-800/50 rounded p-3">
          <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
            <FileText className="w-3.5 h-3.5" />
            Files Indexed
          </div>
          <div className="text-xl font-semibold text-white">
            {currentNamespace?.files_count ?? 0}
          </div>
        </div>
        <div className="bg-gray-800/50 rounded p-3">
          <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
            <Database className="w-3.5 h-3.5" />
            Chunks
          </div>
          <div className="text-xl font-semibold text-white">
            {currentNamespace?.chunks_count ?? 0}
          </div>
        </div>
      </div>

      {/* Total Stats */}
      {stats && (
        <div className="px-4 pb-2">
          <div className="text-xs text-gray-500">
            Total: {stats.namespace_count} namespaces | {stats.total_chunks.toLocaleString()} chunks | {stats.total_files} files
          </div>
        </div>
      )}

      {/* Drop Zone */}
      <div
        className={`mx-4 mb-4 border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
          isDragging
            ? 'border-primary bg-primary/10'
            : 'border-gray-600 hover:border-gray-500'
        }`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <Upload className={`w-8 h-8 mx-auto mb-2 ${isDragging ? 'text-primary' : 'text-gray-500'}`} />
        <p className="text-sm text-gray-400 mb-2">
          Drag & drop files to ingest
        </p>
        <p className="text-xs text-gray-500 mb-3">
          PDF, DOCX, images, code files supported
        </p>
        <label className="cursor-pointer">
          <span className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded transition-colors">
            <FolderOpen className="w-4 h-4 inline-block mr-1" />
            Browse Files
          </span>
          <input
            type="file"
            className="hidden"
            multiple
            onChange={(e) => e.target.files && handleFileUpload(e.target.files)}
          />
        </label>
      </div>

      {/* Create Namespace Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-nexus-dark border border-gray-700 rounded-lg p-6 w-80">
            <h3 className="text-lg font-semibold text-white mb-4">Create Agent RAG</h3>
            <input
              type="text"
              value={newNamespaceName}
              onChange={(e) => setNewNamespaceName(e.target.value)}
              placeholder="Namespace name"
              className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white mb-4 focus:outline-none focus:border-primary"
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateNamespace}
                disabled={!newNamespaceName.trim() || loading}
                className="px-4 py-2 bg-primary hover:bg-primary/80 text-white rounded transition-colors disabled:opacity-50"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
