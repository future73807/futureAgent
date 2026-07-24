import React, { useEffect, useState } from 'react'
import { App, Button, Card, Space, Switch, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { apiFetch } from '../api.js'

const { Title, Text } = Typography
export default function UsersPage() {
  const { message } = App.useApp(); const [users, setUsers] = useState([]); const [loading, setLoading] = useState(false)
  const load = async () => { setLoading(true); try { setUsers((await apiFetch('/api/v1/admin/users')).users || []) } catch (error) { message.error(error.message) } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const update = async (user, patch) => { try { await apiFetch(`/api/v1/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify(patch) }); message.success('User updated'); load() } catch (error) { message.error(error.message) } }
  const columns = [
    { title: 'User', render: (_, user) => <Space direction="vertical" size={0}><Text strong>{user.display_name}</Text><Text type="secondary">{user.email}</Text></Space> },
    { title: 'Platform role', dataIndex: 'is_platform_admin', render: (value, user) => <Switch checked={value} onChange={(is_platform_admin) => update(user, { is_platform_admin })} /> },
    { title: 'Account', dataIndex: 'is_active', render: (value, user) => <Space><Switch checked={value} onChange={(is_active) => update(user, { is_active })} /><Tag color={value ? 'success' : 'error'}>{value ? 'Active' : 'Disabled'}</Tag></Space> },
    { title: 'Created', dataIndex: 'created_at', render: (value) => new Date(value).toLocaleString() },
  ]
  return <div><div className="page-heading"><div><Title level={2}>Users</Title><Text type="secondary">Suspend compromised accounts and delegate platform administration through server-enforced roles.</Text></div><Button icon={<ReloadOutlined />} loading={loading} onClick={load}>Refresh</Button></div><Card className="admin-card"><Table rowKey="id" columns={columns} dataSource={users} loading={loading} pagination={{ pageSize: 20 }} /></Card></div>
}
