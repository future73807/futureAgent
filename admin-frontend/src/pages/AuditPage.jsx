import React, { useEffect, useState } from 'react'
import { App, Button, Card, Space, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { apiFetch, toUserErrorMessage } from '../api.js'
import { formatDateTime } from '../formatters.js'

const { Title, Text } = Typography

const actionLabels = {
  'auth.login': '账号登录',
  'auth.logout': '账号退出登录',
  'auth.token_refreshed': '更新登录凭据',
  'workspace.created': '创建工作区',
  'workspace.updated': '更新工作区',
  'workspace.owner_transferred': '转移工作区所有权',
  'member.added': '添加工作区成员',
  'member.role_updated': '更新成员角色',
  'member.removed': '移除工作区成员',
  'project.created': '创建项目',
  'project.updated': '更新项目',
  'task.created': '创建任务',
  'task.updated': '更新任务',
  'work_plan.saved': '保存工作计划',
  'work_plan.approved': '批准工作计划',
  'work_plan.step_updated': '更新计划步骤',
  'conversation.created': '创建对话',
  'conversation.updated': '更新对话',
  'chat.completed': '完成对话生成',
  'agent.completed': '完成智能体执行',
  'agent_run.started': '启动 AI 执行',
  'agent_run.completed': '完成 AI 执行',
  'agent_run.failed': 'AI 执行失败',
  'agent_run.cancelled': '取消 AI 执行',
  'agent_run.timed_out': 'AI 执行超时',
  'attachment.uploaded': '上传附件',
  'model.probed': '完成模型真实探测',
  'model.probe_failed': '模型真实探测失败',
  'skill.created': '创建技能',
  'skill.updated': '更新技能',
  'skill.deleted': '删除技能',
  'policy.created': '创建权限策略',
  'policy.deleted': '删除权限策略',
  'admin.user_updated': '更新账号管理状态',
}

const targetLabels = {
  user: '账号',
  workspace: '工作区',
  membership: '成员关系',
  project: '项目',
  task: '任务',
  work_plan: '工作计划',
  work_plan_step: '计划步骤',
  conversation: '对话',
  agent_run: 'AI 执行',
  attachment: '附件',
  model: '模型',
  skill: '技能',
  policy: '权限策略',
}

const metadataLabels = {
  source: '来源',
  user_id: '账号 ID',
  new_owner_id: '新所有者账号 ID',
  role: '成员角色',
  project_id: '项目 ID',
  task_id: '任务 ID',
  step_id: '计划步骤 ID',
  assignee_id: '负责人账号 ID',
  status: '状态',
  step_count: '步骤数量',
  archived: '是否已归档',
  model_id: '模型 ID',
  skill_name: '技能名称',
  timeout_seconds: '超时秒数',
  name: '名称',
  size_bytes: '文件大小',
  sample_length: '响应字符数',
  is_active: '账号可用',
  is_platform_admin: '平台管理员',
  attempt: '执行次数',
  retry_of_id: '重试来源执行 ID',
  idempotency_key: '请求幂等标识',
}

const roleLabels = { owner: '所有者', admin: '管理员', member: '成员', viewer: '只读成员', readonly: '只读成员' }
const statusLabels = {
  draft: '草稿',
  approved: '已批准',
  in_progress: '进行中',
  todo: '待处理',
  done: '已完成',
  completed: '已完成',
  running: '运行中',
  succeeded: '已成功',
  failed: '失败',
  cancelled: '已取消',
  timed_out: '已超时',
}
const sourceLabels = { self_service_registration: '自主注册' }

function actionColor(action) {
  if (action?.endsWith('.failed')) return 'error'
  if (action?.endsWith('.timed_out')) return 'warning'
  if (action?.endsWith('.completed') || action === 'model.probed') return 'success'
  return 'blue'
}

function actionText(action) {
  return actionLabels[action] || `其他操作（${action || '未知'}）`
}

function targetText(targetType) {
  return targetLabels[targetType] || `其他对象（${targetType || '未知'}）`
}

function formatSize(bytes) {
  if (!Number.isFinite(bytes)) return String(bytes)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 ** 2)).toFixed(1)} MB`
}

function metadataValue(key, value) {
  if (value === null || value === undefined || value === '') return '未设置'
  if (key === 'role') return roleLabels[value] || String(value)
  if (key === 'status') return statusLabels[value] || String(value)
  if (key === 'source') return sourceLabels[value] || String(value)
  if (key === 'size_bytes') return formatSize(Number(value))
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function metadataText(metadata) {
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata) || Object.keys(metadata).length === 0) return <Text type="secondary">无</Text>
  return <Space size={[4, 4]} wrap>{Object.entries(metadata).map(([key, value]) => <Tag key={key}>{metadataLabels[key] || `其他信息（${key}）`}：{metadataValue(key, value)}</Tag>)}</Space>
}

export default function AuditPage() {
  const { message } = App.useApp(); const [events, setEvents] = useState([]); const [loading, setLoading] = useState(false)
  const load = async () => { setLoading(true); try { setEvents((await apiFetch('/api/v1/admin/audit-events?limit=200')).events || []) } catch (error) { message.error(toUserErrorMessage(error, '加载审计轨迹失败，请稍后重试。')) } finally { setLoading(false) } }
  useEffect(() => { load() }, [])
  const columns = [
    { title: '发生时间', dataIndex: 'created_at', width: 180, render: formatDateTime },
    { title: '操作', dataIndex: 'action', width: 190, render: (value) => <Tag color={actionColor(value)}>{actionText(value)}</Tag> },
    { title: '作用对象', width: 250, render: (_, event) => <Space direction="vertical" size={1}><Text strong>{targetText(event.target_type)}</Text><span className="code-text">{targetText(event.target_type)} ID：{event.target_id || '无特定对象'}</span></Space> },
    { title: '执行人', dataIndex: 'actor_id', width: 220, render: (value) => value ? <span className="code-text">账号 ID：{value}</span> : <Tag>系统</Tag> },
    { title: '附加信息', dataIndex: 'metadata', render: metadataText },
  ]
  return <div><div className="page-heading"><div><Title level={2}>审计轨迹</Title><Text type="secondary">集中查看由 API 记录的安全、工作区、任务、计划和 AI 执行活动。</Text></div><Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button></div><Card className="admin-card"><Table rowKey="id" columns={columns} dataSource={events} loading={loading} scroll={{ x: 1300 }} pagination={{ pageSize: 25 }} locale={{ emptyText: '暂无数据' }} /></Card></div>
}
