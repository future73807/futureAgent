import { useCallback, useEffect, useMemo, useState } from 'react'
// 子路径导入，原因见 SettingsModal 顶部注释：antd 顶层入口被别名到
// antd-x-bridge，只有少量白名单导出。
import AntApp from 'antd/es/app'
import Button from 'antd/es/button'
import Empty from 'antd/es/empty'
import Form from 'antd/es/form'
import Input from 'antd/es/input'
import Modal from 'antd/es/modal'
import Popconfirm from 'antd/es/popconfirm'
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Tag from 'antd/es/tag'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { apiFetch } from '../api.js'
import { t } from '../i18n'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

const KNOWLEDGE_API = '/api/v1/knowledge-bases'
// 与后端 KNOWLEDGE_TEXT_EXTENSIONS / MAX_KNOWLEDGE_TEXT_BYTES 保持一致：
// 前端先挡一道，避免把必然失败的请求发出去。
const knowledgeFileExtensions = new Set(['txt', 'md', 'csv', 'json', 'yaml', 'yml', 'log', 'html', 'htm', 'xml'])
const maxKnowledgeFileBytes = 400_000
const knowledgeFileAccept = '.txt,.md,.csv,.json,.yaml,.yml,.log,.html,.htm,.xml'
const CONTENT_PREVIEW_CHARS = 180

function readableError(error) {
  return error?.message || '操作未完成，请稍后重试。'
}

function formatSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return ''
  if (value < 1024) return `${value} B`
  return `${Math.round(value / 1024)} KB`
}

