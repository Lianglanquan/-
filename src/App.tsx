import { useEffect, useMemo, useRef, useState } from 'react'
import MouseFollower from 'mouse-follower'
import { gsap } from 'gsap'
import 'mouse-follower/dist/mouse-follower.min.css'
import ParticipantFlow from './components/participant/ParticipantFlow'

type Criterion = { score: number; description: string; examples: string[] }
type Question = { id: string; question: string; dimension: string; criteria: Criterion[] }
type EvidenceSpan = { text: string; start: number; end: number; rule: string }
type ProbeOption = { id: string; label: string }
type CatProbe = {
  version: string
  probe_id: string
  probe_type: string
  target_gap: string
  cat_reflection: string
  cat_tentative_understanding: string
  cat_humility: string
  cat_invitation: string
  options: ProbeOption[]
  free_text_label: string
  pause_label: string
  response_optional?: boolean
}
type ScoreResult = {
  question_id: string
  response: string
  preliminary_score: number
  score_status: string
  evidence_sufficiency: string
  rationale: string
  evidence_spans: EvidenceSpan[]
  confidence: number
  target_gap?: string | null
  clarification_question?: string | null
  safety_state: string
  rubric_version: string
  provider?: string
  model?: string
  probe_type?: string | null
  cat_probe?: CatProbe | null
}
type NextAction = {
  type: 'CONTINUE_SEED' | 'DEFER_CLARIFICATION' | 'CLARIFY_NOW' | 'CONFIRM_NOW' | 'HUMAN_REVIEW' | 'SAFETY_FLOW' | 'COMPLETE'
  question_id?: string | null
  probe_type?: string | null
  question?: string | null
  interaction?: CatProbe | null
  priority?: number
  rationale?: string
}
type GlobalEvidenceState = {
  version: string
  seed_total: number
  seed_answered: number
  probe_count: number
  burden?: {
    max_session_probes?: number
    used_probes?: number
    remaining_probe_budget?: number
    interruption_rate?: number
  }
  constructs: Array<Record<string, unknown>>
  nodes: Array<Record<string, unknown>>
  cross_item_links: Array<Record<string, unknown>>
  unresolved_gaps: Array<Record<string, unknown>>
  next_action: NextAction
  session_intelligence?: SessionIntelligence
  decision_trace?: Record<string, unknown>
  policy_notes?: string[]
}
type SessionIntelligence = {
  status: string
  provider: string
  model: string
  session_summary?: string
  construct_insights?: Array<Record<string, unknown>>
  planning_notes?: string[]
  guardrail_result?: string
}
type ProviderStatus = { mode: string; provider: string; model: string; session_intelligence?: string }
type ResearchSummary = typeof fallbackSummary & { review_queue?: Record<string, number>; evaluation?: Record<string, unknown> }

const fallbackQuestions: Question[] = [
  ['Q01', '过去两周，当我停止做某件事、一个人安静下来的时候，我的情绪是______。', '触发与情绪 · 情绪痛苦强度'],
  ['Q02', '朋友聚会时，一群人有说有笑的时候，我内心感觉______。', '人际负性体验 · 人际疏离感'],
  ['Q03', '看到家人或亲近的人为了我的事情辛苦奔波、付出很多时，我会______。', '人际负性体验 · 人际累赘感'],
  ['Q04', '把内心最真实、最不愿示人的部分展现给某个人之后，______。', '人际负性体验 · 人际归属感'],
  ['Q05', '如果我陷入一段比较长时间的困境或低谷，身边那些原本和我亲近的人会______。', '人际负性体验 · 人际归属感'],
  ['Q06', '我遇到麻烦的时候，我一般会____倾诉/求助。', '情绪调节与应对效能 · 求助意愿'],
  ['Q07', '跟身边的人聊起自己的困扰，对我来说是一件____的事情。', '情绪调节与应对效能 · 求助意愿'],
  ['Q08', '当事情没有达到我的预期时，我会觉得______。', '负性认知加工 · 认知歪曲类型'],
  ['Q09', '当我把一件事搞砸了之后，我认为：______。', '负性认知加工 · 自我认知偏差'],
  ['Q10', '看到别人轻松做到了我拼尽全力也做不好的事，我认为：______。', '负性认知加工 · 自我认知偏差'],
  ['Q11', '如果反复做一件事都做不好，挫败感越来越强的时候，我通常会____。', '情绪调节与应对效能 · 应对方式倾向'],
  ['Q12', '碰到一时半会儿解决不了的问题，我通常会____。', '情绪调节与应对效能 · 综合效能感'],
  ['Q13', '每当消极想法涌上来时，我对待它们的方式是______。', '负性认知加工 · 反刍思维倾向'],
  ['Q14', '如果关系亲密的人对我态度冷淡，我会认为______。', '负性认知加工 · 认知歪曲类型'],
  ['Q15', '当一件事情超出我的掌控范围时，我内心的想法是____。', '情绪调节与应对效能 · 综合效能感'],
  ['Q16', '有人觉得“牵挂”是一种负担，有人觉得“牵挂”是一种依靠。对我来说，牵挂更像是______。', '生存意愿与未来想象 · 生存理由丰富度'],
  ['Q17', '如果让我描述一下五年后的今天自己正在做什么，我心里下意识想到的是______。', '生存意愿与未来想象 · 未来期待度'],
  ['Q18', '假如遇到地震或火灾这样的突发危险，我做出的反应是______。', '生存意愿与未来想象 · 生存矛盾性'],
  ['Q19', '如果我在过马路时，一辆失控的车冲过来，我确定躲不开了，在那一刻我心里涌上来的感觉是______。', '生存意愿与未来想象 · 死亡认知梯度'],
  ['Q20', '如果0分代表“完全不受影响”，10分代表“已经被它渗透到方方面面”，那么近两周那些难受的事情对我的整体生活影响程度，我打______分。', '触发与情绪 · 心理占据强度'],
].map(([id, question, dimension]) => ({ id, question, dimension, criteria: [] }))

const fallbackSummary = {
  participants: 205,
  responses: 4100,
  score_counts: { '0': 2256, '1': 1477, '2': 367 },
  splits: { train: 129, validation: 38, test: 38 },
  questions: fallbackQuestions.map((q, index) => ({ id: q.id, n: 205, mean_score: [0.34, 0.68, 0.46, 0.82, 0.59][index % 5], provisional_candidates: 8 + (index * 7) % 28 })),
}

const scoreLabels = ['0 · 稳定 / 适应', '1 · 需要关注', '2 · 明显负向']

type Screen = 'welcome' | 'assessment' | 'complete'
type View = 'assessment' | 'evidence' | 'research' | 'review' | 'replay'
type Route = Screen | View

const routeNames: Route[] = ['welcome', 'assessment', 'complete', 'evidence', 'research', 'review', 'replay']

