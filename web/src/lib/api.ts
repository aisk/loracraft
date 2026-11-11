export interface Project {
  id: number
  name: string
  kind: 'character' | 'style' | 'concept'
  trigger: string
  notes: string
  created_at: string
  image_count?: number
  run_count?: number
  uncaptioned_count?: number
  active_runs?: number
  cover_image_id?: number | null
}

export interface DatasetImage {
  id: number
  project_id: number
  filename: string
  width: number
  height: number
  caption: string
}

export interface ImportResult {
  added: DatasetImage[]
  skipped_duplicates: number
  unreadable: string[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init)
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const error = new Error(typeof detail?.detail === 'string' ? detail.detail : `${response.status} ${response.statusText}`)
    error.name = '' // so that String(error) is the message alone, ready to show
    throw error
  }
  return response.json()
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const api = {
  listProjects: () => request<Project[]>('/projects'),
  createProject: (body: Pick<Project, 'name' | 'kind' | 'trigger'>) => request<Project>('/projects', json('POST', body)),
  updateProject: (id: number, body: Partial<Project>) => request<Project>(`/projects/${id}`, json('PATCH', body)),
  deleteProject: (id: number) => request<{ ok: boolean }>(`/projects/${id}`, { method: 'DELETE' }),

  listImages: (projectId: number) => request<DatasetImage[]>(`/projects/${projectId}/images`),
  uploadImages: (projectId: number, files: File[]) => {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    return request<ImportResult>(`/projects/${projectId}/images`, { method: 'POST', body: form })
  },
  importFolder: (projectId: number, path: string) =>
    request<ImportResult>(`/projects/${projectId}/images/import`, json('POST', { path })),
  updateCaption: (imageId: number, caption: string) =>
    request<DatasetImage>(`/images/${imageId}`, json('PATCH', { caption })),
  deleteImages: (imageIds: number[]) => request<{ ok: boolean }>('/images/delete', json('POST', { image_ids: imageIds })),
  editTags: (body: {
    image_ids: number[]
    add?: string[]
    add_position?: 'start' | 'end'
    remove?: string[]
    replace?: Record<string, string>
  }) => request<DatasetImage[]>('/tags/edit', json('POST', body)),
}

export const thumbUrl = (imageId: number) => `/api/images/${imageId}/thumb`
export const fileUrl = (imageId: number) => `/api/images/${imageId}/file`

export const splitTags = (caption: string) =>
  caption
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)

// --- Training runs ---

export interface SamplePrompt {
  prompt: string
  negative_prompt: string
  width: number
  height: number
  steps: number
  cfg_scale: number
  seed: number
}

/** TrainConfig without the dataset snapshot. Mirrors src/loracraft/trainer/config.py. */
export interface TrainSettings {
  base_model: string
  prediction_type: 'epsilon' | 'v_prediction'
  zero_terminal_snr: boolean
  output_name: string
  resolution: number
  repeats: number
  shuffle_caption: boolean
  keep_tokens: number
  caption_dropout_rate: number
  network_dim: number
  network_alpha: number
  epochs: number
  batch_size: number
  optimizer: 'adamw' | 'prodigy'
  unet_lr: number
  train_text_encoder: boolean
  text_encoder_lr: number
  lr_scheduler: 'constant' | 'constant_with_warmup' | 'cosine' | 'cosine_with_restarts' | 'linear'
  lr_warmup_steps: number
  min_snr_gamma: number | null
  noise_offset: number | null
  mixed_precision: 'no' | 'fp16' | 'bf16'
  seed: number
  save_every_n_epochs: number
  sample_every_n_epochs: number
  sample_prompts: SamplePrompt[]
}

export type RunStatus = 'queued' | 'running' | 'done' | 'stopped' | 'failed'

export interface Run {
  id: number
  project_id: number
  name: string
  status: RunStatus
  config: TrainSettings
  num_images: number
  notes: string
  rating: number
  best_checkpoint: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  progress: {
    phase: string | null
    step: number
    total_steps: number | null
    steps_per_epoch: number | null
    epoch: number
    loss_avg: number | null
    seconds_per_step: number | null
    cache_done: number
    error: string | null
  }
  checkpoints: string[]
  samples: string[]
}

export interface RunEvent {
  type: string
  time: number
  [key: string]: unknown
}

/** Whether the Python environment can train. `problem` says why not. */
export interface TrainerStatus {
  ready: boolean
  problem: 'missing' | 'no_gpu' | 'broken' | null
  torch_version: string
  /** What the trainer will run on: `mps` is Apple Silicon. */
  device: 'cuda' | 'mps' | null
  python: string
}

