import type { AdminSessionSummary } from './AdminSessionsView'
import WorkflowTrail from './WorkflowTrail'

export type AdminReviewPriority = {
  session_id: string
  email?: string | null
  question_id?: string | null
  priority?: number
  status?: string
  target_gap?: string | null
  support_count?: number
  conflict_count?: number
  updated_at?: string | null
}

export type AdminOverview = {
  updated_at?: string | null
  counts: {
    sessions: number
    completed: number
    awaiting_review: number
    safety_sessions: number
    open_nodes: number
  }
  recent_sessions: AdminSessionSummary[]
  review_priorities: AdminReviewPriority[]
  safety_sessions: Array<{ session_id: string; email?: string | null; updated_at?: string | null; status?: string }>
  disclaimer?: string
}

type Props = {
  overview: AdminOverview | null
  loading: boolean
  syncing: boolean
  message: string
  onRefresh: () => Promise<void>
  onOpenSession: (sessionId: string, questionId?: string | null) => void
  onOpenReview: () => void
  onStartTest: () => void
  onMembers: () => void
}

function formatDate(value?: string | null) {
  if (!value) return '尚未同步'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '尚未同步' : parsed.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function statusLabel(value?: string) {
  return ({ IN_PROGRESS: '仍在进行', AWAITING_PROBE: '等待求证', AWAITING_REVIEW: '等待复核', COMPLETED: '已经收束' } as Record<string, string>)[value || ''] || '尚未完成'
}

export default function AdminOverviewView({ overview, loading, syncing, message, onRefresh, onOpenSession, onOpenReview, onStartTest, onMembers }: Props) {
  if (loading && !overview) return <div className="admin-initial-loading">正在整理最近的评估证据…</div>
  const counts = overview?.counts ?? { sessions: 0, completed: 0, awaiting_review: 0, safety_sessions: 0, open_nodes: 0 }
  const priorities = overview?.review_priorities ?? []
  const recent = overview?.recent_sessions ?? []

  return <div className="detail-view admin-overview-view">
    <WorkflowTrail active="overview" />
    <section className="admin-overview-hero">
      <div>
        <div className="eyebrow"><span>ASSESSMENT OVERVIEW</span><span className="eyebrow-line" /><span>证据优先</span></div>
        <h2>先看还需要判断的地方</h2>
        <p className="view-intro">这里不替任何人下结论。它把已经听清的证据、仍有张力的节点和下一步复核顺序放在一起。</p>
      </div>
      <div className="admin-overview-actions">
        <button className="secondary-button" type="button" onClick={onStartTest}>以测试者身份开始</button>
        <button className="ghost-button" type="button" onClick={() => void onRefresh()} disabled={syncing}>{syncing ? '正在同步…' : '同步最新内容 ↻'}</button>
      </div>
    </section>

    <div className="admin-sync-line" aria-live="polite">
      <span className={syncing ? 'is-syncing' : ''} />
      {syncing ? '正在同步，当前内容保持不变' : `上次同步 ${formatDate(overview?.updated_at)}`}
      {message && <em>{message}</em>}
    </div>

    <section className="admin-signal-grid" aria-label="评估总览摘要">
      <div><span>需要专家判断</span><strong>{counts.awaiting_review}</strong><small>场评估正等待复核</small></div>
      <div><span>仍未听清</span><strong>{counts.open_nodes}</strong><small>个节点保留不确定性</small></div>
      <div><span>专业流程优先</span><strong>{counts.safety_sessions}</strong><small>场会话停止自动可爱化流程</small></div>
      <div><span>已经收束</span><strong>{counts.completed}</strong><small>共记录 {counts.sessions} 场评估</small></div>
    </section>

    <div className="admin-overview-columns">
      <section className="admin-priority-panel">
        <div className="section-heading"><div><strong>优先复核</strong><small>按证据缺口、冲突和构念位置排序</small></div><button type="button" onClick={onOpenReview}>进入专家工作台 →</button></div>
        <div className="admin-priority-list">
          {priorities.slice(0, 6).map((item, index) => <button type="button" key={`${item.session_id}-${item.question_id}-${index}`} onClick={() => onOpenSession(item.session_id, item.question_id)}>
            <span className="priority-rank">{String(index + 1).padStart(2, '0')}</span>
            <div><strong>{item.email || '未关联邮箱'} · {item.question_id || '会话节点'}</strong><p>{item.target_gap || '这部分证据仍需要专业人员结合原话判断。'}</p><small>{Number(item.support_count || 0)} 处支持 · {Number(item.conflict_count || 0)} 处冲突</small></div>
            <span className="priority-score">{Math.round(Number(item.priority || 0) * 100)}</span>
          </button>)}
          {!priorities.length && <div className="admin-calm-empty"><span>✓</span><strong>当前没有排队的未决节点</strong><p>新的评估完成或出现证据冲突后，会在这里出现。</p></div>}
        </div>
      </section>

      <section className="admin-recent-panel">
        <div className="section-heading"><div><strong>最近评估</strong><small>先看变化，不让总分抢走判断</small></div></div>
        <div className="admin-recent-list">
          {recent.slice(0, 7).map((session) => {
            const evidence = session.metadata?.latest_global_evidence as Record<string, unknown> | undefined
            return <button type="button" key={session.id} onClick={() => onOpenSession(session.id)}><div><strong>{session.email || '未关联邮箱'}</strong><span>{statusLabel(session.status)}</span></div><small>{Number(evidence?.seed_answered ?? 0)} / {Number(evidence?.seed_total ?? 19)} 题 · {formatDate(session.updated_at)}</small></button>
          })}
          {!recent.length && <div className="admin-calm-empty compact"><strong>还没有评估会话</strong></div>}
        </div>
        <button className="admin-members-link" type="button" onClick={onMembers}>成员与权限 <span>→</span></button>
      </section>
    </div>

    <p className="admin-overview-disclaimer">{overview?.disclaimer || '这里展示的是研究评估证据与复核队列，不是临床诊断或自动干预结论。'}</p>
  </div>
}
