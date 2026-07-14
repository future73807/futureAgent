import React, { useState, useEffect } from 'react'
import { Layout, Menu, ConfigProvider, theme, message } from 'antd'
import {
  MessageOutlined,
  RobotOutlined,
  ToolOutlined,
  SafetyOutlined,
  SettingOutlined,
  DashboardOutlined,
} from '@ant-design/icons'
import ChatPanel from './components/ChatPanel.jsx'
import ModelManager from './components/ModelManager.jsx'
import SkillManager from './components/SkillManager.jsx'
import McpManager from './components/McpManager.jsx'
import AuthManager from './components/AuthManager.jsx'
import SettingsPanel from './components/SettingsPanel.jsx'
import Dashboard from './components/Dashboard.jsx'

const { Header, Sider, Content } = Layout

const items = [
  { key: 'dashboard', icon: <DashboardOutlined />, label: '概览' },
  { key: 'chat', icon: <MessageOutlined />, label: '对话' },
  { key: 'models', icon: <RobotOutlined />, label: '模型管理' },
  { key: 'skills', icon: <ToolOutlined />, label: 'Skill 管理' },
  { key: 'mcp', icon: <SettingOutlined />, label: 'MCP 管理' },
  { key: 'auth', icon: <SafetyOutlined />, label: '权限管理' },
  { key: 'settings', icon: <SettingOutlined />, label: '设置' },
]

export default function App() {
  const [selectedKey, setSelectedKey] = useState('dashboard')
  const [apiStatus, setApiStatus] = useState('checking')

  useEffect(() => {
    checkApiStatus()
    const interval = setInterval(checkApiStatus, 30000)
    return () => clearInterval(interval)
  }, [])

  const checkApiStatus = async () => {
    try {
      const res = await fetch('/api/v1/health')
      const data = await res.json()
      setApiStatus(data.status === 'ok' ? 'online' : 'offline')
    } catch (e) {
      setApiStatus('offline')
    }
  }

  const renderContent = () => {
    switch (selectedKey) {
      case 'dashboard': return <Dashboard />
      case 'chat': return <ChatPanel />
      case 'models': return <ModelManager />
      case 'skills': return <SkillManager />
      case 'mcp': return <McpManager />
      case 'auth': return <AuthManager />
      case 'settings': return <SettingsPanel />
      default: return <Dashboard />
    }
  }

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#60a5fa',
          colorBgContainer: '#1a1a2e',
          colorBgElevated: '#16213e',
          colorBorder: '#2a2a4a',
        },
      }}
    >
      <Layout style={{ minHeight: '100vh' }}>
        <Sider
          breakpoint="lg"
          collapsedWidth="0"
          style={{
            background: 'linear-gradient(180deg, #1a1a2e 0%, #16213e 100%)',
            borderRight: '1px solid #2a2a4a',
          }}
        >
          <div
            style={{
              height: 64,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 20,
              fontWeight: 'bold',
              background: 'linear-gradient(90deg, #60a5fa, #a78bfa)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              borderBottom: '1px solid #2a2a4a',
            }}
          >
            futureAgent
          </div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[selectedKey]}
            items={items}
            onClick={({ key }) => setSelectedKey(key)}
            style={{
              background: 'transparent',
              borderRight: 'none',
              marginTop: 8,
            }}
          />
        </Sider>
        <Layout>
          <Header
            style={{
              padding: '0 24px',
              background: '#1a1a2e',
              borderBottom: '1px solid #2a2a4a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ color: '#888', fontSize: 14 }}>
                {items.find(i => i.key === selectedKey)?.label}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: apiStatus === 'online' ? '#86efac' : '#f87171',
                  display: 'inline-block',
                }}
              />
              <span style={{ color: '#888', fontSize: 13 }}>
                {apiStatus === 'online' ? '服务在线' : apiStatus === 'checking' ? '检查中...' : '服务离线'}
              </span>
            </div>
          </Header>
          <Content style={{ margin: 24, overflow: 'auto' }}>
            {renderContent()}
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  )
}