function routeFromHash(): Route {
  if (typeof window === 'undefined') return 'welcome'
  const value = window.location.hash.replace(/^#/, '') as Route
  return routeNames.includes(value) ? value : 'welcome'
}

function routeState(route: Route): { screen: Screen; view: View } {
  if (route === 'welcome') return { screen: 'welcome', view: 'assessment' }
  if (route === 'complete') return { screen: 'complete', view: 'assessment' }
  return { screen: 'assessment', view: route as View }
}

function localScore(questionId: string, response: string): ScoreResult {
  const high = ['绝望', '解脱', '负担', '废物', '没用', '等待死亡', '不想活', '自杀', '放弃']
  const mid = ['焦虑', '恐惧', '害怕', '难过', '孤单', '失望', '烦躁', '困难', '随缘', '不知道', '担心']
  const score = questionId === 'Q20' && /^\s*(10|[0-9])/.test(response) ? (Number(response.match(/^\s*(10|[0-9])/)?.[1]) > 8 ? 2 : Number(response.match(/^\s*(10|[0-9])/)?.[1]) > 5 ? 1 : 0) : high.some((x) => response.includes(x)) ? 2 : mid.some((x) => response.includes(x)) ? 1 : 0
  const normalized = response.trim()
  const provisional = questionId === 'Q20'
    ? !/(^|\D)(10|[0-9])(?!\d)/.test(normalized)
    : ['责任', '随缘', '不知道', '还行', '担心', '不清楚', '无所谓', '说不清', '没想法'].includes(normalized)
      || (normalized.length === 1 && questionId !== 'Q07')
  const term = [...high, ...mid].find((x) => response.includes(x))
  return { question_id: questionId, response, preliminary_score: score, score_status: provisional ? 'PROVISIONAL' : 'CONFIRMED', evidence_sufficiency: provisional ? 'INSUFFICIENT' : 'SUFFICIENT', rationale: provisional ? '我还不确定这句话的方向，先记下一个暂时分数。' : `这句话的意思比较清楚，我先按当前规则记为 ${score} 分。`, evidence_spans: term ? [{ text: term, start: response.indexOf(term), end: response.indexOf(term) + term.length, rule: '与该题 rubric 的语义线索匹配' }] : [], confidence: provisional ? 0.48 : 0.78, target_gap: provisional ? '我还不确定这句话指向哪里' : null, clarification_question: provisional ? '可以说说当时的具体感受吗？' : null, safety_state: high.some((x) => ['不想活', '自杀'].includes(x) && response.includes(x)) ? 'SAFETY_REVIEW' : 'CLEAR', rubric_version: '1.0.0' }
}

function ScorePill({ score }: { score: number }) {
  return <span className={`score-pill score-${score}`}>{score}分</span>
}

function App() {
  const [questions, setQuestions] = useState<Question[]>(fallbackQuestions)
  const [summary, setSummary] = useState(fallbackSummary)
  const initialRoute = routeFromHash()
  const [screen, setScreen] = useState<Screen>(() => routeState(initialRoute).screen)
  const [view, setView] = useState<View>(() => routeState(initialRoute).view)
  const [selected, setSelected] = useState(0)
  const [response, setResponse] = useState('')
  const [result, setResult] = useState<ScoreResult | null>(null)
  const [clarification, setClarification] = useState('')
  const [submitted, setSubmitted] = useState<Record<string, ScoreResult>>({})
  const [cases, setCases] = useState<Array<Record<string, unknown>>>([])
  const [reviewOffset, setReviewOffset] = useState(0)
  const [reviewHasMore, setReviewHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null)
  const [nextAction, setNextAction] = useState<NextAction>({ type: 'CONTINUE_SEED' })
  const [globalEvidence, setGlobalEvidence] = useState<GlobalEvidenceState | null>(null)
  const [completionHandoff, setCompletionHandoff] = useState(false)
  const [researchToken, setResearchToken] = useState(() => typeof window !== 'undefined' ? window.sessionStorage.getItem('research_access_token') ?? '' : '')
  const [researchTokenDraft, setResearchTokenDraft] = useState(() => typeof window !== 'undefined' ? window.sessionStorage.getItem('research_access_token') ?? '' : '')
  const [researchReady, setResearchReady] = useState(false)
  const [researchLoading, setResearchLoading] = useState(false)
  const [entryTransition, setEntryTransition] = useState(false)

  useEffect(() => {
    fetch('/api/questions').then((res) => res.ok ? res.json() : Promise.reject()).then(setQuestions).catch(() => undefined)
    fetch('/api/provider').then((res) => res.ok ? res.json() : Promise.reject()).then(setProviderStatus).catch(() => undefined)

    const syncRoute = () => {
      const next = routeState(routeFromHash())
      setScreen(next.screen)
      setView(next.view)
    }
    if (typeof window !== 'undefined') {
      if (!window.location.hash) window.history.replaceState(null, '', '#welcome')
      window.addEventListener('hashchange', syncRoute)
      return () => window.removeEventListener('hashchange', syncRoute)
    }
  }, [])

  useEffect(() => {
    if (!researchToken) {
      setResearchReady(false)
      return
    }
    setResearchLoading(true)
    const headers = { 'X-Research-Token': researchToken }
    Promise.all([
      fetch('/api/research/summary', { headers }).then((res) => res.ok ? res.json() : Promise.reject()),
      fetch('/api/review/cases?limit=200&offset=0', { headers }).then((res) => res.ok ? res.json() : Promise.reject()),
    ]).then(([nextSummary, nextCases]) => {
      setSummary(nextSummary as ResearchSummary)
      setCases(nextCases)
      setReviewOffset(Array.isArray(nextCases) ? nextCases.length : 0)
      setReviewHasMore(Array.isArray(nextCases) && nextCases.length === 200)
      setResearchReady(true)
    }).catch(() => {
      setResearchReady(false)
    }).finally(() => setResearchLoading(false))
  }, [researchToken])

  const refreshReviewCases = async () => {
    if (!researchToken) return
    const res = await fetch('/api/review/cases?limit=200&offset=0', { headers: { 'X-Research-Token': researchToken } })
    if (!res.ok) return
    const nextCases = await res.json() as Array<Record<string, unknown>>
    setCases(nextCases)
    setReviewOffset(nextCases.length)
    setReviewHasMore(nextCases.length === 200)
  }

  const loadMoreReviewCases = async () => {
    if (!researchToken || !reviewHasMore) return
    const res = await fetch(`/api/review/cases?limit=200&offset=${reviewOffset}`, { headers: { 'X-Research-Token': researchToken } })
    if (!res.ok) return
    const nextCases = await res.json() as Array<Record<string, unknown>>
    setCases((previous) => [...previous, ...nextCases])
    setReviewOffset((previous) => previous + nextCases.length)
    setReviewHasMore(nextCases.length === 200)
  }

  useEffect(() => {
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }, [screen, view, selected])

  const question = questions[selected] ?? fallbackQuestions[0]
  const answered = Object.keys(submitted).length
  const currentResult = result ?? submitted[question.id]
  const scoreDistribution = useMemo(() => Object.entries(summary.score_counts).map(([score, count]) => ({ score: Number(score), count: Number(count) })), [summary])

  const runScore = async (text = response, isClarification = false, requestedProbeType?: string | null, probeOptionId?: string | null, probeAction: 'ANSWER' | 'PAUSE' = 'ANSWER') => {
    if (!text.trim()) return
    setLoading(true)
    setErrorMessage('')
    try {
      const endpoint = sessionId ? `/api/assessment/${sessionId}/responses` : '/api/score'
      const requestText = text
      const requestBody = { question_id: question.id, response: requestText, ...(sessionId ? { clarification: isClarification, ...(requestedProbeType ? { probe_type: requestedProbeType } : {}), ...(probeOptionId ? { probe_option_id: probeOptionId } : {}), ...(isClarification ? { probe_action: probeAction } : {}) } : {}) }
      const res = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody) })
      if (!res.ok) {
        const body = await res.json().catch(() => null) as { detail?: unknown } | null
        const detail = typeof body?.detail === 'string' ? body.detail : `服务暂时没有接住这句话（${res.status}）`
        throw new Error(detail)
      }
      const payload = await res.json()
      setErrorMessage('')
      const next: ScoreResult = sessionId && payload.score ? payload.score : payload
      const action = sessionId && payload.next_action ? payload.next_action as NextAction : { type: 'CONTINUE_SEED' as const }
      if (sessionId && payload.global_evidence) setGlobalEvidence(payload.global_evidence as GlobalEvidenceState)
      setNextAction(action)
      setResult(next)
      setSubmitted((prev) => ({ ...prev, [question.id]: next }))
      const seedFinished = Number(payload.global_evidence?.seed_answered ?? 0) >= questions.length
      if (seedFinished) setCompletionHandoff(true)
      if (sessionId && !seedFinished && action.question_id && ['CLARIFY_NOW', 'CONFIRM_NOW'].includes(action.type) && action.question_id !== question.id) {
        const targetIndex = questions.findIndex((item) => item.id === action.question_id)
        if (targetIndex >= 0) {
          setSelected(targetIndex)
          setResult(null)
          setResponse(submitted[action.question_id]?.response ?? '')
          setClarification('')
        }
      }
    } catch (error) {
      // Once a session exists, never silently downgrade a failed probe to the
      // stateless local scorer: doing so would make the participant think the
      // cat heard them while leaving the audit chain incomplete. The local
      // fallback remains available only when a session could not be started.
      if (sessionId) {
        setErrorMessage(error instanceof Error ? error.message : '服务暂时不可用，请稍后再试。')
        return
      }
      const next = localScore(question.id, text)
      setResult(isClarification ? { ...next, rationale: `${next.rationale} 已纳入补充回答，等待专家确认。` } : next)
      setSubmitted((prev) => ({ ...prev, [question.id]: next }))
      setNextAction({ type: next.score_status === 'PROVISIONAL' ? 'CLARIFY_NOW' : 'CONTINUE_SEED', question_id: next.score_status === 'PROVISIONAL' ? question.id : null, probe_type: next.score_status === 'PROVISIONAL' ? 'CLARIFICATION' : null, question: next.clarification_question })
    } finally { setLoading(false) }
  }

  const startAssessment = async () => {
    if (entryTransition) return
    setEntryTransition(true)
    // A new visit starts a fresh participant session. This also clears a
    // previous safety gate so the decorative companion cannot leak into (or
    // disappear from) the wrong session state.
    setSessionId(null)
    setSelected(0)
    setResponse('')
    setClarification('')
    setResult(null)
    setSubmitted({})
    setGlobalEvidence(null)
    setCompletionHandoff(false)
    setNextAction({ type: 'CONTINUE_SEED' })
    setErrorMessage('')
    await new Promise((resolve) => window.setTimeout(resolve, 760))
    navigate('assessment')
    setEntryTransition(false)
    try {
      const res = await fetch('/api/assessment/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'participant' }) })
      if (res.ok) {
        const payload = await res.json()
        if (payload?.id) setSessionId(String(payload.id))
      }
    } catch { /* local session is still usable */ }
  }

  const navigate = (route: Route) => {
    if (typeof window !== 'undefined' && window.location.hash !== `#${route}`) window.location.hash = route
    const next = routeState(route)
    setScreen(next.screen)
    setView(next.view)
  }

  const selectQuestion = (index: number) => {
    if (safetyFlowActive) return
    const item = questions[index]
    setSelected(index)
    setResult(null)
    setResponse(item ? submitted[item.id]?.response ?? '' : '')
    setClarification('')
    setErrorMessage('')
    navigate('assessment')
  }
  const continueAfterCompletion = () => {
    setCompletionHandoff(false)
    if (!safetyFlowActive && ['CLARIFY_NOW', 'CONFIRM_NOW'].includes(nextAction.type) && nextAction.question_id) {
      const targetIndex = questions.findIndex((item) => item.id === nextAction.question_id)
      if (targetIndex >= 0) {
        const target = questions[targetIndex]
        setSelected(targetIndex)
        setResult(submitted[target.id] ?? null)
        setResponse(submitted[target.id]?.response ?? '')
        setClarification('')
        setErrorMessage('')
        navigate('assessment')
        return
      }
    }
    navigate('assessment')
  }
  const nextQuestion = () => {
    if (safetyFlowActive) return
    const seedFinished = answered >= questions.length || Number(globalEvidence?.seed_answered ?? 0) >= questions.length
    if (selected >= questions.length - 1 && seedFinished) {
      navigate('complete')
      return
    }
    if (['CLARIFY_NOW', 'CONFIRM_NOW'].includes(nextAction.type) && nextAction.question_id) {
      const targetIndex = questions.findIndex((item) => item.id === nextAction.question_id)
      if (targetIndex >= 0 && targetIndex !== selected) {
        selectQuestion(targetIndex)
        return
      }
    }
    if (selected >= questions.length - 1) navigate('complete')
    else selectQuestion(selected + 1)
  }
  const openView = (nextView: View) => {
    if (nextView === 'assessment') setCompletionHandoff(false)
    navigate(nextView)
  }
  const unlockResearch = () => {
    const value = researchTokenDraft.trim()
    if (typeof window !== 'undefined') {
      if (value) window.sessionStorage.setItem('research_access_token', value)
      else window.sessionStorage.removeItem('research_access_token')
    }
    setResearchToken(value)
  }

  const participantView = view === 'assessment' || view === 'evidence' || view === 'replay'
  const participantSurface = screen === 'welcome' || (screen === 'assessment' && participantView)
  const playfulSurface = screen === 'welcome' || screen === 'complete' || (screen === 'assessment' && view === 'assessment')
  const safetyFlowActive = nextAction.type === 'SAFETY_FLOW' || (result?.safety_state !== undefined && result.safety_state !== 'CLEAR')
  const catPlayfulSurface = playfulSurface && !safetyFlowActive

  return (
    <main className={`app-shell ${screen === 'welcome' ? 'landing-active' : ''} ${screen === 'assessment' && participantView ? 'participant-active' : ''}`}>
      <PlayfulCursor key={`${screen}-${view}`} enabled={catPlayfulSurface} />
      <OnekoCat enabled={catPlayfulSurface && (screen === 'welcome' || screen === 'complete' || entryTransition || (screen === 'assessment' && view === 'assessment'))} transitioning={entryTransition} region={screen === 'assessment' && view === 'assessment' ? '[data-oneko-region]' : undefined} />
      <PlayfulInteractions enabled={catPlayfulSurface} />
      <header className="topbar">
        <button className="brand brand-button" type="button" data-cursor="-text" data-cursor-text="回到开始" onClick={() => navigate('welcome')}><span className="brand-mark">✳</span><span>听见自己</span><small>留一点时间给自己</small></button>
        <div className="topbar-actions">
          {screen === 'assessment' && <button className="header-quiet" type="button" data-cursor="-text" data-cursor-text="暂离" onClick={() => navigate('welcome')}>暂离</button>}
          <div className="top-status"><span className="status-dot" /> 只留在这里 <span className="divider" /> <span className="ai-status">{providerStatus?.mode === 'llm' ? `AI 已连接 · ${providerStatus.model}${providerStatus.session_intelligence === 'llm-advisory' ? ' · 会话编排已启用' : ''}` : 'AI 评分准备中'}</span><span className="divider" /> <span className="mono">PRIVATE SESSION</span></div>
        </div>
      </header>
      {screen === 'welcome' && <WelcomeView onStart={startAssessment} />}
      {screen === 'complete' && <CompletionView answered={answered} submitted={submitted} globalEvidence={globalEvidence} nextAction={nextAction} onContinue={continueAfterCompletion} onEvidence={() => openView('evidence')} onReplay={() => openView('replay')} />}
      {screen === 'assessment' && <div className={`workspace ${participantView ? 'participant-workspace' : 'research-workspace'}`}>
        {participantView && <ParticipantAtmosphere />}
        {participantView && <QuestionDirectory questions={questions} selected={selected} answered={answered} submitted={submitted} onSelect={selectQuestion} disabled={safetyFlowActive} />}
        <section className="main-panel">
          <nav className="view-tabs" aria-label="页面导航">
            <div className="participant-tabs">
              {([['assessment', '继续']] as Array<[View, string]>).map(([id, label]) => <button key={id} className={view === id ? 'selected' : ''} onClick={() => openView(id)}>{label}</button>)}
            </div>
            <div className="research-tabs">
              <span className="research-label">研究空间</span>
              {([['research', '研究台'], ['review', '专家工作']] as Array<[View, string]>).map(([id, label]) => <button key={id} className={view === id ? 'selected' : ''} onClick={() => openView(id)}>{label}</button>)}
            </div>
          </nav>
          {view === 'assessment' && <ParticipantFlow initialStage="question" suppressProbe={completionHandoff} onComplete={nextQuestion} totalQuestions={questions.length} question={question} selected={selected} response={response} setResponse={setResponse} result={currentResult} nextAction={nextAction} clarification={clarification} setClarification={setClarification} runScore={runScore} loading={loading} errorMessage={errorMessage} onNext={nextQuestion} />}
          {view === 'evidence' && <EvidenceView question={question} result={currentResult} response={response} globalEvidence={globalEvidence} />}
          {view === 'research' && <ResearchView summary={summary} distribution={scoreDistribution} tokenDraft={researchTokenDraft} setTokenDraft={setResearchTokenDraft} onUnlock={unlockResearch} ready={researchReady} loading={researchLoading} />}
          {view === 'review' && <ReviewView cases={cases} token={researchToken} onReviewed={refreshReviewCases} onLoadMore={loadMoreReviewCases} hasMore={reviewHasMore} tokenDraft={researchTokenDraft} setTokenDraft={setResearchTokenDraft} onUnlock={unlockResearch} ready={researchReady} loading={researchLoading} />}
          {view === 'replay' && <ReplayView submitted={submitted} questions={questions} />}
        </section>
      </div>}
    </main>
  )
}

