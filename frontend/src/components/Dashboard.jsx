import React from 'react'
import { Card, Row, Col, Statistic, Tag, Typography } from 'antd'
import {
  RobotOutlined,
  ToolOutlined,
  SafetyOutlined,
  MessageOutlined,
} from '@ant-design/icons'

const { Title, Paragraph } = Typography

export default function Dashboard() {
  const stats = [
    { title: '可用模型', value: 9, icon: <RobotOutlined />, color: '#60a5fa' },
    { title: '已注册 Skill', value: 4, icon: <ToolOutlined />, color: '#a78bfa' },
    { title: '权限角色', value: 3, icon: <SafetyOutlined />, color: '#86efac' },
    { title: 'API 端点', value: 6, icon: <MessageOutlined />, color: '#fbbf24' },
  ]

  const features = [
    { title: '多模型切换', desc: '支持 9+ 大模型，一键切换' },
    { title: '权限管理', desc: 'Casbin RBAC 细粒度控制' },
    { title: 'Skill 装配', desc: '动态加载领域专属技能' },
    { title: 'MCP 工具', desc: '标准协议集成外部工具' },
    { title: '流式响应', desc: 'SSE 实时推送' },
    { title: 'LangGraph 编排', desc: '状态机驱动 Agent 执行' },
  ]

  return (
    <div>
      <Title level={3} style={{ color: '#e0e0e0', marginBottom: 24 }}>
        系统概览
      </Title>
      
      <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
        {stats.map((s, i) => (
          <Col xs={24} sm={12} lg={6} key={i}>
            <Card
              style={{
                background: '#1a1a2e',
                border: '1px solid #2a2a4a',
                borderRadius: 12,
              }}
            >
              <Statistic
                title={<span style={{ color: '#888' }}>{s.title}</span>}
                value={s.value}
                prefix={
                  <span style={{ color: s.color, marginRight: 8 }}>{s.icon}</span>
                }
                valueStyle={{ color: '#e0e0e0' }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      <Title level={4} style={{ color: '#e0e0e0', marginBottom: 16 }}>
        核心功能
      </Title>
      <Row gutter={[16, 16]}>
        {features.map((f, i) => (
          <Col xs={24} sm={12} lg={8} key={i}>
            <Card
              hoverable
              style={{
                background: '#1a1a2e',
                border: '1px solid #2a2a4a',
                borderRadius: 12,
              }}
            >
              <Title level={5} style={{ color: '#e0e0e0', marginBottom: 8 }}>
                {f.title}
              </Title>
              <Paragraph style={{ color: '#888', fontSize: 13, margin: 0 }}>
                {f.desc}
              </Paragraph>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
