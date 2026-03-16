/**
 * NEXUS CEREBRO API Client
 * V11.6.2 IRONCLAD: Automatic JWT header injection
 */

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

interface ApiError extends Error {
  status: number;
  detail?: string;
}

class ApiClient {
  private tokenGetter: (() => string | null) | null = null;

  /**
   * Set the token getter function (called by App.tsx after AuthProvider mount)
   */
  setTokenGetter(fn: () => string | null): void {
    this.tokenGetter = fn;
  }

  /**
   * Make an authenticated API request
   */
  async request<T>(
    endpoint: string,
    method: HttpMethod = 'GET',
    body?: unknown
  ): Promise<T> {
    const token = this.tokenGetter?.();

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    // IRONCLAD: Add Authorization header if token available
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(endpoint, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    // Handle 401 Unauthorized - dispatch event for App to handle
    if (res.status === 401) {
      console.warn('[API] 401 Unauthorized - dispatching auth:expired event');
      window.dispatchEvent(new CustomEvent('auth:expired'));
      const error = new Error('Unauthorized') as ApiError;
      error.status = 401;
      throw error;
    }

    // Handle other errors
    if (!res.ok) {
      let detail: string | undefined;
      try {
        const errorData = await res.json();
        detail = errorData.detail;
      } catch {
        // Response wasn't JSON
      }
      const error = new Error(detail || `API Error: ${res.status}`) as ApiError;
      error.status = res.status;
      error.detail = detail;
      throw error;
    }

    return res.json();
  }

  /**
   * GET request
   */
  get<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, 'GET');
  }

  /**
   * POST request
   */
  post<T>(endpoint: string, body?: unknown): Promise<T> {
    return this.request<T>(endpoint, 'POST', body);
  }

  /**
   * PUT request
   */
  put<T>(endpoint: string, body?: unknown): Promise<T> {
    return this.request<T>(endpoint, 'PUT', body);
  }

  /**
   * DELETE request
   */
  delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, 'DELETE');
  }
}

// Singleton instance
export const api = new ApiClient();
