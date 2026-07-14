import React, { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, Space, Typography, message, Modal, Input } from 'antd'
import { ToolOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'

const { Title, Paragraph } = Typography

export default function SkillManager() {
  const [skills, setSkills] = useState([])
  const [loading, setLoading] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [newSkill, setNewSkill] = useState({ name: '', description: '', system_prompt: '' })

  const fetchSkills = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/v1/skills')
      const data = await res.json()
      setSkills(data.skills || [])
    } catch (e) {
      message.error('获取 Skill 列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSkills()
  }, [])

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (text) => <code style={{ color: '#a78bfa' }}>{text}</code>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      render: (text) => <span style={{ color: '#888' }}>{text}</span>,
    },
    {
      title: '工具白名单',
      dataIndex: 'allowed_tool_names',
      key: 'tools',
      render: (tools) => (
        <Space wrap>
          {(tools || []).map((t, i) => (
            <Tag key={i} color="cyan">{t}</Tag>
          ))}
          {(!tools || tools.length === 0) && <Tag>全部工具</Tag>}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ color: '#e0e0e0', margin: 0 }}>
            Skill 管理
          </Title>
          <Paragraph style={{ color: '#888', margin: '4px 0 0 0' }}>
            管理领域专属技能配置
          </Paragraph>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchSkills} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalOpen(true)}>
            新建 Skill
          </Button>
        </Space>
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
          dataSource={skills.map((s, i) => ({ ...s, key: i }))}
          pagination={false}
          loading={loading}
          style={{ background: 'transparent' }}
        />
      </Card>

      <Modal
        title="新建 Skill"
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        onOk={() => {
          message.success('Skill 创建成功（演示）')
          setIsModalOpen(false)
        }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <div>
            <label style={{ color: '#888', fontSize: 13 }}>名称</label>
            <Input
              value={newSkill.name}
              onChange={(e) => setNewSkill({ ...newSkill, name: e.target.value })}
              placeholder="my_skill"
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <label style={{ color: '#888', fontSize: 13 }}>描述</label>
            <Input
              value={newSkill.description}
              onChange={(e) => setNewSkill({ ...newSkill, description: e.target.value })}
              placeholder="我的自定义 Skill"
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <label style={{ color: '#888', fontSize: 13 }}>系统提示词</label>
            <Input.TextArea
              value={newSkill.system_prompt}
              onChange={(e) => setNewSkill({ ...newSkill, system_prompt: e.target.value })}
              placeholder="你是一个专业的..."
              rows={4}
              style={{ marginTop: 4 }}
            />
          </div>
        </Space>
      </Modal>
    </div>
  )
}
