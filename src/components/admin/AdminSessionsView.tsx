import { useEffect, useMemo } from 'react'
import WorkflowTrail from './WorkflowTrail'

export type AdminSessionSummary = {
  id: string
  user_id?: string | null
  email?: string | null
  role?: string | null
  created_at?: string
  updated_at?: string
  status?: string
  metadata?: Record<string, unknown>
}

export type AdminSessionItem = {
  event_id?: string
  question_id: string
  response: string
  event_type?: string
  clarification_round?: number
  probe_type?: string | null
  created_at?: string
  score?: {
    preliminary_score?: number
    score_status?: string
    evidence_sufficiency?: string
    confidence?: number
    rationale?: string
  }
}

export type AdminSessionDetail = AdminSessionSummary & {
  items: AdminSessionItem[]
  decision_history?: Array<{ id: string; event_id?: string; created_at?: string; ai_analysis?: Record<string, unknown> }>
  global_evidence?: {
    seed_answered?: number
    seed_total?: number
    probe_count?: number
    constructs?: Array<Record<string, unknown>>
    unresolved_gaps?: Array<Record<string, unknown>>
    next_action?: Record<string, unknown>
  }
  next_action?: Record<string, unknown>
  session_intelligence?: {
    status?: string
    model?: string
    session_summary?: string
    planning_notes?: string[]
  }
  participant_handoff?: { message?: string; mode?: string }
  admin_report?: {
    answered?: number
    seed_total?: number
    total_score?: number | null
    max_score?: number
    mean_score?: number | null
    score_counts?: Record<string, number>
    risk_level?: string
    intervention_recommendation?: string
    disclaimer?: string
  }
  evidence_report?: {
    session_id?: string
    overview?: Record<string, unknown>
    constructs?: Array<Record<string, unknown>>
    item_matrix?: Array<Record<string, unknown>>
    timeline?: Array<Record<string, unknown>>
    probe_summary?: Record<string, unknown>
    uncertainty?: Record<string, unknown>
    ai_decisions?: Array<Record<string, unknown>>
    review_queue?: Array<Record<string, unknown>>
    versions?: Record<string, unknown>
  }
}