function formatTime(value) {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

function KnowledgeContent({ workspaceRole = 'member' }) {
  const { message } = AntApp.useApp()
  const canWrite = workspaceRole !== 'viewer'
  const canManage = ['owner', 'admin'].includes(workspaceRole)
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const loadDocuments = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await apiFetch(KNOWLEDGE_API)
      setDocuments(Array.isArray(payload?.knowledge_bases) ? payload.knowledge_bases : [])
    } catch (loadFailure) {
      setError(readableError(loadFailure))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadDocuments() }, [loadDocuments])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setEditorOpen(true)
  }

  const openEdit = (document) => {
    setEditing(document)
    form.setFieldsValue({
      title: document.title,
      description: document.description || '',
      content: document.content || '',
    })
    setEditorOpen(true)
  }

  const submitEditor = async (values) => {
    setSaving(true)
    try {
      if (editing) {
        await apiFetch(`${KNOWLEDGE_API}/${editing.id}`, {
          method: 'PATCH',
          body: {
            title: values.title,
            description: values.description || '',
            content: values.content || '',
          },
        })
        message.success('知识库文档已更新，向量切块已重建。')
      } else {
        await apiFetch(KNOWLEDGE_API, {
          method: 'POST',
          body: {
            title: values.title,
            description: values.description || '',
            content: values.content || '',
          },
        })
        message.success('知识库文档已创建。')
      }
      setEditorOpen(false)
      setEditing(null)
      form.resetFields()
      loadDocuments()
    } catch (submitFailure) {
      message.error(readableError(submitFailure))
    } finally {
      setSaving(false)
    }
  }

  const uploadDocument = async (file) => {
    const extension = String(file.name || '').split('.').pop().toLowerCase()
    const contentType = String(file.type || '').toLowerCase()
    const textualType = contentType.startsWith('text/')
      || ['application/json', 'application/xml', 'application/yaml', 'application/x-yaml'].includes(contentType)
    if (!textualType && !knowledgeFileExtensions.has(extension)) {
      message.error('仅支持 UTF-8 文本、Markdown、CSV、JSON、YAML、HTML 和 XML 文件。')
      return false
    }
    if (Number(file.size || 0) > maxKnowledgeFileBytes) {
      message.error('知识库文件不能超过约 400 KB。')
      return false
    }
    setUploading(true)
    try {
      const body = new FormData()
      body.append('file', file)
      body.append('title', file.name.replace(/\.[^/.]+$/, ''))
      await apiFetch(`${KNOWLEDGE_API}/upload`, { method: 'POST', body })
      message.success('知识库文件已上传，向量切块已重建。')
      loadDocuments()
    } catch (uploadFailure) {
      message.error(readableError(uploadFailure))
    } finally {
      setUploading(false)
    }
    return false
  }

  const removeDocument = async (document) => {
    try {
      await apiFetch(`${KNOWLEDGE_API}/${document.id}`, { method: 'DELETE' })
      message.success('知识库文档已删除。')
      loadDocuments()
    } catch (removeFailure) {
      message.error(readableError(removeFailure))
    }
  }

  const cards = useMemo(() => documents.map((document) => ({
    ...document,
    source: document.file_name ? '上传文件' : '手动创建',
    size: formatSize(document.file_size),
    updated: formatTime(document.updated_at),
    preview: (document.content || '').replace(/\s+/g, ' ').trim().slice(0, CONTENT_PREVIEW_CHARS),
  })), [documents])

  return (
    <div className="kb-page">
      <div className="kb-header">
        <div className="kb-header-copy">
          <Title level={3} className="kb-title">{t('knowledge.title')}</Title>
          <Text type="secondary">{t('knowledge.subtitle')}</Text>
        </div>
        <Space wrap>
          {canWrite && <Button icon={<PlusOutlined />} onClick={openCreate}>{t('knowledge.btn.create')}</Button>}
          {canWrite && (
            <Upload accept={knowledgeFileAccept} showUploadList={false} beforeUpload={uploadDocument} disabled={uploading}>
              <Button icon={<UploadOutlined />} loading={uploading}>{t('knowledge.btn.upload')}</Button>
            </Upload>
          )}
          <Button icon={<ReloadOutlined />} onClick={loadDocuments}>{t('knowledge.btn.refresh')}</Button>
        </Space>
      </div>
      <Text type="secondary" className="kb-hint">{t('knowledge.hint')}</Text>

      <Spin spinning={loading}>
        {error ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={error} />
        ) : cards.length ? (
          <div className="kb-list">
            {cards.map((document) => (
              <div key={document.id} className="kb-card">
                <div className="kb-card-head">
                  <Text strong className="kb-card-title">{document.title}</Text>
                  <Tag bordered={false}>{document.source}</Tag>
                  {document.size && <Tag bordered={false} color="blue">{document.size}</Tag>}
                </div>
                {document.description && <Text type="secondary" className="kb-card-desc">{document.description}</Text>}
                {document.preview && <Paragraph className="kb-card-preview" type="secondary">{document.preview}</Paragraph>}
                <div className="kb-card-foot">
                  <Text type="secondary">
                    {document.file_name ? `${document.file_name} · ` : ''}
                    {document.updated ? `更新于 ${document.updated}` : ''}
                  </Text>
                  <Space size={4}>
                    {canWrite && <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(document)} aria-label={`编辑 ${document.title}`} />}
                    {canManage && (
                      <Popconfirm title="确认删除该文档？" description="它的向量切块会一并删除，之后不再被检索召回。" onConfirm={() => removeDocument(document)} okText="删除" cancelText="取消">
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} aria-label={`删除 ${document.title}`} />
                      </Popconfirm>
                    )}
                  </Space>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={canWrite ? t('knowledge.empty') : t('knowledge.emptyReadonly')}
          />
        )}
      </Spin>

      <Modal
        title={editing ? '编辑知识库文档' : '创建知识库文档'}
        open={editorOpen}
        onCancel={() => { setEditorOpen(false); setEditing(null) }}
        onOk={() => form.submit()}
        okText={editing ? '保存' : '创建'}
        cancelText="取消"
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={submitEditor}>
          <Form.Item name="title" label="文档标题" rules={[{ required: true, min: 2, message: '请输入至少两个字的文档标题' }]}>
            <Input placeholder="例如：生产流程规范" />
          </Form.Item>
          <Form.Item name="description" label="文档说明">
            <Input placeholder="简要说明文档内容" />
          </Form.Item>
          <Form.Item name="content" label="文档内容">
            <TextArea rows={8} placeholder="智能助手回答时会检索并引用这里的内容" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default function KnowledgePage(props) {
  return <KnowledgeContent {...props} />
}
