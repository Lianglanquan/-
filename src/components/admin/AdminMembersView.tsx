import { FormEvent, useState } from 'react'

export type AdminMember = {
  id: string
  email: string
  role: string
  email_verified: boolean
  is_active: boolean
  created_at?: string
  updated_at?: string
  last_login_at?: string | null
  session_count?: number
}

type AdminMembersViewProps = {
  members: AdminMember[]
  currentUserId: string
  loading: boolean
  message: string
  onInvite: (email: string) => Promise<void>
  onRoleChange: (member: AdminMember) => Promise<void>
  onActiveChange: (member: AdminMember) => Promise<void>
  onRefresh: () => Promise<void>
}

function formatDate(value?: string | null) {
  if (!value) return '还没有登录'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function AdminMembersView({ members, currentUserId, loading, message, onInvite, onRoleChange, onActiveChange, onRefresh }: AdminMembersViewProps) {
  const [email, setEmail] = useState('')
  const [inviteLoading, setInviteLoading] = useState(false)

  const submitInvite = async (event: FormEvent) => {
    event.preventDefault()
    if (!email.trim() || inviteLoading) return
    setInviteLoading(true)
    try {
      await onInvite(email.trim())
      setEmail('')
    } finally {
      setInviteLoading(false)
    }
  }

  return <div className="detail-view members-view">
    <div className="eyebrow"><span>MEMBERS & PERMISSIONS</span><span className="eyebrow-line" /><span>ADMIN ONLY</span></div>
    <h2>把谁带进这间房间</h2>
    <p className="view-intro">管理员可以一起看见完整评估，也可以自己回到“继续”里作为测试人员走完一场会话。</p>
    <section className="members-invite-card">
      <div><span className="box-kicker">预授权管理员邮箱</span><p>对方使用这个邮箱注册后，会自动拥有管理员权限；密码仍由对方自己设置。</p></div>
      <form onSubmit={submitInvite}><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="teammate@example.com" required /><button className="secondary-button" type="submit" disabled={inviteLoading}>{inviteLoading ? '保存中…' : '预授权邮箱 →'}</button></form>
    </section>
    <div className="members-toolbar"><span className="box-kicker">成员 {members.length}</span><button className="ghost-button" type="button" onClick={() => void onRefresh()} disabled={loading}>{loading ? '读取中…' : '刷新列表 ↻'}</button></div>
    <div className="members-table">
      <div className="members-table-head"><span>成员</span><span>权限</span><span>最近登录</span><span>会话</span><span>操作</span></div>
      {members.map((member) => <div className={`member-row ${member.is_active ? '' : 'member-row-inactive'}`} key={member.id}>
        <div className="member-identity"><strong>{member.email}</strong><small>{member.email_verified ? '邮箱已确认' : '等待邮箱确认'} · 加入于 {formatDate(member.created_at)}</small></div>
        <span className={`member-role ${member.role.toLowerCase()}`}>{member.role === 'ADMIN' ? '管理员' : '参与者'}</span>
        <span className="member-meta">{formatDate(member.last_login_at)}</span>
        <span className="member-meta">{member.session_count ?? 0}</span>
        <div className="member-actions">
          <button type="button" onClick={() => void onRoleChange(member)} disabled={loading}>{member.role === 'ADMIN' ? '撤销管理员' : '设为管理员'}</button>
          <button type="button" onClick={() => void onActiveChange(member)} disabled={loading || member.id === currentUserId}>{member.is_active ? '停用' : '恢复'}</button>
        </div>
      </div>)}
      {members.length === 0 && <div className="members-empty">还没有成员记录。</div>}
    </div>
    {message && <div className="members-message" role="status">{message}</div>}
    <div className="members-note"><span>♡</span> 角色变更、账号状态和管理员查看动作都会留下审计记录。</div>
  </div>
}
