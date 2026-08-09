import React, { useEffect, useState } from 'react'
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { App, Button, Card, Input, Modal, Popconfirm, Space, Table, Tag, Typography } from 'antd'
import { apiFetch, toUserErrorMessage } from '../api.js'

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
    catch (error) { message.error(toUserErrorMessage(error, '加载权限策略失败，请稍后重试。')) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const add = async () => {
    if (!draft.role || !draft.resource || !draft.action) return message.warning('请完整填写策略')
    try {
      await apiFetch('/api/v1/auth/policies', { method: 'POST', body: JSON.stringify(draft) })
      message.success('策略已添加'); setOpen(false); setDraft(emptyPolicy); load()
    } catch (error) { message.error(toUserErrorMessage(error, '添加权限策略失败，请检查内容后重试。')) }
  }
  const remove = async (policy) => {
    try { await apiFetch('/api/v1/auth/policies', { method: 'DELETE', body: JSON.stringify(policy) }); message.success('策略已删除'); load() }
    catch (error) { message.error(toUserErrorMessage(error, '删除权限策略失败，请稍后重试。')) }
  }

  const columns = [
    { title: '角色', dataIndex: 'role', render: (value) => <Tag color="purple">{value}</Tag> },
    { title: '资源', dataIndex: 'resource', render: (value) => <span className="code-text">{value}</span> },
    { title: '动作', dataIndex: 'action', render: (value) => <Tag color="green">{value}</Tag> },
    { title: '操作', width: 100, render: (_, policy) => <Popconfirm title="删除这条策略？" onConfirm={() => remove(policy)} okText="确认" cancelText="取消"><Button danger type="link" icon={<DeleteOutlined />}>删除</Button></Popconfirm> },
  ]

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>权限策略</Title><Text type="secondary">Casbin RBAC 控制模型、技能、MCP 服务与具体工具</Text></div>
        <Space><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>添加策略</Button></Space>
      </div>
      <Card className="admin-card"><Table rowKey={(item) => `${item.role}:${item.resource}:${item.action}`} columns={columns} dataSource={policies} loading={loading} pagination={false} scroll={{ x: 'max-content' }} locale={{ emptyText: '暂无数据' }} /></Card>
      <Modal title="添加权限策略" open={open} onCancel={() => setOpen(false)} onOk={add} okText="确认" cancelText="取消">
        <div className="form-stack">
          <div><label htmlFor="policy-role">角色</label><Input id="policy-role" aria-required="true" value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value })} placeholder="developer" /></div>
          <div><label htmlFor="policy-resource">资源</label><Input id="policy-resource" aria-required="true" value={draft.resource} onChange={(event) => setDraft({ ...draft, resource: event.target.value })} placeholder="model:*" /></div>
          <div><label htmlFor="policy-action">动作</label><Input id="policy-action" aria-required="true" value={draft.action} onChange={(event) => setDraft({ ...draft, action: event.target.value })} placeholder="use" /></div>
        </div>
      </Modal>
    </div>
  )
}
