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
      messageApi?.success('对话已恢复')
      loadArchived()
      onRefresh?.()
    } catch (error) {
      messageApi?.error(readableError(error))
    }
  }

  const archive = (conversation) => {
    modal.confirm({
      title: `归档对话「${conversation.label}」？`,
      content: '归档后不再出现在最近对话里，可在「已归档对话」中恢复。',
      okText: '归档',
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiFetch(`/api/v1/conversations/${conversation.key}`, { method: 'PATCH', body: JSON.stringify({ archived: true }) })
          messageApi?.success('对话已归档')
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
      title: `删除对话「${conversation.label}」？`,
      content: '对话消息与已上传附件会一并删除，且不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiFetch(`/api/v1/conversations/${conversation.key}`, { method: 'DELETE' })
          messageApi?.success('对话已删除')
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
      messageApi?.success('对话已重命名')
      setRenameTarget(null)
      onRefresh?.()
    } catch (error) {
      messageApi?.error(readableError(error))
    }
  }

  return (
    <div className={`sidebar-conversations${isCurrentView ? ' is-current' : ''}`}>
      <Button type="primary" icon={<PlusOutlined />} block onClick={() => onCreate?.()} disabled={!canWrite}>
        新建对话
      </Button>
      {/* 归档入口放在标题行而不是底部：列表本身占 flex:1，底部再放一个
          链接会在对话较少时留下一大片空白。 */}
      <Flex className="sidebar-section-label" justify="space-between" align="center">
        <Flex gap={6} align="center">
          <span className="sidebar-section-mark" aria-hidden="true" />
          <Text type="secondary" className="sidebar-section-title">对话</Text>
        </Flex>
        <Flex gap={0} align="center">
          <Text type="secondary">{conversations.length}</Text>
          <Tooltip title="已归档对话">
            <Button
              type="text"
              size="small"
              className="sidebar-archived-button"
              icon={<FolderOutlined />}
              onClick={() => { setArchivedOpen(true); loadArchived() }}
              aria-label="已归档对话"
            />
          </Tooltip>
        </Flex>
      </Flex>
      {conversations.length ? (
        <Conversations
          aria-label="对话列表"
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
        <Empty className="sidebar-conversations-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话" />
      )}

      <Drawer title="已归档对话" open={archivedOpen} onClose={() => setArchivedOpen(false)} width="min(88vw, 360px)">
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
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无归档对话" />
        )}
      </Drawer>

      <Modal title="重命名对话" open={Boolean(renameTarget)} onCancel={() => setRenameTarget(null)} onOk={() => renameForm.submit()} okText="保存" cancelText="取消" destroyOnHidden>
        <Form form={renameForm} layout="vertical" onFinish={submitRename}>
          <Form.Item name="title" label="对话标题" rules={[{ required: true, min: 2, message: '标题至少 2 个字符' }]}>
            <Input placeholder="输入新的对话标题" maxLength={120} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