function QuestionDirectory({ questions, selected, answered, submitted, onSelect, disabled = false }: { questions: Question[]; selected: number; answered: number; submitted: Record<string, ScoreResult>; onSelect: (index: number) => void; disabled?: boolean }) {
  const [hovered, setHovered] = useState(false)
  const [pinned, setPinned] = useState(false)
  const open = hovered || pinned

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPinned(false)
        setHovered(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  return <div className={`directory-peek ${open ? 'is-open' : ''}`} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
    <button className="directory-peek-tab" type="button" aria-expanded={open} aria-label={pinned ? '取消固定答题目录' : '打开答题目录'} onClick={() => setPinned((value) => !value)}>
      <span className="directory-peek-glyph">☷</span>
      <strong>{answered.toString().padStart(2, '0')}</strong>
      <span>/ {questions.length}</span>
    </button>
    <aside className="directory-drawer" aria-hidden={!open}>
      <div className="directory-heading"><span>回答轨迹</span><strong>{answered.toString().padStart(2, '0')} / {questions.length}</strong><button className="directory-close" type="button" aria-label="收起答题目录" onClick={() => { setPinned(false); setHovered(false) }}>×</button></div>
      <div className="progress-track"><span style={{ width: `${questions.length ? (answered / questions.length) * 100 : 0}%` }} /></div>
      <div className="directory-list">
        {questions.map((item, index) => <button key={item.id} title={`${item.id} · ${item.dimension}`} aria-label={`${item.id} ${item.dimension.split(' · ')[1] ?? item.dimension}${submitted[item.id] ? ' 已记录' : ''}`} className={`directory-item ${index === selected ? 'active' : ''} ${submitted[item.id] ? 'done' : ''}`} disabled={disabled} onClick={() => { onSelect(index); setPinned(false); setHovered(false) }}><span className="q-number">{item.id.slice(1)}</span><span className="directory-item-label">{item.dimension.split(' · ')[1] ?? item.dimension}</span>{submitted[item.id] && <span className="directory-item-check">✓</span>}</button>)}
      </div>
      <div className="directory-hint"><span>♡</span> 随时回到某一题</div>
    </aside>
  </div>
}

function PlayfulCursor({ enabled }: { enabled: boolean }) {
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return
    if (window.matchMedia('(pointer: coarse)').matches || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    MouseFollower.registerGSAP(gsap)
    const cursor = new MouseFollower({
      speed: 0.42,
      ease: 'expo.out',
      skewing: 1,
      skewingText: 1.2,
      skewingIcon: 1,
      stickDelta: 0.16,
      initialPos: [window.innerWidth - 72, window.innerHeight - 72],
      stateDetection: { '-pointer': 'button, a, textarea' },
    })
    return () => cursor.destroy()
  }, [enabled])
  return null
}

