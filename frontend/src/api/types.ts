export interface CategoryNode {
  id: number
  parent_id: number | null
  name: string
  level: number
  sort_order: number
  path: string
  question_count: number
  knowledge_count: number
  children: CategoryNode[]
}

export interface TagRef {
  id: number
  name: string
}

export interface Schedule {
  reps: number
  ef: number
  interval_days: number
  lapses: number
  next_review_date: string | null
  last_q: number | null
  first_reviewed_at: string | null
  last_rated_at: string | null
  last_schedule_date: string | null
  is_new: boolean
}

export interface Question {
  id: number
  stem: string
  answer?: string | null
  key_points?: string[]
  notes?: string | null
  difficulty: number | null
  frequency: string | null
  status: string
  source_type: string
  is_deleted: boolean
  mastery: string
  schedule: Schedule
  tags: TagRef[]
  companies: TagRef[]
  categories: { id: number; name: string; level: number; path: string }[]
  category_path: string
  bookmarked: boolean
  in_mistake: boolean
  created_at: string
  updated_at: string
  origins?: Origin[]
  history?: MasteryHistory[]
  knowledge?: QuestionKnowledgeLink[]
  [key: string]: unknown
}

export interface Origin {
  id: number
  source_type: string
  origin_ref: string | null
  import_batch_id: number | null
  crawl_task_id: number | null
  created_at: string
}

export interface MasteryHistory {
  id: number
  q: number
  mode: string
  created_at: string
  local_date: string
}

export interface QuestionKnowledgeLink {
  id: number
  title: string
  kind: string
  relation_type: string
  category_path: string
}

export interface Knowledge {
  id: number
  title: string
  content: string
  kind: string
  aliases: string[]
  status: string
  source_type: string
  category_id: number | null
  category_path: string
  question_count?: number
  created_at: string
  updated_at: string
  origins?: Origin[]
  questions?: { id: number; stem: string; relation_type: string; mastery: string }[]
  [key: string]: unknown
}

export interface PendingItem {
  id: number
  item_type: 'question' | 'knowledge'
  source_type: string
  status: string
  origin_ref: string | null
  raw_text: string | null
  stem: string | null
  answer: string | null
  knowledge_title: string | null
  knowledge_content: string | null
  suggested_meta: Record<string, any>
  parse_confidence: number | null
  content_hash: string | null
  dup_of: number | null
  dup_of_pending_id: number | null
  dup_of_knowledge_id: number | null
  created_question_id: number | null
  created_knowledge_id: number | null
  reviewer_note: string | null
  import_batch_id: number | null
  crawl_task_id: number | null
  created_at: string
  reviewed_at: string | null
  similar?: SimilarItem[]
  suggested_knowledge?: {
    id: number
    title: string
    kind: string
    category_path: string
    relation_type: string
  }[]
  [key: string]: unknown
}

export interface SimilarItem {
  type: string
  id: number
  title: string
  distance: number
  exact: boolean
}

export interface ImportBatch {
  id: number
  filename: string | null
  format: string
  status: string
  total_rows: number
  ok_rows: number
  fail_rows: number
  file_hash: string | null
  operator: string | null
  created_at: string
  finished_at: string | null
  [key: string]: unknown
}

export interface CrawlSource {
  id: number
  name: string
  source_kind: string
  url: string
  enabled: boolean
  user_agent: string
  interval_sec: number
  timeout_sec: number
  max_retries: number
  max_files_per_run: number
  last_run_at: string | null
  next_run_at: string | null
  created_at: string
  [key: string]: unknown
}

export interface CrawlTask {
  id: number
  source_id: number
  parent_task_id: number | null
  status: string
  attempt: number
  total_files: number
  success_files: number
  failed_files: number
  log: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  [key: string]: unknown
}

export interface CrawlTaskFile {
  id: number
  task_id: number
  url: string
  status: string
  http_status: number | null
  parsed_count: number
  error: string | null
  cached_path: string | null
  fetched_at: string | null
}

export interface TrendPoint {
  date: string
  label: string
  reviews: number
  accuracy: number | null
}

export interface DashboardStats {
  definitions_version: string
  total_questions: number
  learned: number
  unlearned: number
  due: number
  mastered: number
  mistakes: number
  streak: number
  knowledge_count: number
  trend: TrendPoint[]
}

export interface ReviewPayload {
  date: string
  due: Question[]
  new: Question[]
  counts: {
    due_total: number
    due_returned: number
    new_total: number
    new_returned: number
    backlog: number
    completed: number
  }
  limits: {
    daily_new_limit: number
    daily_review_limit: number
  }
}

export interface Settings {
  'sm2.ef_initial': number
  'sm2.ef_min': number
  'sm2.interval_cap_days': number
  'sm2.daily_new_limit': number
  'sm2.daily_review_limit': number
  'dedupe.simhash_threshold': number
  'manual.new_to_pending': boolean
  'import.direct_to_active': boolean
  'import.max_rows': number
  'import.max_bytes': number
  'review.early_advances': boolean
  'crawl.max_files_per_run': number
  'auth.token_ttl_minutes': number
  'mistake.auto_remove_streak': number
  [key: string]: number | boolean
}

export interface TagRule {
  id: number
  keyword: string
  match_type: string
  tag_id: number | null
  tag_name: string | null
  category_id: number | null
  category_path: string
  difficulty: number | null
  frequency: string | null
  weight: number
  enabled: boolean
  created_at: string
}