export interface BaseModel {
  path: string
  name: string
  size_gb: number
  v_prediction: boolean
  zero_terminal_snr: boolean
}

export interface Settings {
  model_dirs: string[]
  export_dir: string
  tagger_base_url: string
  tagger_api_key: string
  tagger_model: string
}

export const runApi = {
  list: (projectId: number) => request<Run[]>(`/projects/${projectId}/runs`),
  create: (projectId: number, name: string, config: TrainSettings) =>
    request<Run>(`/projects/${projectId}/runs`, json('POST', { name, config })),
  events: (runId: number, after: number) =>
    request<{ status: RunStatus; events: RunEvent[] }>(`/runs/${runId}/events?after=${after}`),
  stop: (runId: number) => request<{ ok: boolean }>(`/runs/${runId}/stop`, { method: 'POST' }),
  update: (runId: number, body: Partial<Pick<Run, 'name' | 'notes' | 'rating' | 'best_checkpoint'>>) =>
    request<Run>(`/runs/${runId}`, json('PATCH', body)),
  remove: (runId: number) => request<{ ok: boolean }>(`/runs/${runId}`, { method: 'DELETE' }),
  exportCheckpoint: (runId: number, checkpoint: string) =>
    request<{ path: string }>(`/runs/${runId}/export`, json('POST', { checkpoint })),

  models: () => request<{ models: BaseModel[]; missing_dirs: string[] }>('/models'),
  trainer: () => request<TrainerStatus>('/trainer'),
  getSettings: () => request<Settings>('/settings'),
  putSettings: (settings: Settings) => request<Settings>('/settings', json('PUT', settings)),
}

export const sampleUrl = (runId: number, name: string) => `/api/runs/${runId}/samples/${name}`

/** "e003_p01.png" -> { epoch: 3, prompt: 1 } */
export function parseSampleName(name: string) {
  const match = /^e(\d+)_p(\d+)\.png$/.exec(name)
  return match ? { epoch: Number(match[1]), prompt: Number(match[2]) } : null
}

/** "name-000004.safetensors" -> 4 */
export const checkpointEpoch = (name: string) => Number(/-(\d+)\.safetensors$/.exec(name)?.[1] ?? 0)

export function formatDuration(seconds: number) {
  if (!isFinite(seconds) || seconds < 0) return '—'
  if (seconds < 90) return `${Math.round(seconds)} 秒`
  const minutes = Math.round(seconds / 60)
  if (minutes < 90) return `${minutes} 分钟`
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
}

// --- Auto-captioning ---

export interface TaggingProfile {
  goal: 'character' | 'style' | 'concept' | 'general'
  format: 'danbooru' | 'natural' | 'mixed'
  fixed_traits: string[]
  concept: string
  preferred_tags: string[]
  preferred_only: boolean
  banned_tags: string[]
  extra_instructions: string
}

export interface TagIssue {
  tag: string
  kind: 'unknown' | 'corrected' | 'banned' | 'fixed_trait' | 'not_in_vocabulary'
  original?: string
}

export interface TagSuggestion {
  image_id: number
  caption: string
  groups: Record<string, string[]>
  issues: TagIssue[]
  model: string
  goal: string
}

export interface TaggingState {
  profile: TaggingProfile
  prompt: string
  configured: boolean
  dictionary_size: number
  job: { total: number; done: number; running: boolean; errors: { image_id: number; message: string }[] } | null
  suggestions: TagSuggestion[]
}

export const taggingApi = {
  get: (projectId: number) => request<TaggingState>(`/projects/${projectId}/tagging`),
  prompt: (profile: TaggingProfile) => request<{ prompt: string }>('/tagging/prompt', json('POST', profile)),
  run: (projectId: number, imageIds: number[], profile: TaggingProfile) =>
    request<unknown>(`/projects/${projectId}/tagging/run`, json('POST', { image_ids: imageIds, profile })),
  cancel: (projectId: number) => request<unknown>(`/projects/${projectId}/tagging/cancel`, { method: 'POST' }),
  accept: (imageIds: number[], captions: Record<number, string> = {}) =>
    request<DatasetImage[]>('/tagging/accept', json('POST', { image_ids: imageIds, captions })),
  discard: (imageIds: number[]) => request<unknown>('/tagging/discard', json('POST', { image_ids: imageIds })),
}