type AdminSessionsViewProps = {
  sessions: AdminSessionSummary[]
  selected: AdminSessionDetail | null
  loading: boolean
  detailLoading: boolean
  message: string
  exportMessage: string
  focusedQuestionId?: string | null
  onRefresh: () => Promise<void>
  onSelect: (sessionId: string) => Promise<void>
  onReview: (sessionId: string, questionId: string) => void
  onExport: () => Promise<void>
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function statusLabel(value?: string) {
  const labels: Record<string, string> = {
    IN_PROGRESS: '进行中', AWAITING_PROBE: '等待靠近', AWAITING_REVIEW: '等待复核', COMPLETED: '已完成',
  }
  return labels[value || ''] || value || '未开始'
}

function scoreLabel(value?: string) {
  const labels: Record<string, string> = { CONFIRMED: '已确认', PROVISIONAL: '暂定', HUMAN_REVIEW: '人工复核' }
  return labels[value || ''] || value || '未评估'
}

function reviewStatusLabel(value?: string) {
  const labels: Record<string, string> = { OPEN: '待专家复核', UNRESOLVED: '暂不确定', ADJUDICATED: '专家已确认', NOT_REQUIRED: '无需复核' }
  return labels[value || ''] || value || '待专家复核'
}

function riskLabel(value?: string) {
  const labels: Record<string, string> = { LOW: '低关注', MODERATE: '中关注', HIGH: '高关注', INCOMPLETE: '未完成', SAFETY_REVIEW: '安全复核' }
  return labels[value || ''] || value || '未分层'
}

export default function AdminSessionsView({ sessions, selected, focusedQuestionId, loading, detailLoading, message, exportMessage, onRefresh, onSelect, onReview, onExport }: AdminSessionsViewProps) {
  const selectedId = selected?.id
  const report = selected?.evidence_report
  const overview = report?.overview ?? {}
  const constructs = report?.constructs ?? selected?.global_evidence?.constructs ?? []
  const matrix = report?.item_matrix ?? []
  const timeline = report?.timeline ?? []
  const unresolved = report?.review_queue ?? selected?.global_evidence?.unresolved_gaps ?? []
  const answered = useMemo(() => Number(overview.seed_answered ?? selected?.global_evidence?.seed_answered ?? selected?.items.filter((item) => item.event_type === 'INITIAL').length ?? 0), [overview.seed_answered, selected])
  const asNumber = (value: unknown, fallback = 0) => typeof value === 'number' ? value : Number(value ?? fallback)
  const asText = (value: unknown, fallback = '—') => typeof value === 'string' && value ? value : fallback

  useEffect(() => {
    if (!selectedId || !focusedQuestionId) return
    const target = document.getElementById(`session-item-${selectedId}-${focusedQuestionId}`)
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [selectedId, focusedQuestionId, matrix.length])

  return <div className="detail-view admin-sessions-view">
    <WorkflowTrail active="report" />
    <div className="eyebrow"><span>ASSESSMENT SESSIONS</span><span className="eyebrow-line" /><span>ADMIN ONLY</span></div>
    <h2>选择测试者，进入单场评估报告</h2>
    <p className="view-intro">先从左侧选一位测试者，再按“证据地图 → 未决节点 → 专家复核”的顺序阅读。跨题关系只帮助安排复核，不会改写任何一道题的评分。</p>
    <div className="sessions-toolbar"><span className="box-kicker">会话 {sessions.length} · 默认每 30 秒同步</span><span className="sessions-sync-note">{loading ? '正在同步…' : '上一份内容仍保留'}</span><button className="ghost-button" type="button" onClick={() => void onRefresh()} disabled={loading}>{loading ? '同步中…' : '同步列表 ↻'}</button></div>
    {message && <div className="members-message" role="status">{message}</div>}
    <div className="sessions-layout">
      <div className="sessions-list" aria-label="评估会话列表"><div className="sessions-list-heading"><strong>测试者</strong><span>{sessions.length} 场评估</span></div>
        {sessions.map((session) => {
          const evidence = session.metadata?.latest_global_evidence as Record<string, unknown> | undefined
          const report = session.metadata?.latest_admin_report as Record<string, unknown> | undefined
          return <button className={`session-row ${session.id === selectedId ? 'selected' : ''}`} type="button" key={session.id} onClick={() => void onSelect(session.id)}>
            <div className="session-row-top"><strong>{session.email || '未关联邮箱'}</strong><span>{statusLabel(session.status)}</span></div>
            <div className="session-row-meta"><span>{formatDate(session.updated_at)}</span><span>{Number(evidence?.seed_answered ?? 0)} / {Number(evidence?.seed_total ?? 20)} 题</span><span>总分 {report?.total_score == null ? '—' : `${String(report.total_score)}/${String(report.max_score ?? 40)}`}</span><span>{riskLabel(String(report?.risk_level ?? 'INCOMPLETE'))}</span></div>
          </button>
        })}
        {!sessions.length && <div className="members-empty">还没有评估会话。</div>}
      </div>
      <section className="session-detail" aria-live="polite">
        {detailLoading && selected && <div className="session-detail-syncing">正在同步这场会话，上一份内容仍保留。</div>}
        {!selected && <div className="session-detail-empty"><span className="empty-glyph">⌁</span><strong>从左侧选择一场会话</strong><span>这里会显示完整回答、证据地图和评估路径。</span></div>}
        {selected && <>
          <div className="session-detail-heading"><div><span className="box-kicker">{selected.email || '未关联邮箱'}</span><h3>{statusLabel(selected.status)}</h3></div><div className="session-detail-actions"><span className="session-detail-date">更新于 {formatDate(selected.updated_at)}</span><button className="ghost-button" type="button" onClick={() => void onExport()}>导出已确认数据</button></div></div>
          {exportMessage && <div className="admin-export-message" role="status">{exportMessage}</div>}
          <div className="session-detail-stats"><div><strong>{answered}</strong><span>Seed 回答</span></div><div><strong>{asNumber(report?.probe_summary?.total, selected.global_evidence?.probe_count ?? 0)}</strong><span>求证事件</span></div><div><strong>{asNumber(report?.uncertainty?.open_nodes, unresolved.length)}</strong><span>未决节点</span></div><div><strong>{asNumber(report?.uncertainty?.conflict_links)}</strong><span>跨题冲突</span></div></div>
          <div className="session-reading-note"><span className="box-kicker">AI 会话摘要</span><p>{asText(overview.session_summary, selected.session_intelligence?.session_summary || '这场评估还在形成中。先从原话和证据充分性开始阅读。')}</p><small>{asText(report?.versions?.session_model, selected.session_intelligence?.model || 'session-level advisory')}</small></div>
          <div className="session-report-overview"><div><span className="box-kicker">研究分层 · 仅用于分流</span><strong>{riskLabel(asText(overview.research_band, 'INCOMPLETE'))}</strong></div><p>{asText(overview.support_recommendation, '先看证据质量和未决节点，再决定是否需要专家复核。')}</p></div>
          <div className="session-report-section"><div className="section-heading"><div><strong>证据地图</strong><small>表现方向与证据质量分开阅读</small></div><span>{answered} / {asNumber(overview.seed_total, 20)} 题</span></div><div className="session-construct-list">{constructs.map((construct, index) => <div className="session-construct-row" key={String(construct.id ?? index)}><div><strong>{String(construct.label ?? construct.id ?? '未分类')}</strong><span>{String(construct.evidence_quality ?? construct.status ?? 'UNASSESSED')}</span></div><small>{asNumber(construct.answered)} 题 · {String(construct.pattern_level ?? 'UNASSESSED')}</small><i><span style={{ width: `${Math.min(100, asNumber(construct.evidence_density) * 100)}%` }} /></i></div>)}</div></div>
          <div className="session-report-section"><div className="section-heading"><div><strong>20题证据矩阵</strong><small>跨题关系不会改变这里的单题分数</small></div><span>{matrix.length} items</span></div><div className="session-matrix">{matrix.map((item, index) => { const score = item.score as Record<string, unknown> | undefined; const evidence = item.evidence as Record<string, unknown> | undefined; const relationships = item.relationships as Record<string, unknown> | undefined; const questionId = String(item.question_id); return <article id={`session-item-${selected.id}-${questionId}`} className={focusedQuestionId === questionId ? 'is-focused' : ''} key={`${questionId}-${index}`}><div className="session-matrix-top"><span className="mono">{questionId}</span><strong>{asText(item.dimension, '未分类')}</strong><span>{scoreLabel(asText(score?.status))}</span></div><p>{asText(item.latest_response, '尚未回答')}</p><div><span>有效分 {score?.effective == null ? '—' : String(score.effective)}</span><span>证据 {String(evidence?.sufficiency ?? 'UNASSESSED')}</span><span>把握 {typeof evidence?.confidence === 'number' ? `${Math.round(Number(evidence.confidence) * 100)}%` : '—'}</span><span>支持/冲突 {asNumber(relationships?.support_count)}/{asNumber(relationships?.conflict_count)}</span></div></article> })}</div></div>
          {unresolved.length > 0 && <div className="session-report-section"><div className="section-heading"><div><strong>未决节点</strong><small>优先处理最影响整体理解的地方</small></div><button className="session-review-link" type="button" onClick={() => onReview(selected.id, String(unresolved[0]?.question_id || ''))}>进入专家工作台 →</button></div><div className="session-open-list">{unresolved.map((item, index) => { const questionId = String(item.question_id || ''); return <div key={`${questionId}-${index}`}><div className="session-open-heading"><strong>{questionId || '一处回答'}</strong><span>{reviewStatusLabel(String(item.status || 'OPEN'))} · 优先级 {Math.round(asNumber(item.priority) * 100)}</span></div><p>{String(item.target_gap || '这部分证据还没有完全打开。')}</p>{questionId && <button className="session-review-link" type="button" onClick={() => onReview(selected.id, questionId)}>进入复核 →</button>}</div> })}</div></div>}
          <div className="session-report-section"><div className="section-heading"><div><strong>评估路径</strong><small>AI 如何发现缺口、求证并交接</small></div><span>{timeline.length} steps</span></div><div className="session-timeline">{timeline.map((event, index) => <div key={`${String(event.id)}-${index}`}><span className={`timeline-dot timeline-${String(event.kind || '').toLowerCase()}`} /><div><small>{formatDate(String(event.created_at || ''))} · {String(event.kind || 'EVENT')}</small><strong>{String(event.title || '记录了一步判断')}</strong><p>{String(event.description || '')}</p></div></div>)}</div></div>
          <div className="session-report-section"><div className="section-heading"><div><strong>原话回放</strong><small>完整证据链仍可逐条查看</small></div><span>{selected.items.length} events</span></div><div className="session-event-list">{selected.items.map((item, index) => <article className="session-event" key={item.event_id || `${item.question_id}-${index}`}><div className="session-event-meta"><span className="mono">{item.question_id}</span><span>{item.event_type === 'INITIAL' ? 'Seed' : item.probe_type || item.event_type || 'Probe'}</span><time>{formatDate(item.created_at)}</time></div><p>{item.response || '（空白）'}</p><div className="session-event-score"><span>{scoreLabel(item.score?.score_status)}</span><span>{item.score?.evidence_sufficiency || 'UNASSESSED'}</span><span>{typeof item.score?.confidence === 'number' ? `${Math.round(item.score.confidence * 100)}% 把握` : '—'}</span></div></article>)}</div></div>
        </>}
      </section>
    </div>
  </div>
}
