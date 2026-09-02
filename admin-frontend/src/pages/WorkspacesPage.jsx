import React, { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { apiFetch, toUserErrorMessage } from '../api.js'
import { formatDateTime } from '../formatters.js'

const { Title, Text } = Typography
const planLabels = { free: '免费版', trial: '试用版', pro: '专业版', professional: '专业版', enterprise: '企业版' }

export default function WorkspacesPage() {
  const { message, modal } = App.useApp(); const [workspaces, setWorkspaces] = useState([]); const [loading, setLoading] = useState(false); const [createOpen, setCreateOpen] = useState(false); const [creating, setCreating] = useState(false); const [userOptions, setUserOptions] = useState([]); const [form] = Form.useForm()
  const load = async () => { setLoading(true); try { setWorkspaces((await apiFetch('/api/v1/admin/workspaces')).workspaces || []) } catch (error) { message.error(toUserErrorMessage(error, '加载工作区列表失败，请稍后重试。')) } finally { setLoading(false) } }
  const loadUsers = async () => {
    try { setUserOptions((await apiFetch('/api/v1/admin/users?limit=200')).users || []) } catch { /* 下拉为空时仍可打开弹窗 */ }
  }
  useEffect(() => { load() }, [])
  const openCreate = () => { loadUsers(); setCreateOpen(true) }
  const createWorkspace = async (values) => {
    setCreating(true)
    try {
      await apiFetch('/api/v1/admin/workspaces', { method: 'POST', body: JSON.stringify(values) })
      message.success('工作区已创建，所有者已自动加入')
      setCreateOpen(false)
      form.resetFields()
      await load()
    } catch (error) { message.error(toUserErrorMessage(error, '创建工作区失败，请稍后重试。')) } finally { setCreating(false) }
  }
  const requestDelete = (workspace) => {
    modal.confirm({
      title: `确认删除工作区“${workspace.name}”？`,
      content: '将永久删除该工作区的全部成员、项目、任务、对话、附件与审计记录，且不可恢复。',
      okText: '永久删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await apiFetch(`/api/v1/admin/workspaces/${workspace.id}`, { method: 'DELETE' })
          message.success('工作区已删除')
          await load()
        } catch (error) { message.error(toUserErrorMessage(error, '删除工作区失败，请稍后重试。')) }
      },
    })
  }
  const columns = [
    { title: '工作区', render: (_, item) => <><Text strong>{item.name}</Text><br /><Text type="secondary" className="code-text">{item.slug}</Text></> },
    { title: '套餐', dataIndex: 'plan', render: (value) => <Tag color="blue">{planLabels[value] || value || '未设置'}</Tag> },
    { title: '成员数', dataIndex: 'member_count' },
    { title: '创建时间', dataIndex: 'created_at', render: formatDateTime },
    { title: '操作', width: 100, render: (_, item) => <Button size="small" danger icon={<DeleteOutlined />} onClick={() => requestDelete(item)} aria-label={`删除 ${item.name}`}>删除</Button> },
  ]
  return <div>
    <div className="page-heading">
      <div><Title level={2}>工作区</Title><Text type="secondary">租户边界、所有权和成员关系均由服务端持久化管理，不依赖浏览器状态。</Text></div>
      <Space>
        <Button icon={<PlusOutlined />} type="primary" onClick={openCreate}>新建工作区</Button>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
      </Space>
    </div>
    <Card className="admin-card"><Table rowKey="id" columns={columns} dataSource={workspaces} loading={loading} locale={{ emptyText: '暂无数据' }} /></Card>
    <Modal title="新建工作区" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => form.submit()} confirmLoading={creating} okText="创建" cancelText="取消" destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={createWorkspace}>
        <Form.Item name="name" label="工作区名称" rules={[{ required: true, min: 2 }]}><Input placeholder="例如：产品研发中心" /></Form.Item>
        <Form.Item name="owner_user_id" label="所有者（已注册用户）" rules={[{ required: true, message: '请选择所有者' }]}>
          <Select showSearch optionFilterProp="label" placeholder="选择一个用户作为所有者" options={userOptions.map((user) => ({ value: user.id, label: `${user.display_name}（${user.email}）` }))} />
        </Form.Item>
      </Form>
    </Modal>
  </div>
}
