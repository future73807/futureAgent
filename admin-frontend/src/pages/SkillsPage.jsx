import React, { useEffect, useState } from 'react'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { App, Button, Card, Input, Modal, Popconfirm, Space, Table, Tag, Typography } from 'antd'
import { apiFetch, toUserErrorMessage } from '../api.js'

const { Title, Text } = Typography
const emptySkill = { name: '', description: '', system_prompt: '', allowed_tool_names: [] }

export default function SkillsPage() {
  const { message } = App.useApp()
  const [skills, setSkills] = useState([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(emptySkill)
  const [tools, setTools] = useState('')

  const load = async () => {
    setLoading(true)
    try { setSkills((await apiFetch('/api/v1/skills')).skills || []) }
    catch (error) { message.error(toUserErrorMessage(error, '加载技能列表失败，请稍后重试。')) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const showEditor = (skill) => {
    setEditing(Boolean(skill))
    setDraft(skill ? { ...skill } : { ...emptySkill })
    setTools((skill?.allowed_tool_names || []).join(', '))
    setOpen(true)
  }

  const save = async () => {
    if (!draft.name || !draft.description || !draft.system_prompt) return message.warning('请完整填写技能信息')
    const payload = { ...draft, allowed_tool_names: tools.split(',').map((item) => item.trim()).filter(Boolean) }
    try {
      await apiFetch(editing ? `/api/v1/skills/${draft.name}` : '/api/v1/skills', {
        method: editing ? 'PUT' : 'POST', body: JSON.stringify(payload),
      })
      message.success(editing ? '技能已更新' : '技能已创建')
      setOpen(false)
      load()
    } catch (error) { message.error(toUserErrorMessage(error, editing ? '更新技能失败，请检查内容后重试。' : '创建技能失败，请检查内容后重试。')) }
  }

  const remove = async (name) => {
    try { await apiFetch(`/api/v1/skills/${name}`, { method: 'DELETE' }); message.success('技能已删除'); load() }
    catch (error) { message.error(toUserErrorMessage(error, '删除技能失败，请稍后重试。')) }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', render: (value) => <span className="code-text">{value}</span> },
    { title: '描述', dataIndex: 'description' },
    { title: '工具白名单', dataIndex: 'allowed_tool_names', render: (values) => <Space wrap>{values?.length ? values.map((value) => <Tag color="cyan" key={value}>{value}</Tag>) : <Tag>全部授权工具</Tag>}</Space> },
    {
      title: '操作', width: 170,
      render: (_, skill) => skill.name === 'default' ? <Tag>内置</Tag> : (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => showEditor(skill)}>编辑</Button>
          <Popconfirm title="删除这个技能？" onConfirm={() => remove(skill.name)} okText="确认" cancelText="取消"><Button danger type="link" icon={<DeleteOutlined />}>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>技能管理</Title><Text type="secondary">维护系统提示词与工具白名单，配置持久化到 YAML</Text></div>
        <Space><Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => showEditor(null)}>新建技能</Button></Space>
      </div>
      <Card className="admin-card"><Table rowKey="name" columns={columns} dataSource={skills} loading={loading} pagination={false} scroll={{ x: 'max-content' }} locale={{ emptyText: '暂无数据' }} /></Card>
      <Modal title={editing ? '编辑技能' : '新建技能'} open={open} onCancel={() => setOpen(false)} onOk={save} okText="确认" cancelText="取消" width={680}>
        <div className="form-stack">
          <div><label htmlFor="skill-name">名称</label><Input id="skill-name" aria-required="true" disabled={editing} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="my_skill" /></div>
          <div><label htmlFor="skill-description">描述</label><Input id="skill-description" aria-required="true" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></div>
          <div><label htmlFor="skill-system-prompt">系统提示词</label><Input.TextArea id="skill-system-prompt" aria-required="true" rows={8} value={draft.system_prompt} onChange={(event) => setDraft({ ...draft, system_prompt: event.target.value })} /></div>
          <div><label htmlFor="skill-tools">工具白名单（逗号分隔，留空表示全部授权工具）</label><Input id="skill-tools" value={tools} onChange={(event) => setTools(event.target.value)} placeholder="read_file, read_csv" /></div>
        </div>
      </Modal>
    </div>
  )
}