/**
 * Small open-source companion from adryd325/oneko.js. It is intentionally
 * used on the welcome scene and the participant's companion area. The cat
 * remains constrained away from the question and textarea.
 */
function OnekoCat({ enabled, transitioning, region }: { enabled: boolean; transitioning: boolean; region?: string }) {
  useEffect(() => {
    if (!enabled || typeof document === 'undefined' || typeof window === 'undefined') return
    if (window.matchMedia('(pointer: coarse)').matches || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const existing = document.getElementById('oneko-loader')
    if (existing) return
    const script = document.createElement('script')
    script.id = 'oneko-loader'
    script.src = '/vendor/oneko/oneko.js'
    script.dataset.cat = '/vendor/oneko/oneko.gif'
    script.dataset.anchor = '[data-oneko-anchor]'
    if (region) script.dataset.region = region
    script.dataset.persistPosition = 'false'
    document.body.appendChild(script)
    return () => {
      document.getElementById('oneko')?.remove()
      script.remove()
    }
  }, [enabled, region])
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return
    const applyState = () => {
      const cat = document.getElementById('oneko')
      if (!cat) return false
      cat.classList.toggle('oneko-transitioning', transitioning)
      return true
    }
    if (applyState()) return
    const timer = window.setTimeout(applyState, 50)
    return () => window.clearTimeout(timer)
  }, [enabled, transitioning])
  return null
}

type ParticleVariant = 'spark' | 'leaf' | 'heart' | 'firefly' | 'ripple'

