import type { HealthResponse, PipelineResult } from '../types/pipeline';

export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch('/health');
  const data = await res.json();
  if (!res.ok || data.status !== 'ok') {
    throw new Error(data.status ?? 'unexpected response');
  }
  return data as HealthResponse;
}

export class PipelineHttpError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Submits a file (picked or recorded) through the exact same endpoint either way. */
export async function runPipeline(file: File): Promise<PipelineResult> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch('/pipeline/run', { method: 'POST', body: formData });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new PipelineHttpError(err.detail ?? `Server error ${res.status}`, res.status);
  }

  return (await res.json()) as PipelineResult;
}
