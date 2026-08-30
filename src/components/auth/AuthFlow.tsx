import { FormEvent, useState } from 'react'

export type AuthUser = {
  id: string
  email: string
  role: 'ADMIN' | 'PARTICIPANT' | string
  email_verified: boolean
  is_active: boolean
  created_at?: string
}

type AuthFlowProps = {
  onAuthenticated: (user: AuthUser) => void
}

type Mode = 'login' | 'register' | 'verify' | 'forgot' | 'reset'

async function callAuth(path: string, body: Record<string, string>) {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await response.json().catch(() => ({})) as { detail?: string; user?: AuthUser; message?: string }
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '暂时没能接住这次操作，请稍后再试。')
  return payload
}

export default function AuthFlow({ onAuthenticated }: AuthFlowProps) {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (loading) return
    setLoading(true)
    setError('')
    setMessage('')
    try {
      if (mode === 'login') {
        const payload = await callAuth('/api/auth/login', { email, password })
        if (payload.user) onAuthenticated(payload.user)
      } else if (mode === 'register') {
        await callAuth('/api/auth/register', { email, password })
        setMode('verify')
        setMessage('验证码已经寄出。先不用急，我们在这里等你。')
      } else if (mode === 'verify') {
        await callAuth('/api/auth/verify-email', { email, code })
        setMode('login')
        setMessage('邮箱已经确认，可以用刚才设置的密码进来了。')
      } else if (mode === 'forgot') {
        await callAuth('/api/auth/request-reset', { email })
        setMode('reset')
        setMessage('如果这个邮箱已经注册，验证码会寄到那里。')
      } else {
        await callAuth('/api/auth/reset-password', { email, code, new_password: newPassword })
        setMode('login')
        setPassword('')
        setNewPassword('')
        setMessage('密码已更新。愿你接下来少记一件需要担心的事。')
      }
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : '暂时没能完成，请稍后再试。')
    } finally {
      setLoading(false)
    }
  }

  const resendVerification = async () => {
    if (!email.trim() || loading) return
    setLoading(true)
    setError('')
    try {
      const payload = await callAuth('/api/auth/resend-verification', { email })
      setMessage(payload.message ?? '如果需要，新的验证码已经寄出。')
    } catch (resendError) {
      setError(resendError instanceof Error ? resendError.message : '暂时没能寄出，请稍后再试。')
    } finally {
      setLoading(false)
    }
  }

  const title = mode === 'login' ? '先认出你，再慢慢开始' : mode === 'register' ? '给这段路留一个名字' : mode === 'verify' ? '收一下邮箱里的信' : mode === 'forgot' ? '密码忘了也没关系' : '换一把新的钥匙'
  const subtitle = mode === 'login'
    ? '每一次回答都会归属于你的私密会话。邮箱只是为了把这段记录好好交还给你。'
    : mode === 'register'
      ? '我们只用邮箱确认身份，不把回答寄出去，也不把它变成任何公开标签。'
      : mode === 'verify'
        ? '验证码只使用一次，十分钟内有效。小猫会替你把这封信看好。'
        : '我们不会透露一个邮箱是否已经注册。'

  return <main className="auth-scene">
    <section className="auth-card" aria-label="邮箱登录">
      <div className="auth-cat" aria-hidden="true">◡̈</div>
      <div className="hero-kicker"><span /> 听见自己 · 私密会话</div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <form onSubmit={submit} className="auth-form">
        <label>邮箱<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required placeholder="you@example.com" /></label>
        {(mode === 'login' || mode === 'register') && <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={8} required placeholder="至少 8 个字符" /></label>}
        {(mode === 'verify' || mode === 'reset') && <label>邮箱验证码<input inputMode="numeric" pattern="[0-9]{6}" value={code} onChange={(event) => setCode(event.target.value)} required placeholder="6 位数字" /></label>}
        {mode === 'reset' && <label>新密码<input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" minLength={8} required placeholder="至少 8 个字符" /></label>}
        {error && <div className="auth-error" role="alert">{error}</div>}
        {message && <div className="auth-message" role="status">{message}</div>}
        <button className="auth-submit" type="submit" disabled={loading}>{loading ? '请稍等…' : mode === 'login' ? '进入私密会话 →' : mode === 'register' ? '寄出验证码 →' : mode === 'verify' ? '确认邮箱 →' : mode === 'forgot' ? '发送重置验证码 →' : '保存新密码 →'}</button>
      </form>
      <div className="auth-links">
        {mode === 'login' && <><button type="button" onClick={() => { setMode('register'); setError(''); setMessage('') }}>第一次来，创建账号</button><button type="button" onClick={() => { setMode('forgot'); setError(''); setMessage('') }}>忘记密码</button></>}
        {mode === 'register' && <button type="button" onClick={() => { setMode('login'); setError(''); setMessage('') }}>已经有账号？登录</button>}
        {mode === 'verify' && <><button type="button" onClick={() => void resendVerification()}>再寄一次验证码</button><button type="button" onClick={() => { setMode('login'); setError(''); setMessage('') }}>稍后验证，回到登录</button></>}
        {(mode === 'forgot' || mode === 'reset') && <button type="button" onClick={() => { setMode('login'); setError(''); setMessage('') }}>回到登录</button>}
      </div>
      <small className="auth-footnote">管理员由邮箱白名单授予权限；其他账号只能看见自己的回答与分析。</small>
    </section>
  </main>
}