function PlayfulInteractions({ enabled }: { enabled: boolean }) {
  useEffect(() => {
    if (!enabled || typeof document === 'undefined' || typeof window === 'undefined') return
    if (window.matchMedia('(pointer: coarse)').matches || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const root = document.body
    const isQuestionBody = (target: Element | null) => Boolean(target?.closest('.assessment-view h1, .assessment-view textarea'))
    let lastSpeechAt = 0
    const chooseVariant = (target: Element | null): ParticleVariant => {
      if (target?.closest('.landing-primary, .primary-button, .secondary-button')) return 'spark'
      if (target?.closest('.brand, .header-quiet')) return 'heart'
      if (target?.closest('.question-nav, .view-tabs button')) return 'firefly'
      if (target?.closest('.score-panel, .clarify-box')) return 'heart'
      return 'leaf'
    }
    const spawnParticles = (x: number, y: number, variant: ParticleVariant, amount = 5) => {
      const symbols: Record<ParticleVariant, string[]> = {
        spark: ['✦', '✧', '·', '✦'],
        leaf: ['❧', '·', '✿', '⌁'],
        heart: ['♡', '♥', '·', '♡'],
        firefly: ['·', '•', '✧', '·'],
        ripple: ['◌', '○', '◦', '·'],
      }
      const palette: Record<ParticleVariant, string[]> = {
        spark: ['#f0a27f', '#f6d78d', '#f8efe4'],
        leaf: ['#6f9a70', '#9bbf86', '#d5e1b4'],
        heart: ['#e88978', '#efb18b', '#f8ddd1'],
        firefly: ['#f5d875', '#dce9a8', '#fff4be'],
        ripple: ['#d9e5c9', '#f2eee0', '#bdd3b4'],
      }
      for (let index = 0; index < amount; index += 1) {
        const particle = document.createElement('span')
        particle.className = `playful-particle particle-${variant}`
        particle.textContent = symbols[variant][index % symbols[variant].length]
        particle.style.left = `${x}px`
        particle.style.top = `${y}px`
        particle.style.color = palette[variant][index % palette[variant].length]
        particle.style.setProperty('--dx', `${Math.round((Math.random() - .5) * (variant === 'firefly' ? 70 : 110))}px`)
        particle.style.setProperty('--dy', `${Math.round(-24 - Math.random() * (variant === 'ripple' ? 20 : 72))}px`)
        particle.style.setProperty('--delay', `${Math.round(Math.random() * 90)}ms`)
        root.appendChild(particle)
        window.setTimeout(() => particle.remove(), variant === 'firefly' ? 1300 : 980)
      }
    }
    const speakCat = (message: string) => {
      const cat = document.getElementById('oneko')
      if (!cat || !message) return
      if (document.visibilityState === 'hidden' || document.activeElement?.matches('textarea')) return
      const now = window.performance.now()
      if (now - lastSpeechAt < 1400) return
      lastSpeechAt = now
      root.querySelectorAll('.cat-bubble').forEach((node) => node.remove())
      const rect = cat.getBoundingClientRect()
      const bubble = document.createElement('span')
      bubble.className = 'cat-bubble'
      bubble.textContent = message
      bubble.style.left = `${Math.min(window.innerWidth - 170, Math.max(12, rect.left + rect.width * .16))}px`
      bubble.style.top = `${Math.max(12, rect.top - 40)}px`
      root.appendChild(bubble)
      window.setTimeout(() => bubble.remove(), 1650)
    }
    const onCatMessage = (event: Event) => {
      const message = (event as CustomEvent<{ message?: string }>).detail?.message
      if (message) speakCat(message)
    }
    const triggerCat = (mood: 'hop' | 'spin' | 'dash' | 'wave' | 'sleep' | 'peek' | 'celebrate', message?: string) => {
      const cat = document.getElementById('oneko')
      if (!cat) return
      const classes = ['cat-hop', 'cat-spin', 'cat-dash', 'cat-wave', 'cat-sleep', 'cat-peek', 'cat-celebrate']
      cat.classList.remove(...classes)
      // Force a fresh animation when a user clicks repeatedly.
      void cat.offsetWidth
      cat.classList.add(`cat-${mood}`)
      window.setTimeout(() => cat.classList.remove(`cat-${mood}`), mood === 'sleep' ? 2200 : 920)
      const rect = cat.getBoundingClientRect()
      const emote = document.createElement('span')
      emote.className = 'cat-emote'
      emote.textContent = { hop: '✦', spin: '◎', dash: '➜', wave: '♡', sleep: 'zZ', peek: '…', celebrate: '✧' }[mood]
      emote.style.left = `${rect.left + rect.width / 2}px`
      emote.style.top = `${rect.top - 8}px`
      root.appendChild(emote)
      window.setTimeout(() => emote.remove(), 1050)
      if (message) speakCat(message)
    }
    const onClick = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null
      if (isQuestionBody(target)) return
      const variant = chooseVariant(target)
      const amount = target?.closest('button, a, .question-nav, .view-tabs button') ? 6 : 4
      spawnParticles(event.clientX, event.clientY, variant, amount)
      if (target?.closest('button, a, .question-nav, .view-tabs button')) {
        triggerCat(target.closest('.landing-primary, .primary-button') ? 'celebrate' : 'hop')
      } else if (target?.closest('.landing-scene')) {
        triggerCat('peek')
      } else if (target?.closest('.participant-workspace')) {
        triggerCat('peek')
      }
    }
    const onDoubleClick = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null
      if (isQuestionBody(target)) return
      spawnParticles(event.clientX, event.clientY, 'heart', 10)
      triggerCat('spin')
    }
    const onPointerMove = (event: PointerEvent) => {
      const target = event.target instanceof Element ? event.target : null
      if (!target?.closest('.landing-scene, .completion-scene, .participant-workspace') || isQuestionBody(target)) return
      if (Math.random() > .035) return
      spawnParticles(event.clientX, event.clientY, 'firefly', 1)
    }
    const idleTimer = window.setInterval(() => {
      if (!document.getElementById('oneko')) return
      const moods: Array<'hop' | 'spin' | 'dash' | 'wave' | 'sleep' | 'peek' | 'celebrate'> = ['hop', 'wave', 'peek', 'sleep']
      triggerCat(moods[Math.floor(Math.random() * moods.length)])
    }, 9000)
    root.addEventListener('click', onClick, true)
    root.addEventListener('dblclick', onDoubleClick, true)
    root.addEventListener('pointermove', onPointerMove, { passive: true })
    window.addEventListener('cat:message', onCatMessage)
    return () => {
      root.removeEventListener('click', onClick, true)
      root.removeEventListener('dblclick', onDoubleClick, true)
      root.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('cat:message', onCatMessage)
      window.clearInterval(idleTimer)
      root.querySelectorAll('.playful-particle, .cat-emote, .cat-bubble').forEach((node) => node.remove())
    }
  }, [enabled])
  return null
}

function ParticipantAtmosphere() {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const promise = video.play()
    promise?.catch(() => undefined)
  }, [])
  return <div className="participant-atmosphere" aria-hidden="true">
    <video ref={videoRef} src="/user-references/assessment-atmosphere.mp4" poster="/user-references/assessment-atmosphere.jpg" muted playsInline loop preload="metadata" />
    <div className="participant-atmosphere-wash" />
    <div className="participant-atmosphere-grain" />
  </div>
}

function WelcomeView({ onStart }: { onStart: () => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [leaving, setLeaving] = useState(false)
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const promise = video.play()
    promise?.catch(() => undefined)
  }, [])
  const handleStart = () => {
    if (leaving) return
    setLeaving(true)
    onStart()
  }
  return <section className={`landing-scene ${leaving ? 'landing-leaving' : ''}`}>
    <video ref={videoRef} className="landing-video" src="/user-references/ref1.mp4" poster="/user-references/ref1.jpg" muted playsInline loop preload="metadata" aria-hidden="true" />
    <div className="landing-wash" />
    <div className="landing-grain" />
    <div className="landing-content">
      <div className="landing-kicker"><span className="landing-kicker-dot" /> A QUIET PLACE TO BEGIN <span className="landing-kicker-line" /> <span>01 / 20</span></div>
      <h1><span>听见</span><em>自己</em></h1>
      <p className="landing-lede">写下此刻，从一句话开始</p>
      <div className="landing-actions">
        <button className="landing-primary" type="button" data-oneko-anchor data-cursor="-text" data-cursor-text="开始" onClick={handleStart}>开始 <span>↗</span></button>
        <span className="landing-cat-note"><span>♡</span> 喵～ 慢慢来就好</span>
      </div>
    </div>
    <div className="landing-footer"><span>听见自己</span><span className="landing-footer-center">从这里开始 <span>↓</span></span><span>约 10 分钟 · 随时暂停</span></div>
  </section>
}

