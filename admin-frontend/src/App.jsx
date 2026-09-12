import React, { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { App as AntApp, Avatar, Badge, Button, Card, ConfigProvider, Drawer, Dropdown, Form, Grid, Input, Layout, Menu, Select, Space, Spin, Tooltip, Typography, theme } from 'antd'
import { ApiOutlined, AppstoreOutlined, AuditOutlined, BulbOutlined, CheckCircleFilled, DashboardOutlined, ExportOutlined, FundOutlined, GlobalOutlined, LogoutOutlined, MenuOutlined, RobotOutlined, SafetyOutlined, SettingOutlined, TeamOutlined, ToolOutlined, UserOutlined } from '@ant-design/icons'
import { apiFetch, applyAuthSession, clearAuthSession, getAccessToken, getWorkspaceId, refreshAccessToken, setWorkspaceId, toUserErrorMessage, userFrontendUrl } from './api.js'
import { t, antdLocaleOf } from './i18n.js'
import { applyThemeMode, getThemeMode, toggleThemeMode } from './theme.js'

const DashboardPage = lazy(() => import('./pages/DashboardPage.jsx'))
const ModelsPage = lazy(() => import('./pages/ModelsPage.jsx'))
const SkillsPage = lazy(() => import('./pages/SkillsPage.jsx'))
const McpPage = lazy(() => import('./pages/McpPage.jsx'))
const PoliciesPage = lazy(() => import('./pages/PoliciesPage.jsx'))
const SettingsPage = lazy(() => import('./pages/SettingsPage.jsx'))
const UsersPage = lazy(() => import('./pages/UsersPage.jsx'))
const WorkspacesPage = lazy(() => import('./pages/WorkspacesPage.jsx'))
const AuditPage = lazy(() => import('./pages/AuditPage.jsx'))
const UsagePage = lazy(() => import('./pages/UsagePage.jsx'))

const { Header, Sider, Content } = Layout
const { Text, Title } = Typography
const buildNavItems = () => [
  {
    type: 'group', label: t('admin.nav.group.ops'), children: [
      { key: 'dashboard', icon: <DashboardOutlined />, label: t('admin.nav.dashboard') },
      { key: 'users', icon: <UserOutlined />, label: t('admin.nav.users') },
      { key: 'workspaces', icon: <TeamOutlined />, label: t('admin.nav.workspaces') },
      { key: 'audit', icon: <AuditOutlined />, label: t('admin.nav.audit') },
      { key: 'usage', icon: <FundOutlined />, label: t('admin.nav.usage') },
    ],
  },
  {
    type: 'group', label: t('admin.nav.group.capability'), children: [
      { key: 'models', icon: <RobotOutlined />, label: t('admin.nav.models') },
      { key: 'skills', icon: <ToolOutlined />, label: t('admin.nav.skills') },
      { key: 'mcp', icon: <ApiOutlined />, label: t('admin.nav.mcp') },
      { key: 'policies', icon: <SafetyOutlined />, label: t('admin.nav.policies') },
      { key: 'settings', icon: <SettingOutlined />, label: t('admin.nav.settings') },
    ],
  },
]

const buildPageLabels = () => Object.fromEntries(buildNavItems().flatMap((group) => group.children || []).map((item) => [item.key, item.label]))

function Login({ onLogin }) {
  const { message } = AntApp.useApp(); const [loading, setLoading] = useState(false)
  const submit = async (values) => { setLoading(true); try { const data = await apiFetch('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(values), workspaceId: '' }); applyAuthSession(data); await onLogin(data) } catch (error) { message.error(toUserErrorMessage(error, '登录失败，请检查账号和网络后重试。')) } finally { setLoading(false) } }
  return <main className="admin-auth">
    <div className="admin-auth-shell">
      <section className="admin-auth-intro" aria-label="平台能力简介">
        <div className="admin-auth-brand"><span className="admin-auth-logo"><AppstoreOutlined /></span><span>futureAgent</span></div>
        <div>
          <Text className="admin-auth-eyebrow">{t('admin.tagline')}</Text>
          <Title>让模型、工具和权限<br />保持清晰可控</Title>
          <Text className="admin-auth-copy">统一管理团队工作区、模型路由、技能与 MCP 服务，在一个可靠边界内完成运营与审计。</Text>
        </div>
        <Space direction="vertical" size={10} className="admin-auth-points">
          <Text><CheckCircleFilled /> 工作区级权限隔离</Text>
          <Text><CheckCircleFilled /> 模型与工具状态可验证</Text>
          <Text><CheckCircleFilled /> 关键操作全程可审计</Text>
        </Space>
      </section>
      <Card className="admin-auth-card" variant="borderless">
        <Space direction="vertical" className="admin-auth-heading">
          <Avatar size={48} icon={<SafetyOutlined />} />
          <div><Title level={2}>{t('admin.auth.title')}</Title><Text type="secondary">{t('admin.auth.subtitle')}</Text></div>
        </Space>
        <Form layout="vertical" onFinish={submit} requiredMark={false} size="large" validateMessages={{ required: '${label}不能为空', types: { email: '${label}格式不正确' } }}>
          <Form.Item name="email" label={t('admin.auth.email')} rules={[{ required: true, type: 'email' }]} validateTrigger="onBlur"><Input autoComplete="email" autoFocus placeholder="name@company.com" /></Form.Item>
          <Form.Item name="password" label={t('admin.auth.password')} rules={[{ required: true }]}><Input.Password autoComplete="current-password" placeholder="请输入登录密码" /></Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={loading}>{t('admin.auth.submit')}</Button>
        </Form>
        <Text type="secondary" className="admin-auth-note">{t('admin.auth.note')}</Text>
      </Card>
    </div>
  </main>
}

function AdminShell({ profile, workspaces, onLogout }) {
  const initialPage = window.location.hash.replace(/^#\/?/, '')
  const screens = Grid.useBreakpoint()
  const initialPageLabels = buildPageLabels(); const [selectedKey, setSelectedKey] = useState(initialPageLabels[initialPage] ? initialPage : 'dashboard'); const [collapsed, setCollapsed] = useState(false); const [mobileNav, setMobileNav] = useState(false); const [online, setOnline] = useState(false); const [workspaceId, setCurrentWorkspace] = useState(getWorkspaceId() || workspaces[0]?.id || '')
  const userAppUrl = userFrontendUrl()
  useEffect(() => { setWorkspaceId(workspaceId) }, [workspaceId])
  useEffect(() => { window.scrollTo(0, 0) }, [selectedKey])
  useEffect(() => { const check = () => apiFetch('/api/v1/health', { workspaceId: '' }).then(() => setOnline(true)).catch(() => setOnline(false)); check(); const timer = setInterval(check, 30_000); return () => clearInterval(timer) }, [])
  const navigate = (key) => { if (!buildPageLabels()[key]) return; setSelectedKey(key); setMobileNav(false); window.history.replaceState(null, '', `#/${key}`) }
  const pages = useMemo(() => ({ dashboard: <DashboardPage onNavigate={navigate} />, users: <UsersPage />, workspaces: <WorkspacesPage />, audit: <AuditPage />, usage: <UsagePage />, models: <ModelsPage />, skills: <SkillsPage />, mcp: <McpPage />, policies: <PoliciesPage />, settings: <SettingsPage /> }), [])
  const accountMenu = { items: [{ key: 'account', disabled: true, label: <div className="admin-account-summary"><strong>{profile.display_name}</strong><span>{profile.email}</span></div> }, { type: 'divider' }, { key: 'logout', icon: <LogoutOutlined />, label: t('admin.common.logout'), danger: true }], onClick: ({ key }) => key === 'logout' && onLogout() }
  const navigation = (isCollapsed = false) => <div className="admin-navigation">
    <div className="admin-brand"><AppstoreOutlined />{!isCollapsed && <div><strong>futureAgent</strong><span>{t('admin.tagline')}</span></div>}</div>
    <Menu theme="dark" mode="inline" selectedKeys={[selectedKey]} items={buildNavItems()} onClick={({ key }) => navigate(key)} />
    {!isCollapsed && <div className="admin-sider-status"><span className={online ? 'is-online' : ''} />{online ? t('admin.status.online') : t('admin.status.offline')}</div>}
  </div>
  return <Layout className="admin-layout">
    {screens.lg ? <Sider collapsible collapsed={collapsed} collapsedWidth={72} onCollapse={setCollapsed} width={248} theme="dark">{navigation(collapsed)}</Sider> : <Drawer placement="left" width="min(86vw, 288px)" open={mobileNav} onClose={() => setMobileNav(false)} closable={false} rootClassName="admin-mobile-drawer" styles={{ body: { padding: 0 } }}>{navigation(false)}</Drawer>}
    <Layout>
      <Header className="admin-header">
        <div className="admin-header-title">{!screens.lg && <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileNav(true)} aria-label="打开管理导航" />}<Text strong>{buildPageLabels()[selectedKey]}</Text><Badge status={online ? 'success' : 'error'} text={online ? t('admin.header.apiOk') : t('admin.header.apiError')} /></div>
        <Space className="admin-header-actions" size={10}>
          <Tooltip title={getThemeMode() === 'dark' ? '切换到浅色' : '切换到深色'}>
            <Button type="text" icon={<BulbOutlined />} onClick={() => toggleThemeMode()} aria-label="切换深浅色主题" />
          </Tooltip>
          <div className="admin-workspace-switch"><Text type="secondary">{t('admin.header.currentWorkspace')}</Text><Select aria-label="切换当前工作区" value={workspaceId || undefined} onChange={setCurrentWorkspace} placeholder="选择工作区" notFoundContent="暂无可切换的工作区" options={workspaces.map((item) => ({ value: item.id, label: item.name }))} /></div>
          <Button icon={<ExportOutlined />} href={userAppUrl} target="_blank" rel="noreferrer" aria-label="打开用户端"><span className="admin-action-label">{t('admin.header.userFrontend')}</span></Button>
          <Dropdown menu={accountMenu} placement="bottomRight" trigger={['click']}><Button type="text" className="admin-account-button" aria-label={`账号菜单：${profile.display_name}`}><Avatar size={30}>{profile.display_name?.slice(0, 1)}</Avatar><span className="admin-account-name">{profile.display_name}</span></Button></Dropdown>
        </Space>
      </Header>
      <Content className="admin-content"><Suspense fallback={<div className="admin-page-loading" aria-label="正在加载页面"><Spin size="large" /></div>}>{pages[selectedKey]}</Suspense></Content>
    </Layout>
  </Layout>
}

function AdminApp() {
  const { message } = AntApp.useApp(); const [session, setSession] = useState(null); const [restoring, setRestoring] = useState(true)
  useEffect(() => { const restore = async () => { try { if (!getAccessToken()) await refreshAccessToken(); const me = await apiFetch('/api/v1/auth/me', { workspaceId: '' }); if (!me.user.is_platform_admin) throw new Error('当前账号不是平台管理员') ; setSession(me) } catch { clearAuthSession() } finally { setRestoring(false) } }; restore() }, [])
  const loggedIn = async (payload) => { try { const me = await apiFetch('/api/v1/auth/me', { workspaceId: '' }); if (!me.user.is_platform_admin) { clearAuthSession(); throw new Error('当前账号不是平台管理员') } setSession(me) } catch (error) { message.error(toUserErrorMessage(error, '无法验证平台管理员权限，请重新登录后重试。')) } }
  const logout = async () => { try { await apiFetch('/api/v1/auth/logout', { method: 'POST', workspaceId: '' }) } catch { /* 清理本地凭据同样会结束当前会话。 */ } clearAuthSession(); setSession(null); message.success('已退出登录') }
  if (restoring) return <div className="admin-loading" aria-label="正在恢复登录状态"><Spin size="large" /></div>
  return session ? <AdminShell profile={session.user} workspaces={session.workspaces || []} onLogout={logout} /> : <Login onLogin={loggedIn} />
}

export default function App() {
  const [themeMode, setThemeMode] = useState(getThemeMode)
  useEffect(() => {
    applyThemeMode(getThemeMode())
    const themeListener = (event) => setThemeMode(event.detail || getThemeMode())
    window.addEventListener('futureagent-admin-theme', themeListener)
    return () => {
      window.removeEventListener('futureagent-admin-theme', themeListener)
    }
  }, [])
  const isDark = themeMode === 'dark'
  return <ConfigProvider locale={antdLocaleOf()} theme={{
    algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: '#4f5fd5',
      colorInfo: '#4f5fd5',
      colorBgLayout: isDark ? '#0e1420' : '#f4f7fc',
      colorBgContainer: isDark ? '#151c2b' : '#ffffff',
      colorText: isDark ? '#e3e8f2' : '#15233d',
      borderRadius: 14,
      fontFamily: '"PingFang SC", "Microsoft YaHei", ui-sans-serif, system-ui, sans-serif',
    },
  }}><AntApp><AdminApp /></AntApp></ConfigProvider>
}
