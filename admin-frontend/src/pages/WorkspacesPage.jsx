import React, { useEffect, useState } from 'react'
import { App, Button, Card, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { apiFetch, toUserErrorMessage } from '../api.js'
import { formatDateTime } from '../formatters.js'

const { Title, Text } = Typography
const planLabels = { free: '免费版', trial: '试用版', pro: '专业版', professional: '专业版', enterprise: '企业版' }

export default function WorkspacesPage() {
  const { message } = App.useApp(); const [workspaces, setWorkspaces] = useState([]); const [loading, setLoading] = useState(false)
  const load = async () => { setLoading(true); try { setWorkspaces((await apiFetch('/api/v1/admin/workspaces')).workspaces || []) } catch (error) { message.error(toUserErrorMessage(error, '加载工作区列表失败，请稍后重试。')) } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const columns = [{ title: '工作区', render: (_, item) => <><Text strong>{item.name}</Text><br /><Text type="secondary" className="code-text">{item.slug}</Text></> }, { title: '套餐', dataIndex: 'plan', render: (value) => <Tag color="blue">{planLabels[value] || value || '未设置'}</Tag> }, { title: '成员数', dataIndex: 'member_count' }, { title: '创建时间', dataIndex: 'created_at', render: formatDateTime }]
  return <div><div className="page-heading"><div><Title level={2}>工作区</Title><Text type="secondary">租户边界、所有权和成员关系均由服务端持久化管理，不依赖浏览器状态。</Text></div><Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button></div><Card className="admin-card"><Table rowKey="id" columns={columns} dataSource={workspaces} loading={loading} locale={{ emptyText: '暂无数据' }} /></Card></div>
}