function CompletionView({ answered, submitted, globalEvidence, nextAction, onContinue, onEvidence, onReplay }: { answered: number; submitted: Record<string, ScoreResult>; globalEvidence: GlobalEvidenceState | null; nextAction: NextAction; onContinue: () => void; onEvidence: () => void; onReplay: () => void }) {
  const humanReview = Object.values(submitted).filter((item) => item.score_status === 'HUMAN_REVIEW').length
  const unresolved = globalEvidence?.unresolved_gaps ?? []
  const constructs = globalEvidence?.constructs ?? []
  const safety = nextAction.type === 'SAFETY_FLOW' || Object.values(submitted).some((item) => item.safety_state !== 'CLEAR')
  const summary = globalEvidence?.session_intelligence?.session_summary
  const canContinueProbe = !safety && unresolved.length > 0 && ['CLARIFY_NOW', 'CONFIRM_NOW'].includes(nextAction.type) && Boolean(nextAction.question_id)
  const headline = safety
    ? '先停在这里，剩下的交给专业人员。'
    : unresolved.length > 0
      ? '20句话已经走完，还有几处值得再听听。'
      : humanReview > 0
        ? '20句话已经走完，有些地方先留给专业人员复核。'
        : '20句话已经汇成一张证据地图。'
  const detail = safety
    ? '这次对话不会继续自动追问；如果你愿意，可以在专业人员陪伴下继续。'
    : unresolved.length > 0
      ? `小猫没有急着替你下结论，当前还有 ${unresolved.length} 个节点保留着自己的声音。`
      : '每一条回答都留在会话里，之后可以回看它们怎样彼此照见。'
  return <section className="completion-scene"><div className="completion-backdrop"><img src="/user-references/ref3.jpg" alt="抽象的安静旅程插画" /></div><div className="completion-overlay" /><div className="completion-inner"><div className="completion-kicker"><span className="landing-kicker-dot" /> SESSION EVIDENCE MAP</div><h1>谢谢你，<br /><em>让自己被听见。</em></h1><p>{headline}</p><div className="completion-stats"><div><strong>{answered}</strong><span>已记录</span></div><div><strong>{globalEvidence?.probe_count ?? 0}</strong><span>次靠近</span></div><div><strong>{unresolved.length}</strong><span>保留未决</span></div></div><div className="completion-session-card"><div className="completion-session-heading"><span className="box-kicker">整场评估的回声</span><span className="completion-session-status">{safety ? '专业流程' : unresolved.length ? '仍可求证' : humanReview ? '等待复核' : '已收束'}</span></div><p>{summary || detail}</p><div className="completion-constructs">{constructs.map((construct, index) => <div className="completion-construct" key={String(construct.id ?? index)}><div><strong>{String(construct.label ?? construct.id ?? '未分类')}</strong><span>{String(construct.status ?? 'UNANSWERED')}</span></div><small>{String(construct.answered ?? 0)} 题 · 证据 {Math.round(Number(construct.evidence_density ?? 0) * 100)}%</small><i><span style={{ width: `${Math.min(100, Number(construct.evidence_density ?? 0) * 100)}%` }} /></i></div>)}</div>{!safety && unresolved.length > 0 && <div className="completion-unresolved"><span className="box-kicker">下一步</span><span>可以再靠近一处，也可以先把整场地图收好。</span></div>}</div><div className="completion-actions"><button className="landing-primary" type="button" onClick={canContinueProbe ? onContinue : onEvidence}>{canContinueProbe ? '继续靠近一处' : '看整场地图'} <span>↗</span></button><button className="landing-secondary light" type="button" onClick={onReplay}>回看回答 <span>↺</span></button><button className="landing-secondary light" type="button" onClick={canContinueProbe ? onEvidence : onContinue}>{canContinueProbe ? '先收好地图' : '稍后'} <span>→</span></button></div></div><div className="completion-corner">SESSION TRACE <span /> {globalEvidence ? `${globalEvidence.seed_answered} / ${globalEvidence.seed_total}` : `${answered} / 20`}</div></section>
}

function AssessmentView({ question, selected, response, setResponse, result, clarification, setClarification, runScore, loading, onNext }: { question: Question; selected: number; response: string; setResponse: (v: string) => void; result?: ScoreResult; clarification: string; setClarification: (v: string) => void; runScore: (text?: string, isClarification?: boolean) => void; loading: boolean; onNext: () => void }) {
  return <div className="assessment-view"><img className="framebase-reference" src="/mindful-companion.webp" alt="" aria-hidden="true" /><div className="eyebrow"><span>第 {question.id.slice(1)} 题 / 20</span><span className="eyebrow-line" /><span>{question.dimension}</span></div><h1>{question.question}</h1><div className="answer-layout"><div className="answer-column"><label htmlFor="response">第一句话</label><textarea id="response" value={response} onChange={(event) => setResponse(event.target.value)} placeholder="从几个字开始，也很好" /><div className="answer-actions"><span className="char-count">{response.length} / 5000</span><button className="primary-button" onClick={() => runScore()} disabled={!response.trim() || loading}>{loading ? '读一读…' : '继续'} <span>→</span></button></div>{result && result.score_status === 'PROVISIONAL' && <div className="clarify-box"><div className="box-kicker"><span className="warning-dot" /> 我还想听清楚一点</div><p>{result.target_gap}。我不替你猜。</p><label htmlFor="clarification">如果愿意，再说一句</label><div className="clarification-question">{result.clarification_question}</div><textarea id="clarification" className="clarification-input" value={clarification} onChange={(event) => setClarification(event.target.value)} placeholder="一个时刻、一个对象，或一种感受" /><button className="secondary-button" disabled={!clarification.trim()} onClick={() => runScore(`${response}；补充：${clarification}`, true)}>继续 <span>↗</span></button></div>}{result && <div className="next-row"><button className="ghost-button" onClick={onNext}>下一句 <span>→</span></button><span>可随时回看</span></div>}</div><ScorePanel result={result} /></div></div>
}

function ScorePanel({ result }: { result?: ScoreResult }) {
  if (!result) return <aside className="score-companion" data-oneko-region aria-label="等待第一句回答">
    <span className="score-companion-anchor" data-oneko-anchor aria-hidden="true" />
  </aside>
  const label = result.safety_state !== 'CLEAR' ? '先停一下' : result.score_status === 'CONFIRMED' ? '比较清楚' : result.score_status === 'HUMAN_REVIEW' ? '暂留复核' : '还想确认'
  return <aside className={`score-panel score-panel-${result.score_status.toLowerCase()}`}><div className="panel-top"><span className="box-kicker">我对这句话的暂时理解</span><span className={`state-label ${result.score_status.toLowerCase()}`}>{label}</span></div><div className="score-display"><ScorePill score={result.preliminary_score} /><strong>{scoreLabels[result.preliminary_score].split(' · ')[1]}</strong></div><div className="confidence-row"><span>理解的把握</span><strong>{Math.round(result.confidence * 100)}%</strong><div className="confidence-bar"><span style={{ width: `${result.confidence * 100}%` }} /></div></div><div className="panel-rule" /><span className="box-kicker">我为什么这样理解</span><p className="rationale">{result.rationale}</p><div className="evidence-status"><span className={result.evidence_sufficiency === 'SUFFICIENT' ? 'check' : 'warning'}>{result.evidence_sufficiency === 'SUFFICIENT' ? '✓' : '!'}</span><span>{result.evidence_sufficiency === 'SUFFICIENT' ? '这句话的信息够清楚了' : '我不想替你脑补'}</span></div>{result.safety_state !== 'CLEAR' && <div className="safety-alert">我会先把这句话交给专业人员，不继续自动追问。</div>}<button className="text-button" type="button">看看我读到的依据 <span>↗</span></button>{result.model && <span className="model-note">由 {result.model} 辅助理解</span>}</aside>
}

