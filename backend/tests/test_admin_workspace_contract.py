from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_admin_workspace_contract_has_overview_report_and_non_destructive_sync() -> None:
    app = (ROOT / 'src/App.tsx').read_text(encoding='utf-8')
    sessions = (ROOT / 'src/components/admin/AdminSessionsView.tsx').read_text(encoding='utf-8')
    overview = (ROOT / 'src/components/admin/AdminOverviewView.tsx').read_text(encoding='utf-8')

    assert "'/api/admin/overview'" in app
    assert '/api/admin/sessions/${encodeURIComponent(id)}/report' in app
    assert 'setInterval' in app
    assert '30000' in app
    assert 'visibilitychange' in app
    assert '正在同步' in sessions
    assert '上一份内容仍保留' in sessions
    for label in ('证据地图', '20题证据矩阵', '评估路径'):
        assert label in sessions
    assert '干预建议' not in sessions
    assert '评估总览' in overview
