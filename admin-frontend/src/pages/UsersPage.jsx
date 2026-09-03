import React, { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, Modal, Space, Switch, Table, Tag, Typography } from 'antd'
import { LogoutOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { apiFetch, toUserErrorMessage } from '../api.js'
import { formatDateTime } from '../formatters.js'

const { Title, Text } = Typography
export default function UsersPage() {
  const { message, modal } = App.useApp(); const [users, setUsers] = useState([]); const [loading, setLoading] = useState(false); const [updatingKey, setUpdatingKey] = useState(''); const [createOpen, setCreateOpen] = useState(false); const [creating, setCreating] = useState(false); const [resetTarget, setResetTarget] = useState(null); const [resetForm] = Form.useForm(); const [createForm] = Form.useForm()
  const load = async () => { setLoading(true); try { setUsers((await apiFetch('/api/v1/admin/users?limit=200')).users || []) } catch (error) { message.error(toUserErrorMessage(error, '加载用户列表失败，请稍后重试。')) } finally { setLoading(false) } }
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
  const createUser = async (values) => {
    setCreating(true)
    try {
      await apiFetch('/api/v1/admin/users', {
        method: 'POST',
        body: JSON.stringify({ ...values, is_platform_admin: Boolean(values.is_platform_admin) }),
      })
      message.success('用户已创建')
      setCreateOpen(false)
      createForm.resetFields()
      await load()
    } catch (error) { message.error(toUserErrorMessage(error, '创建用户失败，请稍后重试。')) } finally { setCreating(false) }
  }
  const submitReset = async (values) => {
    try {
      await apiFetch(`/api/v1/admin/users/${resetTarget.id}/reset-password`, { method: 'POST', body: JSON.stringify({ password: values.password }) })
      message.success('密码已重置，该账号的登录会话已全部撤销')
      setResetTarget(null)
      resetForm.resetFields()
    } catch (error) { message.error(toUserErrorMessage(error, '重置密码失败，请稍后重试。')) }
  }
  const revokeSessions = (user) => {
    modal.confirm({
      title: `吊销「${user.display_name || user.email}」的全部登录会话？`,
      content: '吊销后该账号需要重新登录才能继续使用。',
      okText: '吊销会话',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const result = await apiFetch(`/api/v1/admin/users/${user.id}/revoke-sessions`, { method: 'POST' })
          message.success(`已吊销 ${result.revoked} 个活跃会话`)
        } catch (error) { message.error(toUserErrorMessage(error, '吊销会话失败，请稍后重试。')) }
      },
    })
  }
  const columns = [
    { title: '用户', render: (_, user) => <Space direction="vertical" size={0}><Text strong>{user.display_name}</Text><Text type="secondary">{user.email}</Text></Space> },
    { title: '平台管理员', dataIndex: 'is_platform_admin', render: (value, user) => <Switch checked={value} checkedChildren="开" unCheckedChildren="关" loading={updatingKey === `${user.id}:is_platform_admin`} aria-label={`切换 ${user.display_name || user.email} 的平台管理员权限`} onChange={(is_platform_admin) => requestUpdate(user, 'is_platform_admin', is_platform_admin)} /> },
    { title: '账号状态', dataIndex: 'is_active', render: (value, user) => <Space><Switch checked={value} checkedChildren="开" unCheckedChildren="关" loading={updatingKey === `${user.id}:is_active`} aria-label={`切换 ${user.display_name || user.email} 的账号状态`} onChange={(is_active) => requestUpdate(user, 'is_active', is_active)} /><Tag color={value ? 'success' : 'error'}>{value ? '正常' : '已停用'}</Tag></Space> },
    { title: '创建时间', dataIndex: 'created_at', render: formatDateTime },
    {
      title: '操作', width: 190, render: (_, user) => <Space size={4}>
        <Button size="small" onClick={() => { setResetTarget(user); resetForm.resetFields() }}>重置密码</Button>
        <Button size="small" icon={<LogoutOutlined />} disabled={!user.is_active} onClick={() => revokeSessions(user)}>吊销会话</Button>
      </Space>,
    },
  ]
  return <div>
    <div className="page-heading">
      <div><Title level={2}>用户管理</Title><Text type="secondary">创建账号、重置密码、停用风险账号，并通过服务端强制的角色权限委派平台管理职责。</Text></div>
      <Space>
        <Button icon={<PlusOutlined />} type="primary" onClick={() => setCreateOpen(true)}>新建用户</Button>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
      </Space>
    </div>
    <Card className="admin-card"><Table rowKey="id" columns={columns} dataSource={users} loading={loading} pagination={{ pageSize: 20 }} locale={{ emptyText: '暂无数据' }} /></Card>
    <Modal title="新建用户" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => createForm.submit()} confirmLoading={creating} okText="创建" cancelText="取消" destroyOnHidden>
      <Form form={createForm} layout="vertical" onFinish={createUser} initialValues={{ is_platform_admin: false }}>
        <Form.Item name="display_name" label="姓名" rules={[{ required: true, min: 2 }]}><Input placeholder="团队成员姓名" /></Form.Item>
        <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}><Input placeholder="name@company.com" /></Form.Item>
        <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 10, message: '密码至少 10 个字符' }]}><Input.Password placeholder="至少 10 个字符" autoComplete="new-password" /></Form.Item>
        <Form.Item name="is_platform_admin" label="平台管理员" valuePropName="checked"><Switch checkedChildren="是" unCheckedChildren="否" /></Form.Item>
      </Form>
    </Modal>
    <Modal title={`重置密码：${resetTarget?.display_name || resetTarget?.email || ''}`} open={Boolean(resetTarget)} onCancel={() => setResetTarget(null)} onOk={() => resetForm.submit()} okText="重置" cancelText="取消" destroyOnHidden>
      {resetTarget && <Text type="secondary">重置后该账号（{resetTarget.email}）的全部登录会话将被撤销，需要用新密码重新登录。</Text>}
      <Form form={resetForm} layout="vertical" onFinish={submitReset} style={{ marginTop: 16 }}>
        <Form.Item name="password" label="新密码" rules={[{ required: true, min: 10, message: '密码至少 10 个字符' }]}><Input.Password placeholder="至少 10 个字符" autoComplete="new-password" /></Form.Item>
      </Form>
    </Modal>
  </div>
}
