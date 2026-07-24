import React, { useEffect, useState } from 'react'
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { App, Button, Card, Input, Modal, Popconfirm, Space, Table, Tag, Typography } from 'antd'
import { apiFetch } from '../api.js'

const { Title, Text } = Typography
const emptyPolicy = { role: '', resource: '', action: 'use' }

export default function PoliciesPage() {
  const { message } = App.useApp()
  const [policies, setPolicies] = useState([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(emptyPolicy)

  const load = async () => {
    setLoading(true)
    try { setPolicies(((await apiFetch('/api/v1/auth/policies')).policies || []).map(([role, resource, action]) => ({ role, resource, action }))) }
    catch (error) { message.error(error.message) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const add = async () => {
    if (!draft.role || !draft.resource || !draft.action) return message.warning('请完整填写策略')
    try {
      await apiFetch('/api/v1/auth/policies', { method: 'POST', body: JSON.stringify(draft) })
      message.success('策略已添加'); setOpen(false); setDraft(emptyPolicy); load()
    } catch (error) { message.error(error.message) }
  }
  const remove = async (policy) => {
    try { await apiFetch('/api/v1/auth/policies', { method: 'DELETE', body: JSON.stringify(policy) }); message.success('策略已删除'); load() }
    catch (error) { message.error(error.message) }
  }

  const columns = [
    { title: '角色', dataIndex: 'role', render: (value) => <Tag color="purple">{value}</Tag> },
    { title: '资源', dataIndex: 'resource', render: (value) => <span className="code-text">{value}</span> },
    { title: '动作', dataIndex: 'action', render: (value) => <Tag color="green">{value}</Tag> },
    { title: '操作', width: 100, render: (_, policy) => <Popconfirm title="删除这条策略？" onConfirm={() => remove(policy)}><Button danger type="link" icon={<DeleteOutlined />}>删除</Button></Popconfirm> },
  ]

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>权限策略</Title><Text type="secondary">Casbin RBAC 控制模型、Skill、MCP 服务与具体工具</Text></div>
        <Space><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>添加策略</Button></Space>
      </div>
      <Card className="admin-card"><Table rowKey={(item) => `${item.role}:${item.resource}:${item.action}`} columns={columns} dataSource={policies} loading={loading} pagination={false} /></Card>
      <Modal title="添加权限策略" open={open} onCancel={() => setOpen(false)} onOk={add}>
        <div className="form-stack">
          <div><label>角色</label><Input value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value })} placeholder="developer" /></div>
          <div><label>资源</label><Input value={draft.resource} onChange={(event) => setDraft({ ...draft, resource: event.target.value })} placeholder="model:*" /></div>
          <div><label>动作</label><Input value={draft.action} onChange={(event) => setDraft({ ...draft, action: event.target.value })} placeholder="use" /></div>
        </div>
      </Modal>
    </div>
  )
}
