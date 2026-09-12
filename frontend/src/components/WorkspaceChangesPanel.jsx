// 工作区文件版本与差异面板。
// 原先定义在 App.jsx 内部；对话页的"查看文件变更"抽屉与工作模式的结果
// 面板都要复用它，独立成文件避免 App.jsx 与 ChatPage 的循环依赖。
import React, { useCallback, useEffect, useState } from 'react'
import AntApp from 'antd/es/app'
import Alert from 'antd/es/alert'
import Button from 'antd/es/button'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Segmented from 'antd/es/segmented'
import Select from 'antd/es/select'
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Typography from 'antd/es/typography'
import { ReloadOutlined } from '@ant-design/icons'
import { apiFetch } from '../api.js'

const { Text } = Typography

// 与 App.jsx 同款兜底：供应商错误可能不含中文，透出英文原文体验不好。
function readableError(error) {
  const text = String(error?.message || '').trim()
  return /[\u3400-\u9fff]/.test(text) ? text : '操作未完成，请稍后重试。'
}

function diffLineClass(line) {
  if (line.startsWith('+++') || line.startsWith('---')) return 'diff-header'
  if (line.startsWith('@@')) return 'diff-hunk'
  if (line.startsWith('+')) return 'diff-add'
  if (line.startsWith('-')) return 'diff-remove'
  return ''
}

function DiffView({ diff }) {
  if (!diff) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择文件与两个版本后点“比对”" />
  if (!diff.diff_available) return <Alert type="info" showIcon message="该文件不提供文本差异" description={diff.reason || '二进制格式可分别下载各版本后自行比对。'} />
  if (diff.format === 'side-by-side') {
    return <>
      <div className="diff-side-by-side">{diff.rows.map((row, index) => (
        <div key={index} className={`diff-row diff-${row.kind}`}>
          <span className="diff-cell">{row.left || ' '}</span>
          <span className="diff-cell">{row.right || ' '}</span>
        </div>
      ))}</div>
      {diff.truncated && <Text type="secondary">差异过长，已截断展示。</Text>}
    </>
  }
  if (!diff.changed) return <Alert type="success" showIcon message="两个版本内容完全相同" />
  return <>
    <pre className="attachment-preview diff-unified">{diff.lines.map((line, index) => (
      <div key={index} className={diffLineClass(line)}>{line || ' '}</div>
    ))}</pre>
    {diff.truncated && <Text type="secondary">差异过长，已截断展示。</Text>}
  </>
}

export default function WorkspaceChangesPanel() {
  const { message } = AntApp.useApp()
  const [files, setFiles] = useState([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [path, setPath] = useState('')
  const [versions, setVersions] = useState([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [fromVersion, setFromVersion] = useState(null)
  const [toVersion, setToVersion] = useState(0)
  const [format, setFormat] = useState('unified')
  const [diff, setDiff] = useState(null)
  const [diffLoading, setDiffLoading] = useState(false)

  const loadFiles = useCallback(async () => {
    setFilesLoading(true)
    try {
      const data = await apiFetch('/api/v1/workspace/files')
      setFiles(data.files || [])
    } catch (error) { message.error(readableError(error)) } finally { setFilesLoading(false) }
  }, [])
  useEffect(() => { loadFiles() }, [loadFiles])

  const selectFile = async (nextPath) => {
    setPath(nextPath)
    setDiff(null)
    setVersions([])
    setFromVersion(null)
    if (!nextPath) return
    setVersionsLoading(true)
    try {
      const data = await apiFetch(`/api/v1/workspace/files/versions?path=${encodeURIComponent(nextPath)}`)
      const items = data.versions || []
      setVersions(items)
      // 默认拿最新快照与当前文件比，这就是“AI 刚刚改了什么”。
      setFromVersion(items.length ? items[items.length - 1].version : null)
      if (!items.length) message.info('该文件还没有历史版本：只有被覆盖过的文件才会留下快照。')
    } catch (error) { message.error(readableError(error)) } finally { setVersionsLoading(false) }
  }

  const compare = async () => {
    if (!path || fromVersion === null || fromVersion === toVersion) return
    setDiffLoading(true)
    try {
      const params = new URLSearchParams({ path, from: String(fromVersion), to: String(toVersion), format })
      setDiff(await apiFetch(`/api/v1/workspace/files/diff?${params.toString()}`))
    } catch (error) { message.error(readableError(error)); setDiff(null) } finally { setDiffLoading(false) }
  }

  const versionOptions = versions.map((item) => ({
    value: item.version,
    label: `v${item.version} · ${item.change_kind === 'generate' ? '生成' : item.change_kind === 'edit' ? '编辑' : '覆写'}${item.snapshot ? '' : '（无副本）'}`,
    disabled: !item.snapshot,
  }))
  const targetOptions = [
    { value: 0, label: '当前文件' },
    ...versionOptions,
  ]

  return <Space direction="vertical" size="small" style={{ width: '100%' }}>
    <Alert type="info" showIcon message="版本快照在文件被覆盖前自动保存" description="快照存放在租户目录之外，模型无法读写；清单只保留最近若干个版本，更早的改动已被清理。" />
    <Flex gap={8} wrap="wrap" align="center">
      <Select
        showSearch
        style={{ width: 260, maxWidth: '100%' }}
        placeholder="选择工作区文件"
        value={path || undefined}
        onChange={selectFile}
        loading={filesLoading}
        notFoundContent="工作区暂无文件"
        options={files.map((file) => ({ value: file.path, label: file.path }))}
      />
      <Select style={{ width: 190 }} placeholder="起始版本" value={fromVersion ?? undefined} onChange={setFromVersion} options={versionOptions} disabled={!versionOptions.length} notFoundContent="暂无历史版本" />
      <Select style={{ width: 150 }} placeholder="对比到" value={toVersion} onChange={setToVersion} options={targetOptions} disabled={!versions.length} />
      <Segmented size="small" value={format} onChange={setFormat} options={[{ label: '统一差异', value: 'unified' }, { label: '左右对照', value: 'side-by-side' }]} />
      <Button size="small" type="primary" loading={diffLoading} disabled={!path || fromVersion === null || fromVersion === toVersion} onClick={compare}>比对</Button>
      <Button size="small" icon={<ReloadOutlined />} onClick={loadFiles} loading={filesLoading}>刷新文件</Button>
    </Flex>
    {versionsLoading ? <Spin /> : (path && !versions.length) ? (
      // 只给一次性 toast 不够：控件会停在禁用态而无任何解释，
      // 使用者无法区分“没版本”与“功能坏了”。
      <Alert type="warning" showIcon message="该文件还没有历史版本"
        description="版本快照只在文件被覆盖前生成。这个文件新建后还没被改写过，所以没有可对比的历史版本；让 AI 再改一次它，就会出现版本并可比对。" />
    ) : <DiffView diff={diff} />}
  </Space>
}
