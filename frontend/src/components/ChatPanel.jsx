import React, { useState, useRef, useEffect } from 'react'
import { Card, Input, Button, Select, Tag, Space, Typography, Empty, Spin } from 'antd'
import { SendOutlined, UserOutlined, RobotOutlined } from '@ant-design/icons'

const { TextArea } = Input
const { Title, Text } = Typography

export default function ChatPanel() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [model, setModel] = useState('gpt-4o-mini')
  const [role, setRole] = useState('developer')
  const [skill, setSkill] = useState('default')
  const messagesEndRef = useRef(null)

  const models = [
    { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
    { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
    { value: 'claude-3-haiku-20240307', label: 'Claude 3 Haiku' },
    { value: 'ollama/llama3', label: 'Llama 3 (Ollama)' },
    { value: 'ollama/qwen2.5', label: 'Qwen 2.5 (Ollama)' },
    { value: 'gemini/gemini-1.5-pro', label: 'Gemini 1.5 Pro' },
    { value: 'gemini/gemini-1.5-flash', label: 'Gemini 1.5 Flash' },
  ]

  const roles = [
    { value: 'admin', label: 'Admin' },
    { value: 'developer', label: 'Developer' },
    { value: 'user', label: 'User' },
  ]

  const skills = [
    { value: 'default', label: '默认助手' },
    { value: 'chatbot', label: '聊天机器人' },
    { value: 'data_analyst', label: '数据分析师' },
    { value: 'coder', label: '代码助手' },
  ]

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async () => {
    if (!input.trim() || loading) return

    const userMsg = { role: 'user', content: input }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch('/api/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: input,
          user_role: role,
          model_id: model,
        }),
      })
      const data = await res.json()
      const assistantMsg = {
        role: 'assistant',
        content: data.content || JSON.stringify(data),
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: `错误: ${e.message}` }])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)' }}>
      <Space style={{ marginBottom: 16 }}>
        <Select value={model} onChange={setModel} options={models} style={{ width: 180 }} />
        <Select value={role} onChange={setRole} options={roles} style={{ width: 120 }} />
        <Select value={skill} onChange={setSkill} options={skills} style={{ width: 140 }} />
      </Space>

      <Card
        style={{
          flex: 1,
          background: '#1a1a2e',
          border: '1px solid #2a2a4a',
          borderRadius: 12,
          overflow: 'auto',
          marginBottom: 16,
        }}
        bodyStyle={{ padding: 16, minHeight: '100%' }}
      >
        {messages.length === 0 ? (
          <Empty
            description={<span style={{ color: '#888' }}>开始对话吧</span>}
            style={{ marginTop: 80 }}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {messages.map((msg, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                }}
              >
                <div
                  style={{
                    maxWidth: '70%',
                    padding: '10px 16px',
                    borderRadius: 12,
                    background: msg.role === 'user'
                      ? 'linear-gradient(135deg, #3b82f6, #6366f1)'
                      : '#2a2a4a',
                    color: '#e0e0e0',
                    fontSize: 14,
                    lineHeight: 1.6,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    {msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                    <Text style={{ color: '#888', fontSize: 12 }}>
                      {msg.role === 'user' ? '你' : 'AI'}
                    </Text>
                  </div>
                  <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                </div>
              </div>
            ))}
            {loading && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#888' }}>
                <Spin size="small" />
                <span>AI 正在思考...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </Card>

      <div style={{ display: 'flex', gap: 12 }}>
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
          autoSize={{ minRows: 1, maxRows: 4 }}
          style={{
            background: '#1a1a2e',
            border: '1px solid #2a2a4a',
            color: '#e0e0e0',
          }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={sendMessage}
          loading={loading}
          style={{ height: 'auto' }}
        >
          发送
        </Button>
      </div>
    </div>
  )
}
