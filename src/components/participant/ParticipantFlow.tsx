import { useEffect, useRef, useState } from 'react'

type ParticipantQuestion = {
  id: string
  question: string
  dimension: string
  criteria?: Array<{ score: number; description: string }>
}

type ParticipantEvidenceSpan = { text: string; start: number; end: number; rule: string }
type ParticipantProbeOption = { id: string; label: string }
type ParticipantCatProbe = {
  version: string
  probe_id: string
  probe_type: string
  target_gap: string
  cat_reflection: string
  cat_tentative_understanding: string
  cat_humility: string
  cat_invitation: string
  options: ParticipantProbeOption[]
  free_text_label: string
  pause_label: string
  response_optional?: boolean
}

type ParticipantScoreResult = {
  question_id: string
  response: string
  preliminary_score: number
  score_status: string
  evidence_sufficiency: string
  rationale: string
  evidence_spans: ParticipantEvidenceSpan[]
  confidence: number
  target_gap?: string | null
  clarification_question?: string | null
  safety_state: string
  rubric_version: string
  model?: string
  probe_type?: string | null
  cat_probe?: ParticipantCatProbe | null
}

type ParticipantNextAction = {
  type: string
  question_id?: string | null
  probe_type?: string | null
  question?: string | null
  interaction?: ParticipantCatProbe | null
  rationale?: string
}

type ParticipantFlowProps = {
  question: ParticipantQuestion
  selected: number
  totalQuestions?: number
  response: string
  setResponse: (value: string) => void
  result?: ParticipantScoreResult
  nextAction?: ParticipantNextAction
  clarification: string
  setClarification: (value: string) => void
  runScore: (text?: string, isClarification?: boolean, probeType?: string | null, probeOptionId?: string | null, probeAction?: 'ANSWER' | 'PAUSE') => void
  loading: boolean
  errorMessage?: string
  /** After the final Seed Probe, let the participant see the session handoff first. */
  suppressProbe?: boolean
  onNext: () => void
  /** When embedded in App, let the host own the existing completion screen. */
  onComplete?: () => void
  initialStage?: Exclude<FlowStage, 'completion'>
}

type FlowStage = 'welcome' | 'question' | 'clarification' | 'completion'

const scoreLabels = ['稳定 / 适应', '需要关注', '明显负向']

function humanizeGap(gap?: string | null) {
  if (!gap) return '我还不确定这句话指向哪里'
  if (/方向|正负/.test(gap)) return '我还不确定，你指的是哪一面'
  if (/对象|谁|什么/.test(gap)) return '我还不确定，你说的是谁或什么'
  if (/程度|强度|多少/.test(gap)) return '我还不确定，这种感受有多重'
  if (/时间|时点|持续/.test(gap)) return '我还不确定，这种感受在什么时候出现'
  if (/情境|具体|场景/.test(gap)) return '我还缺一个具体的时刻'
  return '我还想知道，这句话对你具体意味着什么'
}

function ScorePill({ score }: { score: number }) {
  return <span className={`score-pill score-${score}`}>{score}分</span>
}

/**
 * Participant-facing flow. It deliberately owns only the four participant
 * stages; scoring remains in App so the existing /api/score and safety gate
 * are unchanged.
 */
