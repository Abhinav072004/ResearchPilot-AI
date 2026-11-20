export interface Account { id: string; email: string }
export interface Named { id: string; title: string }
export interface Evidence {
  id: string; document_id: string; title: string; text: string; section: string;
  page: number | null; kind: string; doi: string | null; access: string;
  metadata: {document_link?: string; retracted?: boolean; authors?: string[]; year?: number; journal?: string};
  anchor: {xml_path?: string};
}
export interface Source {
  external_id: string; title: string; doi: string | null; authors: string[];
  journal: string | null; year: string | number | null; access: string;
  url: string | null; retracted?: boolean;
}
export interface Observation {
  id: string; passage_id: string; title: string; metric: string; value: string; unit: string;
  study_type: string; conditions: Record<string, string>; confidence: string;
}
export interface Comparison {
  matched: {rows: Observation[]; observed_span: string; unit: string}[];
  unmatched: Observation[]; interpretation: string;
}
export interface Result {
  claims?: {claim_id: string; text: string; evidence: Evidence; type: string; supporting_evidence?: Evidence[]}[];
  gaps?: string[]; intent?: string; formats?: string[]; approval?: {purpose: string};
  metadata_leads?: Source[]; comparisons?: Record<string, Comparison>;
}
export interface Job { id: string; kind: string; status: string; error: string | null; result: Result | null }
export interface Activity { stage: string; created: number }

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/api/v1' + path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === 'string' ? payload.detail :
      Array.isArray(payload.detail) ? payload.detail.map((item: {msg: string}) => item.msg).join('. ') :
      `Request failed (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export function json(body: unknown, method = 'POST'): RequestInit {
  return {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
}

export function safeUrl(value: string | null) {
  if (!value) return undefined;
  try {
    const parsed = new URL(value);
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}
