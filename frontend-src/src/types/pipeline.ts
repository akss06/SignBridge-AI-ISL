/**
 * Mirrors backend/schemas.py exactly — GlossToken, SentenceResult, PipelineResult.
 * Keep in sync with the backend; this is a read-only mirror, not a source of truth.
 */

export interface GlossToken {
  token: string;
  surface: string | null;
  clip_path: string | null;
  matched: boolean;
}

export interface SentenceResult {
  original: string;
  gloss_tokens: GlossToken[];
}

export interface PipelineResult {
  transcript: string;
  sentences: SentenceResult[];
  coverage: number;
  output_video_url: string | null;
  error: string | null;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}