export function ParticipantFlow({
  question,
  selected,
  totalQuestions = 20,
  response,
  setResponse,
  result,
  nextAction,
  clarification,
  setClarification,
  runScore,
  loading,
  errorMessage,
  suppressProbe = false,
  onNext,
  onComplete,
  initialStage = 'welcome',
}: ParticipantFlowProps) {
  const [stage, setStage] = useState<FlowStage>(initialStage)
  const [started, setStarted] = useState(initialStage !== 'welcome')
  const isLastQuestion = selected >= totalQuestions - 1
  const lastCatMessage = useRef<string | null>(null)

  // The cat only speaks when the assessment state changes. It never invents
  // a psychological interpretation; it acknowledges certainty and handoff.
  useEffect(() => {
    if (!result || typeof window === 'undefined') return
    const key = `${result.question_id}:${result.response}:${result.score_status}:${result.safety_state}`
    if (lastCatMessage.current === key) return
    lastCatMessage.current = key
    const probeIsSelected = ['CLARIFY_NOW', 'CONFIRM_NOW'].includes(nextAction?.type ?? '') && (!nextAction?.question_id || nextAction.question_id === result.question_id)
    const message = result.safety_state !== 'CLEAR'
      ? '先停一下'
      : probeIsSelected
        ? nextAction?.interaction?.cat_reflection || result.cat_probe?.cat_reflection || '我想再靠近一点'
        : result.score_status === 'PROVISIONAL'
        ? '再近一点'
        : '先放在这里'
    window.dispatchEvent(new CustomEvent('cat:message', { detail: { message } }))
  }, [result?.question_id, result?.response, result?.score_status, result?.safety_state, nextAction?.type, nextAction?.question_id, nextAction?.interaction?.cat_reflection, result?.cat_probe?.cat_reflection])

  // Moving to another seed probe always returns to the writing page. A new
  // provisional result moves to its one-question clarification page.
  useEffect(() => {
    if (!started) return
    const shouldProbeNow = !suppressProbe && ['PROVISIONAL', 'HUMAN_REVIEW'].includes(result?.score_status ?? '') && ['CLARIFY_NOW', 'CONFIRM_NOW'].includes(nextAction?.type ?? '') && (!nextAction?.question_id || nextAction.question_id === question.id)
    if (shouldProbeNow) {
      setStage('clarification')
      return
    }
    if (stage !== 'completion') setStage('question')
    // Only values that identify a new result/seed probe should affect stage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, result?.score_status, nextAction?.type, nextAction?.question_id, started, suppressProbe])

  const start = () => {
    setStarted(true)
    const shouldProbeNow = !suppressProbe && ['PROVISIONAL', 'HUMAN_REVIEW'].includes(result?.score_status ?? '') && ['CLARIFY_NOW', 'CONFIRM_NOW'].includes(nextAction?.type ?? '')
    setStage(shouldProbeNow ? 'clarification' : 'question')
  }

  const handleNext = () => {
    if (isLastQuestion) {
      if (onComplete) {
        onComplete()
        return
      }
      setStage('completion')
      return
    }
    onNext()
    setStage('question')
  }

  if (stage === 'welcome') return <WelcomePage totalQuestions={totalQuestions} onStart={start} />
  if (stage === 'clarification' && result) {
    return (
      <ClarificationPage
        key={`${question.id}:${nextAction?.type}:${nextAction?.interaction?.probe_id || ''}`}
        question={question}
        response={response}
        result={result}
        nextAction={nextAction}
        clarification={clarification}
        setClarification={setClarification}
        loading={loading}
        errorMessage={errorMessage}
        onSubmit={(value, optionId, action) => runScore(value, true, nextAction?.probe_type, optionId, action)}
      />
    )
  }
  if (stage === 'completion') {
    return <CompletionPage totalQuestions={totalQuestions} onReturn={() => setStage('question')} />
  }
  return (
    <QuestionPage
      question={question}
      selected={selected}
      totalQuestions={totalQuestions}
      response={response}
      setResponse={setResponse}
      result={result}
      nextAction={nextAction}
      suppressProbe={suppressProbe}
      loading={loading}
      errorMessage={errorMessage}
      onSubmit={() => runScore()}
      onNext={handleNext}
    />
  )
}

function WelcomePage({ totalQuestions, onStart }: { totalQuestions: number; onStart: () => void }) {
  return (
    <div className="assessment-view" style={{ minHeight: 530, display: 'flex', alignItems: 'center' }}>
      <img className="framebase-reference" src="/framesbase/nature-ritual.webp" alt="" aria-hidden="true" />
      <div style={{ position: 'relative', zIndex: 1, maxWidth: 660 }}>
        <div className="eyebrow">
          <span>BEGIN</span>
          <span className="eyebrow-line" />
          <span>从这里开始</span>
        </div>
        <h1>不用想得完整，从第一句话开始</h1>
        <p className="prompt-note" style={{ maxWidth: 520 }}>
          接下来有 {totalQuestions} 个小问题。想到什么，就写什么。
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap' }}>
          <button className="primary-button" type="button" onClick={onStart}>
            开始 <span>→</span>
          </button>
          <span style={{ color: '#777487', fontSize: 11 }}>随时可以停一停</span>
        </div>
      </div>
    </div>
  )
}

function QuestionPage({
  question,
  selected,
  totalQuestions,
  response,
  setResponse,
  result,
  nextAction,
  suppressProbe,
  loading,
  onSubmit,
  onNext,
  errorMessage,
}: {
  question: ParticipantQuestion
  selected: number
  totalQuestions: number
  response: string
  setResponse: (value: string) => void
  result?: ParticipantScoreResult
  nextAction?: ParticipantNextAction
  suppressProbe?: boolean
  loading: boolean
  onSubmit: () => void
  onNext: () => void
  errorMessage?: string
}) {
  return (
    <div className="assessment-view">
      <img className="framebase-reference" src="/framesbase/mindful-companion.webp" alt="" aria-hidden="true" />
      <div className="eyebrow">
        <span>第 {question.id.slice(1)} 题 / {totalQuestions}</span>
        <span className="eyebrow-line" />
        <span>{question.dimension}</span>
      </div>
      <h1>{question.question}</h1>
      <div className="answer-layout">
        <div className="answer-column">
          <label htmlFor="response">第一句话</label>
          <textarea
            id="response"
            value={response}
            onChange={(event) => setResponse(event.target.value)}
            placeholder="从几个字开始，也很好"
          />
          <div className="answer-actions">
            <span className="char-count">{response.length} / 5000</span>
            <button className="primary-button" type="button" onClick={onSubmit} disabled={!response.trim() || loading}>
              {loading ? '读一读…' : '继续'} <span>→</span>
            </button>
          </div>
          {result && result.safety_state === 'CLEAR' && !(suppressProbe !== true && nextAction?.question_id === question.id && ['CLARIFY_NOW', 'CONFIRM_NOW'].includes(nextAction.type)) && (
            <div className="next-row">
              <button className="ghost-button" type="button" onClick={onNext}>
                {selected >= totalQuestions - 1 ? '完成' : '下一句'} <span>→</span>
              </button>
              <span>可随时回看</span>
            </div>
          )}
          {result?.score_status === 'PROVISIONAL' && nextAction?.type === 'DEFER_CLARIFICATION' && (
            <div className="deferred-probe-note">我先记下这处未决，继续了解后面的回答，再决定是否回来求证。</div>
          )}
          {errorMessage && <div className="cat-probe-error" role="alert">{errorMessage}</div>}
        </div>
        <ScorePanel result={result} />
      </div>
    </div>
  )
}

function ClarificationPage({
  question,
  response,
  result,
  nextAction,
  clarification,
  setClarification,
  loading,
  onSubmit,
  errorMessage,
}: {
  question: ParticipantQuestion
  response: string
  result: ParticipantScoreResult
  nextAction?: ParticipantNextAction
  clarification: string
  setClarification: (value: string) => void
  loading: boolean
  onSubmit: (value: string, optionId?: string | null, action?: 'ANSWER' | 'PAUSE') => void
  errorMessage?: string
}) {
  const interaction = nextAction?.interaction || result.cat_probe
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null)
  const selectedOption = interaction?.options.find((option) => option.id === selectedOptionId)
  const isPause = selectedOptionId === 'not_ready'
  const needsOwnWords = selectedOptionId === 'other'
  const submit = () => {
    const freeText = clarification.trim()
    const optionText = selectedOption?.label || ''
    const value = needsOwnWords
      ? freeText
      : freeText && optionText && !isPause
        ? `${optionText}；${freeText}`
        : freeText || optionText
    if (!value || (needsOwnWords && !freeText)) return
    onSubmit(value, selectedOptionId, isPause ? 'PAUSE' : 'ANSWER')
  }
  return (
    <div className="assessment-view">
      <img className="framebase-reference" src="/framesbase/routine-coach.webp" alt="" aria-hidden="true" />
      <div className="eyebrow">
        <span>{nextAction?.probe_type === 'CONFIRMATION' ? 'ONE MORE LISTEN' : 'A LITTLE CLOSER'}</span>
        <span className="eyebrow-line" />
        <span>{question.id}</span>
      </div>
      <h1>{interaction?.cat_reflection || '我想再靠近一点。'}</h1>
      <p className="prompt-note">{interaction?.cat_tentative_understanding || humanizeGap(result.target_gap)}</p>
      <div className="answer-layout">
        <div className="answer-column">
          <div className="cat-probe-card">
            <div className="box-kicker"><span className="companion-dot" aria-hidden="true">✦</span> {interaction?.cat_humility || '也可能是我听偏了。'}</div>
            <p className="cat-probe-invitation">{interaction?.cat_invitation || '你愿意带我再靠近一点吗？'}</p>
            {interaction?.options?.length ? <div className="cat-option-grid" role="group" aria-label="选择一种更接近的说法">
              {interaction.options.map((option) => <button key={option.id} type="button" aria-pressed={selectedOptionId === option.id} className={`cat-option ${selectedOptionId === option.id ? 'selected' : ''} ${option.id === 'not_ready' ? 'quiet' : ''}`} onClick={() => setSelectedOptionId((current) => current === option.id ? null : option.id)}>{option.label}</button>)}
            </div> : null}
            {needsOwnWords && <p className="cat-probe-hint">这一条不替你解释；写下你的版本，小猫会照着你的话再听一遍。</p>}
            {isPause && <p className="cat-probe-hint">不用解释，停在这里也可以。等你准备好了，我们再回来。</p>}
            <label htmlFor="clarification">{interaction?.free_text_label || '都不太像，我想自己说'}</label>
            <textarea
              id="clarification"
              className="clarification-input"
              value={clarification}
              onChange={(event) => setClarification(event.target.value)}
              placeholder={needsOwnWords ? '这一条只替你留位置，不替你解释；写下你自己的话就好' : '也可以用你自己的话，不急着说完整'}
            />
            <button className="secondary-button" type="button" disabled={(!clarification.trim() && !selectedOptionId) || (needsOwnWords && !clarification.trim()) || loading} onClick={submit}>
              {loading ? '听一听…' : isPause ? (interaction?.pause_label || '今天先放在这里') : '把这句话交给我'} <span>↗</span>
            </button>
            {errorMessage && <div className="cat-probe-error" role="alert">{errorMessage}</div>}
          </div>
          <div className="cat-probe-source">你刚才写下：“{response}”</div>
        </div>
        <ScorePanel result={result} />
      </div>
    </div>
  )
}

function CompletionPage({ totalQuestions, onReturn }: { totalQuestions: number; onReturn: () => void }) {
  return (
    <div className="assessment-view" style={{ minHeight: 530, display: 'flex', alignItems: 'center' }}>
      <img className="framebase-reference" src="/framesbase/celestial-renewal.webp" alt="" aria-hidden="true" />
      <div style={{ position: 'relative', zIndex: 1, maxWidth: 660 }}>
        <div className="eyebrow">
          <span>PAUSE</span>
          <span className="eyebrow-line" />
          <span>{totalQuestions} 句</span>
        </div>
        <h1>写到这里，<br />就很好。</h1>
        <p className="prompt-note" style={{ maxWidth: 520 }}>
          你写下的每一句，都留在这里。想回看时，随时回来。
        </p>
        <button className="ghost-button" type="button" onClick={onReturn}>回看 <span>↺</span></button>
      </div>
    </div>
  )
}

function ScorePanel({ result }: { result?: ParticipantScoreResult }) {
  if (!result) {
    return (
      <aside className="score-companion" data-oneko-region aria-label="等待第一句回答">
        <span className="score-companion-anchor" data-oneko-anchor aria-hidden="true" />
      </aside>
    )
  }
  const safetyGated = result.safety_state !== 'CLEAR'
  const humanReview = result.score_status === 'HUMAN_REVIEW'
  const label = safetyGated ? '先停一下' : humanReview ? '暂留复核' : result.score_status === 'PROVISIONAL' ? '还想确认' : '继续'
  const headline = safetyGated ? '我会先停在这里。' : humanReview ? '这句话我先不替你定下来。' : result.score_status === 'PROVISIONAL' ? '我还缺一点信息。' : '你可以继续下一句。'
  const detail = safetyGated
    ? '这句话会进入预定义的专业评估流程。'
    : humanReview
      ? '你可以继续下一句；需要时再由专业人员回看。'
      : result.score_status === 'PROVISIONAL'
        ? '如果愿意，补充问题中的那一句；不需要猜我想听什么。'
        : '评分细节不会在作答过程中展示，以免影响后面的回答。'
  return (
    <aside className={`score-panel score-panel-${result.score_status.toLowerCase()}`}>
      <div className="panel-top">
        <span className="box-kicker">这句话已记录</span>
        <span className={`state-label ${result.score_status.toLowerCase()}`}>{label}</span>
      </div>
      <div className="score-companion-copy">
        <strong>{headline}</strong>
        <p>{detail}</p>
      </div>
      {safetyGated && <div className="safety-alert">这句话需要专业人员一起看看。</div>}
    </aside>
  )
}

export default ParticipantFlow
