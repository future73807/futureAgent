import React, { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, Space, Typography, message } from 'antd'
import { RobotOutlined, ReloadOutlined } from '@ant-design/icons'

const { Title, Paragraph } = Typography

export default function ModelManager() {
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(false)

  const fetchModels = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/v1/models')
      const data = await res.json()
      setModels(data.models || [])
    } catch (e) {
      message.error('获取模型列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchModels()
  }, [])

  const columns = [
    {
      title: '模型 ID',
      dataIndex: 'id',
      key: 'id',
      render: (text) => <code style={{ color: '#60a5fa' }}>{text}</code>,
    },
    {
      title: '提供商',
      dataIndex: 'provider',
      key: 'provider',
      render: (text) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: () => <Tag color="green">可用</Tag>,
    },
  ]

  const modelData = models.map((m, i) => {
    const parts = m.split('/')
    const provider = parts[0] || 'unknown'
    return {
      key: i,
      id: m,
      provider: provider.charAt(0).toUpperCase() + provider.slice(1),
      status: 'active',
    }
  })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ color: '#e0e0e0', margin: 0 }}>
            模型管理
          </Title>
          <Paragraph style={{ color: '#888', margin: '4px 0 0 0' }}>
            管理和切换不同的大语言模型
          </Paragraph>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={fetchModels}
          loading={loading}
        >
          刷新
        </Button>
      </div>

      <Card
        style={{
          background: '#1a1a2e',
          border: '1px solid #2a2a4a',
          borderRadius: 12,
        }}
      >
        <Table
          columns={columns}
          dataSource={modelData}
          pagination={false}
          loading={loading}
          style={{ background: 'transparent' }}
        />
      </Card>
    </div>
  )
}
