import React, { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import zhCN from 'antd/es/locale/zh_CN'
import { App as AntApp, Avatar, Badge, Button, Card, ConfigProvider, Drawer, Dropdown, Form, Grid, Input, Layout, Menu, Select, Space, Spin, Typography, theme } from 'antd'
import { ApiOutlined, AppstoreOutlined, AuditOutlined, CheckCircleFilled, DashboardOutlined, ExportOutlined, LogoutOutlined, MenuOutlined, RobotOutlined, SafetyOutlined, SettingOutlined, TeamOutlined, ToolOutlined, UserOutlined } from '@ant-design/icons'
import { apiFetch, applyAuthSession, clearAuthSession, getAccessToken, getWorkspaceId, refreshAccessToken, setWorkspaceId, toUserErrorMessage, userFrontendUrl } from './api.js'

const DashboardPage = lazy(() => import('./pages/DashboardPage.jsx'))
const ModelsPage = lazy(() => import('./pages/ModelsPage.jsx'))
const SkillsPage = lazy(() => import('./pages/SkillsPage.jsx'))
const McpPage = lazy(() => import('./pages/McpPage.jsx'))
const PoliciesPage = lazy(() => import('./pages/PoliciesPage.jsx'))
const SettingsPage = lazy(() => import('./pages/SettingsPage.jsx'))
const UsersPage = lazy(() => import('./pages/UsersPage.jsx'))
const WorkspacesPage = lazy(() => import('./pages/WorkspacesPage.jsx'))
const AuditPage = lazy(() => import('./pages/AuditPage.jsx'))

const { Header, Sider, Content } = Layout
const { Text, Title } = Typography
const navItems = [
  {
    type: 'group', label: '运营管理', children: [
      { key: 'dashboard', icon: <DashboardOutlined />, label: '平台概览' },
      { key: 'users', icon: <UserOutlined />, label: '用户管理' },
      { key: 'workspaces', icon: <TeamOutlined />, label: '工作区' },
      { key: 'audit', icon: <AuditOutlined />, label: '审计轨迹' },
    ],
  },
  {
    type: 'group', label: '能力与治理', children: [
      { key: 'models', icon: <RobotOutlined />, label: '模型中心' },
      { key: 'skills', icon: <ToolOutlined />, label: '技能管理' },
      { key: 'mcp', icon: <ApiOutlined />, label: 'MCP 服务' },
      { key: 'policies', icon: <SafetyOutlined />, label: '权限策略' },
      { key: 'settings', icon: <SettingOutlined />, label: '运行设置' },
    ],
  },
]

const pageLabels = Object.fromEntries(navItems.flatMap((group) => group.children || []).map((item) => [item.key, item.label]))

function Login({ onLogin }) {
  const { message } = AntApp.useApp(); const [loading, setLoading] = useState(false)
  const submit = async (values) => { setLoading(true); try { const data = await apiFetch('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(values), workspaceId: '' }); applyAuthSession(data); await onLogin(data) } catch (error) { message.error(toUserErrorMessage(error, '登录失败，请检查账号和网络后重试。')) } finally { setLoading(false) } }
  return <main className="admin-auth">
    <div className="admin-auth-shell">
      <section className="admin-auth-intro" aria-label="平台能力简介">
        <div className="admin-auth-brand"><span className="admin-auth-logo"><AppstoreOutlined /></span><span>futureAgent</span></div>
        <div>
          <Text className="admin-auth-eyebrow">AI WORKSPACE CONTROL</Text>
          <Title>让模型、工具和权限<br />保持清晰可控</Title>
          <Text className="admin-auth-copy">统一管理团队工作区、模型路由、Skills 与 MCP 服务，在一个可靠边界内完成运营与审计。</Text>
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
          <div><Title level={2}>欢迎回来</Title><Text type="secondary">登录平台运营中心</Text></div>
        </Space>
        <Form layout="vertical" onFinish={submit} requiredMark={false} size="large" validateMessages={{ required: '${label}不能为空', types: { email: '${label}格式不正确' } }}>
          <Form.Item name="email" label="管理员邮箱" rules={[{ required: true, type: 'email' }]}><Input autoComplete="email" autoFocus placeholder="name@company.com" /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" placeholder="请输入登录密码" /></Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={loading}>进入管理后台</Button>
        </Form>
        <Text type="secondary" className="admin-auth-note">仅限已授权的平台管理员访问</Text>
      </Card>
    </div>
  </main>
}

function AdminShell({ profile, workspaces, onLogout }) {
  const initialPage = window.location.hash.replace(/^#\/?/, '')
  const screens = Grid.useBreakpoint()
  const [selectedKey, setSelectedKey] = useState(pageLabels[initialPage] ? initialPage : 'dashboard'); const [collapsed, setCollapsed] = useState(false); const [mobileNav, setMobileNav] = useState(false); const [online, setOnline] = useState(false); const [workspaceId, setCurrentWorkspace] = useState(getWorkspaceId() || workspaces[0]?.id || '')
  const userAppUrl = userFrontendUrl()
  useEffect(() => { setWorkspaceId(workspaceId) }, [workspaceId])
  useEffect(() => { const check = () => apiFetch('/api/v1/health', { workspaceId: '' }).then(() => setOnline(true)).catch(() => setOnline(false)); check(); const timer = setInterval(check, 30_000); return () => clearInterval(timer) }, [])
  const navigate = (key) => { if (!pageLabels[key]) return; setSelectedKey(key); setMobileNav(false); window.history.replaceState(null, '', `#/${key}`) }
  const pages = useMemo(() => ({ dashboard: <DashboardPage onNavigate={navigate} />, users: <UsersPage />, workspaces: <WorkspacesPage />, audit: <AuditPage />, models: <ModelsPage />, skills: <SkillsPage />, mcp: <McpPage />, policies: <PoliciesPage />, settings: <SettingsPage /> }), [])
  const accountMenu = { items: [{ key: 'account', disabled: true, label: <div className="admin-account-summary"><strong>{profile.display_name}</strong><span>{profile.email}</span></div> }, { type: 'divider' }, { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true }], onClick: ({ key }) => key === 'logout' && onLogout() }
  const navigation = (isCollapsed = false) => <div className="admin-navigation">
    <div className="admin-brand"><AppstoreOutlined />{!isCollapsed && <div><strong>futureAgent</strong><span>平台运营中心</span></div>}</div>
    <Menu theme="dark" mode="inline" selectedKeys={[selectedKey]} items={navItems} onClick={({ key }) => navigate(key)} />
    {!isCollapsed && <div className="admin-sider-status"><span className={online ? 'is-online' : ''} />{online ? '服务运行正常' : '服务连接异常'}</div>}
  </div>
  return <Layout className="admin-layout">
    {screens.lg ? <Sider collapsible collapsed={collapsed} collapsedWidth={72} onCollapse={setCollapsed} width={248} theme="dark">{navigation(collapsed)}</Sider> : <Drawer placement="left" width="min(86vw, 288px)" open={mobileNav} onClose={() => setMobileNav(false)} closable={false} rootClassName="admin-mobile-drawer" styles={{ body: { padding: 0 } }}>{navigation(false)}</Drawer>}
    <Layout>
      <Header className="admin-header">
        <div className="admin-header-title">{!screens.lg && <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileNav(true)} aria-label="打开管理导航" />}<Text strong>{pageLabels[selectedKey]}</Text><Badge status={online ? 'success' : 'error'} text={online ? 'API 正常' : 'API 异常'} /></div>
        <Space className="admin-header-actions" size={10}>
          <div className="admin-workspace-switch"><Text type="secondary">当前工作区</Text><Select aria-label="切换当前工作区" value={workspaceId || undefined} onChange={setCurrentWorkspace} placeholder="选择工作区" notFoundContent="暂无可切换的工作区" options={workspaces.map((item) => ({ value: item.id, label: item.name }))} /></div>
          <Button icon={<ExportOutlined />} href={userAppUrl} target="_blank" rel="noreferrer"><span className="admin-action-label">用户端</span></Button>
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

export default function App() { return <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#4263eb', borderRadius: 14, colorBgLayout: '#f3f6fc', fontFamily: '"PingFang SC", "Microsoft YaHei", ui-sans-serif, system-ui, sans-serif' } }}><AntApp><AdminApp /></AntApp></ConfigProvider> }
