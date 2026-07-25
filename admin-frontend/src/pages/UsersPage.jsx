import React, { useEffect, useState } from 'react'
import { App, Button, Card, Space, Switch, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { apiFetch, toUserErrorMessage } from '../api.js'
import { formatDateTime } from '../formatters.js'

const { Title, Text } = Typography
export default function UsersPage() {
  const { message, modal } = App.useApp(); const [users, setUsers] = useState([]); const [loading, setLoading] = useState(false); const [updatingKey, setUpdatingKey] = useState('')
  const load = async () => { setLoading(true); try { setUsers((await apiFetch('/api/v1/admin/users')).users || []) } catch (error) { message.error(toUserErrorMessage(error, '加载用户列表失败，请稍后重试。')) } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const update = async (user, patch) => {
    const field = Object.keys(patch)[0]
    setUpdatingKey(`${user.id}:${field}`)
    try { await apiFetch(`/api/v1/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify(patch) }); message.success('用户信息已更新'); await load() } catch (error) { message.error(toUserErrorMessage(error, '更新用户信息失败，请稍后重试。')) } finally { setUpdatingKey('') }
  }
  const requestUpdate = (user, field, checked) => {
    const isAdmin = field === 'is_platform_admin'
    const action = isAdmin ? (checked ? '授予平台管理员权限' : '移除平台管理员权限') : (checked ? '启用账号' : '停用账号')
    modal.confirm({
      title: `确认${action}？`,
      content: `${action}将立即影响“${user.display_name || user.email}”的访问范围。`,
      okText: '确认',
      cancelText: '取消',
      okButtonProps: checked ? undefined : { danger: true },
      onOk: () => update(user, { [field]: checked }),
    })
  }
  const columns = [
    { title: '用户', render: (_, user) => <Space direction="vertical" size={0}><Text strong>{user.display_name}</Text><Text type="secondary">{user.email}</Text></Space> },
    { title: '平台管理员', dataIndex: 'is_platform_admin', render: (value, user) => <Switch checked={value} checkedChildren="开" unCheckedChildren="关" loading={updatingKey === `${user.id}:is_platform_admin`} aria-label={`切换 ${user.display_name || user.email} 的平台管理员权限`} onChange={(is_platform_admin) => requestUpdate(user, 'is_platform_admin', is_platform_admin)} /> },
    { title: '账号状态', dataIndex: 'is_active', render: (value, user) => <Space><Switch checked={value} checkedChildren="开" unCheckedChildren="关" loading={updatingKey === `${user.id}:is_active`} aria-label={`切换 ${user.display_name || user.email} 的账号状态`} onChange={(is_active) => requestUpdate(user, 'is_active', is_active)} /><Tag color={value ? 'success' : 'error'}>{value ? '正常' : '已停用'}</Tag></Space> },
    { title: '创建时间', dataIndex: 'created_at', render: formatDateTime },
  ]
  return <div><div className="page-heading"><div><Title level={2}>用户管理</Title><Text type="secondary">停用风险账号，并通过服务端强制的角色权限委派平台管理职责。</Text></div><Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button></div><Card className="admin-card"><Table rowKey="id" columns={columns} dataSource={users} loading={loading} pagination={{ pageSize: 20 }} locale={{ emptyText: '暂无数据' }} /></Card></div>
}
