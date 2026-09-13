import React, { useState } from 'react'
import Button from 'antd/es/button'
import Drawer from 'antd/es/drawer'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Form from 'antd/es/form'
import Input from 'antd/es/input'
import List from 'antd/es/list'
import Modal from 'antd/es/modal'
import Spin from 'antd/es/spin'
import Tooltip from 'antd/es/tooltip'
import Typography from 'antd/es/typography'
import { DeleteOutlined, EditOutlined, FolderOutlined, MessageOutlined, PlusOutlined } from '@ant-design/icons'
import { Conversations } from '@ant-design/x'
import { apiFetch } from '../api.js'

const { Text } = Typography

// 与各页面保持一致的错误文案提取：优先用后端 detail，否则用浏览器原文。
function readableError(error) {
  return error?.detail || error?.message || '请求失败，请检查网络或稍后重试。'
}

/**
 * 侧边栏里的会话列表。
 *
 * 原先对话列表是 ChatPage 内部的第二条侧边栏，与全局导航并排占掉 524px。
 * 提出来之后它与导航共用同一条侧边栏，对话因此成为工作台的主入口：
 * 在看板或工作模式下也能直接看到并切换会话。
 */
export default function SidebarConversations({
  conversations = [],
  activeConversationId,
  canWrite = true,
  isCurrentView = false,
  onCreate,
  onSelect,
  onRefresh,
  messageApi,
  modal,
}) {
  const [renameTarget, setRenameTarget] = useState(null)
  const [archivedOpen, setArchivedOpen] = useState(false)
  const [archivedLoading, setArchivedLoading] = useState(false)
  const [archivedList, setArchivedList] = useState([])
  const [renameForm] = Form.useForm()

  const loadArchived = async () => {
    setArchivedLoading(true)
    try {
      const data = await apiFetch('/api/v1/conversations?include_archived=true')
      setArchivedList((data.conversations || []).filter((item) => item.archived))
    } catch {
      setArchivedList([])
    } finally {
      setArchivedLoading(false)
    }
  }

  const unarchive = async (conversation) => {
    try {
      await apiFetch(`/api/v1/conversations/${conversation.id}`, { method: 'PATCH', body: JSON.stringify({ archived: false }) })
      messageApi?.success('任务已恢复')
      loadArchived()
      onRefresh?.()
    } catch (error) {
      messageApi?.error(readableError(error))
    }
  }

  const archive = (conversation) => {
    modal.confirm({
      title: `归档任务「${conversation.label}」？`,
      content: '归档后不再出现在任务列表里，可在「已归档任务」中恢复。',
      okText: '归档',
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiFetch(`/api/v1/conversations/${conversation.key}`, { method: 'PATCH', body: JSON.stringify({ archived: true }) })
          messageApi?.success('任务已归档')
          if (activeConversationId === conversation.key) {
            const remaining = conversations.find((item) => item.id !== conversation.key)
            if (remaining) onSelect?.(remaining.id)
          }
          onRefresh?.()
        } catch (error) {
          messageApi?.error(readableError(error))
        }
      },
    })
  }

  const confirmDelete = (conversation) => {
    modal.confirm({
      title: `删除任务「${conversation.label}」？`,
      content: '任务消息与已上传附件会一并删除，且不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiFetch(`/api/v1/conversations/${conversation.key}`, { method: 'DELETE' })
          messageApi?.success('任务已删除')
          if (activeConversationId === conversation.key) {
            const remaining = conversations.find((item) => item.id !== conversation.key)
            if (remaining) onSelect?.(remaining.id)
          }
          onRefresh?.()
        } catch (error) {
          messageApi?.error(readableError(error))
        }
      },
    })
  }

  const openRename = (conversation) => {
    setRenameTarget(conversation)
    renameForm.setFieldsValue({ title: conversation.label })
  }

  const submitRename = async (values) => {
    const title = (values.title || '').trim()
    if (!renameTarget || !title) return
    try {
      await apiFetch(`/api/v1/conversations/${renameTarget.key}`, { method: 'PATCH', body: JSON.stringify({ title }) })
      messageApi?.success('任务已重命名')
      setRenameTarget(null)
      onRefresh?.()
    } catch (error) {
      messageApi?.error(readableError(error))
    }
  }

  return (
    <div className={`sidebar-conversations${isCurrentView ? ' is-current' : ''}`}>
      {/* 分组标题同时承担"新建"与"归档"两个入口：参考稿把列表级动作放在
          标题行右侧，比在顶部再压一个大按钮更省垂直空间，也让侧边栏上半部
          专心放导航。 */}
      <Flex className="sidebar-section-label" justify="space-between" align="center">
        <Flex gap={6} align="center">
          <span className="sidebar-section-mark" aria-hidden="true" />
          <Text type="secondary" className="sidebar-section-title">任务列表</Text>
        </Flex>
        <Flex gap={0} align="center" className="sidebar-group-actions">
          <Text type="secondary" className="sidebar-section-count">{conversations.length}</Text>
          <Tooltip title="新建任务">
            <Button
              type="text"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => onCreate?.()}
              disabled={!canWrite}
              aria-label="新建任务"
            />
          </Tooltip>
          <Tooltip title="已归档任务">
            <Button
              type="text"
              size="small"
              className="sidebar-archived-button"
              icon={<FolderOutlined />}
              onClick={() => { setArchivedOpen(true); loadArchived() }}
              aria-label="已归档任务"
            />
          </Tooltip>
        </Flex>
      </Flex>
      {conversations.length ? (
        <Conversations
          aria-label="任务列表"
          items={conversations.map((item) => ({ key: item.id, label: item.title, timestamp: item.updated_at, icon: <MessageOutlined /> }))}
          activeKey={activeConversationId}
          onActiveChange={(key) => onSelect?.(key)}
          menu={(conversation) => ({
            items: [
              { key: 'rename', label: '重命名', icon: <EditOutlined />, disabled: !canWrite },
              { key: 'archive', label: '归档', icon: <FolderOutlined />, disabled: !canWrite },
              { key: 'delete', label: '删除', icon: <DeleteOutlined />, danger: true, disabled: !canWrite },
            ],
            onClick: ({ key }) => {
              const target = conversations.find((item) => item.id === conversation.key)
              if (!target) return
              const wrapped = { key: target.id, label: target.title }
              if (key === 'rename') openRename(wrapped)
              else if (key === 'archive') archive(wrapped)
              else if (key === 'delete') confirmDelete(wrapped)
            },
          })}
        />
      ) : (
        <Empty className="sidebar-conversations-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无任务" />
      )}

      <Drawer title="已归档任务" open={archivedOpen} onClose={() => setArchivedOpen(false)} width="min(88vw, 360px)">
        {archivedLoading ? (
          <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
        ) : archivedList.length ? (
          <List
            size="small"
            dataSource={archivedList}
            renderItem={(item) => (
              <List.Item actions={[<Button key="restore" size="small" onClick={() => unarchive(item)}>恢复</Button>]}>
                <List.Item.Meta title={item.title} description={new Date(item.updated_at).toLocaleString('zh-CN', { hour12: false })} />
              </List.Item>
            )}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无归档任务" />
        )}
      </Drawer>

      <Modal title="重命名任务" open={Boolean(renameTarget)} onCancel={() => setRenameTarget(null)} onOk={() => renameForm.submit()} okText="保存" cancelText="取消" destroyOnHidden>
        <Form form={renameForm} layout="vertical" onFinish={submitRename}>
          <Form.Item name="title" label="任务标题" rules={[{ required: true, min: 2, message: '标题至少 2 个字符' }]}>
            <Input placeholder="输入新的任务标题" maxLength={120} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
