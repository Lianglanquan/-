type WorkflowStep = 'overview' | 'report' | 'review' | 'research'

const steps: Array<{ id: WorkflowStep; label: string }> = [
  { id: 'overview', label: '评估总览' },
  { id: 'report', label: '选择测试者 · 单场评估报告' },
  { id: 'review', label: '专家复核' },
  { id: 'research', label: 'Rubric / 模型迭代' },
]

export default function WorkflowTrail({ active }: { active: WorkflowStep }) {
  const activeIndex = steps.findIndex((step) => step.id === active)
  return <nav className="workflow-trail" aria-label="评估工作链路">
    {steps.map((step, index) => <div className={`workflow-step ${step.id === active ? 'active' : ''} ${index < activeIndex ? 'visited' : ''}`} key={step.id}>
      <span>{String(index + 1).padStart(2, '0')}</span><strong>{step.label}</strong>{index < steps.length - 1 && <i aria-hidden="true">→</i>}
    </div>)}
  </nav>
}