function EvidenceView({ question, result, response, globalEvidence }: { question: Question; result?: ScoreResult; response: string; globalEvidence: GlobalEvidenceState | null }) {
  const constructs = globalEvidence?.constructs ?? []
  const unresolved = globalEvidence?.unresolved_gaps ?? []
  const intelligence = globalEvidence?.session_intelligence
  return <div className="detail-view"><div className="eyebrow"><span>EVIDENCE MAP</span><span className="eyebrow-line" /><span>{question.id} · SESSION</span></div><h2>让每一个分数都能被重放</h2><p className="view-intro">单题证据保持 rubric-local；跨题信号只用于决定下一步如何求证。</p><div className="chain"><div className="chain-step"><span className="chain-index">01</span><div><span className="box-kicker">原始回答</span><p>{result?.response || response || '尚未提交回答'}</p></div></div><div className="chain-connector" /><div className="chain-step"><span className="chain-index">02</span><div><span className="box-kicker">原文证据</span>{result?.evidence_spans.length ? result.evidence_spans.map((span) => <p className="evidence-quote" key={`${span.start}-${span.end}`}><mark>{span.text}</mark><small>{span.rule} · chars {span.start}–{span.end}</small></p>) : <p className="muted">评分后会在此标记证据片段。</p>}</div></div><div className="chain-connector" /><div className="chain-step"><span className="chain-index">03</span><div><span className="box-kicker">rubric 对照</span><p>{question.criteria?.find((criterion) => criterion.score === result?.preliminary_score)?.description || '该题的 0/1/2 特征描述来自专家源文档，当前版本可在 rubric 文件中复核。'}</p></div></div><div className="chain-connector" /><div className="chain-step"><span className="chain-index">04</span><div><span className="box-kicker">可靠性决定</span><p className={result?.score_status === 'PROVISIONAL' ? 'highlight-text' : ''}>{result ? `${result.score_status} · Evidence ${result.evidence_sufficiency} · ${Math.round(result.confidence * 100)}% confidence` : '等待评分'}</p></div></div></div><section className="session-evidence-map"><div className="section-heading"><strong>整场评估的证据地图</strong><span>{globalEvidence ? `${globalEvidence.seed_answered} / ${globalEvidence.seed_total} seed · ${globalEvidence.probe_count} probes` : '等待会话'}</span></div><div className="construct-map">{constructs.map((construct, index) => <div className="construct-card" key={String(construct.id ?? index)}><div className="construct-card-top"><span>{String(construct.label ?? construct.id)}</span><strong>{construct.score_mean == null ? '—' : Number(construct.score_mean).toFixed(2)}</strong></div><div className="construct-card-meta"><span>{String(construct.answered ?? 0)} answered</span><span>{String(construct.status ?? 'UNANSWERED')}</span><span>证据 {Math.round(Number(construct.evidence_density ?? 0) * 100)}%</span></div><div className="construct-card-bar"><span style={{ width: `${Math.min(100, Number(construct.evidence_density ?? 0) * 100)}%` }} /></div></div>)}</div>{unresolved.length > 0 && <div className="unresolved-strip"><span className="box-kicker">当前未决节点</span>{unresolved.slice(0, 6).map((item, index) => <span className="unresolved-chip" key={`${String(item.question_id)}-${index}`}><b>{String(item.question_id)}</b> {String(item.probe_type ?? item.status)} · {Math.round(Number(item.priority ?? 0) * 100)}%</span>)}</div>}{globalEvidence && <p className="map-footnote">跨题关联 {globalEvidence.cross_item_links.length} 条；这些关联用于编排策略，不改变任何单题分数。</p>}{intelligence && <div className="ai-session-note"><div className="section-heading"><strong>会话级 AI 参与</strong><span>{intelligence.status} · {intelligence.model}</span></div><p>{intelligence.session_summary || 'AI 正在整合当前会话证据。'}</p>{intelligence.guardrail_result && <small>{intelligence.guardrail_result}</small>}{intelligence.planning_notes?.[0] && <small>{intelligence.planning_notes[0]}</small>}</div>}</section></div>
}

function ResearchAccessBar({ tokenDraft, setTokenDraft, onUnlock, ready, loading }: { tokenDraft: string; setTokenDraft: (value: string) => void; onUnlock: () => void; ready: boolean; loading: boolean }) {
  return <div className="research-access-bar">
    <span className="box-kicker">RESEARCH ACCESS</span>
    <input type="password" value={tokenDraft} onChange={(event) => setTokenDraft(event.target.value)} placeholder="输入研究访问口令" aria-label="研究访问口令" />
    <button className="secondary-button" type="button" onClick={onUnlock} disabled={loading}>{loading ? '验证中…' : ready ? '已连接' : '解锁研究空间'}</button>
  </div>
}

function ResearchView({ summary, distribution, tokenDraft, setTokenDraft, onUnlock, ready, loading }: { summary: ResearchSummary; distribution: Array<{ score: number; count: number }>; tokenDraft: string; setTokenDraft: (value: string) => void; onUnlock: () => void; ready: boolean; loading: boolean }) {
  if (!ready) return <div className="detail-view research-view"><div className="eyebrow"><span>RESEARCH DASHBOARD</span><span className="eyebrow-line" /><span>PROTECTED</span></div><h2>研究空间需要口令</h2><p className="view-intro">历史回答、评估指标和复核队列只对研究人员开放。</p><ResearchAccessBar tokenDraft={tokenDraft} setTokenDraft={setTokenDraft} onUnlock={onUnlock} ready={ready} loading={loading} /></div>
  const max = Math.max(...distribution.map((item) => item.count))
  const evaluation = (summary.evaluation ?? {}) as Record<string, unknown>
  const testMetrics = (evaluation.test ?? {}) as Record<string, unknown>
  const selectiveTest = ((evaluation.selective as Record<string, unknown> | undefined)?.test ?? {}) as Record<string, unknown>
  const runtime = (summary as ResearchSummary & { assessment_runtime?: Record<string, unknown> }).assessment_runtime ?? {}
  const metric = (value: unknown, suffix = '') => typeof value === 'number' ? `${(value * (suffix === '%' ? 100 : 1)).toFixed(suffix === '%' ? 1 : 3)}${suffix}` : '—'
  return <div className="detail-view research-view"><div className="eyebrow"><span>RESEARCH DASHBOARD</span><span className="eyebrow-line" /><span>LOCKED PARTICIPANT SPLIT</span></div><h2>数据决定架构</h2><p className="view-intro">历史人工标签永久保留为 legacy_score；证据充分性是独立标注轴。</p><ResearchAccessBar tokenDraft={tokenDraft} setTokenDraft={setTokenDraft} onUnlock={onUnlock} ready={ready} loading={loading} /><div className="metric-grid"><div><span className="box-kicker">参与者</span><strong>{summary.participants}</strong><small>participant-level split</small></div><div><span className="box-kicker">逐题回答</span><strong>{summary.responses.toLocaleString()}</strong><small>20 seed probes</small></div><div><span className="box-kicker">test participants</span><strong>{summary.splits.test}</strong><small>no leakage across questions</small></div><div><span className="box-kicker">待复核候选</span><strong>{summary.questions.reduce((sum, item) => sum + item.provisional_candidates, 0)}</strong><small>item-aware evidence gaps</small></div></div><div className="research-evaluation"><div><span>TEST ACCURACY</span><strong>{metric(testMetrics.accuracy, '%')}</strong></div><div><span>MACRO-F1</span><strong>{metric(testMetrics.macro_f1)}</strong></div><div><span>SELECTIVE COVERAGE</span><strong>{metric(selectiveTest.coverage, '%')}</strong></div><div><span>覆盖集 ACC</span><strong>{metric(selectiveTest.accuracy_on_covered, '%')}</strong></div><div><span>CLARIFICATIONS</span><strong>{String(runtime.clarifications ?? 0)}</strong></div><div><span>HUMAN REVIEW</span><strong>{String(runtime.human_review_events ?? 0)}</strong></div></div><div className="research-columns"><section className="chart-section"><div className="section-heading"><strong>Legacy score distribution</strong><span>n = {summary.responses.toLocaleString()}</span></div><div className="bars">{distribution.map((item) => <div className="bar-row" key={item.score}><span><ScorePill score={item.score} /></span><div className="bar-track"><span className={`bar-fill fill-${item.score}`} style={{ width: `${(item.count / max) * 100}%` }} /></div><strong>{item.count.toLocaleString()}</strong></div>)}</div><div className="split-pills">{Object.entries(summary.splits).map(([key, value]) => <span key={key}><b>{key}</b> {value} participants</span>)}</div></section><section className="difficulty-section"><div className="section-heading"><strong>题目难度 / 模糊候选</strong><span>provisional candidates</span></div><div className="difficulty-list">{summary.questions.slice(0, 10).map((item) => <div className="difficulty-row" key={item.id}><span className="mono">{item.id}</span><div className="difficulty-track"><span style={{ width: `${Math.min(100, item.provisional_candidates * 3)}%` }} /></div><strong>{item.provisional_candidates}</strong></div>)}</div></section></div></div>
}

