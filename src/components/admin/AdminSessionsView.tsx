import { useMemo } from 'react'

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
}

type AdminSessionsViewProps = {
  sessions: AdminSessionSummary[]
  selected: AdminSessionDetail | null
  loading: boolean
  detailLoading: boolean
  message: string
  onRefresh: () => Promise<void>
  onSelect: (sessionId: string) => Promise<void>
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

function riskLabel(value?: string) {
  const labels: Record<string, string> = { LOW: '低关注', MODERATE: '中关注', HIGH: '高关注', INCOMPLETE: '未完成', SAFETY_REVIEW: '安全复核' }
  return labels[value || ''] || value || '未分层'
}

export default function AdminSessionsView({ sessions, selected, loading, detailLoading, message, onRefresh, onSelect }: AdminSessionsViewProps) {
  const selectedId = selected?.id
  const selectedEvidence = selected?.global_evidence
  const report = selected?.admin_report
  const constructs = selectedEvidence?.constructs ?? []
  const unresolved = selectedEvidence?.unresolved_gaps ?? []
  const answered = useMemo(() => selected?.items.filter((item) => item.event_type === 'INITIAL').length ?? 0, [selected])

  return <div className="detail-view admin-sessions-view">
    <div className="eyebrow"><span>SESSION CONTROL ROOM</span><span className="eyebrow-line" /><span>ADMIN ONLY</span></div>
    <h2>每一场评估，都能被看见</h2>
    <p className="view-intro">按会话查看参与者原话、逐题证据、AI 的会话判断与最终编排。这里的阅读动作会留下审计记录。</p>
    <div className="sessions-toolbar"><span className="box-kicker">会话 {sessions.length} · 每 15 秒自动更新</span><button className="ghost-button" type="button" onClick={() => void onRefresh()} disabled={loading}>{loading ? '读取中…' : '刷新列表 ↻'}</button></div>
    {message && <div className="members-message" role="status">{message}</div>}
    <div className="sessions-layout">
      <div className="sessions-list" aria-label="评估会话列表">
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
        {detailLoading && <div className="session-detail-empty">正在打开这场会话…</div>}
        {!detailLoading && !selected && <div className="session-detail-empty"><span className="empty-glyph">⌁</span><strong>从左侧选择一场会话</strong><span>这里会显示完整回答、AI 分析和证据链。</span></div>}
        {!detailLoading && selected && <>
          <div className="session-detail-heading"><div><span className="box-kicker">{selected.email || '未关联邮箱'}</span><h3>{statusLabel(selected.status)}</h3></div><span className="session-detail-date">更新于 {formatDate(selected.updated_at)}</span></div>
          <div className="session-detail-stats"><div><strong>{answered}</strong><span>Seed 回答</span></div><div><strong>{selectedEvidence?.probe_count ?? 0}</strong><span>探针事件</span></div><div><strong>{unresolved.length}</strong><span>未决节点</span></div><div><strong>{selected.decision_history?.length ?? 0}</strong><span>AI 决策</span></div></div>
          {report && <div className="session-admin-report"><div className="session-report-heading"><span className="box-kicker">管理员摘要 · {report.disclaimer || '研究规则'}</span><strong>{riskLabel(report.risk_level)}</strong></div><div className="session-report-metrics"><div><span>总分</span><strong>{report.total_score == null ? '—' : `${report.total_score} / ${report.max_score ?? 40}`}</strong></div><div><span>平均题分</span><strong>{report.mean_score == null ? '—' : report.mean_score}</strong></div><div><span>0 / 1 / 2</span><strong>{Object.entries(report.score_counts ?? {}).map(([score, count]) => `${score}:${count}`).join('  ') || '—'}</strong></div></div><p className="session-report-recommendation"><span>干预建议（需人工确认）</span>{report.intervention_recommendation || '等待更多证据。'}</p></div>}
          {selected.session_intelligence?.session_summary && <div className="session-ai-summary"><div className="section-heading"><strong>会话级 AI 摘要</strong><span>{selected.session_intelligence.model || 'advisory'}</span></div><p>{selected.session_intelligence.session_summary}</p>{selected.session_intelligence.planning_notes?.[0] && <small>{selected.session_intelligence.planning_notes[0]}</small>}</div>}
          {selected.participant_handoff?.message && <div className="session-handoff-note"><span className="box-kicker">参与者交付</span><p>{selected.participant_handoff.message}</p></div>}
          <div className="session-detail-section"><div className="section-heading"><strong>构念证据</strong><span>{selectedEvidence?.seed_answered ?? 0} / {selectedEvidence?.seed_total ?? 20} seed</span></div><div className="session-construct-list">{constructs.map((construct, index) => <div className="session-construct-row" key={String(construct.id ?? index)}><div><strong>{String(construct.label ?? construct.id ?? '未分类')}</strong><span>{String(construct.status ?? 'UNANSWERED')}</span></div><small>{String(construct.answered ?? 0)} 题 · 证据 {Math.round(Number(construct.evidence_density ?? 0) * 100)}%</small><i><span style={{ width: `${Math.min(100, Number(construct.evidence_density ?? 0) * 100)}%` }} /></i></div>)}</div></div>
          {unresolved.length > 0 && <div className="session-detail-section"><div className="section-heading"><strong>未决节点</strong><span>需要进一步理解或复核</span></div><div className="session-open-list">{unresolved.map((item, index) => <div key={`${String(item.question_id)}-${index}`}><strong>{String(item.question_id || '一处回答')}</strong><span>{String(item.status || item.probe_type || 'OPEN')}</span><p>{String(item.target_gap || item.clarification_question || '这部分证据还没有完全打开。')}</p></div>)}</div></div>}
          <div className="session-detail-section"><div className="section-heading"><strong>原话与评分事件</strong><span>{selected.items.length} events</span></div><div className="session-event-list">{selected.items.map((item, index) => <article className="session-event" key={item.event_id || `${item.question_id}-${index}`}><div className="session-event-meta"><span className="mono">{item.question_id}</span><span>{item.event_type === 'INITIAL' ? 'Seed' : item.probe_type || item.event_type || 'Probe'}</span><time>{formatDate(item.created_at)}</time></div><p>{item.response || '（空白）'}</p><div className="session-event-score"><span>{scoreLabel(item.score?.score_status)}</span><span>{item.score?.evidence_sufficiency || 'UNASSESSED'}</span><span>{typeof item.score?.confidence === 'number' ? `${Math.round(item.score.confidence * 100)}% 把握` : '—'}</span></div></article>)}</div></div>
        </>}
      </section>
    </div>
  </div>
}