function ReviewView({ cases, token, onReviewed, onLoadMore, hasMore, tokenDraft, setTokenDraft, onUnlock, ready, loading }: { cases: Array<Record<string, unknown>>; token: string; onReviewed: () => Promise<void>; onLoadMore: () => Promise<void>; hasMore: boolean; tokenDraft: string; setTokenDraft: (value: string) => void; onUnlock: () => void; ready: boolean; loading: boolean }) {
  if (!ready) return <div className="detail-view"><div className="eyebrow"><span>EXPERT REVIEW QUEUE</span><span className="eyebrow-line" /><span>PROTECTED</span></div><h2>专家工作台需要口令</h2><p className="view-intro">历史回答和人工仲裁结果不会在参与者空间公开。</p><ResearchAccessBar tokenDraft={tokenDraft} setTokenDraft={setTokenDraft} onUnlock={onUnlock} ready={ready} loading={loading} /></div>
  return <ReviewWorkspace cases={cases} token={token} onReviewed={onReviewed} onLoadMore={onLoadMore} hasMore={hasMore} tokenDraft={tokenDraft} setTokenDraft={setTokenDraft} onUnlock={onUnlock} ready={ready} loading={loading} />
}

function ReviewWorkspace({ cases, token, onReviewed, onLoadMore, hasMore, tokenDraft, setTokenDraft, onUnlock, ready, loading }: { cases: Array<Record<string, unknown>>; token: string; onReviewed: () => Promise<void>; onLoadMore: () => Promise<void>; hasMore: boolean; tokenDraft: string; setTokenDraft: (value: string) => void; onUnlock: () => void; ready: boolean; loading: boolean }) {
  const [selectedId, setSelectedId] = useState('')
  const [adjudicatedScore, setAdjudicatedScore] = useState('')
  const [evidenceSufficiency, setEvidenceSufficiency] = useState('SUFFICIENT')
  const [note, setNote] = useState('')
  const [message, setMessage] = useState('')
  const selected = cases.find((item) => String(item.response_id) === selectedId)
  const submitReview = async () => {
    if (!selectedId) return
    setMessage('保存中…')
    try {
      const response = await fetch(`/api/review/${encodeURIComponent(selectedId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Research-Token': token },
        body: JSON.stringify({ adjudicated_score: adjudicatedScore === '' ? null : Number(adjudicatedScore), evidence_sufficiency: evidenceSufficiency, note }),
      })
      if (!response.ok) throw new Error('review failed')
      await onReviewed()
      setSelectedId('')
      setAdjudicatedScore('')
      setNote('')
      setMessage('已保存，案例已从开放队列移除。')
    } catch {
      setMessage('保存失败，请检查研究口令或服务状态。')
    }
  }
  return <div className="detail-view"><div className="eyebrow"><span>EXPERT REVIEW QUEUE</span><span className="eyebrow-line" /><span>LEGACY ≠ GOLD</span></div><h2>把不确定性留给专业人员</h2><p className="view-intro">这些回答因语义缺口、历史标签冲突或理由不一致而进入复核队列。</p><ResearchAccessBar tokenDraft={tokenDraft} setTokenDraft={setTokenDraft} onUnlock={onUnlock} ready={ready} loading={loading} /><div className="review-table"><div className="table-head"><span>RESPONSE</span><span>ITEM</span><span>LEGACY</span><span>STATUS</span></div>{cases.map((item, index) => <button className={`table-row review-select-row ${String(item.response_id) === selectedId ? 'selected' : ''}`} type="button" key={`${String(item.response_id)}-${index}`} onClick={() => { setSelectedId(String(item.response_id)); setAdjudicatedScore(item.legacy_score == null ? '' : String(item.legacy_score)); setEvidenceSufficiency(String(item.evidence_sufficiency ?? 'UNASSESSED') === 'UNASSESSED' ? 'SUFFICIENT' : String(item.evidence_sufficiency)); setMessage('') }}><span className="response-cell">{String(item.response)}</span><span className="mono">{String(item.question_id)}</span><ScorePill score={Number(item.legacy_score ?? item.preliminary_score) || 0} /><span className="review-status">{String(item.status ?? item.evidence_sufficiency ?? 'OPEN')}</span></button>)}</div>{cases.length === 0 && <div className="empty-table">当前没有开放复核案例。</div>}{hasMore && <button className="ghost-button review-load-more" type="button" onClick={() => void onLoadMore()}>加载更多案例 <span>↓</span></button>}{selected && <div className="review-editor"><div className="box-kicker">当前案例 · {String(selected.question_id)}</div><p className="review-editor-response">{String(selected.response)}</p><div className="review-editor-grid"><label>仲裁分数<select value={adjudicatedScore} onChange={(event) => setAdjudicatedScore(event.target.value)}><option value="">未确定</option><option value="0">0</option><option value="1">1</option><option value="2">2</option></select></label><label>证据充分性<select value={evidenceSufficiency} onChange={(event) => setEvidenceSufficiency(event.target.value)}><option value="SUFFICIENT">SUFFICIENT</option><option value="INSUFFICIENT">INSUFFICIENT</option><option value="EXPERT_DISAGREEMENT">EXPERT_DISAGREEMENT</option></select></label></div><label>专家备注<textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录边界、依据或需要进一步讨论的地方" /></label><button className="secondary-button" type="button" onClick={submitReview}>保存仲裁</button>{message && <span className="review-message">{message}</span>}</div>}</div>
}

function ReplayView({ submitted, questions }: { submitted: Record<string, ScoreResult>; questions: Question[] }) {
  const entries = Object.entries(submitted)
  return <div className="detail-view"><div className="eyebrow"><span>CASE REPLAY</span><span className="eyebrow-line" /><span>SESSION TRACE</span></div><h2>逐步回放一次评估</h2><p className="view-intro">每个事件带着题目、回答、初评与证据充分性写入本地会话。</p>{entries.length === 0 ? <div className="empty-replay"><div className="empty-glyph">↺</div><strong>还没有评估事件</strong><span>从左侧选择题目并提交回答，回放会自动生成。</span></div> : <div className="replay-list">{entries.map(([id, item], index) => <div className="replay-row" key={id}><span className="chain-index">{String(index + 1).padStart(2, '0')}</span><div><span className="mono">{id} · {questions.find((q) => q.id === id)?.dimension}</span><p>{item.response}</p></div><ScorePill score={item.preliminary_score} /><span className={`state-label ${item.score_status.toLowerCase()}`}>{item.score_status}</span></div>)}</div>}</div>
}

export default App
